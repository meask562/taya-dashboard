<div dir="rtl">

# STATUS — لوحة طايا (TIC)
**آخر تحديث:** 2026-06-20

## المنجز في هذه الجلسة
- تثبيت **impeccable** + `PRODUCT.md` / `DESIGN.md`، وإعادة تصميم اللوحة لمعيار impeccable.
- التسلسل: **critique** (31/40) → **onboard** (تحميل/خطأ بلغة المدير/حالات فارغة/تلميح أول مرة/شروح ⓘ)
  → **animate** (عدّ تصاعدي للأرقام + نبضة الفرق، مع حارس setTimeout و`prefers-reduced-motion`).
- **اكتشاف API بسيطة الحقيقي:** المفترض `POST /api/precord/rer_transactions/data` خاطئ (403)؛ الصحيح
  `GET /api/get_geojson_filterd_rer_transactions?sw_lat=&sw_lng=&ne_lat=&ne_lng=` (GeoJSON). ملف Chrome
  `~/Library/Application Support/taya-chrome-profile` مسجَّل دخوله في بسيطة. أُنشئ `.env` و`setup.sh`.
- 3 موكابات لإعادة تصميم جريئة (`site/mockups/`)؛ المالك اعتمد **C — بيان أصول**.
- بدء تطبيق ثيم C على `site/index.html` (أوكسبلود/نحاسي/Almarai، أرقام بطل).
- ضبط `~/.claude/settings.json` (bypassPermissions + deny لأوامر خطرة).

## القرارات المتخذة
- اعتماد اتجاه **«بيان أصول» (C)**: تخطيط بيان، أرقام بطل كبيرة، مع مراجعة الأقسام.
- **ألوان TIC الرسميّة إلزاميّة** (navy/teal من tic-taya.sa) — الثيم الأوكسبلود الحالي **مرفوض** ويُعاد لألوان TIC.
- حفظ النسخة الفاتحة المصقولة بألوان TIC في `site/index-classic.html` كمرجع آمن.
- البيانات الحيّة مؤجَّلة لآخر المشروع بقرار المالك (اللوحة على بيانات توضيحية sample=true حاليًا).

## المعلّق
1. **🔴 إرجاع `site/index.html` لألوان TIC** (الثيم الحالي خارج الهوية). الأولوية القادمة.
2. **البيانات الحيّة:** تبديل endpoint في `fetch.py` لـ `get_geojson_filterd_rer_transactions` ثم fetch+analytics.
3. **ربط Vercel** + `scheduler/install.sh` (يتطلب حساب المالك).

## نتيجة الاختبارات
`​.venv/bin/python -m pytest fetcher/test_normalize.py -q` → **21 passed in 0.03s** ✅
(تطبيع الأرقام العربية، التواريخ، `find_rows`، `map_row`، منطق عدم الاختلاق). الكاشف `impeccable detect` → `[]`.

## الخطوة التالية المقترحة
ادخل **tic-taya.sa**، عاين الباليت الرسمي، ثم أعد كسوة `site/index.html` (تخطيط بيان الأصول المعتمد)
**بألوان TIC** بدل الأوكسبلود/النحاسي. التفاصيل في `_ملخص الجلسة للمتابعة.md`.

</div>
