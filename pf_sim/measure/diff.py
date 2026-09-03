from __future__ import annotations

from PIL import Image, ImageChops


def compare(a: Image.Image, b: Image.Image, a_ink: dict, b_ink: dict) -> tuple[Image.Image, list[str]]:
    if a.size != b.size: raise ValueError("reason=diff_size_mismatch")
    changed = sorted(node for node in a_ink.keys() & b_ink.keys()
                     if a_ink[node].get("ink_extents") != b_ink[node].get("ink_extents"))
    return ImageChops.difference(a.convert("RGB"), b.convert("RGB")), changed

