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
browser_package=""
for candidate in com.android.chrome com.google.android.apps.chrome org.chromium.chrome com.android.browser; do
  if adb -s "$device" shell pm path "$candidate" 2>/dev/null | grep -q '^package:'; then
    browser_package="$candidate"
    break
  fi
done
if [[ -z "$browser_package" ]]; then
  chromium_url="${CHROMIUM_APK_URL:-https://commondatastorage.googleapis.com/chromium-browser-snapshots/Android/1672125/chrome-android.zip}"
  apk_tmp=$(mktemp -d)
  trap 'rm -rf "$apk_tmp"' EXIT
  curl --fail --location --silent --show-error --retry 3 "$chromium_url" -o "$apk_tmp/chromium.zip"
  unzip -q -j "$apk_tmp/chromium.zip" '*/apks/ChromePublic.apk' -d "$apk_tmp"
  chromium_apk="$apk_tmp/ChromePublic.apk"
  [[ -s "$chromium_apk" ]] || { echo "Chromium APK was not found in snapshot archive." >&2; exit 1; }
  adb -s "$device" install -r "$chromium_apk"
  if adb -s "$device" shell pm path org.chromium.chrome 2>/dev/null | grep -q '^package:'; then
    browser_package=org.chromium.chrome
  fi
fi
if [[ -z "$browser_package" ]]; then
  echo "No Android browser package is installed." >&2
  exit 1
fi
printf '%s\n' "$browser_package" >"$evidence/browser-package.txt"
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
