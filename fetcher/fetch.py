#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher/fetch.py — جالب صفقات السجل العقاري من بسيطة (Paseetah) عبر Chrome profile مسجَّل دخوله.

المعمارية: Playwright + persistent context يشير إلى ملف Chrome المالك المسجَّل دخوله في بسيطة
(لا OTP داخل السكربت). يستدعي API بسيطة الداخلي same-origin، يطبّع الأرقام، ويخزّن UPSERT في
data/taya.db، ثم يصدّر snapshot يومي. عند انتهاء الجلسة → إشعار + خروج بكود غير صفري دون كسر آخر بيانات.

الاستخدام:
    python fetcher/fetch.py --login    # أول مرة: يفتح Chrome مرئياً لتسجيل دخول بسيطة (يُحفظ الـ profile)
    python fetcher/fetch.py            # تشغيل مجدول: headless، جلب incremental
    python fetcher/fetch.py --headed   # تشغيل مرئي للتشخيص
    python fetcher/fetch.py --full     # تجاهل آخر تاريخ مخزّن وأعد الجلب لكامل نافذة CUTOFF_MONTHS

أمانة البيانات: لا اختلاق. كل صف يُخزَّن مع raw_json الأصلي. الإحداثيات/الأرقام الناقصة تُترك NULL
ولا تُختلق. المصدر: بسيطة (RER) فقط — الإعلانات ليست مصدراً.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# ── المسارات (جذر المشروع = أب مجلد fetcher) ──────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "taya.db"
SNAP_DIR = DATA_DIR / "snapshots"

# ── الإعدادات من البيئة (.env اختياري) ────────────────────────────────────────
def _load_env() -> None:
    """حمّل .env إن وُجدت python-dotenv؛ وإلا تجاهل بصمت (المتغيرات قد تكون مُصدّرة)."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


_load_env()

PROFILE_PATH = os.environ.get("TAYA_CHROME_PROFILE", "").strip()
CUTOFF_MONTHS = int(os.environ.get("TAYA_CUTOFF_MONTHS", "24") or "24")
PASEETAH_BASE = os.environ.get("PASEETAH_BASE", "https://paseetah.com").rstrip("/")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "").strip()

# نطاق الجلب
NEIGHBORHOODS = [11010192, 11010065, 11010061, 11010117]  # المصفاة، الصناعية الجديدة، السلي، المصانع
TARGET_PLANS = {"2377", "3880/1", "3796", "3200"}          # المخططات الأساسية (تصنيف؛ لا يُسقط غيرها)
# bounding box احتياطي حول مركز TIC (يُستخدم للتصفية فقط لو لزم؛ لا يُسقط صفوفاً بلا إحداثيات)
TIC_LAT = float(os.environ.get("TIC_LAT", "24.4887"))
TIC_LNG = float(os.environ.get("TIC_LNG", "46.8813"))
BBOX = {"lat_min": TIC_LAT - 0.08, "lat_max": TIC_LAT + 0.08,
        "lng_min": TIC_LNG - 0.10, "lng_max": TIC_LNG + 0.10}

PAGE_SIZE = 50
MAX_PAGES = 400                # حدّ أمان ضد الحلقة اللانهائية
INCREMENTAL_OVERLAP_DAYS = 7   # نافذة تداخل لالتقاط صفقات سُجّلت متأخّرة
API_PATH = "/api/precord/rer_transactions/data"


class SessionExpiredError(RuntimeError):
    """تُرفع عندما تنتهي جلسة بسيطة (يلزم إعادة تسجيل دخول Chrome)."""


# ─────────────────────────────────────────────────────────────────────────────
# تطبيع الأرقام والتواريخ
# ─────────────────────────────────────────────────────────────────────────────
_ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"        # U+0660–0669
_EXT_ARABIC = "۰۱۲۳۴۵۶۷۸۹"        # U+06F0–06F9 (فارسية/أردية)
_DIGIT_MAP = {ord(a): str(i) for i, a in enumerate(_ARABIC_INDIC)}
_DIGIT_MAP.update({ord(a): str(i) for i, a in enumerate(_EXT_ARABIC)})
_DIGIT_MAP[ord("٫")] = "."          # الفاصلة العشرية العربية
_DIGIT_MAP[ord("٬")] = ""           # فاصل الآلاف العربي
_DIGIT_MAP[ord("،")] = ""           # الفاصلة العربية


def normalize_digits(value) -> str:
    """حوّل الأرقام العربية-الهندية/الفارسية إلى لاتينية وفواصلها إلى لاتينية. يُرجع نصاً."""
    if value is None:
        return ""
    return str(value).translate(_DIGIT_MAP)


def to_number(value):
    """طبّع ثم استخرج رقماً (float). يُرجع None لو خلا من رقم. لا يختلق قيمة."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = normalize_digits(value)
    # احذف فواصل الآلاف والمسافات والعملة، أبقِ الأرقام والنقطة والإشارة
    s = s.replace(",", "").replace(" ", " ").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def parse_date(value):
    """طبّع ثم حلّل التاريخ إلى date. يُرجع None عند الفشل (يُبقي الصف، لا يُسقطه)."""
    if value is None:
        return None
    s = normalize_digits(value).strip()
    if not s:
        return None
    s_short = s[:19]
    for fmt in _DATE_FORMATS:
        for candidate in (s, s_short, s[:10]):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    # محاولة ISO مرنة
    try:
        return datetime.fromisoformat(s_short).date()
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# مطابقة حقول الاستجابة (مرنة — تُثبَّت بعد أول تشغيل ضد raw_json)
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ أسماء حقول استجابة بسيطة غير موثّقة هنا؛ نجرّب مرشّحات ونخزّن raw_json للتحقق.
FIELD_CANDIDATES = {
    "transaction_date": ["transaction_date", "transactionDate", "date", "deal_date", "registration_date"],
    "plan": ["plan", "plan_no", "plan_number", "planNo", "plan_name", "subdivision"],
    "parcel": ["parcel", "parcel_no", "parcel_number", "land_number", "plot_no", "piece_no", "land_no"],
    "real_estate_number": ["real_estate_number", "realEstateNumber", "property_number",
                           "re_number", "deed_number", "property_no"],
    "area": ["area", "space", "land_area", "area_m2", "total_area", "size"],
    "usage": ["usage", "land_use", "use", "property_usage", "land_usage"],
    "type": ["type", "transaction_type", "deal_type", "property_type", "trans_type"],
    "meter_price": ["meter_price", "price_per_meter", "price_meter", "meterPrice",
                    "unit_price", "price_of_meter", "metter_price"],
    "amount": ["amount", "price", "total_price", "value", "deal_amount", "transaction_price", "total"],
    "lat": ["lat", "latitude", "y", "lat_y"],
    "lng": ["lng", "lon", "long", "longitude", "x", "lng_x"],
}


def _pick(raw: dict, keys):
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return None


def map_row(raw: dict) -> dict:
    """حوّل صفاً خاماً من بسيطة إلى مخطط deals. القيم الناقصة → None (لا اختلاق)."""
    txt = lambda v: None if v is None else normalize_digits(v).strip() or None

    plan = txt(_pick(raw, FIELD_CANDIDATES["plan"]))
    parcel = txt(_pick(raw, FIELD_CANDIDATES["parcel"]))
    ren = txt(_pick(raw, FIELD_CANDIDATES["real_estate_number"]))
    tdate_raw = _pick(raw, FIELD_CANDIDATES["transaction_date"])
    tdate = parse_date(tdate_raw)

    area = to_number(_pick(raw, FIELD_CANDIDATES["area"]))
    meter_price = to_number(_pick(raw, FIELD_CANDIDATES["meter_price"]))
    amount = to_number(_pick(raw, FIELD_CANDIDATES["amount"]))
    lat = to_number(_pick(raw, FIELD_CANDIDATES["lat"]))
    lng = to_number(_pick(raw, FIELD_CANDIDATES["lng"]))

    # اشتقاق سعر المتر من القيمة/المساحة فقط عند غيابه (يُعلَّم derived، ليس اختلاقاً)
    derived = 0
    if meter_price is None and amount and area:
        meter_price = round(amount / area, 2)
        derived = 1

    return {
        "transaction_date": tdate.isoformat() if tdate else (txt(tdate_raw) or ""),
        "plan": plan or "",
        "parcel": parcel or "",
        "real_estate_number": ren or "",
        "area": area,
        "usage": txt(_pick(raw, FIELD_CANDIDATES["usage"])),
        "type": txt(_pick(raw, FIELD_CANDIDATES["type"])),
        "meter_price": meter_price,
        "amount": amount,
        "lat": lat,
        "lng": lng,
        "source": "Paseetah/RER",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "meter_price_derived": derived,
        "raw_json": json.dumps(raw, ensure_ascii=False),
    }


def find_rows(payload):
    """استخرج قائمة صفوف الـ dict من استجابة بسيطة مهما كان تغليفها (Laravel paginator/…)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # مفاتيح شائعة بالترتيب
        for key in ("data", "records", "rows", "items", "result", "results"):
            if key in payload:
                inner = payload[key]
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
                if isinstance(inner, dict):  # paginator: {"data": {"data": [...]}}
                    nested = find_rows(inner)
                    if nested:
                        return nested
        # وإلا: أول قيمة قائمة-من-dict
        for v in payload.values():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return v
    return []


# ─────────────────────────────────────────────────────────────────────────────
# قاعدة البيانات
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_date    TEXT NOT NULL,
    plan                TEXT NOT NULL,
    parcel              TEXT NOT NULL,
    real_estate_number  TEXT NOT NULL,
    area                REAL,
    usage               TEXT,
    type                TEXT,
    meter_price         REAL,
    amount              REAL,
    lat                 REAL,
    lng                 REAL,
    source              TEXT DEFAULT 'Paseetah/RER',
    fetched_at          TEXT,
    meter_price_derived INTEGER DEFAULT 0,
    raw_json            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_deal_key
    ON deals (real_estate_number, transaction_date, parcel);
CREATE INDEX IF NOT EXISTS ix_deal_date ON deals (transaction_date);
"""

UPSERT = """
INSERT INTO deals
    (transaction_date, plan, parcel, real_estate_number, area, usage, type,
     meter_price, amount, lat, lng, source, fetched_at, meter_price_derived, raw_json)
VALUES
    (:transaction_date, :plan, :parcel, :real_estate_number, :area, :usage, :type,
     :meter_price, :amount, :lat, :lng, :source, :fetched_at, :meter_price_derived, :raw_json)
ON CONFLICT (real_estate_number, transaction_date, parcel) DO UPDATE SET
    plan=excluded.plan, area=excluded.area, usage=excluded.usage, type=excluded.type,
    meter_price=excluded.meter_price, amount=excluded.amount, lat=excluded.lat, lng=excluded.lng,
    fetched_at=excluded.fetched_at, meter_price_derived=excluded.meter_price_derived,
    raw_json=excluded.raw_json
WHERE excluded.fetched_at IS NOT NULL;
"""


def db_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def last_stored_date(conn) -> date | None:
    row = conn.execute(
        "SELECT MAX(transaction_date) AS d FROM deals WHERE length(transaction_date)>=10"
    ).fetchone()
    return parse_date(row["d"]) if row and row["d"] else None


def upsert_rows(conn, mapped_rows) -> int:
    """UPSERT الصفوف ويُرجع عدد الصفوف الجديدة (insert فقط)."""
    before = conn.execute("SELECT COUNT(*) AS c FROM deals").fetchone()["c"]
    conn.executemany(UPSERT, mapped_rows)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) AS c FROM deals").fetchone()["c"]
    return after - before


# ─────────────────────────────────────────────────────────────────────────────
# عميل بسيطة عبر Playwright (in-page same-origin fetch)
# ─────────────────────────────────────────────────────────────────────────────
_IN_PAGE_FETCH = """
async ({ url, body }) => {
  function getCookie(name) {
    const m = document.cookie.match(new RegExp('(^|; )' + name + '=([^;]+)'));
    return m ? decodeURIComponent(m[2]) : null;
  }
  const xsrf = getCookie('XSRF-TOKEN');
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  if (xsrf) headers['X-XSRF-TOKEN'] = xsrf;
  const res = await fetch(url, {
    method: 'POST', headers, credentials: 'include', body: JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, redirected: res.redirected, finalUrl: res.url, body: text };
}
"""


def _require_profile():
    if not PROFILE_PATH:
        raise SystemExit(
            "خطأ: TAYA_CHROME_PROFILE غير مضبوط. انسخ .env.example إلى .env واضبط المسار، "
            "ثم سجّل الدخول مرة:  python fetcher/fetch.py --login"
        )


def _looks_like_login(status: int, final_url: str, body_text: str) -> bool:
    if status in (401, 419, 403):
        return True
    low = (final_url or "").lower()
    if "login" in low or "signin" in low or "auth" in low:
        return True
    head = (body_text or "")[:600].lower()
    if "<!doctype html" in head and ("login" in head or "تسجيل الدخول" in (body_text or "")[:2000]):
        return True
    return False


def fetch_page(page, page_no: int):
    """اطلب صفحة واحدة من بسيطة. يُرجع (rows_raw, raw_payload). يرفع SessionExpiredError عند انتهاء الجلسة."""
    body = {
        "page": page_no,
        "regions": [1],
        "cities": [1],
        "neighborhoods": NEIGHBORHOODS,
        "planExactMatch": True,
        "parcelExactMatch": True,
        "realEstateNumberExactMatch": True,
        "sort_column": "transaction_date",
        "sort_order": "descending",
        "perPage": PAGE_SIZE,
        "per_page": PAGE_SIZE,
    }
    result = page.evaluate(_IN_PAGE_FETCH, {"url": PASEETAH_BASE + API_PATH, "body": body})
    status = result.get("status", 0)
    text = result.get("body", "") or ""
    if _looks_like_login(status, result.get("finalUrl", ""), text):
        raise SessionExpiredError(f"الجلسة منتهية (status={status}).")
    if status >= 400:
        raise RuntimeError(f"استجابة غير متوقّعة من بسيطة: status={status} body[:200]={text[:200]}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # JSON غير صالح وغير شكل تسجيل دخول → غالباً انتهاء جلسة مقنّع أو تغيّر API
        raise SessionExpiredError("استجابة ليست JSON (محتملة انتهاء جلسة أو تغيّر في API).")
    return find_rows(payload), payload


def run_fetch(headless: bool, full: bool) -> dict:
    """ينفّذ الجلب الكامل ويُرجع ملخّصاً. يرفع SessionExpiredError عند انتهاء الجلسة."""
    _require_profile()
    from playwright.sync_api import sync_playwright  # استيراد كسول (كي لا تتطلّبه الاختبارات)

    conn = db_connect()
    stored = None if full else last_stored_date(conn)
    if stored:
        cutoff = _minus_days(stored, INCREMENTAL_OVERLAP_DAYS)
        mode = f"incremental (منذ {cutoff.isoformat()}، تداخل {INCREMENTAL_OVERLAP_DAYS} يوماً)"
    else:
        cutoff = _minus_months(date.today(), CUTOFF_MONTHS)
        mode = f"كامل (نافذة {CUTOFF_MONTHS} شهراً، منذ {cutoff.isoformat()})"

    print(f"[fetch] الوضع: {mode}")
    total_seen = total_new = 0
    sample_logged = False

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_PATH, channel="chrome", headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            resp = page.goto(PASEETAH_BASE, wait_until="domcontentloaded", timeout=45000)
            if resp is not None and _looks_like_login(resp.status, page.url, ""):
                raise SessionExpiredError("صفحة تسجيل دخول عند فتح بسيطة — الجلسة منتهية.")

            for page_no in range(1, MAX_PAGES + 1):
                rows_raw, _payload = fetch_page(page, page_no)
                if not rows_raw:
                    break

                if not sample_logged:
                    print("[fetch] عيّنة صف خام (لتثبيت مطابقة الحقول):")
                    print("        " + json.dumps(rows_raw[0], ensure_ascii=False)[:500])
                    sample_logged = True

                mapped = [map_row(r) for r in rows_raw]
                total_seen += len(mapped)
                total_new += upsert_rows(conn, mapped)

                # توقّف عند تجاوز cutoff (مُرتّب تنازلياً): إن كان أقدم صف في الصفحة < cutoff
                page_dates = [parse_date(m["transaction_date"]) for m in mapped]
                oldest = min([d for d in page_dates if d], default=None)
                if oldest and oldest < cutoff:
                    break
                if len(rows_raw) < PAGE_SIZE:
                    break
        finally:
            ctx.close()

    last = last_stored_date(conn)
    total_rows = conn.execute("SELECT COUNT(*) AS c FROM deals").fetchone()["c"]
    conn.close()
    summary = {
        "mode": mode, "seen": total_seen, "new": total_new,
        "total_rows": total_rows, "last_date": last.isoformat() if last else None,
        "cutoff": cutoff.isoformat(),
    }
    export_snapshot(summary)
    return summary


def export_snapshot(summary: dict) -> Path:
    """يصدّر snapshot يومي = كامل جدول deals الحالي (نقطة زمنية، للتدقيق وعدم الاختلاق)."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    conn = db_connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT transaction_date, plan, parcel, real_estate_number, area, usage, type, "
        "meter_price, amount, lat, lng, source, meter_price_derived "
        "FROM deals ORDER BY transaction_date DESC"
    ).fetchall()]
    conn.close()
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "السجل العقاري (RER) عبر بسيطة",
        "data_window_cutoff": summary.get("cutoff"),
        "count": len(rows),
        "new_this_run": summary.get("new"),
        "deals": rows,
    }
    path = SNAP_DIR / f"{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fetch] snapshot: {path.relative_to(ROOT)} ({len(rows)} صفقة)")
    return path


# ── حساب التواريخ بلا اعتماديات خارجية ────────────────────────────────────────
def _minus_days(d: date, days: int) -> date:
    from datetime import timedelta
    return d - timedelta(days=days)


def _minus_months(d: date, months: int) -> date:
    m = d.month - 1 - months
    y = d.year + m // 12
    m = m % 12 + 1
    # ثبّت اليوم ضمن حدود الشهر
    last_day = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last_day))


# ─────────────────────────────────────────────────────────────────────────────
# الإشعارات عند انتهاء الجلسة
# ─────────────────────────────────────────────────────────────────────────────
def notify_session_expired() -> None:
    msg = "انتهت جلسة بسيطة — افتح Chrome وسجّل الدخول: python fetcher/fetch.py --login"
    title = "Taya Dashboard — تجديد مطلوب"
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "{title}"'],
            check=False, timeout=10,
        )
    except Exception:
        pass
    if NOTIFY_EMAIL:
        _send_email(title, msg)


def _send_email(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        port = int(os.environ.get("SMTP_PORT", "587") or "587")
        user = os.environ.get("SMTP_USER", "").strip()
        pwd = os.environ.get("SMTP_PASS", "").strip()
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user or NOTIFY_EMAIL
        msg["To"] = NOTIFY_EMAIL
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            if user:
                s.login(user, pwd)
            s.send_message(msg)
        print("[notify] أُرسل بريد التنبيه.")
    except Exception as e:
        print(f"[notify] تعذّر إرسال البريد: {e}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# وضع تسجيل الدخول لمرة واحدة
# ─────────────────────────────────────────────────────────────────────────────
def run_login() -> None:
    _require_profile()
    from playwright.sync_api import sync_playwright
    print("─" * 60)
    print("تسجيل دخول بسيطة لمرة واحدة")
    print("سيُفتح Chrome مرئياً. سجّل الدخول (جوال + OTP)، فعّل «تذكّرني»،")
    print("ثم ارجع هنا واضغط Enter لإغلاق المتصفّح وحفظ الجلسة في الـ profile.")
    print("─" * 60)
    Path(PROFILE_PATH).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_PATH, channel="chrome", headless=False,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(PASEETAH_BASE, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        try:
            input("\n[انتظار] بعد إتمام تسجيل الدخول، اضغط Enter هنا… ")
        finally:
            ctx.close()
    print("تم حفظ الجلسة. التشغيلات المجدولة ستعمل headless بلا OTP حتى تنتهي الجلسة.")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="جالب صفقات بسيطة لمحيط مدينة طايا الصناعية")
    ap.add_argument("--login", action="store_true", help="فتح Chrome مرئياً لتسجيل دخول بسيطة لمرة واحدة")
    ap.add_argument("--headed", action="store_true", help="تشغيل الجلب مرئياً (تشخيص)")
    ap.add_argument("--full", action="store_true", help="تجاهل آخر تاريخ وأعد جلب كامل النافذة")
    args = ap.parse_args(argv)

    if args.login:
        run_login()
        return 0

    try:
        summary = run_fetch(headless=not args.headed, full=args.full)
    except SessionExpiredError as e:
        print(f"[session] {e}", file=sys.stderr)
        notify_session_expired()
        return 2  # لا يدفع run.sh عند 2؛ آخر نشر يبقى سليماً
    except Exception as e:
        print(f"[error] فشل الجلب: {e}", file=sys.stderr)
        return 1

    print(f"[done] جديد={summary['new']} · مرئي={summary['seen']} · "
          f"إجمالي={summary['total_rows']} · آخر تاريخ={summary['last_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
