from __future__ import annotations


def _edges(box: dict) -> tuple[int, int, int, int]:
    return box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]


def axis_gap(a: dict, b: dict, axis: str) -> int:
    ax0, ay0, ax1, ay1 = _edges(a); bx0, by0, bx1, by1 = _edges(b)
    a0, a1, b0, b1 = (ax0, ax1, bx0, bx1) if axis == "horizontal" else (ay0, ay1, by0, by1)
    return max(a0, b0) - min(a1, b1)


def matrix(nodes: dict[str, dict], min_gap: int = 0) -> dict:
    pairs = []
    ids = list(nodes)
    for offset, left in enumerate(ids):
        for right in ids[offset + 1:]:
            item = {"a": left, "b": right}
            for source, key in (("ink_extents", "ink"), ("declared_bounds", "declared")):
                a, b = nodes[left].get(source), nodes[right].get(source)
                item[key] = None if not a or not b else {
                    "horizontal": axis_gap(a, b, "horizontal"),
                    "vertical": axis_gap(a, b, "vertical"),
                }
            # Rectangles normally overlap on the perpendicular axis. Their useful
            # separation is therefore the larger axis gap; it is negative only
            # when they overlap on both axes.
            values = [] if item["ink"] is None else list(item["ink"].values())
            item["under_min_gap"] = bool(values) and max(values) < min_gap
            pairs.append(item)
    return {"min_gap": min_gap, "pairs": pairs}
