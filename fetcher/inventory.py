#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مخزون قطع طايا — سحب حقيقي من موقع مدينة طايا الصناعيّة → site/data/inventory.json.

المصدر: صفحة العقارات tic-taya.sa/listings (Livewire). لكل قطعة: الكود الحقيقي
(LI-B11-173)، البلوك ورقم القطعة (مستخرجان من الكود)، المساحة، النوع، الاتجاه، عرض الشارع،
والحالة (للبيع/محجوز/مباع). يُسحب كل قطاع بطلب Livewire واحد (selectedSector + perPage عالٍ).

ملاحظات أمانة:
  • الموقع العام يعرض القطع المعروضة للبيع (+ القليل محجوز) — لا يَنشُر «المباع»؛ فحقل
    المباع يبقى من نظام TIC الداخلي لاحقًا (هنا 0/غير منشور، لا اختلاق).
  • إحداثيات الموقع العام تبدو placeholder (مكرّرة لكل بلوك، 24.7/46.73)؛ والموقع الفعلي
    لطايا قرب المصفاة (24.49/46.88) — لذا نوزّع القطع توزيعًا حتميًّا حول المركز الصحيح
    للعرض على الخريطة فقط (مواقع تقريبيّة)، مع الإبقاء على بقيّة الحقول حقيقيّة.
  • السعر غير منشور على الموقع (طلب اتصال)؛ نستخدم تقدير سعر القطاع لحساب «خط الأنابيب».

تشغيل:
    python fetcher/inventory.py            # سحب حيّ من tic-taya.sa → inventory.json
    python fetcher/inventory.py --offline  # يبقي الملف الحالي إن تعذّر السحب (لا يكتب عيّنة)
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import urllib.request
import http.cookiejar
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "site" / "data" / "inventory.json"

BASE = "https://www.tic-taya.sa"
LISTINGS = BASE + "/listings"
UPDATE = BASE + "/livewire/update"
TIMEOUT = 120

# الموقع الفعلي لطايا (منطقة المصفاة) — للعرض على الخريطة (إحداثيات الموقع العام placeholder)
TIC_LAT, TIC_LNG = 24.4887, 46.8813
_LNG_SCALE = 1.0 / math.cos(math.radians(TIC_LAT))

# قطاعات الموقع → مفاتيح benchmarks في metrics.json (+ تقدير سعر للقطاع، ر.س/م²)
SECTORS = [
    ("light_industrial",  "light",   "صناعي خفيف",  1850),
    ("medium_industrial", "medium",  "صناعي متوسط", 1700),
    ("ready_made",        "factory", "مصانع جاهزة", 2200),
    ("warehouse",         "wh",      "مستودعات",    1800),
    ("commercial",        "comm",    "تجاري",       3000),
    ("residential",       "res",     "سكني",        1100),
]
STATUS_MAP = {"للبيع": "available", "متاح": "available",
              "محجوز": "reserved", "مباع": "sold", "مباعة": "sold", "تم البيع": "sold"}

CODE_RE = re.compile(r"[A-Z]{2}-B\d+-\d+")
CODE_PARTS = re.compile(r"^([A-Z]{2})-B(\d+)-(\d+)$")


def _scatter(seed_str):
    """توزيع حتميّ داخل قرص طايا (~900م) — مواقع تقريبيّة للعرض فقط."""
    seed = (abs(hash(seed_str)) * 0x9E3779B1 + 0x2545F491) & 0xFFFFFFFF
    ang = (seed % 4096) / 4096.0 * 2 * math.pi
    r = 0.0012 + math.sqrt(((seed >> 12) % 4096) / 4096.0) * 0.0105
    return (round(TIC_LAT + math.sin(ang) * r, 6),
            round(TIC_LNG + math.cos(ang) * r * _LNG_SCALE, 6))


def _num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def _opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", "Mozilla/5.0"), ("Accept", "text/html")]
    return op


def _session(op):
    """يفتح الصفحة ويلتقط csrf + snapshot مكوّن القوائم."""
    h = op.open(LISTINGS, timeout=TIMEOUT).read().decode("utf-8")
    csrf = re.search(r'csrf-token" content="([^"]+)"', h).group(1)
    snaps = [html.unescape(s) for s in re.findall(r'wire:snapshot="([^"]*)"', h)]
    snap = next(s for s in snaps if "taya-listing-component" in s)
    return csrf, snap


def _fetch_sector(op, csrf, snap, sector_value):
    body = json.dumps({"_token": csrf, "components": [
        {"snapshot": snap, "updates": {"selectedSector": sector_value, "perPage": 3000}, "calls": []}]})
    req = urllib.request.Request(UPDATE, data=body.encode(), headers={
        "Content-Type": "application/json", "X-CSRF-TOKEN": csrf, "Accept": "application/json"})
    j = json.loads(op.open(req, timeout=TIMEOUT).read().decode("utf-8"))
    return j["components"][0]["effects"]["html"]


def _parse_card(card_html, key, sector_name, ask):
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(card_html)))
    mc = CODE_RE.search(txt)
    if not mc:
        return None
    code = mc.group(0)
    mp = CODE_PARTS.match(code)
    block = int(mp.group(2)) if mp else None
    plot_idx = int(mp.group(3)) if mp else None

    status_ar = None
    mb = re.search(r"(للبيع|محجوز|مباعة|مباع|تم البيع|متاح)", txt)
    if mb:
        status_ar = mb.group(1)
    status = STATUS_MAP.get(status_ar, "available")

    m_area = re.search(r"المساحة الإجمالية\s*([\d.,]+)", txt)
    area = _num(m_area.group(1)) if m_area else None
    m_type = re.search(r"نوع العقار\s*([^0-9]+?)\s*الاتجاه", txt)
    ptype = m_type.group(1).strip() if m_type else None
    m_dir = re.search(r"الاتجاه\s*([^0-9]+?)\s*عرض الشارع", txt)
    direction = m_dir.group(1).strip() if m_dir else None
    m_w = re.search(r"عرض الشارع\s*([\d]+)", txt)
    street_w = _num(m_w.group(1)) if m_w else None

    lat, lng = _scatter(code)
    rec = {
        "plot_no": code, "sector": key, "sector_name": sector_name,
        "block": block, "plot_index": plot_idx,
        "area": area, "type": ptype, "direction": direction, "street_width": street_w,
        "status": status, "asking_price": ask, "lat": lat, "lng": lng,
    }
    return rec


def fetch_live():
    op = _opener()
    csrf, snap = _session(op)
    plots, seen = [], set()
    counts = {}
    for sector_value, key, sector_name, ask in SECTORS:
        hh = _fetch_sector(op, csrf, snap, sector_value)
        n = 0
        for seg in hh.split('class="tic-listing-card"')[1:]:
            rec = _parse_card(seg[:2800], key, sector_name, ask)
            if not rec or rec["plot_no"] in seen:
                continue
            seen.add(rec["plot_no"])
            plots.append(rec)
            n += 1
        counts[key] = n
    if not plots:
        raise RuntimeError("لم تُستخرَج أي قطعة — تغيّر بناء الصفحة؟")
    by_status = {}
    for p in plots:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    return {
        "sample": False,
        "source": "tic-taya.sa/listings",
        "source_note": ("قطع حقيقيّة من موقع مدينة طايا الصناعيّة. الموقع العام يعرض المعروض "
                        "للبيع (+ محجوز) ولا يَنشُر المباع — فالمبيعات تُضاف من النظام الداخلي. "
                        "المواقع على الخريطة تقريبيّة (إحداثيات الموقع placeholder)."),
        "generated_at": date.today().isoformat() + "T00:00:00",
        "tic_center": [TIC_LAT, TIC_LNG],
        "sector_counts": counts,
        "status_counts": by_status,
        "plots": plots,
    }


def main():
    ap = argparse.ArgumentParser(description="سحب مخزون قطع طايا الحقيقي → inventory.json")
    ap.add_argument("--offline", action="store_true", help="لا تكتب شيئًا إن تعذّر السحب")
    args = ap.parse_args()
    try:
        data = fetch_live()
    except Exception as e:  # noqa: BLE001
        print(f"[inventory] تعذّر السحب الحيّ: {e}", file=sys.stderr)
        if args.offline or OUT_PATH.exists():
            print("[inventory] أبقيت الملف الحالي دون تغيير.", file=sys.stderr)
            return 1
        raise
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data["plots"])
    print(f"[inventory] كُتب {OUT_PATH.relative_to(ROOT)} — {n} قطعة حقيقيّة · "
          f"قطاعات {data['sector_counts']} · حالات {data['status_counts']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
