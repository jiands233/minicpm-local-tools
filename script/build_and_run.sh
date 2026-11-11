#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="MiniCPMClipboard"
BUNDLE_ID="local.minicpm.clipboard"
APP_BUNDLE="$ROOT_DIR/macos/dist/$APP_NAME.app"
case "$MODE" in run|--build-only|--verify|--debug|--logs|--telemetry) ;; *) echo "usage: $0 [--build-only|--verify|--debug|--logs|--telemetry]" >&2; exit 2;; esac
if [ "$MODE" != "--build-only" ]; then pkill -x "$APP_NAME" >/dev/null 2>&1 || true; fi
swift build --package-path "$ROOT_DIR/macos" -c release
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
cp "$ROOT_DIR/macos/.build/release/$APP_NAME" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
printf '%s\n' "$ROOT_DIR" > "$APP_BUNDLE/Contents/Resources/project-root.txt"
/usr/bin/python3 - "$APP_BUNDLE/Contents/Resources/model-config.json" <<'PYCONFIG'
import json, os, pathlib, sys
names = ['MINICPM_BASE_URL', 'MINICPM_MODEL', 'MINICPM_OCR_URL', 'MINICPM_OCR_MODEL',
         'MINICPM_EMBED_URL', 'MINICPM_EMBED_MODEL', 'MINICPM_TIMEOUT']
pathlib.Path(sys.argv[1]).write_text(json.dumps({k: os.environ[k] for k in names if k in os.environ}))
PYCONFIG
cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>$APP_NAME</string>
<key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
<key>CFBundleName</key><string>MiniCPM Clipboard</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSPrincipalClass</key><string>NSApplication</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
case "$MODE" in
 --build-only) echo "$APP_BUNDLE" ;;
 --debug) lldb -- "$APP_BUNDLE/Contents/MacOS/$APP_NAME" ;;
 --verify) /usr/bin/open -n "$APP_BUNDLE"; sleep 1; pgrep -x "$APP_NAME" ;;
 --logs) /usr/bin/open -n "$APP_BUNDLE"; /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\"" ;;
 --telemetry) /usr/bin/open -n "$APP_BUNDLE"; /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\"" ;;
 run) /usr/bin/open -n "$APP_BUNDLE" ;;
esac
