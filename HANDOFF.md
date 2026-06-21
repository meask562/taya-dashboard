<div dir="rtl">

# دليل التسليم للفريق — لوحة طايا (TIC)

هذا الملف نقطة البداية للفريق الذي سيكمل المشروع (بما فيه الربط مع نظام ERP).
يلخّص: ما هو المشروع · كيف يعمل · مصادر البيانات · كيف تربط ERP · المتبقّي · النشر.
مراجع تكميليّة في المستودع: `README.md` · `STATUS.md` (آخر حالة) · `DESIGN.md` · `PRODUCT.md`.

---

## 1) ما هو المشروع
لوحة قرار عقاريّة (Arabic RTL، صفحة واحدة) لمالك مدينة طايا الصناعيّة:
- **تقنيّة:** HTML/CSS/JavaScript صرف (بلا framework) + Chart.js + Leaflet. الواجهة كلّها في `site/index.html`.
- **مبدأ المعمار:** مصدر الحقيقة هو ملفّات **JSON** في `site/data/`. سكربتات `fetcher/` تنتج هذه الملفّات؛ الواجهة تقرأها فقط. أي مصدر بيانات جديد (ERP مثلاً) = سكربت يكتب JSON بنفس المخطّط.
- **حيّ الآن:** https://meask562.github.io/taya-dashboard/

## 2) كيف يحصل الفريق على كل الملفّات
المشروع كلّه في مستودع GitHub:  **github.com/meask562/taya-dashboard**
- **مبرمج:** `git clone https://github.com/meask562/taya-dashboard.git`
- **غير مبرمج:** زرّ **Code → Download ZIP** في صفحة المستودع.
- **للمساهمة (الدفع للمستودع):** يضيف المالكُ أعضاءَ الفريق Collaborators من
  Settings → Collaborators في GitHub (أو الفريق يعمل Fork).

> ملاحظة خصوصيّة: المستودع **عام** حاليًّا. لو رغبتم بإبقائه داخليًّا، اجعلوه Private من
> Settings (لكن GitHub Pages للمستودع الخاص يحتاج خطة مدفوعة — أو انقلوا النشر إلى Vercel).

## 3) هيكل المستودع
```
site/
  index.html            ← اللوحة كاملة (واجهة + كل منطق JS)
  data/*.json           ← بيانات الواجهة (تُولَّد من fetcher/)
fetcher/
  inventory.py          ← مخزون قطع طايا (سحب حقيقي من tic-taya.sa)
  suhail.py             ← صفقات السوق من منصّة سهيل (api2.suhail.ai)
  merge.py              ← دمج المصادر + إزالة التكرار → market.json
  analytics.py          ← مؤشّرات بسيطة من data/taya.db (عيّنة حاليًّا)
  fetch.py              ← جلب بسيطة (Playwright) — غير مفعّل بعد
  test_*.py             ← اختبارات وحدة (pytest)
.github/workflows/deploy.yml   ← نشر تلقائي + تحديث بيانات أسبوعي
STATUS.md               ← آخر حالة وقرارات ومتبقّي (اقرأه أولاً)
scheduler/              ← جدولة محليّة بديلة (launchd) — اختياري
```

## 4) التشغيل محليًّا
```bash
# بيئة بايثون (للسكربتات)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # Playwright فقط لبسيطة؛ بقية السكربتات stdlib

# توليد البيانات
python fetcher/inventory.py               # مخزون طايا الحقيقي
python fetcher/suhail.py                   # صفقات سهيل
python fetcher/merge.py                    # الدمج
# analytics.py يحتاج data/taya.db (من بسيطة) — غير متوفّر بعد

# الاختبارات
python -m pytest fetcher/ -q              # 26 اختبارًا

# المعاينة: أي خادم ثابت على مجلّد site/
cd site && python3 -m http.server 8000    # ثم افتح http://localhost:8000
```

## 5) مصادر البيانات (الحالة الحقيقيّة)
| الملف | المصدر | الحالة | ملاحظات |
|---|---|---|---|
| `inventory.json` | **tic-taya.sa/listings** (Livewire) | **حقيقي** | 728 قطعة بأكواد/بلوك/مساحة/حالة. الموقع العام يعرض المعروض للبيع فقط (+1 محجوز) — **لا يَنشُر المباع**. |
| `suhail.json` | **api2.suhail.ai** (سهيل) | **حقيقي** | صفقات محيط طايا. ⚠ راجع تنبيه ToS أدناه. |
| `market.json` | دمج سهيل + بسيطة (`merge.py`) | محرّك جاهز | إزالة التكرار **برقم الصفقة الرسميّ (tx_no) حصرًا**، لا بالصفات. |
| `metrics.json` | بسيطة عبر `analytics.py`/`taya.db` | **عيّنة** | بسيطة لم تُربط حيًّا بعد (قرار سابق). |

### تفاصيل واجهة سهيل (مكتشَفة من حزمة الموقع العامّة)
- المضيف `https://api2.suhail.ai/` · ترويسة `PLATFORM: WEB` تكفي (لا مصادقة للبيانات العامّة).
- `GET api/transactions/search?regionId=10&offset=&limit=` (الرياض regionId=10، provinceId=101000).
- `GET transactionsAsMapboxGeojson?RegionId=10&LookbackType=months&LookbackValue=12` (صفقات GeoJSON).
- `GET api/mapMetrics/landMetrics/list?regionId=10&offset=&limit=` (مؤشّرات لكل حي).
- التفاصيل الكاملة في تعليقات `fetcher/suhail.py`.

## 6) ربط نظام ERP (المهمّة الرئيسة للفريق)
المعمار مصمَّم ليستقبل ERP بسهولة — **النمط:** `ERP → سكربت fetcher → JSON بنفس المخطّط → الواجهة`.
أهمّ نقاط الربط:

1. **بيانات «المباع» والأسعار (المخزون):** الموقع العام لا يوفّرها. اكتبوا مصدرًا من ERP
   يملأ في كل قطعة بـ `inventory.json`: `status` (`sold`/`reserved`/`available`)،
   و`sold_price`/`sold_date` للمباعة، و`asking_price` الحقيقي. عندها تعمل تلقائيًّا مؤشّرات
   «نسبة البيع / الإيراد المحقّق / سرعة البيع» (الآن صفر لغياب بيانات المبيعات).
2. **صفقات السوق:** إن كان لديكم مصدر داخلي/رسمي للصفقات، أضيفوه كمصدر في `merge.py`
   (دالة `load_*`) ووفّروا `tx_no` (رقم صفقة وزارة العدل) ليعمل **إزالة التكرار** عبر المصادر.
3. **بسيطة:** فعّلوا `fetch.py` (Playwright) لجلب بسيطة الحيّة → `taya.db` → `analytics.py`.

### مخطّطات JSON (لإنتاج ملفّات متوافقة)
- **inventory.json** → `{ plots: [{ plot_no, sector, sector_name, block, area, type,
  direction, street_width, status, asking_price, sold_price?, sold_date?, lat, lng }], ... }`
  مفاتيح القطاعات: `light · medium · wh · factory · comm · res` (تطابق benchmarks في metrics.json).
- **سجلّ صفقة موحّد** (لـ merge) → `{ source, tx_no, date, plan, parcel, area, meter_price,
  total_price, type, neighborhood, lat, lng }`.
- بقيّة المخطّطات ظاهرة في مخرجات السكربتات وملفّات `site/data/*.json` الحاليّة كمرجع حيّ.

## 7) النشر والتحديث التلقائي
- `.github/workflows/deploy.yml`: عند الدفع لـ `main` → ينشر `site/` على GitHub Pages.
- مجدول **أسبوعيًّا (الأحد 05:00 UTC)** + زرّ يدوي (Actions → Run workflow): يسحب سهيل/طايا،
  يدمج، يحفظ البيانات، وينشر — تلقائيًّا.
- بديل محليّ: `scheduler/` (launchd على ماك) — اختياري.

## 8) المتبقّي / قرارات معلّقة (انظر STATUS.md للتفصيل)
1. ربط **ERP** لبيانات المبيعات والأسعار (الأهمّ).
2. ربط **بسيطة** حيًّا.
3. **تأكيد موقع طايا الجغرافي:** إحداثيات الموقع تبدو placeholder؛ المرجّح قرب المصفاة (24.49/46.88).
4. خصوصيّة الرابط (عام ↔ خاص/Vercel).

## 9) ⚠ تنبيهات مهمّة
- **شروط استخدام سهيل:** الواجهة عامّة الوصول، لكن السحب البرمجي/المجدوَل قد يخالف شروط سهيل.
  للإنتاج: احصلوا على **وصول API رسمي/اتفاق شراكة** قبل الاعتماد عليه.
- **لا تُختلق الأرقام:** المبدأ المتّبع — كل رقم منسوب لمصدره وتاريخه؛ الناقص يُعرض «غير متوفّر» لا يُخمَّن.
- **الأسرار:** لا تضعوا مفاتيح/كوكيز في المستودع (انظر `.gitignore`). جلسة بسيطة وملفّات `.env` محليّة فقط.

</div>
