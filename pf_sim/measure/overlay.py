from __future__ import annotations

from PIL import Image, ImageDraw


COLORS = {"text": "#00d4ff", "button": "#ff9f1c", "screen": "#888888", "image": "#2ec4b6"}


def render(image: Image.Image, nodes: list[dict], focused: str | None) -> Image.Image:
    output = image.convert("RGB").copy(); draw = ImageDraw.Draw(output)
    for node in nodes:
        bounds = node.get("bounds")
        if isinstance(bounds, list): x, y, width, height = bounds
        elif isinstance(bounds, dict): x, y, width, height = (bounds.get(k, 0) for k in ("x", "y", "width", "height"))
        else: continue
        role = node.get("role") or node.get("type_role") or node.get("content", {}).get("kind", "node")
        color = "#ff3366" if node.get("id") == focused else COLORS.get(role, "#f4d35e")
        line = 3 if node.get("id") == focused else 1
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline=color, width=line)
        label = node.get("id", "?") + (" " + str(node.get("accessible_label") or node.get("label")) if node.get("accessible_label") or node.get("label") else "")
        draw.text((x + 2, y + 1), label, fill=color, stroke_width=1, stroke_fill="black")
    return output

