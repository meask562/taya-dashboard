#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مولّد مخزون قطع طايا (عيّنة) → site/data/inventory.json.

بيانات توضيحيّة مُعلَّمة sample=true حتى يُربط لاحقًا بمصدر آليّ (خريطة طايا/
النظام الداخلي). كل قطعة: رقم · قطاع · مساحة · حالة (متاح/محجوز/مباع) ·
سعر طلب، وللمباعة سعر/تاريخ بيع، وإحداثيات داخل نطاق طايا للخريطة.

التصميم مقصود حتميّ (بلا عشوائيّة) كي يُعاد إنتاجه بثبات.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "site" / "data" / "inventory.json"

TIC_LAT, TIC_LNG = 24.491, 46.876
_LNG_SCALE = 1.0 / math.cos(math.radians(TIC_LAT))

# قطاعات طايا الستّة — المفاتيح تطابق benchmarks في metrics.json.
# الإجمالي يطابق الرقم الرسمي في tic-taya.sa (+728 فرصة استثماريّة على 3.6M م²).
# (المفتاح، الاسم، البادئة، سعر الطلب التقريبي ر.س/م²، إجمالي القطع، عدد المباع، عدد المحجوز، متوسط المساحة)
SECTORS = [
    ("light",   "صناعي خفيف",  "LI", 1850, 220, 130,  8, 560),
    ("medium",  "صناعي متوسط", "MI", 1700, 150,  70, 12, 1500),
    ("wh",      "مستودعات",    "WH", 1800, 130,  95,  5, 1400),
    ("factory", "مصانع جاهزة", "FC", 2200,  80,  22,  6, 900),
    ("comm",    "تجاري",       "CM", 3000,  60,  14,  5, 700),
    ("res",     "سكني",        "RS", 1100,  88,  60,  4, 620),
]


def _scatter(k):
    """إحداثيات حتميّة داخل قرص طايا (نصف قطر ~900م)."""
    seed = (k * 0x9E3779B1 + 0x2545F491) & 0xFFFFFFFF
    ang = (seed % 4096) / 4096.0 * 2 * math.pi
    r = 0.0012 + math.sqrt(((seed >> 12) % 4096) / 4096.0) * 0.0105
    return (round(TIC_LAT + math.sin(ang) * r, 6),
            round(TIC_LNG + math.cos(ang) * r * _LNG_SCALE, 6))


def sample_plots(today=None):
    today = today or date.today()
    plots = []
    gi = 0
    for key, name, prefix, ask, total, sold, reserved, base_area in SECTORS:
        for j in range(total):
            gi += 1
            # تنويع المساحة حتميًّا حول متوسط القطاع (±~25%)
            area = int(round(base_area * (0.78 + ((j * 7) % 9) / 18.0)))
            lat, lng = _scatter(gi)
            plot = {
                "plot_no": f"{prefix}-{101 + j}",
                "sector": key, "sector_name": name,
                "area": area, "asking_price": ask,
                "lat": lat, "lng": lng,
            }
            if j < sold:
                # مباعة: سعر بيع قريب من الطلب (±6%) وتاريخ خلال آخر ~10 أشهر
                factor = 1 + (((j * 5) % 7) - 3) * 0.02
                plot["status"] = "sold"
                plot["sold_price"] = int(round(ask * factor))
                days_ago = 12 + (j * 23) % 285          # موزّع على ~10 أشهر
                plot["sold_date"] = (today - timedelta(days=days_ago)).isoformat()
            elif j < sold + reserved:
                plot["status"] = "reserved"
            else:
                plot["status"] = "available"
            plots.append(plot)
    return plots


def build(today=None):
    today = today or date.today()
    plots = sample_plots(today)
    return {
        "generated_at": today.isoformat() + "T00:00:00",
        "sample": True,
        "source_note": ("بيانات مخزون توضيحيّة — تُربط آليًّا لاحقًا بخريطة طايا "
                        "ثلاثيّة الأبعاد/النظام الداخلي."),
        "tic_center": [TIC_LAT, TIC_LNG],
        "plots": plots,
    }


def main():
    data = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data["plots"])
    sold = sum(1 for p in data["plots"] if p["status"] == "sold")
    avail = sum(1 for p in data["plots"] if p["status"] == "available")
    print(f"[inventory] كُتب {OUT_PATH.relative_to(ROOT)} — {n} قطعة "
          f"(مباع {sold} · متاح {avail}).")


if __name__ == "__main__":
    main()
