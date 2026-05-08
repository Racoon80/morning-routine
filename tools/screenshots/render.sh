#!/usr/bin/env bash
# Render the four mockup HTML files to PNG screenshots via headless Chrome.
# Output goes to ../../images/. Re-runnable; idempotent.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/../../images"
mkdir -p "$OUT"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  echo "Google Chrome not found at expected path" >&2
  exit 1
fi

render() {
  local name="$1"
  local size="$2"
  echo "→ $name ($size)"
  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --hide-scrollbars \
    --no-sandbox \
    --window-size="$size" \
    --virtual-time-budget=10000 \
    --default-background-color=00000000 \
    --screenshot="$OUT/${name}.png" \
    "file://$DIR/${name}.html" >/dev/null 2>&1
}

render overlay-normal "1920,1080"
render overlay-hc     "1920,1080"
render idle-normal    "1920,1080"
render idle-hc        "1920,1080"

# Icon — 256x256, transparent background. The icon HTML draws its own
# rounded-rect background, so the page itself is transparent.
echo "→ icon (256x256)"
"$CHROME" \
  --headless=new --disable-gpu --hide-scrollbars --no-sandbox \
  --window-size="256,256" \
  --virtual-time-budget=10000 \
  --default-background-color=00000000 \
  --screenshot="$OUT/icon.png" \
  "file://$DIR/icon.html" >/dev/null 2>&1

echo "Done. Output:"
ls -la "$OUT"/*.png
