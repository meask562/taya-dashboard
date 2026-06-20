# -*- coding: utf-8 -*-
"""
اختبارات وحدة لطبقة التطبيع والمطابقة في fetch.py.
تشغيل:  pytest fetcher/test_normalize.py -q
لا تتطلّب Playwright (الاستيراد كسول داخل دوال الجلب).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fetch  # noqa: E402


# ── normalize_digits ──────────────────────────────────────────────────────────
def test_normalize_arabic_indic_digits():
    assert fetch.normalize_digits("١٢٣٤٥٦٧٨٩٠") == "1234567890"


def test_normalize_extended_arabic_digits():
    assert fetch.normalize_digits("۱۲۳") == "123"


def test_normalize_mixed_and_separators():
    # فاصلة آلاف عربية تُحذف، فاصلة عشرية عربية تصبح نقطة
    assert fetch.normalize_digits("١٬٨٢٠") == "1820"
    assert fetch.normalize_digits("١٫٥") == "1.5"


def test_normalize_none_and_passthrough():
    assert fetch.normalize_digits(None) == ""
    assert fetch.normalize_digits("ABC 12") == "ABC 12"


# ── to_number ────────────────────────────────────────────────────────────────
def test_to_number_arabic_price():
    assert fetch.to_number("١,٨٢٠") == 1820.0
    assert fetch.to_number("١٬٨٢٠") == 1820.0


def test_to_number_with_currency_text():
    assert fetch.to_number("1,840 ر.س/م²") == 1840.0


def test_to_number_decimal():
    assert fetch.to_number("٠٫٥") == 0.5


def test_to_number_passthrough_numeric():
    assert fetch.to_number(1500) == 1500.0
    assert fetch.to_number(1500.5) == 1500.5


def test_to_number_empty_returns_none():
    assert fetch.to_number(None) is None
    assert fetch.to_number("") is None
    assert fetch.to_number("لا يوجد") is None


# ── parse_date ───────────────────────────────────────────────────────────────
def test_parse_date_iso():
    d = fetch.parse_date("2026-06-18")
    assert (d.year, d.month, d.day) == (2026, 6, 18)


def test_parse_date_arabic_digits():
    d = fetch.parse_date("٢٠٢٦-٠٦-١٨")
    assert (d.year, d.month, d.day) == (2026, 6, 18)


def test_parse_date_with_time():
    d = fetch.parse_date("2026-06-18T07:30:00")
    assert (d.year, d.month, d.day) == (2026, 6, 18)


def test_parse_date_invalid_returns_none():
    assert fetch.parse_date("ليس تاريخاً") is None
    assert fetch.parse_date(None) is None


# ── find_rows (تغليفات استجابة مختلفة) ────────────────────────────────────────
def test_find_rows_plain_list():
    assert fetch.find_rows([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_find_rows_data_key():
    assert fetch.find_rows({"data": [{"x": 1}]}) == [{"x": 1}]


def test_find_rows_laravel_paginator():
    payload = {"data": {"current_page": 1, "data": [{"x": 1}, {"x": 2}]}}
    assert fetch.find_rows(payload) == [{"x": 1}, {"x": 2}]


def test_find_rows_empty():
    assert fetch.find_rows({"meta": {"total": 0}}) == []


# ── map_row (مطابقة + اشتقاق سعر المتر) ───────────────────────────────────────
def test_map_row_basic_fields():
    raw = {
        "transaction_date": "2026-06-18", "plan": "2377", "parcel": "12",
        "real_estate_number": "RE-9", "area": "٦٢٥", "meter_price": "١,٨٤٠",
        "type": "صناعي", "usage": "صناعي",
    }
    m = fetch.map_row(raw)
    assert m["transaction_date"] == "2026-06-18"
    assert m["plan"] == "2377"
    assert m["area"] == 625.0
    assert m["meter_price"] == 1840.0
    assert m["meter_price_derived"] == 0
    assert m["source"] == "Paseetah/RER"


def test_map_row_derives_meter_price_from_amount():
    raw = {"transaction_date": "2026-06-15", "plan": "3880/1", "parcel": "5",
           "real_estate_number": "RE-1", "area": "1000", "amount": "1500000"}
    m = fetch.map_row(raw)
    assert m["meter_price"] == 1500.0
    assert m["meter_price_derived"] == 1


def test_map_row_missing_values_stay_none_not_fabricated():
    raw = {"transaction_date": "2026-06-10", "plan": "3796", "parcel": "1",
           "real_estate_number": "RE-2"}
    m = fetch.map_row(raw)
    assert m["area"] is None
    assert m["meter_price"] is None
    assert m["amount"] is None
    assert m["lat"] is None and m["lng"] is None


def test_map_row_preserves_raw_json():
    raw = {"transaction_date": "2026-06-10", "plan": "3200", "parcel": "9",
           "real_estate_number": "RE-3", "weird_extra": "قيمة"}
    m = fetch.map_row(raw)
    import json
    assert json.loads(m["raw_json"])["weird_extra"] == "قيمة"
