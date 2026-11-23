#!/bin/sh
# Copies DiceWeb (cloned next to this folder) into diceweb/, which is what the
# Pi serves as its desktop. Run it whenever DiceWeb changes.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
SRC=${1:-"$HERE/../DiceWeb"}
[ -f "$SRC/index.html" ] || { echo "No DiceWeb at $SRC"; exit 1; }
rm -rf "$HERE/diceweb"
mkdir -p "$HERE/diceweb"
cp -r "$SRC/index.html" "$SRC/css" "$SRC/js" "$SRC/package.json" "$HERE/diceweb/"
echo "Copied DiceWeb $(python3 -c "import json;print(json.load(open('$SRC/package.json'))['version'])") into diceweb/"
