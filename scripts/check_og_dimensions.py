#!/usr/bin/env python3
import re
from pathlib import Path


WIDTH = 1200
HEIGHT = 630


def _parse_numeric(value: str) -> int:
    cleaned = value.strip().replace('px', '')
    if not re.fullmatch(r'\d+(\.\d+)?', cleaned):
        raise ValueError(f'Invalid numeric value: {value}')
    return int(float(cleaned))


def get_svg_size(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding='utf-8')

    width_match = re.search(r'\bwidth="([^"]+)"', text)
    height_match = re.search(r'\bheight="([^"]+)"', text)

    if width_match and height_match:
        return _parse_numeric(width_match.group(1)), _parse_numeric(height_match.group(1))

    viewbox_match = re.search(r'\bviewBox="([^"]+)"', text)
    if not viewbox_match:
        raise ValueError('SVG must have width/height or viewBox')

    parts = viewbox_match.group(1).split()
    if len(parts) != 4:
        raise ValueError('Invalid viewBox format')

    return _parse_numeric(parts[2]), _parse_numeric(parts[3])


if __name__ == '__main__':
    image_path = Path('og-cover.svg')
    width, height = get_svg_size(image_path)
    print(f'og-cover.svg: {width}x{height}')
    if (width, height) != (WIDTH, HEIGHT):
        raise SystemExit(f'ERROR: og-cover.svg must be exactly {WIDTH}x{HEIGHT}')
