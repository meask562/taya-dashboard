#!/usr/bin/env bash
# إلغاء جدولة launchd. التشغيل:  bash scheduler/uninstall.sh
set -euo pipefail

LABEL="com.tic.taya.fetch"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -f "$DEST" ]; then
  launchctl unload "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "أُلغي وحُذف $DEST"
else
  echo "لا يوجد $DEST — ربما غير مثبّت."
fi
