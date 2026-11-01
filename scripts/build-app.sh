#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h:h}"
source "$TASK_ROOT/scripts/python-path.sh"
APP="$TASK_ROOT/dist/H3 Queue.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$TASK_ROOT/.build"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
/usr/bin/xcrun swiftc -parse-as-library -target arm64-apple-macosx14.0 -O -swift-version 5 -module-cache-path "$TASK_ROOT/.build/module-cache" -framework AppKit -framework SwiftUI "$TASK_ROOT"/macos/*.swift -o "$APP/Contents/MacOS/H3Queue"
for LOCALIZATION in "$TASK_ROOT"/macos/Resources/*.lproj; do
    /usr/bin/plutil -lint "$LOCALIZATION/Localizable.strings"
    /bin/cp -R "$LOCALIZATION" "$APP/Contents/Resources/"
done
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>H3Queue</string>
<key>CFBundleIdentifier</key><string>local.queue-mac-h3.widget</string>
<key>CFBundleName</key><string>IdleDock</string>
<key>CFBundleDisplayName</key><string>IdleDock</string>
<key>CFBundleDevelopmentRegion</key><string>en</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
"$QUEUE_PYTHON" - "$TASK_ROOT" "$QUEUE_PYTHON" "$APP/Contents/Resources/config.json" <<'PY'
import json,sys,plistlib
from pathlib import Path
Path(sys.argv[3]).write_text(json.dumps({'root':sys.argv[1],'python':sys.argv[2]}))
info=Path(sys.argv[3]).parents[1]/'Info.plist'
metadata=plistlib.loads(info.read_bytes())
metadata['CFBundleLocalizations']=sorted(p.stem for p in (Path(sys.argv[1])/'macos/Resources').glob('*.lproj'))
info.write_bytes(plistlib.dumps(metadata))
PY
/usr/bin/codesign --force --sign - "$APP"
print "$APP"
