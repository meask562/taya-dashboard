#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher/merge.py — محرّك دمج صفقات السوق من عدّة مصادر + إزالة التكرار → site/data/market.json

مستقلّ عن المصدر: يقرأ سجلّات صفقات موحّدة من كل مصدر مُسجَّل ويدمجها ويزيل التكرار،
ثم يحسب مؤشّرات سوق طايا المدمجة (سيولة شهريّة، وسيط سعر المتر الشهري، تفصيل بالحي/الاستخدام،
أحدث الصفقات، نقاط الخريطة)، مع إحصاء لكل مصدر وعدد المكرّرات المُزالة.

المصادر الآن:
  • سهيل  → site/data/suhail.json["transactions"]  (حيّ — حقيقي)
  • بسيطة → site/data/metrics.json["deals"]        (عيّنة الآن؛ تنضمّ حيًّا حين تجهز)

إزالة التكرار: المصدران ينهلان من إفراغات وزارة العدل، فقد تتكرّر الصفقة. المفتاح هو
**رقم الصفقة الرسميّ** (tx_no) حصرًا — لأن الدمج بالصفات (تاريخ/مساحة/سعر) يُتلف صفقات
متمايزة (قطع نمطيّة كثيرة تُباع بنفس اليوم/المساحة/السعر بأرقام صفقات مختلفة). عند تطابق
tx_no نُبقي الأغنى مصدرًا (أولويّة: suhail > baseeta). سجلّ بلا tx_no يمرّ كما هو (يُحصى،
ولا يُجمع بالصفات أبدًا). فحين تجهز بسيطة حيًّا بأرقام وزارة العدل يُزال التكرار الحقيقي تلقائيًّا.

تشغيل:
    python fetcher/merge.py        # يدمج المتوفّر من المصادر → market.json
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUHAIL_PATH = ROOT / "site" / "data" / "suhail.json"
METRICS_PATH = ROOT / "site" / "data" / "metrics.json"
OUT_PATH = ROOT / "site" / "data" / "market.json"

# أولويّة المصدر عند التكرار (الأعلى يُبقى)
SOURCE_PRIORITY = {"suhail": 2, "baseeta": 1}
MAP_CAP = 1500


def _median(xs):
    xs = [x for x in xs if x]
    return round(statistics.median(xs), 1) if xs else None


def load_suhail() -> list[dict]:
    """سجلّات سهيل الموحّدة (suhail.py يكتبها مُطبَّعة مسبقًا)."""
    if not SUHAIL_PATH.exists():
        return []
    d = json.loads(SUHAIL_PATH.read_text(encoding="utf-8"))
    return list(d.get("transactions") or [])


def load_baseeta() -> list[dict]:
    """صفقات بسيطة من metrics.json["deals"] → سجلّات موحّدة (عيّنة الآن)."""
    if not METRICS_PATH.exists():
        return []
    d = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    out = []
    for x in d.get("deals") or []:
        area = x.get("area")
        pm = x.get("meter_price")
        total = round(pm * area) if pm and area else None
        out.append({
            "source": "baseeta",
            "tx_no": x.get("transaction_no"),  # عيّنة بسيطة بلا رقم الآن؛ يُملأ عند الربط الحيّ
            "date": x.get("transaction_date"),
            "plan": x.get("plan"),
            "parcel": str(x["parcel"]) if x.get("parcel") is not None else None,
            "area": round(area, 1) if area else None,
            "meter_price": round(pm) if pm else None,
            "total_price": total,
            "type": x.get("type") or x.get("usage"),
            "neighborhood": None,
            "lat": x.get("lat"), "lng": x.get("lng"),
        })
    return out


def dedupe_key(r: dict):
    """رقم الصفقة الرسميّ (وزارة العدل) حصرًا — لا دمج بالصفات (يُتلف صفقات متمايزة)."""
    n = r.get("tx_no")
    return ("txno", n) if n is not None else None


def merge(records: list[dict]) -> tuple[list[dict], int, int]:
    """يدمج السجلّات ويزيل المكرّرات برقم الصفقة؛ يُرجِع (الفريدة، عدد المُزال، بلا رقم)."""
    best: dict = {}
    passthrough: list[dict] = []
    removed = 0
    no_key = 0
    for r in records:
        k = dedupe_key(r)
        if k is None:
            no_key += 1
            passthrough.append(r)  # بلا رقم رسميّ → يمرّ كما هو (لا يُجمع بالصفات)
            continue
        if k not in best:
            best[k] = r
        else:
            removed += 1
            cur = best[k]
            if SOURCE_PRIORITY.get(r["source"], 0) > SOURCE_PRIORITY.get(cur["source"], 0):
                best[k] = r  # أبقِ الأغنى مصدرًا
    return list(best.values()) + passthrough, removed, no_key


def aggregate(unique: list[dict], by_source: Counter, removed: int, no_key: int, sources_meta: dict) -> dict:
    priced = [r["meter_price"] for r in unique if r.get("meter_price")]
    values = [r["total_price"] for r in unique if r.get("total_price")]

    by_month = defaultdict(list)
    for r in unique:
        ym = (r.get("date") or "")[:7]
        if ym:
            by_month[ym].append(r.get("meter_price"))
    months = sorted(by_month)
    monthly = [{"ym": m, "count": len(by_month[m]), "median_pm": _median(by_month[m])} for m in months]

    # سيولة: الشهر الحالي مقابل متوسط الأشهر الثلاثة السابقة
    this_month = monthly[-1]["count"] if monthly else 0
    prior3 = [s["count"] for s in monthly[-4:-1]] if len(monthly) >= 2 else []
    avg_prior_3m = round(sum(prior3) / len(prior3), 1) if prior3 else None

    by_hood = defaultdict(list)
    by_use = defaultdict(list)
    for r in unique:
        if r.get("neighborhood"):
            by_hood[r["neighborhood"]].append(r.get("meter_price"))
        if r.get("type"):
            by_use[r["type"]].append(r.get("meter_price"))

    recent = sorted([r for r in unique if r.get("date")], key=lambda r: r["date"], reverse=True)[:12]
    map_points = [{"lat": r["lat"], "lng": r["lng"], "pm": r.get("meter_price"),
                   "source": r["source"], "type": r.get("type")}
                  for r in unique if r.get("lat") and r.get("lng")][:MAP_CAP]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": sources_meta,
        "merge": {
            "by_source": dict(by_source),
            "duplicates_removed": removed,
            "without_tx_no": no_key,
            "unique_total": len(unique),
            "dedupe_key": "official transaction number (tx_no)",
        },
        "summary": {
            "deal_count": len(unique),
            "total_value": round(sum(values)) if values else None,
            "median_price_of_meter": _median(priced),
            "months_covered": months,
        },
        "liquidity": {"this_month": this_month, "avg_prior_3m": avg_prior_3m,
                      "months": [{"month": s["ym"], "count": s["count"]} for s in monthly]},
        "monthly": monthly,
        "by_neighborhood": [{"name": n, "count": len(v), "median_pm": _median(v)}
                            for n, v in sorted(by_hood.items(), key=lambda kv: -len(kv[1]))],
        "by_use": [{"use": g, "count": len(v), "median_pm": _median(v)}
                   for g, v in sorted(by_use.items(), key=lambda kv: -len(kv[1]))],
        "deals_recent": recent,
        "map_points": map_points,
    }


def build() -> dict:
    suhail = load_suhail()
    baseeta = load_baseeta()
    records = suhail + baseeta
    by_source = Counter(r["source"] for r in records)

    # وسم حالة كل مصدر (حيّ/عيّنة)
    sources_meta = {}
    if SUHAIL_PATH.exists():
        sd = json.loads(SUHAIL_PATH.read_text(encoding="utf-8"))
        sources_meta["suhail"] = {"sample": sd.get("sample", True), "label": "سهيل",
                                  "count": by_source.get("suhail", 0)}
    if METRICS_PATH.exists():
        md = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        sources_meta["baseeta"] = {"sample": md.get("sample", True), "label": "بسيطة",
                                   "count": by_source.get("baseeta", 0)}

    unique, removed, no_key = merge(records)
    return aggregate(unique, by_source, removed, no_key, sources_meta)


def main() -> int:
    data = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    m = data["merge"]
    s = data["summary"]
    src = " · ".join(f"{v['label']} {v['count']}{' (عيّنة)' if v['sample'] else ' (حيّ)'}"
                     for v in data["sources"].values())
    print(f"[merge] كُتب {OUT_PATH.relative_to(ROOT)} — {s['deal_count']} صفقة فريدة "
          f"(مكرّرات مُزالة: {m['duplicates_removed']}) · المصادر: {src} · "
          f"وسيط {s['median_price_of_meter']} ر.س/م².")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
