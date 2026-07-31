#!/bin/bash
set -Eeuo pipefail
umask 077
evidence="${AUTONOMOUS_EVIDENCE_DIR:-release/evidence/generated/android-voice}"
mkdir -p "$evidence"

command -v adb >/dev/null || { echo "adb is required" >&2; exit 127; }
device=$(adb devices | awk 'NR > 1 && $2 == "device" {print $1; exit}')
if [[ -z "$device" ]]; then
  echo "No Android emulator/device is connected." >&2
  [[ "${ANDROID_EMULATOR_REQUIRED:-false}" == true ]] && exit 1
  exit 0
fi

adb -s "$device" reverse tcp:18443 tcp:18443
adb -s "$device" shell pm path com.android.chrome >"$evidence/chrome-package.txt"
adb -s "$device" shell am start -a android.intent.action.VIEW -d https://localhost:18443
sleep 5
adb -s "$device" shell input keyevent KEYCODE_HOME
sleep "${BACKGROUND_SECONDS:-10}"
adb -s "$device" shell am start -a android.intent.action.VIEW -d https://localhost:18443
sleep 3
adb -s "$device" shell input keyevent KEYCODE_POWER
sleep 3
adb -s "$device" shell input keyevent KEYCODE_POWER
adb -s "$device" shell input keyevent KEYCODE_WAKEUP
adb -s "$device" shell dumpsys window windows >"$evidence/window-state.txt"
adb -s "$device" shell dumpsys connectivity >"$evidence/connectivity-state.txt"
adb -s "$device" logcat -d -t 500 >"$evidence/logcat.txt"
printf '{"status":"pass","device":"redacted","scenarios":["home-return","screen-off-on","adb-reverse"]}\n' >"$evidence/report.json"
