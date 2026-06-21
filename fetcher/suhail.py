#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher/suhail.py — نموذج تجريبي: يسحب صفقات السوق الحقيقيّة من منصّة سهيل
(api2.suhail.ai) لمحيط مدينة طايا الصناعيّة ويكتب site/data/suhail.json.

اكتُشفت الواجهة بمراقبة شبكة تطبيق سهيل (الواجهة عامّة الوصول، ترويسة PLATFORM فقط).
يجمع صفقات الرياض (regionId=10) ثم يفلترها جغرافيًّا بمحيط طايا (centroidX/Y)، ويحسب:
الإجمالي/القيمة/وسيط سعر المتر، السلسلة الشهريّة (سيولة + وسيط سعر)، تفصيل بالحي والاستخدام،
أحدث الصفقات، ونقاط الخريطة. الوسيط لا المتوسط · كل رقم منسوب لمصدره وتاريخه · لا اختلاق.

⚠ ملاحظة قانونيّة: هذا نموذج تجريبي. الاستخدام البرمجي قد يخالف شروط سهيل —
المسار الإنتاجي السليم هو وصول API رسمي/اتفاق شراكة قبل أي تشغيل مجدوَل.

تشغيل:
    python fetcher/suhail.py            # سحب حيّ من سهيل → site/data/suhail.json
    python fetcher/suhail.py --sample   # بيانات توضيحية مُعلَّمة (بلا شبكة) لاختبار الواجهة
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "site" / "data" / "suhail.json"

# مصدر سهيل (مُكتشف من حزمة الواجهة العامّة)
API_BASE = "https://api2.suhail.ai/"
HEADERS = {"PLATFORM": "WEB", "Device-Id": "taya-dashboard-prototype", "Accept": "application/json"}
REGION_ID = 10          # الرياض
PROVINCE_ID = 101000    # الرياض

# محيط مدينة طايا الصناعيّة (يطابق tic_center في inventory.json)
TAYA_LAT, TAYA_LNG = 24.491, 46.876
RADIUS_DEG = 0.07       # ~7.5 كم

FETCH_LIMIT = 8000      # سقف صفوف الصفقات المسحوبة (الرياض)
MAP_CAP = 1500          # حدّ نقاط الخريطة في الإخراج
TIMEOUT = 60


def _get(path: str, params: dict) -> dict:
    url = API_BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _median(xs):
    xs = [x for x in xs if x]
    return round(statistics.median(xs), 1) if xs else None


def _in_taya(t) -> bool:
    cx, cy = t.get("centroidX"), t.get("centroidY")
    return bool(cx and cy and abs(cy - TAYA_LAT) < RADIUS_DEG and abs(cx - TAYA_LNG) < RADIUS_DEG)


def fetch_live() -> dict:
    payload = _get("api/transactions/search", {"regionId": REGION_ID, "offset": 0, "limit": FETCH_LIMIT})
    rows = payload["data"] if isinstance(payload, dict) else payload
    near = [t for t in rows if _in_taya(t)]
    if not near:
        raise RuntimeError("لا صفقات في محيط طايا من الاستجابة — راجع المعطيات.")

    # السلسلة الشهريّة: سيولة (عدد) + وسيط سعر المتر
    by_month_prices = defaultdict(list)
    for t in near:
        d = (t.get("transactionDate") or "")[:7]
        if d:
            by_month_prices[d].append(t.get("priceOfMeter"))
    monthly = [
        {"ym": m, "count": len(v), "median_pm": _median(v)}
        for m, v in sorted(by_month_prices.items())
    ]

    prices = [t.get("priceOfMeter") for t in near if t.get("priceOfMeter")]
    values = [t.get("transactionPrice") or t.get("totalTransactionPrice") for t in near]
    values = [v for v in values if v]

    by_hood = defaultdict(list)
    by_use = defaultdict(list)
    for t in near:
        by_hood[t.get("neighborhoodName") or "غير محدد"].append(t.get("priceOfMeter"))
        g = t.get("landUseGroup") or t.get("landuseagroup") or "غير محدد"
        by_use[g].append(t.get("priceOfMeter"))

    recent = sorted(near, key=lambda t: t.get("transactionDate") or "", reverse=True)[:12]
    deals_recent = [{
        "date": (t.get("transactionDate") or "")[:10],
        "neighborhood": t.get("neighborhoodName"),
        "use": t.get("landUseGroup") or t.get("landuseagroup"),
        "subdivision_no": t.get("subdivisionNo"),
        "area": t.get("area"),
        "price_of_meter": t.get("priceOfMeter"),
        "total_price": t.get("transactionPrice") or t.get("totalTransactionPrice"),
    } for t in recent]

    map_points = [{
        "lat": t["centroidY"], "lng": t["centroidX"],
        "pm": t.get("priceOfMeter"), "use": t.get("landUseGroup") or t.get("landuseagroup"),
    } for t in near if t.get("centroidX")][:MAP_CAP]

    transactions = [normalize_tx(t) for t in near]

    return {
        "sample": False,
        "source": "suhail.ai",
        "source_note": "صفقات حقيقيّة من منصّة سهيل (api2.suhail.ai) — نموذج تجريبي، تُراجَع شروط الاستخدام قبل الإنتاج.",
        "region_id": REGION_ID, "province_id": PROVINCE_ID,
        "taya_center": [TAYA_LAT, TAYA_LNG], "radius_km": round(RADIUS_DEG * 111, 1),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "deal_count": len(near),
            "total_value": round(sum(values)) if values else None,
            "median_price_of_meter": _median(prices),
            "months_covered": [m["ym"] for m in monthly],
        },
        "monthly": monthly,
        "by_neighborhood": [{"name": n, "count": len(v), "median_pm": _median(v)}
                            for n, v in sorted(by_hood.items(), key=lambda kv: -len(kv[1]))],
        "by_use": [{"use": g, "count": len(v), "median_pm": _median(v)}
                   for g, v in sorted(by_use.items(), key=lambda kv: -len(kv[1]))],
        "deals_recent": deals_recent,
        "map_points": map_points,
        "transactions": transactions,
    }


def normalize_tx(t) -> dict:
    """صفقة سهيل → سجلّ موحّد مستقلّ عن المصدر (لمحرّك الدمج fetcher/merge.py)."""
    pm = t.get("priceOfMeter")
    area = t.get("area")
    total = t.get("transactionPrice") or t.get("totalTransactionPrice")
    if not total and pm and area:
        total = round(pm * area)
    return {
        "source": "suhail",
        "tx_no": t.get("originalTransactionNumber") or t.get("transactionNumber"),
        "date": (t.get("transactionDate") or "")[:10] or None,
        "plan": t.get("subdivisionNo"),
        "parcel": str(t.get("parcelNo")) if t.get("parcelNo") is not None else None,
        "area": round(area, 1) if area else None,
        "meter_price": round(pm) if pm else None,
        "total_price": round(total) if total else None,
        "type": t.get("landUseGroup") or t.get("landuseagroup"),
        "neighborhood": t.get("neighborhoodName"),
        "lat": t.get("centroidY"), "lng": t.get("centroidX"),
    }


def sample() -> dict:
    """بيانات توضيحية مُعلَّمة (بلا شبكة) — لاختبار عرض الواجهة فقط."""
    today = date.today()
    return {
        "sample": True, "source": "suhail.ai (عيّنة)",
        "source_note": "بيانات توضيحيّة — شغّل بلا --sample لسحب حيّ من سهيل.",
        "region_id": REGION_ID, "province_id": PROVINCE_ID,
        "taya_center": [TAYA_LAT, TAYA_LNG], "radius_km": 7.8,
        "generated_at": today.isoformat() + "T00:00:00",
        "summary": {"deal_count": 313, "total_value": 489_000_000,
                    "median_price_of_meter": 1200.0,
                    "months_covered": ["2026-04", "2026-05", "2026-06"]},
        "monthly": [{"ym": "2026-04", "count": 96, "median_pm": 1150.0},
                    {"ym": "2026-05", "count": 121, "median_pm": 1205.0},
                    {"ym": "2026-06", "count": 96, "median_pm": 1240.0}],
        "by_neighborhood": [{"name": "طيبة", "count": 245, "median_pm": 1180.0},
                            {"name": "المصفاة", "count": 57, "median_pm": 1320.0},
                            {"name": "الغنامية", "count": 7, "median_pm": 980.0}],
        "by_use": [{"use": "أرض سكني", "count": 210, "median_pm": 1100.0},
                   {"use": "أرض صناعي", "count": 64, "median_pm": 1450.0}],
        "deals_recent": [], "map_points": [],
        "transactions": [
            {"source": "suhail", "tx_no": -900001, "date": "2026-06-15", "plan": "3533",
             "parcel": "12", "area": 221.2, "meter_price": 2770, "total_price": 612800,
             "type": "سكني", "neighborhood": "طيبة", "lat": 24.487, "lng": 46.895},
            {"source": "suhail", "tx_no": -900002, "date": "2026-05-20", "plan": "2377",
             "parcel": "8", "area": 600.0, "meter_price": 1434, "total_price": 860400,
             "type": "مصانع", "neighborhood": "المصفاة", "lat": 24.50, "lng": 46.88},
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="سحب صفقات سهيل لمحيط طايا → suhail.json")
    ap.add_argument("--sample", action="store_true", help="بيانات توضيحية بلا شبكة")
    args = ap.parse_args()

    if args.sample:
        data = sample()
    else:
        try:
            data = fetch_live()
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, KeyError, ValueError) as e:
            print(f"[suhail] تعذّر السحب الحيّ ({e}) — اكتب عيّنة بدلًا منه.", file=sys.stderr)
            data = sample()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    s = data["summary"]
    tag = "عيّنة" if data["sample"] else "حيّ"
    print(f"[suhail] كُتب {OUT_PATH.relative_to(ROOT)} ({tag}) — "
          f"{s['deal_count']} صفقة · وسيط {s['median_price_of_meter']} ر.س/م² · "
          f"أشهر {', '.join(s['months_covered'])}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
