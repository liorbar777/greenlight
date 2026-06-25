#!/usr/bin/env bash
# Regenerate icon.icns from make_icon.py. Run from the repo (uses .venv python).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${GREENLIGHT_PY:-$DIR/.venv/bin/python}"
SET="$DIR/icon.iconset"
rm -rf "$SET"; mkdir -p "$SET"

# size_px -> iconset filenames that need it
gen() { "$PY" "$DIR/make_icon.py" "$1" "$SET/$2"; }
gen 16   icon_16x16.png
gen 32   icon_16x16@2x.png
gen 32   icon_32x32.png
gen 64   icon_32x32@2x.png
gen 128  icon_128x128.png
gen 256  icon_128x128@2x.png
gen 256  icon_256x256.png
gen 512  icon_256x256@2x.png
gen 512  icon_512x512.png
gen 1024 icon_512x512@2x.png

iconutil -c icns "$SET" -o "$DIR/icon.icns"
rm -rf "$SET"
echo "wrote $DIR/icon.icns"
