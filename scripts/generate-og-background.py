#!/usr/bin/env python3
"""Regenerate the Open Graph thumbnail background.

    python3 scripts/generate-og-background.py

Mintlify builds a share card for every page itself, overlaying the site logo,
the page title and the page description onto a background. `thumbnails.background`
in `docs.json` is that background, and this paints it: a Parchment field with a
soft Twilight-to-Bluebird wash down the right edge, echoing the gradient in the
logo mark.

Why a background rather than a single static `og:image`: a static card would
show the same title on every page, and the help center's whole value in a link
preview is *which* article was shared. This keeps Mintlify's per-page overlay
and only supplies the canvas underneath.

Why this repo hosts it rather than pointing at bowerlabs.ai or app.bowerlabs.ai:
each Bower property renders and hosts its own share artwork. A versioned URL on
one side would silently break the other's meta tag on the next bump — and on
SPA hosting a missing image returns 200 with an HTML body, so the break would
never surface as a 404. See the same note in the website repo's
`scripts/check-brand-drift.mjs`.

No third-party dependencies: the docs CI runs Python only, and a share-card
background is not worth a toolchain. PNG encoding is `zlib` plus a CRC, both
stdlib.

The output is committed. Mintlify serves this repo verbatim, so the file has to
exist in git — re-run this rather than editing the PNG.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "images" / "og-background.png"

# Open Graph's recommended large-card size, and what Mintlify generates at.
WIDTH = 1200
HEIGHT = 630

# 2026-08 brand palette. Kept in step with the website repo's src/lib/brand.json
# and the app repo's packages/frontend/src/theme/colors.brand.ts; the hashes and
# hexes are asserted by scripts/validate-docs.py.
PARCHMENT = (0xF0, 0xEE, 0xE9)
TWILIGHT = (0x5C, 0x88, 0xDA)
BLUEBIRD = (0x69, 0xB3, 0xE7)

# Peak opacity of the wash, in the bottom-right corner. Deliberately low: the
# card's title and description are drawn by Mintlify in the theme's ink colour
# and this file cannot influence that, so the background has to stay light
# enough that a dark label clears AA everywhere on it. At 0.18 the darkest
# pixel is #D5DCE6, which holds Charcoal #212721 at 12.4:1.
PEAK_ALPHA = 0.18

# The wash is anchored past the corner so only its falloff lands on the canvas,
# and the left ~60% — where the logo and title sit — stays flat Parchment.
CENTRE = (1.12, 1.18)
RADIUS = 0.78


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def pixel(x: int, y: int) -> tuple[int, int, int]:
    """Parchment, with the twilight wash falling off toward the top-left."""
    nx = x / (WIDTH - 1)
    ny = y / (HEIGHT - 1)
    distance = ((nx - CENTRE[0]) ** 2 + (ny - CENTRE[1]) ** 2) ** 0.5

    # Smoothstep the falloff; a linear ramp bands visibly at this bit depth.
    t = max(0.0, min(1.0, 1.0 - distance / RADIUS))
    alpha = PEAK_ALPHA * (t * t * (3.0 - 2.0 * t))

    # The wash itself runs twilight -> bluebird along the diagonal, the same
    # direction as the mark's gradient.
    blend = max(0.0, min(1.0, (nx + (1.0 - ny)) / 2.0))
    wash = [lerp(TWILIGHT[i], BLUEBIRD[i], blend) for i in range(3)]

    return tuple(round(lerp(PARCHMENT[i], wash[i], alpha)) for i in range(3))


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(rows: list[bytearray]) -> bytes:
    # Filter type 0 (None) per scanline. The image is a smooth gradient, so
    # zlib does the work and a per-row filter search would not pay for itself.
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    rows = []
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            row.extend(pixel(x, y))
        rows.append(row)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(encode_png(rows))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
