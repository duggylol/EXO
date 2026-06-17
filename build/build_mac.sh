#!/usr/bin/env bash
# Build the macOS app:  ./build/build_mac.sh
# Produces: dist/EXO.app + dist/EXO-<version>.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-./.venv/bin/python}"
echo "==> Using Python: $PY"

echo "==> Installing build dependencies"
"$PY" -m pip install -q -r requirements.txt
"$PY" -m pip install -q -r requirements-desktop.txt

echo "==> Generating icon"
"$PY" build/make_icon.py || echo "   (icon generation skipped — Pillow missing?)"
if [ -f build/icon.png ]; then
  echo "==> Converting icon.png -> icon.icns"
  ICONSET="build/icon.iconset"; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s build/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s*2)); sips -z $d $d build/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o build/icon.icns
  rm -rf "$ICONSET"
fi

echo "==> Cleaning previous build"
rm -rf build/FuturesBot* dist/"EXO"*

echo "==> Running PyInstaller"
"$PY" -m PyInstaller --noconfirm --clean FuturesBot.spec

APP="dist/EXO.app"
echo "==> Cleaning extended attributes and ad-hoc signing"
# macOS Sequoia+ stamps files with com.apple.provenance, which blocks codesign.
xattr -rd com.apple.provenance "$APP" 2>/dev/null || true
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep -s - "$APP" && codesign --verify --deep "$APP" \
  && echo "   ad-hoc signature valid" || echo "   WARNING: signing failed (app may still run locally)"

VER="$("$PY" -c 'import core.version as v; print(v.VERSION)')"

echo "==> Building DMG installer (drag-to-Applications)"
DMG_STAGE="build/dmg"; rm -rf "$DMG_STAGE"; mkdir -p "$DMG_STAGE"
ditto "$APP" "$DMG_STAGE/EXO.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create -volname "EXO" -srcfolder "$DMG_STAGE" -ov -format UDZO \
  "dist/EXO-$VER.dmg" >/dev/null
rm -rf "$DMG_STAGE"

echo "==> Building update zip (used by the in-app updater)"
# ditto (not zip) preserves the code signature + framework symlinks so the
# auto-updated app still launches on Apple Silicon.
ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/EXO-macOS.zip"

echo ""
echo "==> Done (v$VER):"
echo "   Installer:  dist/EXO-$VER.dmg   (open it, drag to Applications)"
echo "   App:        dist/EXO.app"
echo "   Open with:  open 'dist/EXO.app'"
echo "   First launch (unsigned): right-click the app -> Open -> Open."
