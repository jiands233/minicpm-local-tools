#!/usr/bin/env bash
set -euo pipefail
MODE=run
MODE_SET=0
UPDATE_MODEL_CONFIG=0
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="MiniCPMClipboard"
BUNDLE_ID="local.minicpm.clipboard"
APP_BUNDLE="$ROOT_DIR/macos/dist/$APP_NAME.app"
for arg in "$@"; do
  case "$arg" in
    --update-model-config) UPDATE_MODEL_CONFIG=1 ;;
    run|--build-only|--verify|--debug|--logs|--telemetry)
      if [ "$MODE_SET" = 1 ]; then echo '只能选择一种运行模式。' >&2; exit 2; fi
      MODE="$arg"
      MODE_SET=1 ;;
    *) echo "usage: $0 [--build-only|--verify|--debug|--logs|--telemetry] [--update-model-config]" >&2; exit 2 ;;
  esac
done
if [ "$MODE" != "--build-only" ]; then pkill -x "$APP_NAME" >/dev/null 2>&1 || true; fi
swift build --package-path "$ROOT_DIR/macos" -c release
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
cp "$ROOT_DIR/macos/.build/release/$APP_NAME" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
printf '%s\n' "$ROOT_DIR" > "$APP_BUNDLE/Contents/Resources/project-root.txt"
/usr/bin/python3 - "$APP_BUNDLE/Contents/Resources/model-config.json" "$UPDATE_MODEL_CONFIG" <<'PYCONFIG'
import json, os, pathlib, sys, tempfile
names = ['MINICPM_BASE_URL', 'MINICPM_MODEL', 'MINICPM_OCR_URL', 'MINICPM_OCR_MODEL',
         'MINICPM_EMBED_URL', 'MINICPM_EMBED_MODEL', 'MINICPM_TIMEOUT']
path = pathlib.Path(sys.argv[1])
update = sys.argv[2] == '1'
if path.is_symlink() or (path.exists() and not path.is_file()):
    sys.exit('模型配置路径不是普通文件；请检查后重试。')
if path.exists() and not update:
    print('保留已有模型配置；如需更新，请显式指定 --update-model-config。')
else:
    payload = json.dumps({k: os.environ[k] for k in names if k in os.environ})
    if not update:
        # First build only; avoid replacing a config created concurrently.
        with path.open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        # An explicit update replaces the complete config, not just set keys.
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix='.model-config-', delete=False) as stream:
                tmp = pathlib.Path(stream.name)
                stream.write(payload)
            os.replace(tmp, path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
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
