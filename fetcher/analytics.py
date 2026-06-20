#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher/analytics.py — يقرأ deals من data/taya.db ويكتب site/data/metrics.json للواجهة.

لكل مخطط (2377، 3880/1، 3796، 3200) وللإجمالي: median/p25/p75، trimming للشواذ (IQR×1.5)،
الزخم MoM%/QoQ%، السلسلة الشهرية، السيولة، الطلب (مساحة/استخدام)، benchmarks لفئات طايا الست،
الصفقات اللافتة آخر 30 يوماً، وإحداثيات الصفقات للخريطة.

أمانة: median لا المتوسط · كل رقم منسوب لمصدره وتاريخه · مخطط <5 صفقات → "بيانات غير كافية" ·
لا اختلاق. وضع --sample يولّد بيانات توضيحية مُعلَّمة (sample=true) لاختبار عرض الواجهة فقط.

تشغيل:
    python fetcher/analytics.py            # من data/taya.db → site/data/metrics.json
    python fetcher/analytics.py --sample   # بيانات توضيحية لاختبار الواجهة (مُعلَّمة بوضوح)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "taya.db"
OUT_PATH = ROOT / "site" / "data" / "metrics.json"

MIN_DEALS = 5          # دون ذلك → "بيانات غير كافية"
NOTABLE_PCT = 10.0     # انحراف % عن السائد يجعل الصفقة "لافتة"
NOTABLE_DAYS = 30
LARGE_AREA = 5000      # م² — صفقة كبيرة
MAP_CAP = 2000         # حدّ أعلى لصفوف الخريطة/الجدول في metrics.json

PLAN_META = {
    "2377":   {"label": "صناعي المصفاة · 2377", "short": "المصفاة 2377",  "color": "#28285D", "ref": [1600, 2000]},
    "3880/1": {"label": "الفوزان · 3880/1",      "short": "الفوزان 3880/1", "color": "#1D9E75", "ref": [1100, 2400]},
    "3796":   {"label": "مستودعات · 3796",       "short": "مستودعات 3796",  "color": "#BA7517", "ref": [1200, 1900]},
    "3200":   {"label": "سكن عمالة · 3200",      "short": "سكن عمالة 3200", "color": "#8E5A86", "ref": [833, 1200]},
}
PLAN_ORDER = ["2377", "3880/1", "3796", "3200"]

BENCH_CATEGORIES = [
    {"key": "light",   "name": "صناعي خفيف",  "plan": "2377",            "bench_label": "المصفاة 2377"},
    {"key": "medium",  "name": "صناعي متوسط", "plan": "__industrial__",  "bench_label": "صناعي مرجّح"},
    {"key": "wh",      "name": "مستودعات",    "plan": "3796",            "bench_label": "مستودعات 3796"},
    {"key": "factory", "name": "مصانع جاهزة", "plan": None,              "bench_label": "مبانٍ السلي (سياق)"},
    {"key": "comm",    "name": "تجاري",       "plan": None,              "bench_label": "لا مقارنة مباشرة"},
    {"key": "res",     "name": "سكني",        "plan": "3200",            "bench_label": "سكن عمالة 3200"},
]

AREA_BUCKETS = [
    ("أقل من 500م²", 0, 500),
    ("500–1000م²", 500, 1000),
    ("1000–5000م²", 1000, 5000),
    ("أكثر من 5000م²", 5000, float("inf")),
]


# ─────────────────────────────────────────────────────────────────────────────
# أدوات إحصائية (بلا اعتماديات خارجية)
# ─────────────────────────────────────────────────────────────────────────────
def percentile(values, q):
    """نسبة مئوية بالاستيفاء الخطّي. values قائمة أرقام غير فارغة، q في [0,1]."""
    s = sorted(values)
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(s):
        return s[lo] + (s[lo + 1] - s[lo]) * frac
    return s[lo]


def median(values):
    return percentile(values, 0.5)


def trim_outliers(values):
    """يُرجع (kept, removed_count) باستخدام IQR×1.5. أقل من 4 قيم → بلا قصّ."""
    if len(values) < 4:
        return list(values), 0
    q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [v for v in values if lo <= v <= hi]
    return kept, len(values) - len(kept)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_d(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def r1(x):
    return None if x is None else round(x, 1)


def ri(x):
    return None if x is None else int(round(x))


# ─────────────────────────────────────────────────────────────────────────────
# الحساب الأساسي (دالة نقية — قابلة للاختبار)
# ─────────────────────────────────────────────────────────────────────────────
def monthly_series(deals, months_back=24):
    """median السعر وعدد الصفقات شهرياً لآخر months_back شهراً (مرتّبة زمنياً تصاعدياً)."""
    buckets = {}
    for dd in deals:
        d = dd["_date"]
        if not d:
            continue
        buckets.setdefault(month_key(d), []).append(dd)
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months_back):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    keys = sorted(keys)
    out = []
    for k in keys:
        rows = buckets.get(k, [])
        prices = [r["meter_price"] for r in rows if r["meter_price"]]
        out.append({"month": k, "median": ri(median(prices)) if prices else None, "count": len(rows)})
    return out


def momentum(series):
    """MoM% و QoQ% من السلسلة الشهرية (آخر قيمة غير فارغة)."""
    pts = [(s["month"], s["median"]) for s in series if s["median"] is not None]
    mom = qoq = None
    if len(pts) >= 2:
        cur = pts[-1][1]
        prev = pts[-2][1]
        if prev:
            mom = (cur - prev) / prev * 100
        # QoQ: مقابل قبل 3 نقاط (تقريب الربع)
        if len(pts) >= 4 and pts[-4][1]:
            qoq = (cur - pts[-4][1]) / pts[-4][1] * 100
    return r1(mom), r1(qoq)


def plan_stats(plan, deals):
    meta = PLAN_META[plan]
    rows = [d for d in deals if d["plan_norm"] == plan]
    prices_all = [d["meter_price"] for d in rows if d["meter_price"]]
    kept, removed = trim_outliers(prices_all)
    count = len(rows)
    insufficient = len([p for p in prices_all]) < MIN_DEALS
    series = monthly_series(rows)
    mom, qoq = momentum(series)
    med = ri(median(kept)) if kept else None

    flag = "insufficient"
    if not insufficient and med is not None:
        lo, hi = meta["ref"]
        flag = "below" if med < lo else ("above" if med > hi else "in")

    last_deal = max((d["_date"] for d in rows if d["_date"]), default=None)
    return {
        "plan": plan,
        "label": meta["label"],
        "short": meta["short"],
        "color": meta["color"],
        "ref_range": meta["ref"],
        "median": med,
        "p25": ri(percentile(kept, 0.25)) if kept else None,
        "p75": ri(percentile(kept, 0.75)) if kept else None,
        "count": count,
        "priced_count": len(prices_all),
        "removed_outliers": removed,
        "total_area": ri(sum(d["area"] for d in rows if d["area"])) if rows else 0,
        "total_value": ri(sum(d["amount"] for d in rows if d["amount"])) if rows else 0,
        "last_deal": last_deal.isoformat() if last_deal else None,
        "mom_pct": mom,
        "qoq_pct": qoq,
        "flag": flag,
        "insufficient": insufficient,
        "monthly": series,
    }


def liquidity(deals):
    series = monthly_series(deals)
    counts = [(s["month"], s["count"]) for s in series]
    this_month = counts[-1][1] if counts else 0
    prior = [c for _, c in counts[-4:-1]] if len(counts) >= 4 else []
    avg_prior = sum(prior) / len(prior) if prior else None
    trend = "flat"
    if avg_prior is not None:
        trend = "up" if this_month > avg_prior else ("down" if this_month < avg_prior else "flat")
    return {
        "this_month": this_month,
        "avg_prior_3m": r1(avg_prior) if avg_prior is not None else None,
        "trend": trend,
        "months": [{"month": s["month"], "count": s["count"]} for s in series],
    }


def demand(deals):
    by_area = []
    for label, lo, hi in AREA_BUCKETS:
        n = sum(1 for d in deals if d["area"] and lo <= d["area"] < hi)
        by_area.append({"label": label, "count": n})
    usage_counts = {}
    for d in deals:
        u = d["usage"] or d["type"] or "غير محدّد"
        usage_counts[u] = usage_counts.get(u, 0) + 1
    by_usage = sorted(
        [{"label": k, "count": v} for k, v in usage_counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:6]
    return {"by_area_bucket": by_area, "by_usage": by_usage}


def benchmarks(plans):
    med = {p: plans[p]["median"] for p in PLAN_ORDER}
    industrial = [med[p] for p in ("2377", "3880/1") if med.get(p)]
    ind_avg = ri(sum(industrial) / len(industrial)) if industrial else None
    out = []
    for cat in BENCH_CATEGORIES:
        if cat["plan"] == "__industrial__":
            bench = ind_avg
        elif cat["plan"]:
            bench = med.get(cat["plan"])
        else:
            bench = None
        out.append({"key": cat["key"], "name": cat["name"],
                    "bench": bench, "bench_label": cat["bench_label"]})
    return out


def notable_deals(deals, plans):
    today = date.today()
    med = {p: plans[p]["median"] for p in PLAN_ORDER}
    out = []
    for d in deals:
        if not d["_date"] or (today - d["_date"]).days > NOTABLE_DAYS:
            continue
        plan = d["plan_norm"]
        kind = delta = None
        m = med.get(plan)
        if m and d["meter_price"]:
            delta = (d["meter_price"] - m) / m * 100
            if delta >= NOTABLE_PCT:
                kind = "high"
            elif delta <= -NOTABLE_PCT:
                kind = "low"
        if kind is None and d["area"] and d["area"] >= LARGE_AREA:
            kind = "large"
        if kind:
            out.append({
                "date": d["_date"].isoformat(), "plan": plan or "—",
                "plan_short": PLAN_META.get(plan, {}).get("short", plan or "—"),
                "area": ri(d["area"]), "meter_price": ri(d["meter_price"]),
                "type": d["type"] or d["usage"], "kind": kind,
                "delta_pct": r1(delta) if delta is not None else None,
            })
    out.sort(key=lambda x: (x["kind"] != "large", -(x["delta_pct"] or 0)))
    return out[:8]


def compute_metrics(raw_deals, *, sample=False, source_date=None):
    """دالة نقية: تأخذ صفوف deals وتُرجع dict المؤشرات الكاملة."""
    deals = []
    for d in raw_deals:
        nd = dict(d)
        nd["_date"] = parse_d(d.get("transaction_date"))
        nd["plan_norm"] = (d.get("plan") or "").strip()
        deals.append(nd)

    plans = {p: plan_stats(p, deals) for p in PLAN_ORDER}
    total_removed = sum(p["removed_outliers"] for p in plans.values())
    priced = [d["meter_price"] for d in deals if d["meter_price"]]

    # صفوف الخريطة/الجدول (إحداثيات حقيقية فقط؛ بلا اختلاق)
    map_rows = []
    for d in sorted(deals, key=lambda x: x["_date"] or date.min, reverse=True)[:MAP_CAP]:
        map_rows.append({
            "transaction_date": d["_date"].isoformat() if d["_date"] else None,
            "plan": d["plan_norm"] or "—", "parcel": d.get("parcel"),
            "area": ri(d.get("area")), "meter_price": ri(d.get("meter_price")),
            "type": d.get("type"), "usage": d.get("usage"),
            "lat": d.get("lat"), "lng": d.get("lng"),
        })

    last_date = max((d["_date"] for d in deals if d["_date"]), default=None)
    if sample:
        source_note = "بيانات توضيحية (نموذج): ليست صفقات حقيقية"
    else:
        as_of = source_date or last_date or date.today()
        source_note = f"المصدر: السجل العقاري عبر بسيطة، حتى {as_of.isoformat()}"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sample": sample,
        "source_note": source_note,
        "data_window": {"months": 24, "last_date": last_date.isoformat() if last_date else None},
        "row_count": len(deals),
        "priced_count": len(priced),
        "excluded_outliers": total_removed,
        "plans": plans,
        "totals": {
            "median": ri(median(priced)) if priced else None,
            "count": len(deals),
            "total_area": ri(sum(d["area"] for d in deals if d.get("area"))),
            "total_value": ri(sum(d["amount"] for d in deals if d.get("amount"))),
        },
        "liquidity": liquidity(deals),
        "demand": demand(deals),
        "benchmarks": benchmarks(plans),
        "notable_deals": notable_deals(deals, plans),
        "white_land_fee": None,  # طبقة بسيطة منفصلة — تُضاف عند توفّرها (لا اختلاق)
        "deals": map_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# المصادر: قاعدة البيانات أو بيانات توضيحية
# ─────────────────────────────────────────────────────────────────────────────
def load_from_db():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT transaction_date, plan, parcel, real_estate_number, area, usage, type, "
        "meter_price, amount, lat, lng FROM deals"
    ).fetchall()]
    conn.close()
    return rows


def sample_deals():
    """مجموعة توضيحية صغيرة لاختبار عرض الواجهة فقط — مُعلَّمة sample=true في المخرجات."""
    import math
    base = {"2377": (1820, [1600, 2000], 24.491, 46.876),
            "3880/1": (1540, [1100, 2400], 24.501, 46.901),
            "3796": (1880, [1200, 1900], 24.476, 46.860),
            "3200": (1050, [833, 1200], 24.485, 46.890)}
    types = {"2377": "صناعي", "3880/1": "صناعي", "3796": "مستودع", "3200": "سكن عمالة"}
    areas = {"2377": [480, 625, 710], "3880/1": [4800, 5000, 5100],
             "3796": [1200, 1500, 1800], "3200": [600, 620, 650]}
    out = []
    today = date.today()
    counts = {"2377": 28, "3880/1": 12, "3796": 9, "3200": 15}
    # مسار شهري مميّز لكل مخطط (ميل سنوي · سعة موسميّة · طور) كي تختلف خطوط
    # الاتجاه ونِسب التغيّر فعليًّا بدل أن تتطابق صورتها بعد التطبيع.
    traj = {"2377": (0.009, 0.045, 0.0), "3880/1": (-0.004, 0.110, 1.7),
            "3796": (0.013, 0.030, 3.1), "3200": (-0.006, 0.050, 4.6)}
    lng_scale = 1.0 / math.cos(math.radians(24.49))   # تعويض انضغاط درجات الطول لتبدو الدائرة دائرة
    for pi, (plan, (center, _ref, lat0, lng0)) in enumerate(base.items()):
        slope, amp, phase = traj[plan]
        for i in range(counts[plan]):
            months_ago = i % 12
            y, m = today.year, today.month - months_ago
            while m <= 0:
                m += 12
                y -= 1
            day = 1 + (i * 3) % 27
            seasonal = amp * math.sin(0.55 * months_ago + phase)   # موجة موسميّة بطور مختلف
            noise = ((i % 5) - 2) * 0.010                          # تشتّت بسيط داخل الشهر
            price = round(center * (1 - slope * months_ago + seasonal + noise))
            area = areas[plan][i % 3]
            # تشتّت طبيعي حتميّ داخل قرص حول مركز المخطط (لا حلقات): زاوية عشوائيّة + نصف قطر
            # بجذر تربيعي لتوزيع متجانس على المساحة بدل التكدّس في المركز.
            seed = (pi * 0x9E3779B1 + (i + 1) * 0x85EBCA77) & 0xFFFFFFFF
            ang = (seed % 4096) / 4096.0 * 2 * math.pi
            r = 0.0010 + math.sqrt(((seed >> 12) % 4096) / 4096.0) * 0.0040
            out.append({
                "transaction_date": f"{y:04d}-{m:02d}-{day:02d}",
                "plan": plan, "parcel": str(100 + i),
                "real_estate_number": f"SAMPLE-{plan}-{i}",
                "area": area, "usage": types[plan], "type": types[plan],
                "meter_price": price, "amount": price * area,
                "lat": round(lat0 + math.sin(ang) * r, 6),
                "lng": round(lng0 + math.cos(ang) * r * lng_scale, 6),
            })

    # صفقات لافتة حديثة (≤30 يومًا) لتفعيل قسم «صفقات لافتة»: كبيرة / مرتفعة / منخفضة
    notable_seed = [
        ("3880/1", 5,  5200, 1635, "مستودع"),     # كبيرة (مساحة ≥ 5000 م²)
        ("2377",   9,  710,  2080, "صناعي"),       # مرتفعة (> +10% عن السائد)
        ("3200",   13, 650,  905,  "سكن عمالة"),   # منخفضة (> -10% عن السائد)
    ]
    for k, (plan, days_ago, area, price, typ) in enumerate(notable_seed):
        center, _ref, lat0, lng0 = base[plan]
        dt = today - timedelta(days=days_ago)
        seed = (k * 0x9E3779B1 + 0x517CC1B7) & 0xFFFFFFFF
        ang = (seed % 4096) / 4096.0 * 2 * math.pi
        r = 0.0012 + math.sqrt(((seed >> 12) % 4096) / 4096.0) * 0.0030
        out.append({
            "transaction_date": dt.isoformat(),
            "plan": plan, "parcel": str(900 + k),
            "real_estate_number": f"SAMPLE-N-{plan}-{k}",
            "area": area, "usage": typ, "type": typ,
            "meter_price": price, "amount": price * area,
            "lat": round(lat0 + math.sin(ang) * r, 6),
            "lng": round(lng0 + math.cos(ang) * r * lng_scale, 6),
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="حساب مؤشرات لوحة طايا")
    ap.add_argument("--sample", action="store_true",
                    help="استخدم بيانات توضيحية مُعلَّمة لاختبار عرض الواجهة")
    args = ap.parse_args(argv)

    if args.sample:
        deals = sample_deals()
        metrics = compute_metrics(deals, sample=True)
    else:
        deals = load_from_db()
        metrics = compute_metrics(deals, sample=False)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    tag = "توضيحية" if args.sample else "حقيقية"
    print(f"[analytics] كُتب {OUT_PATH.relative_to(ROOT)} — {metrics['row_count']} صفقة ({tag})، "
          f"مستبعدة={metrics['excluded_outliers']}، إجمالي median={metrics['totals']['median']}")
    if not args.sample and metrics["row_count"] == 0:
        print("[analytics] تنبيه: لا صفقات في القاعدة بعد — شغّل fetch.py أولاً (بعد --login).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
