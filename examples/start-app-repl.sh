#!/usr/bin/env sh

# Public helper to connect to a device, optionally install the APK, and start AIVane REPL.
# Usage:
#   ./examples/start-app-repl.sh <device-ip> [apk-path]

set -eu

DEVICE_IP=${1:?device IP is required}
APK_PATH=${2:-}
ADB_TARGET="${DEVICE_IP}:5555"
APP_PACKAGE="aivane.apprepl"
MAIN_ACTIVITY="${APP_PACKAGE}/.ui.ReplMainActivity"
SERVICE_NAME="${APP_PACKAGE}/.api.ApiService"
ACCESSIBILITY_SERVICE="${APP_PACKAGE}/aivane.android.accessibility.AIVaneAccessibilityService:0"

echo "Connecting to ${ADB_TARGET}..."
adb connect "${ADB_TARGET}" >/dev/null 2>&1 || true

if [ -n "${APK_PATH}" ]; then
  echo "Installing APK from ${APK_PATH}..."
  adb -s "${ADB_TARGET}" install -r "${APK_PATH}"
fi

echo "Enabling accessibility service..."
adb -s "${ADB_TARGET}" shell settings put secure enabled_accessibility_services "${ACCESSIBILITY_SERVICE}" >/dev/null
adb -s "${ADB_TARGET}" shell settings put secure accessibility_enabled 1 >/dev/null

echo "Starting AIVane REPL activity..."
adb -s "${ADB_TARGET}" shell am start -n "${MAIN_ACTIVITY}" >/dev/null

echo "Starting API service..."
adb -s "${ADB_TARGET}" shell am start-foreground-service -n "${SERVICE_NAME}" >/dev/null 2>&1 || true

echo "Checking health..."
sleep 2
if command -v curl >/dev/null 2>&1; then
  curl -s "http://${DEVICE_IP}:8080/health" || true
  echo
fi

echo "AIVane REPL should now be available at http://${DEVICE_IP}:8080"
