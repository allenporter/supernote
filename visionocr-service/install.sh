#!/usr/bin/env bash
# Builds the macos-vision-ocr binary, sets up the Python virtualenv, and
# installs/loads the launchd agent for visionocr-service.
#
# Safe to re-run: rebuilds the binary and reloads the agent each time.
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$SERVICE_DIR/.vendor/macos-vision-ocr"
BIN_DIR="$SERVICE_DIR/bin"
LOGS_DIR="$SERVICE_DIR/logs"
PLIST_LABEL="com.supernote.visionocr-service"
PLIST_SRC="$SERVICE_DIR/$PLIST_LABEL.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

if ! xcode-select -p >/dev/null 2>&1; then
    echo "Xcode Command Line Tools not found. Install with: xcode-select --install" >&2
    exit 1
fi

echo "==> Fetching macos-vision-ocr"
if [ ! -d "$VENDOR_DIR" ]; then
    git clone --depth 1 https://github.com/bytefer/macos-vision-ocr.git "$VENDOR_DIR"
fi

echo "==> Building macos-vision-ocr release binary ($(uname -m))"
( cd "$VENDOR_DIR" && swift build -c release --arch "$(uname -m)" )

mkdir -p "$BIN_DIR"
cp "$VENDOR_DIR/.build/release/macos-vision-ocr" "$BIN_DIR/macos-vision-ocr"

echo "==> Setting up Python virtualenv"
python3 -m venv "$SERVICE_DIR/.venv"
"$SERVICE_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$SERVICE_DIR/.venv/bin/pip" install --quiet -r "$SERVICE_DIR/requirements.txt"

mkdir -p "$LOGS_DIR"

echo "==> Installing launchd agent"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__SERVICE_DIR__#$SERVICE_DIR#g" "$PLIST_SRC" > "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo "==> Done."
echo "    launchctl list | grep visionocr"
echo "    tail -f $LOGS_DIR/visionocr-service.log"
