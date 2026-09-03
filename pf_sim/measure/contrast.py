from __future__ import annotations

from collections import Counter

from PIL import Image

from .ink import different


def luminance(color: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    r, g, b = map(channel, color)
    return .2126 * r + .7152 * g + .0722 * b


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    bright, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (bright + .05) / (dark + .05)


def measure(image: Image.Image, ink: dict, floor: float) -> dict | None:
    bounds = ink.get("declared_bounds")
    if not bounds:
        return None
    rgb = image.convert("RGB")
    x0, y0 = bounds["x"], bounds["y"]
    x1, y1 = x0 + bounds["width"], y0 + bounds["height"]
    inside = [rgb.getpixel((x, y)) for y in range(max(0, y0), min(rgb.height, y1))
              for x in range(max(0, x0), min(rgb.width, x1))]
    if not inside:
        return None
    counts = Counter(inside); background = counts.most_common(1)[0][0]
    ring = [rgb.getpixel((x, y)) for y in range(max(0, y0 - 2), min(rgb.height, y1 + 2))
            for x in range(max(0, x0 - 2), min(rgb.width, x1 + 2))
            if not (x0 <= x < x1 and y0 <= y < y1)]
    outside = Counter(ring).most_common(1)[0][0] if ring else None
    declared_background = ink.get("dominant_background")
    if declared_background is not None and tuple(declared_background) != outside:
        # Text bounds may contain more page bleed than fill at large scales.  The
        # border-derived node background identifies the local box fill while the
        # outside-ring exclusion prevents rounded page corners becoming ink.
        background = tuple(declared_background)
    minimum = max(2, int(len(inside) * .005))
    candidates = [color for color, count in counts.items()
                  if count >= minimum and different(color, background)
                  and color != outside]
    if not candidates:
        return {"ink_color": None, "background_color": list(background), "ratio": None,
                "floor": floor, "status": "NO_INK"}
    color = max(candidates, key=lambda candidate: ratio(candidate, background))
    value = ratio(color, background)
    return {"ink_color": list(color), "background_color": list(background), "ratio": round(value, 4),
            "floor": floor, "status": "PASS" if value >= floor else "FAIL"}
