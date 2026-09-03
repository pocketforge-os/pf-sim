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
    extent, background = ink.get("ink_extents"), ink.get("dominant_background")
    if not extent or background is None:
        return None
    rgb = image.convert("RGB"); bg = tuple(background)
    x0, y0 = extent["x"], extent["y"]
    x1, y1 = x0 + extent["width"], y0 + extent["height"]
    ink_colors = Counter(rgb.getpixel((x, y)) for y in range(max(0, y0), min(rgb.height, y1))
                         for x in range(max(0, x0), min(rgb.width, x1)) if different(rgb.getpixel((x, y)), bg))
    color = tuple(ink.get("dominant_ink") or (ink_colors.most_common(1)[0][0] if ink_colors else bg))
    # The local ring is authoritative when it has a stable colour; the declared
    # dominant is the fallback for boxes at a frame edge.
    ring = []
    for y in range(max(0, y0 - 2), min(rgb.height, y1 + 2)):
        for x in range(max(0, x0 - 2), min(rgb.width, x1 + 2)):
            if not (x0 <= x < x1 and y0 <= y < y1): ring.append(rgb.getpixel((x, y)))
    local_bg = Counter(ring).most_common(1)[0][0] if ring else bg
    value = ratio(color, local_bg)
    return {"ink_color": list(color), "background_color": list(local_bg), "ratio": round(value, 4),
            "floor": floor, "status": "PASS" if value >= floor else "FAIL"}
