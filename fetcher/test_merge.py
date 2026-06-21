# -*- coding: utf-8 -*-
"""
اختبارات وحدة لمحرّك الدمج وإزالة التكرار (fetcher/merge.py).
الضمانة الأساسيّة: لا دمج إلا برقم الصفقة الرسميّ — ولا إتلاف لصفقات متمايزة بالصفات.
تشغيل:  pytest fetcher/test_merge.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import merge  # noqa: E402


def _rec(source, tx_no, date="2026-06-01", area=500.0, total=600000, **kw):
    r = {"source": source, "tx_no": tx_no, "date": date, "area": area,
         "meter_price": round(total / area) if area else None, "total_price": total,
         "type": "صناعي", "neighborhood": "المصفاة", "lat": 24.49, "lng": 46.87}
    r.update(kw)
    return r


def test_same_txno_across_sources_dedupes_keeping_suhail():
    recs = [_rec("baseeta", 555), _rec("suhail", 555)]
    unique, removed, no_key = merge.merge(recs)
    assert removed == 1
    assert len(unique) == 1
    assert unique[0]["source"] == "suhail"  # الأغنى مصدرًا يُبقى


def test_identical_attributes_different_txno_are_kept():
    # نفس التاريخ/المساحة/السعر لكن رقمَي صفقة مختلفين → صفقتان متمايزتان، لا تُدمجان
    recs = [_rec("suhail", 1001), _rec("suhail", 1002)]
    unique, removed, no_key = merge.merge(recs)
    assert removed == 0
    assert len(unique) == 2


def test_records_without_txno_pass_through_and_counted():
    recs = [_rec("baseeta", None), _rec("baseeta", None)]
    unique, removed, no_key = merge.merge(recs)
    assert removed == 0
    assert no_key == 2
    assert len(unique) == 2  # لا يُجمعان بالصفات أبدًا


def test_no_false_merge_between_live_and_sample():
    # سهيل (بأرقام) + بسيطة عيّنة (بلا أرقام) → لا مكرّرات مُزالة
    recs = [_rec("suhail", 7), _rec("suhail", 8), _rec("baseeta", None)]
    unique, removed, no_key = merge.merge(recs)
    assert removed == 0
    assert len(unique) == 3


def test_aggregate_counts_and_median():
    recs = [_rec("suhail", 1, total=500000, area=500.0),   # pm=1000
            _rec("suhail", 2, total=900000, area=600.0),   # pm=1500
            _rec("suhail", 3, total=800000, area=400.0)]   # pm=2000
    unique, removed, no_key = merge.merge(recs)
    from collections import Counter
    agg = merge.aggregate(unique, Counter(r["source"] for r in unique), removed, no_key, {})
    assert agg["summary"]["deal_count"] == 3
    assert agg["summary"]["median_price_of_meter"] == 1500.0
