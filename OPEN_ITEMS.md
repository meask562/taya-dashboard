<div dir="rtl">

# البنود المفتوحة — تسليم لوحة طايا (TIC)

تاريخ التجهيز: 2026-06-20. كل البرمجيات جاهزة ومُختبَرة (21 اختبار وحدة ✓، الواجهة تُعرض ببيانات
توضيحية). البنود أدناه **تحتاج تدخّل المالك** لأنها تتطلب تسجيل دخول بشري أو حساب خارجي — لا يمكن
أتمتتها بأمانة.

---

## ✅ ما تمّ تلقائياً (جاهز)

- **الواجهة** `site/index.html`: data-driven بالكامل من `site/data/metrics.json` — بطاقات KPI، خريطة
  Leaflet (66 ماركر)، رسوم Chart.js (اتجاه/سيولة/طلب)، جدول قابل للفرز والتصفية، بطاقة «موقعك من
  السوق» بإدخال يدوي يُحفظ في localStorage. RTL + هوية TIC، مطابقة للمرجع التصميمي. **تم التحقّق بصرياً.**
- **بيانات توضيحية** مولّدة عبر `python3 fetcher/analytics.py --sample` (مُعلَّمة بوضوح ببانر «نموذج»).
- **الجدولة** `scheduler/run.sh` + `com.tic.taya.fetch.plist` + `install.sh`/`uninstall.sh` — مُتحقَّق
  من الصياغة والـ plist.
- **git**: أول commit يضمّ كل المشروع (عدا الأسرار والـ DB المحلية وملفات الأدوات).

---

## ⏳ بنود تحتاجك (بالترتيب)

### 1) تثبيت بيئة بايثون (مرة واحدة)
```bash
cd "Taya Dashboaerd"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2) تسجيل دخول بسيطة لمرة واحدة  ← الأهم (يفتح باب البيانات الحقيقية)
```bash
python fetcher/fetch.py --login    # يفتح Chrome مرئياً → سجّل الدخول + «تذكّرني» → اضغط Enter
```
بدون هذه الخطوة تبقى الواجهة على البيانات التوضيحية.

### 3) أول جلب فعلي + توليد بيانات حقيقية
```bash
python fetcher/fetch.py            # جلب أولي (حتى 24 شهراً)
python fetcher/analytics.py        # يستبدل metrics.json التوضيحي ببيانات حقيقية
```
سيختفي بانر «بيانات توضيحية» تلقائياً عند وجود بيانات حقيقية.

### 4) ربط Vercel (مرة واحدة) — يتطلب حسابك
1. ادفع الريبو إلى GitHub (أنشئ remote أولاً):
   ```bash
   git remote add origin <رابط-الريبو>
   git push -u origin main
   ```
2. في Vercel: **Import Project** → اختر الريبو · Framework: Other · Output Directory: `site`
   (مضبوط مسبقاً في `vercel.json`).
3. (موصى به) فعّل **Password Protection** ليكون الرابط داخلياً للمدير.

### 5) تفعيل الجدولة اليومية
```bash
bash scheduler/install.sh          # يحمّل launchd — يعمل يومياً 07:30
launchctl start com.tic.taya.fetch # تشغيل فوري للاختبار، ثم راجع scheduler/logs/
```
لإيقاظ الجهاز تلقائياً: `sudo pmset repeat wakeorpoweron MTWRFSU 07:25:00`

---

## معاينة الواجهة محلياً الآن (بدون أي مما سبق)
```bash
cd site && python3 -m http.server 8000
# ثم افتح http://localhost:8000
```
> ملاحظة فنية: إعداد معاينة Claude Code (`.claude/launch.json` + `serve.py`) يخدم نسخة من `site`
> في `/tmp/taya-preview` (حلٌّ لقيود sandbox مع مسار OneDrive)، وهو مُستثنى من git. للمعاينة العادية
> استخدم الأمر أعلاه.

---

## ملاحظات وقرارات
- **عمر جلسة بسيطة غير معروف** — يُقاس فعلياً؛ عند انتهائها يصل إشعار macOS، تُعيد `--login`، ويستأنف الروتين.
- **رسوم الأراضي البيضاء** تظهر «غير متوفّر بعد» حتى تُربط بطبقة بسيطة المخصّصة (لا اختلاق).
- **git remote**: `run.sh` يُنشئ commit محلياً حتى بدون remote، ويدفع تلقائياً بمجرد ربط `origin`.

</div>
