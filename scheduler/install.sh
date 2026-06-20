#!/usr/bin/env bash
# تثبيت جدولة launchd اليومية. التشغيل:  bash scheduler/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.tic.taya.fetch.plist"
LABEL="com.tic.taya.fetch"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST="$DEST_DIR/$LABEL.plist"

[ -f "$PLIST_SRC" ] || { echo "خطأ: لا يوجد $PLIST_SRC"; exit 1; }
chmod +x "$SCRIPT_DIR/run.sh"
mkdir -p "$DEST_DIR" "$SCRIPT_DIR/logs"

# انسخ الـ plist إلى LaunchAgents (نسخة لضمان قراءة launchd لها بثبات)
cp "$PLIST_SRC" "$DEST"
echo "نُسخ الـ plist إلى $DEST"

# أعد التحميل لو كان محمّلاً مسبقاً
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "حُمّل $LABEL — سيعمل يومياً 07:30."
echo
echo "تحقّق:    launchctl list | grep $LABEL"
echo "تشغيل فوري للاختبار:   launchctl start $LABEL   (ثم راجع scheduler/logs/)"
echo
echo "ملاحظة: تأكّد أن الجهاز مستيقظ 07:30. لإيقاظ تلقائي:"
echo "  sudo pmset repeat wakeorpoweron MTWRFSU 07:25:00"
echo "ملاحظة: شغّل أولاً  python fetcher/fetch.py --login  لتسجيل دخول بسيطة مرة واحدة."
