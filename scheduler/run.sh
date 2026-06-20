#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scheduler/run.sh — الروتين اليومي: جلب بسيطة → تحليل → (عند التغيّر) git push → Vercel
#
# يُشغَّل من launchd (com.tic.taya.fetch.plist) أو يدوياً:  bash scheduler/run.sh
#
# سلوك أكواد خروج fetch.py:
#   0 = نجاح        → شغّل analytics ثم ادفع لو تغيّرت البيانات
#   2 = انتهت الجلسة → لا تدفع، أبقِ آخر نشر سليماً (fetch.py أرسل الإشعار للمالك)
#   1 = خطأ عام      → لا تدفع، سجّل الخطأ واخرج بكود غير صفري
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# جذر المشروع = أب مجلد scheduler (بصرف النظر عن مجلد التشغيل)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT" || exit 1

LOG_DIR="$ROOT/scheduler/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y-%m-%d).log"

log(){ printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

log "──────── بدء الروتين ────────"

# ── بايثون: فضّل .venv إن وُجد ──
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate" 2>/dev/null || true
else
  PY="$(command -v python3 || true)"
  log "تنبيه: لا يوجد .venv — استخدام $PY النظامي (تأكّد من تثبيت playwright)."
fi
if [ -z "$PY" ]; then log "خطأ: لا يوجد مفسّر بايثون."; exit 1; fi

# ── 1) الجلب ──
log "تشغيل fetch.py…"
"$PY" "$ROOT/fetcher/fetch.py" >>"$LOG" 2>&1
FETCH_RC=$?
log "fetch.py انتهى بكود $FETCH_RC"

if [ "$FETCH_RC" -eq 2 ]; then
  log "انتهت جلسة بسيطة — لا دفع، آخر نشر يبقى سليماً. المالك سيُسجّل الدخول ثم يستأنف الروتين تلقائياً."
  log "──────── نهاية (جلسة منتهية) ────────"
  exit 0
elif [ "$FETCH_RC" -ne 0 ]; then
  log "فشل الجلب (كود $FETCH_RC) — لا دفع. راجع السجل أعلاه."
  log "──────── نهاية (خطأ) ────────"
  exit "$FETCH_RC"
fi

# ── 2) التحليل ──
log "تشغيل analytics.py…"
"$PY" "$ROOT/fetcher/analytics.py" >>"$LOG" 2>&1
ANALYTICS_RC=$?
if [ "$ANALYTICS_RC" -ne 0 ]; then
  log "فشل التحليل (كود $ANALYTICS_RC) — لا دفع."
  log "──────── نهاية (خطأ تحليل) ────────"
  exit "$ANALYTICS_RC"
fi

# ── 3) النشر: ادفع فقط عند تغيّر المخرجات المنشورة ──
PUBLISH_PATHS=("data/snapshots" "site/data/metrics.json")

if ! command -v git >/dev/null 2>&1; then
  log "تنبيه: git غير متوفّر — تخطّي النشر."
  log "──────── نهاية (بلا نشر) ────────"
  exit 0
fi

git add -- "${PUBLISH_PATHS[@]}" 2>>"$LOG" || true

if git diff --cached --quiet -- "${PUBLISH_PATHS[@]}"; then
  log "لا تغيّر في البيانات المنشورة — لا commit/push."
  log "──────── نهاية (بلا تغيّر) ────────"
  exit 0
fi

STAMP="$(date '+%Y-%m-%d %H:%M')"
git commit -m "data: تحديث صفقات طايا ${STAMP}" >>"$LOG" 2>&1
log "أُنشئ commit للبيانات."

# ادفع فقط لو فيه remote مضبوط (وإلا اترك للمالك ربط Vercel/الريبو لاحقاً)
if git remote get-url origin >/dev/null 2>&1; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  if git push origin "$BRANCH" >>"$LOG" 2>&1; then
    log "تم الدفع إلى origin/$BRANCH → Vercel سيعيد النشر تلقائياً."
  else
    log "تنبيه: فشل git push (راجع السجل) — الـ commit محلي محفوظ، سيُدفع في التشغيل القادم."
  fi
else
  log "تنبيه: لا remote 'origin' مضبوط — الـ commit محلي فقط. اربط الريبو ثم سيُدفع تلقائياً."
fi

log "──────── نهاية (نشر) ────────"
exit 0
