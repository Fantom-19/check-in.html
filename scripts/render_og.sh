#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INPUT="${1:-${ROOT_DIR}/og-cover.svg}"
OUTPUT="${2:-${ROOT_DIR}/build/og-cover.jpg}"
WIDTH="${OG_WIDTH:-1200}"
HEIGHT="${OG_HEIGHT:-630}"
QUALITY="${OG_QUALITY:-90}"

if [[ ! -f "${INPUT}" ]]; then
  echo "ERROR: input file not found: $INPUT" >&2
  exit 1
fi

# Validate SVG dimensions before rendering.
python "${SCRIPT_DIR}/check_og_dimensions.py" >/dev/null

mkdir -p "$(dirname "$OUTPUT")"

render_with_magick() {
  if command -v magick >/dev/null 2>&1; then
    magick "$INPUT" -resize "${WIDTH}x${HEIGHT}^" -gravity center -extent "${WIDTH}x${HEIGHT}" -quality "$QUALITY" "$OUTPUT"
    return 0
  fi
  if command -v convert >/dev/null 2>&1; then
    convert "$INPUT" -resize "${WIDTH}x${HEIGHT}^" -gravity center -extent "${WIDTH}x${HEIGHT}" -quality "$QUALITY" "$OUTPUT"
    return 0
  fi
  return 1
}

render_with_python() {
  python - <<'PY'
from pathlib import Path
import os

inp = os.environ['INPUT']
out = os.environ['OUTPUT']
width = int(os.environ['WIDTH'])
height = int(os.environ['HEIGHT'])
quality = int(os.environ['QUALITY'])

import cairosvg
from PIL import Image

png_bytes = cairosvg.svg2png(url=inp, output_width=width, output_height=height)
Path(out).parent.mkdir(parents=True, exist_ok=True)
with open(out + '.tmp.png', 'wb') as f:
    f.write(png_bytes)
img = Image.open(out + '.tmp.png').convert('RGB')
img.save(out, format='JPEG', quality=quality, optimize=True)
Path(out + '.tmp.png').unlink(missing_ok=True)
PY
}

if render_with_magick; then
  :
elif python - <<'PY' >/dev/null 2>&1
import importlib.util
mods = ['cairosvg', 'PIL']
raise SystemExit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)
PY
then
  INPUT="$INPUT" OUTPUT="$OUTPUT" WIDTH="$WIDTH" HEIGHT="$HEIGHT" QUALITY="$QUALITY" render_with_python
else
  cat >&2 <<MSG
ERROR: No renderer available.
Install one of the following:
  - ImageMagick (magick/convert with SVG support), or
  - Python packages cairosvg + pillow
Then run: bash scripts/render_og.sh [input.svg] [output.jpg]
MSG
  exit 1
fi

if [[ ! -s "$OUTPUT" ]]; then
  echo "ERROR: render failed, output is empty: $OUTPUT" >&2
  exit 1
fi

echo "Rendered: $OUTPUT"
