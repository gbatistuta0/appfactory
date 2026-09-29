#!/bin/zsh
# Prepares a simulator for App Store captures in one language:
# - the SYSTEM language and region: widgets, SpringBoard, the Lock Screen and the Watch follow them, not
#   the app's -AppleLanguages launch argument; they take effect only after a reboot;
# - no delivered notifications and no pending system follow-ups (a "Ready for Apple Intelligence" banner
#   came from followupd in the middle of a capture);
# - the marketing status bar: 9:41 on a fixed date, full bars, NOT charging at 100 % (App Review flagged
#   the charging bolt as misleading), no carrier name;
# - with --app: a clean install. Uninstall first: a reinstall over an existing container keeps its data,
#   so a retried language silently ran on the previous attempt's seeded state.
#
#   Scripts/sim_store_prep.sh <udid> <lang> <region-format> [--app <path/to/App.app>]
#   Scripts/sim_store_prep.sh 88629EC4-… ar ar_SA --app build/dd/Build/Products/Debug-iphonesimulator/__APP_NAME__.app
#
# CAPTURE_DATE (default 2026-09-26) pins the day shown on the Lock Screen. The simulator ends up booted.
# Run it before each language: the override does not survive a reboot.
set -euo pipefail
UDID=$1 LANG_CODE=$2 REGION=$3
APP=""
[[ ${4:-} == --app ]] && APP=${5:-}
BUNDLE_ID=__BUNDLE_ID__
DATA=$HOME/Library/Developer/CoreSimulator/Devices/$UDID/data

xcrun simctl shutdown "$UDID" 2>/dev/null || true
# The Home Screen layout as it was before the first capture, so every language starts from the same
# clean pages. The first run saves it; later runs restore it.
PRISTINE=${CAPTURE_PRISTINE:-$HOME/.appfactory/sim-pristine}/$UDID
if [[ ! -d $PRISTINE ]]; then
  mkdir -p "$PRISTINE"
  cp "$DATA/Library/SpringBoard/IconState.plist" "$PRISTINE/" 2>/dev/null || true
else
  [[ -f $PRISTINE/IconState.plist ]] && cp "$PRISTINE/IconState.plist" "$DATA/Library/SpringBoard/IconState.plist"
fi
find "$DATA/Library/UserNotifications" -name DeliveredNotifications.plist -delete 2>/dev/null || true
rm -f "$DATA/Library/CoreFollowUp/items.db"

xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" >/dev/null
xcrun simctl spawn "$UDID" defaults write -g AppleLanguages -array "$LANG_CODE"
xcrun simctl spawn "$UDID" defaults write -g AppleLocale "$REGION"
# The language reaches SpringBoard and the widgets only after a reboot.
xcrun simctl shutdown "$UDID"
xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" >/dev/null
# An ISO time also pins the Lock Screen's date (a bare "9:41" shows 1 January). simctl takes UTC with
# milliseconds and shows it in the Mac's time zone, so 09:41 local is converted first.
T=$(date -u -r "$(date -j -f "%Y-%m-%d %H:%M:%S" "${CAPTURE_DATE:-2026-09-26} 09:41:00" +%s)" +%Y-%m-%dT%H:%M:%S.000Z)
xcrun simctl status_bar "$UDID" override --time "$T" --operatorName " " --dataNetwork wifi --wifiMode active --wifiBars 3 \
  --cellularMode active --cellularBars 4 --batteryState discharging --batteryLevel 100

if [[ -n $APP ]]; then
  xcrun simctl uninstall "$UDID" "$BUNDLE_ID" 2>/dev/null || true
  xcrun simctl install "$UDID" "$APP"
  # A first launch registers the app's extensions (widget gallery) before a test needs them.
  xcrun simctl launch "$UDID" "$BUNDLE_ID" >/dev/null
  sleep 8
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
fi
echo "sim_store_prep: $UDID $LANG_CODE $REGION ready"
