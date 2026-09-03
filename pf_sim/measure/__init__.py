from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from ..scene import focused_id, iter_nodes
from . import contrast, diff, gaps, ink, overlay, report


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def selected(scene: dict, node_ids: set[str] | None, role: str | None) -> list[dict]:
    result = []
    for node in iter_nodes(scene):
        node_role = node.get("role") or node.get("type_role") or node.get("content", {}).get("kind")
        if node.get("id") and (node_ids is None or node["id"] in node_ids) and (role is None or node_role == role):
            result.append(node)
    return result


def run(png: Path, scene_path: Path, out: Path, *, node_ids=None, role=None, min_gap=0,
        contrast_floor=4.5) -> dict:
    scene = _json(scene_path); image = Image.open(png).convert("RGB")
    nodes = selected(scene, node_ids, role)
    all_nodes = selected(scene, None, None)
    boxes = {node["id"]: ink.declared_box(node) for node in all_nodes}
    measured = {}
    for node in nodes:
        box = boxes[node["id"]]
        exclusions = []
        if box:
            for other in all_nodes:
                other_box = boxes[other["id"]]
                other_role = other.get("role") or other.get("content", {}).get("kind")
                if other["id"] != node["id"] and other_box and other_box != box:
                    other_contains_node = (other_box[0] <= box[0] and other_box[1] <= box[1]
                                           and other_box[2] >= box[2] and other_box[3] >= box[3])
                    overlaps = not (other_box[2] <= box[0] or other_box[0] >= box[2]
                                    or other_box[3] <= box[1] or other_box[1] >= box[3])
                    text_like = other_role in {"text", "label", "caption", "value"}
                    later_text = text_like and other_box[0] > box[0]
                    if overlaps and not other_contains_node and (not text_like or later_text):
                        exclusions.append(other_box)
        measured[node["id"]] = ink.measure_node(image, node, exclusions=exclusions)
    text_ids = {node["id"] for node in nodes if (node.get("type_role") or node.get("role") or node.get("content", {}).get("kind")) in {"text", "label", "caption", "value"}}
    contrast_values = {node: contrast.measure(image, measured[node], contrast_floor) for node in text_ids}
    gap_values = gaps.matrix(measured, min_gap)
    sidecar_path = png.with_suffix(".json")
    provenance = _json(sidecar_path) if sidecar_path.exists() else {}
    provenance["png_sha256"] = hashlib.sha256(png.read_bytes()).hexdigest()
    result = report.build(provenance, measured, gap_values, contrast_values,
                          {"min_gap": min_gap, "contrast_floor": contrast_floor, "ink_threshold": 24})
    out.mkdir(parents=True, exist_ok=True)
    overlay.render(image, nodes, focused_id(scene)).save(out / "overlay.png")
    for name, value in (("ink", measured), ("gaps", gap_values), ("contrast", contrast_values)):
        (out / f"{name}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    report.write(out, result)
    return result


def run_diff(a_png: Path, b_png: Path, a_scene: Path, b_scene: Path, out: Path) -> dict:
    ai, bi = Image.open(a_png).convert("RGB"), Image.open(b_png).convert("RGB")
    an = selected(_json(a_scene), None, None); bn = selected(_json(b_scene), None, None)
    am = {n["id"]: ink.measure_node(ai, n) for n in an}; bm = {n["id"]: ink.measure_node(bi, n) for n in bn}
    raster, moved = diff.compare(ai, bi, am, bm)
    out.mkdir(parents=True, exist_ok=True); raster.save(out / "diff.png")
    value = {"moved_nodes": moved, "a_sha256": hashlib.sha256(a_png.read_bytes()).hexdigest(), "b_sha256": hashlib.sha256(b_png.read_bytes()).hexdigest()}
    (out / "diff.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return value
