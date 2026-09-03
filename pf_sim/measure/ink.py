from __future__ import annotations

from collections import Counter
from typing import Iterable

from PIL import Image

from ..scene import node_bounds


Color = tuple[int, int, int]
BBox = tuple[int, int, int, int]


def dominant(pixels: Iterable[Color]) -> Color | None:
    counts = Counter(pixels)
    return counts.most_common(1)[0][0] if counts else None


def different(a: Color, b: Color, threshold: int = 24) -> bool:
    return max(abs(a[i] - b[i]) for i in range(3)) > threshold


def declared_box(node: dict) -> BBox | None:
    value = node_bounds(node)
    if not value or any(v is None for v in value):
        return None
    x, y, width, height = map(int, value)
    return x, y, x + width, y + height


def measure_node(image: Image.Image, node: dict, threshold: int = 24,
                 exclusions: list[BBox] | None = None) -> dict:
    box = declared_box(node)
    if box is None:
        return {"declared_bounds": None, "ink_extents": None, "insets": None}
    rgb = image.convert("RGB")
    width, height = rgb.size
    x0, y0, x1, y1 = box
    clipped = (max(0, x0), max(0, y0), min(width, x1), min(height, y1))
    pixels = []
    if clipped[2] > clipped[0] and clipped[3] > clipped[1]:
        # A border sample avoids treating a large filled glyph/shape as its own
        # background. This matches the raster-ink guard's local-background idea.
        for y in range(clipped[1], clipped[3]):
            for x in range(clipped[0], clipped[2]):
                if x in (clipped[0], clipped[2] - 1) or y in (clipped[1], clipped[3] - 1):
                    pixels.append(rgb.getpixel((x, y)))
    background = dominant(pixels)
    points: list[tuple[int, int]] = []
    foreground = None
    if background is not None:
        candidates = [rgb.getpixel((x, y)) for y in range(clipped[1], clipped[3])
                      for x in range(clipped[0], clipped[2])
                      if different(rgb.getpixel((x, y)), background, threshold)]
        foreground = dominant(candidates)
        # Include a small halo so overflow just outside a declared box becomes a
        # negative inset. Pixels must differ from the node's own dominant fill.
        halo = (max(0, x0 - 2), max(0, y0 - 2), min(width, x1 + 2), min(height, y1 + 2))
        for y in range(halo[1], halo[3]):
            for x in range(halo[0], halo[2]):
                color = rgb.getpixel((x, y))
                excluded = any(ex0 <= x < ex1 and ey0 <= y < ey1
                               for ex0, ey0, ex1, ey1 in (exclusions or []))
                if not excluded and foreground is not None and max(abs(color[i] - foreground[i]) for i in range(3)) <= 12:
                    points.append((x, y))
    ink = None
    insets = None
    if points:
        ix0 = min(x for x, _ in points); iy0 = min(y for _, y in points)
        ix1 = max(x for x, _ in points) + 1; iy1 = max(y for _, y in points) + 1
        ink = {"x": ix0, "y": iy0, "width": ix1 - ix0, "height": iy1 - iy0}
        insets = {"left": ix0 - x0, "top": iy0 - y0, "right": x1 - ix1, "bottom": y1 - iy1}
    return {
        "declared_bounds": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
        "dominant_background": list(background) if background else None,
        "dominant_ink": list(foreground) if foreground else None,
        "ink_extents": ink,
        "insets": insets,
    }
