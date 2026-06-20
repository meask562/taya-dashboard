<div dir="rtl">

# لوحة متابعة صفقات محيط مدينة طايا الصناعية (TIC)

لوحة قرار للمالك تتابع **أسعار صفقات السجل العقاري** حول مدينة طايا الصناعية بالرياض، تتحدّث يومياً،
متجاوبة (جوال + كمبيوتر)، بهوية TIC. **المدير يفتح رابطاً واحداً فقط** — لا إدخال، لا تجديد.

> الحالة: **Prompts 0–4 منفّذة** — الجلب (fetch.py) والتحليل (analytics.py) والواجهة (site/index.html)
> والجدولة (scheduler/) جاهزة، و21 اختبار وحدة تنجح. الواجهة منشورة ببيانات **توضيحية** (نموذج) حتى أول
> جلب فعلي. **المتبقّي على المالك:** تسجيل دخول بسيطة مرة واحدة (`--login`) + ربط Vercel. انظر
> [`OPEN_ITEMS.md`](OPEN_ITEMS.md).

---

## المعمارية: جلب محلي + نشر سحابي

```
launchd (مجدول macOS يومي ~07:30)
  └─ run.sh
       └─ fetch.py     (Playwright يفتح Chrome بملف المالك المسجَّل دخوله في بسيطة)
            └─ يستدعي API بسيطة الداخلي → يسحب الصفقات الجديدة
                 └─ SQLite محلي (data/taya.db, dedup) + snapshot يومي
       └─ analytics.py (يحسب site/data/metrics.json)
       └─ git commit + push  →  Vercel auto-deploy  →  رابط المدير يتحدّث

عند انتهاء الجلسة (401): إشعار سطح المكتب + بريد للمالك → يسجّل دخول Chrome مرة → يستأنف تلقائياً
```

- **لماذا الجلب محلي؟** جلسة بسيطة في Chrome المالك (مع «تذكّرني») تحلّ مشكلة OTP المتكرّر بأقل احتكاك.
- **لماذا العرض سحابي؟** كي يفتح المدير الرابط من أي مكان دون انتظار تشغيل جهاز المالك لحظة الفتح.
- **شرطان صادقان:** (أ) جهاز المالك مستيقظ وقت التشغيل المجدول؛ (ب) إعادة تسجيل دخول بسيطة عند انتهاء
  الجلسة (نادر) — دقيقة واحدة من المالك ثم يستأنف الروتين وحده.

---

## القيود الحاكمة (لا تُتجاوز)

1. **المصدر الوحيد:** بسيطة/Paseetah API الداخلي (`paseetah.com/api/precord/rer_transactions/data`) —
   يغلّف صفقات وزارة العدل/السجل العقاري. التسلسل المرجعي: **بسيطة → REGA/عدل → بلديات**.
   **الإعلانات (عقار/Bayut) سياق فقط، ليست مصدراً.**
2. **لا اختلاق بيانات.** كل رقم منسوب لمصدره وتاريخه؛ يُصرَّح بعدم اليقين؛ مخطط بـ <5 صفقات →
   «بيانات غير كافية» بلا رقم مضلّل.
3. **عربي RTL** + تطبيع الأرقام العربية-الهندية إلى لاتينية قبل التحليل + `direction:ltr` على أي SVG.
4. **أسعار طرح طايا تُدخل يدوياً** لكل فئة من الواجهة (تُحفظ في المتصفّح) — لا تُجلب ولا تُختلق.
5. **الأمان:** لا كوكيز ولا أسرار ولا ملف Chrome profile في git إطلاقاً (انظر `.gitignore`).

### النطاق (محيط طايا)

| المخطّط | الوصف | نطاق سعري مرجعي (Dec2025–Jun2026) | اللون |
|---|---|---|---|
| 2377 | صناعي المصفاة الملاصق (400–750م²) | 1,600–2,000 ر.س/م² | `#28285D` |
| 3880/1 | الفوزان الصناعية (~5,000م²) | 1,100–2,400 ر.س/م² | `#1D9E75` |
| 3796 | مستودعات الصناعية الجديدة | 1,200–1,900 ر.س/م² | `#BA7517` |
| 3200 | سكن عمالة / سكني مجاور (~600م²) | 833–1,200 ر.س/م² | `#888780` |
| (مرجع) | السلي — مبانٍ مستودعات | 2,650–3,500 ر.س/م² | سياق |

**معرّفات الأحياء (بسيطة):** المصفاة `11010192` · الصناعية الجديدة `11010065` · السلي `11010061`
· المصانع `11010117` (Riyadh: city_id=1, region=1). **مركز TIC:** `24.4887, 46.8813`.

**هوية TIC:** navy `#28285D` / `#0F1B3C` · teal `#5EC2C9` · الشعار من `tic-taya.sa/branding/`.

---

## هيكل المشروع

```
.
├── fetcher/
│   ├── fetch.py            # جالب بسيطة عبر Chrome profile  (يُكتب في Prompt 1)
│   └── analytics.py        # حساب metrics.json              (يُكتب في Prompt 2)
├── data/
│   ├── taya.db             # SQLite محلي (مُستثنى من git — حالة عمل تُعاد بناؤها)
│   └── snapshots/          # snapshots/YYYY-MM-DD.json (تُنشر)
├── site/                   # مجلد النشر على Vercel (static)
│   ├── index.html          # الواجهة المتجاوبة             (تُبنى في Prompt 3)
│   └── data/metrics.json   # ناتج التحليل (يُولّد محلياً ثم يُدفع)
├── scheduler/
│   ├── com.tic.taya.fetch.plist   # launchd                (يُكتب في Prompt 4)
│   ├── run.sh                      # روتين الجلب+التحليل+الدفع
│   └── logs/                       # سجلات التشغيل (مُستثناة من git)
├── Dashboard_TIC_Mockup_مرجع.html       # المرجع التصميمي المُلزِم للواجهة
├── Claude_Code_Prompts_Dashboard_طايا.md # الـ 6 prompts المرجعية
├── requirements.txt   .env.example   .gitignore   vercel.json   README.md
```

> **قرار:** قاعدة `data/taya.db` مُستثناة من git (حالة محلية تُعاد بناؤها من بسيطة)؛ المنشور هو
> `data/snapshots/*.json` و`site/data/metrics.json` فقط. لتغيير ذلك عدّل `.gitignore`.

---

## الإعداد (المالك — مرة واحدة)

```bash
# 1) بيئة بايثون
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2) الإعدادات
cp .env.example .env        # ثم عدّل TAYA_CHROME_PROFILE وبقية القيم

# 3) تسجيل دخول بسيطة لمرة واحدة (يُفعّل في Prompt 1/5)
python fetcher/fetch.py --login    # يفتح Chrome مرئياً → سجّل الدخول + «تذكّرني» → أغلق

# 4) الجدولة اليومية (تُجهَّز في Prompt 4)
#    launchctl load scheduler/com.tic.taya.fetch.plist
```

## ربط Vercel (مرة واحدة)

1. ادفع الريبو إلى GitHub/GitLab.
2. في Vercel: **Import Project** → اختر الريبو.
3. **Framework Preset:** Other · **Output Directory:** `site` (مضبوط مسبقاً في `vercel.json`).
4. (موصى به) فعّل **Password Protection** ليكون الرابط داخلياً للمدير.
5. كل `git push` لاحق → نشر تلقائي. **المدير لا يحتاج أياً من هذا — رابط واحد فقط.**

---

## خريطة الـ Prompts

| # | الهدف | المخرجات الرئيسية |
|---|---|---|
| **0** ✅ | التهيئة | الهيكل · README · requirements · .gitignore · .env.example · vercel.json |
| **1** ✅ | جالب بسيطة | `fetcher/fetch.py` (Playwright + Chrome profile) · SQLite · snapshots · اختبار تطبيع (21 ✓) |
| **2** ✅ | التحليل | `fetcher/analytics.py` → `site/data/metrics.json` (median/الزخم/السيولة/الطلب/benchmarks) |
| **3** ✅ | الواجهة | `site/index.html` مطابق للمرجع (RTL · هوية TIC · خريطة Leaflet · Chart.js · data-driven) |
| **4** ✅ | الجدولة + النشر | `scheduler/run.sh` + `com.tic.taya.fetch.plist` + install/uninstall · `vercel.json` |
| **5** ⏳ | الدخول لمرة واحدة + التحقق | كود `--login` جاهز · **يلزم تنفيذ المالك** (تسجيل دخول + جلب فعلي + ربط Vercel) — انظر `OPEN_ITEMS.md` |

---

*المصدر المنهجي: ذاكرة المشروع — reference-paseetah-data-access (طريقة API المثبتة 2026-06-10) +
project-taya-deals-report.*

</div>
