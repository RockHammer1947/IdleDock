#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h:h}"
TEST_APP="$TASK_ROOT/.build/LocalizationTests.app"
mkdir -p "$TEST_APP/Contents/MacOS" "$TEST_APP/Contents/Resources" "$TASK_ROOT/.build/module-cache"
cp -R "$TASK_ROOT/macos/Resources/" "$TEST_APP/Contents/Resources/"
cat > "$TEST_APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>LocalizationTests</string>
<key>CFBundleIdentifier</key><string>local.queue-mac-h3.localization-tests</string>
<key>CFBundleDevelopmentRegion</key><string>en</string>
</dict></plist>
EOF
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
xcrun swiftc -parse-as-library -DLOCALIZATION_TESTS -swift-version 5 -module-cache-path "$TASK_ROOT/.build/module-cache" \
    -framework AppKit -framework SwiftUI "$TASK_ROOT"/macos/*.swift "$TASK_ROOT/tests/LocalizationTests.swift" \
    -o "$TEST_APP/Contents/MacOS/LocalizationTests"
"$TEST_APP/Contents/MacOS/LocalizationTests" "$TASK_ROOT"
