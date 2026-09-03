from __future__ import annotations


def iter_nodes(scene_json: dict):
    root = scene_json.get("scene", scene_json)
    stack = [root]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        yield node
        stack.extend(reversed(node.get("children", [])))


def find(scene_json: dict, *, role=None, label=None):
    for node in iter_nodes(scene_json):
        content = node.get("content", {})
        node_role = node.get("role", content.get("kind"))
        node_label = node.get("label", content.get("text"))
        if (role is None or node_role == role) and (label is None or node_label == label):
            return node
    return None


def focused_id(scene_json: dict):
    return scene_json.get("focused")


def route(scene_json: dict):
    for node in iter_nodes(scene_json):
        node_id = node.get("id", "")
        if node_id.startswith("room-") and node_id.endswith("-underline"):
            return node_id.removeprefix("room-").removesuffix("-underline").title()
    return scene_json.get("route")


def node_bounds(node: dict):
    bounds = node.get("bounds")
    if isinstance(bounds, dict):
        return tuple(bounds.get(k) for k in ("x", "y", "width", "height"))
    return tuple(bounds) if isinstance(bounds, list) else None
