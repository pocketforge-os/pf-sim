from __future__ import annotations

import re

from .scene import find, focused_id


_QUOTED = r'"((?:[^"\\]|\\.)*)"'
_BINARY = re.compile(rf"^(focused_label|focused_id|route|search_query)\s*==\s*{_QUOTED}$")
_LABEL = re.compile(rf"^(label_present|label_absent)\s+{_QUOTED}$")
_COUNT = re.compile(r"^result_count\s*<\s*(\d+)$")
_STATE = re.compile(r"^(session_state|last_receipt|app_state)\s*==\s*([A-Za-z][A-Za-z_-]*)$")


def parse(expression: str) -> tuple[str, object]:
    expression = expression.strip()
    match = _BINARY.fullmatch(expression) or _LABEL.fullmatch(expression)
    if match:
        return match.group(1), bytes(match.group(2), "utf-8").decode("unicode_escape")
    match = _COUNT.fullmatch(expression)
    if match:
        return "result_count", int(match.group(1))
    match = _STATE.fullmatch(expression)
    if match:
        key, value = match.groups()
        allowed = {
            "session_state": {"launching", "running", "idle"},
            "last_receipt": {"Returned", "Crash", "ForcedClose"},
            "app_state": {"running", "none"},
        }
        if value in allowed[key]:
            return key, value
    raise ValueError("reason=invalid_predicate")


def evaluate(expression: str, scene: dict, history: list[dict], ping: dict | None = None) -> bool:
    kind, expected = parse(expression)
    if kind == "focused_id":
        return focused_id(scene) == expected
    if kind == "focused_label":
        node = next((node for node in _nodes(scene) if node.get("id") == focused_id(scene)), None)
        return _label(node) == expected
    if kind in ("label_present", "label_absent"):
        present = find(scene, label=expected) is not None or any(_label(node) == expected for node in _nodes(scene))
        return present if kind == "label_present" else not present
    if kind == "route":
        return scene.get("route") == expected
    if kind == "search_query":
        return scene.get("search_query") == expected
    if kind == "result_count":
        results = scene.get("search_result_ids", scene.get("results", []))
        return len(results) < expected
    active = next((entry for entry in reversed(history) if not entry.get("receipt")), None)
    if kind == "app_state":
        return ("running" if active and (ping or {}).get("app_state", "running") == "running" else "none") == expected
    if kind == "session_state":
        state = (ping or {}).get("session_state")
        if not state:
            state = "idle" if active is None else (ping or {}).get("app_state", "launching")
        return state == expected
    receipt = history[-1].get("receipt") if history else None
    if isinstance(receipt, dict):
        receipt = receipt.get("kind", next(iter(receipt), None))
    return receipt == expected


def _nodes(scene: dict):
    from .scene import iter_nodes
    return iter_nodes(scene)


def _label(node: dict | None):
    if not node:
        return None
    return node.get("label", node.get("content", {}).get("text"))
