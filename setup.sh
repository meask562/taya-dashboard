#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh — تهيئة المالك بأمر واحد:
#   بيئة بايثون + Playwright → تسجيل دخول بسيطة (مرة) → أول جلب فعلي → حساب المؤشرات.
#
# تشغيل:  bash setup.sh
#
# بعد نجاحه تختفي «بيانات النموذج» وتظهر بيانات بسيطة الحقيقية. آمن للتكرار.
# لا يدفع إلى git ولا يربط Vercel (خطوة قرار صريحة — مطبوعة في النهاية).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

echo "── (1/4) تهيئة بيئة بايثون ──"
[ -d ".venv" ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
python -m playwright install chromium

# تحقّق من .env قبل أي شيء يعتمد على ملف الـ profile
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  أُنشئ .env من .env.example. افتحه واضبط TAYA_CHROME_PROFILE ثم أعد تشغيل setup.sh:"
  echo "    $ROOT/.env"
  exit 1
fi

echo ""
echo "── (2/4) تسجيل دخول بسيطة لمرة واحدة ──"
echo "    سيُفتح Chrome مرئيًا. سجّل الدخول (جوال + OTP) وفعّل «تذكّرني»،"
echo "    ثم ارجع للطرفية واضغط Enter لحفظ الجلسة."
python fetcher/fetch.py --login

echo ""
echo "── (3/4) أول جلب فعلي من بسيطة ──"
python fetcher/fetch.py
rc=$?
if [ "$rc" -eq 2 ]; then
  echo "❌ الجلسة منتهية. أعد تسجيل الدخول:  python fetcher/fetch.py --login"
  exit 2
elif [ "$rc" -ne 0 ]; then
  echo "❌ فشل الجلب (كود $rc). راجع المخرجات أعلاه."
  exit "$rc"
fi

echo ""
echo "── (4/4) حساب المؤشرات ──"
python fetcher/analytics.py

echo ""
echo "✅ تمّ. بيانات حقيقية الآن في site/data/metrics.json — اختفى بانر «النموذج»."
echo ""
echo "الخطوة الأخيرة (نشر — قرارك):"
echo "    git add -A && git commit -m \"data: أول جلب فعلي من بسيطة\" && git push"
echo "    ثم اربط الريبو بـ Vercel (Output Directory = site). التفاصيل في README.md."
echo ""
echo "لتفعيل الجدولة اليومية لاحقًا:  bash scheduler/install.sh"
