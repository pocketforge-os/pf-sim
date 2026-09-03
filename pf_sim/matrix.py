from __future__ import annotations

import html
import json
import shutil
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import capture, measure
from .config import safe_child, sim_home, validate_name
from .scenario import LiveBackend


@dataclass(frozen=True)
class Route:
    name: str
    steps: tuple[dict, ...]
    nodes: frozenset[str] | None
    role: str | None
    skip: bool = False
    reason: str | None = None
    profiles: frozenset[str] | None = None
    expect: dict | None = None


@dataclass(frozen=True)
class Matrix:
    name: str
    routes: tuple[str, ...]
    scales: tuple[str, ...]
    contrasts: tuple[str, ...]
    profiles: tuple[str, ...]
    definitions: dict[str, Route]
    min_gap: int
    contrast_floor: float


@dataclass(frozen=True)
class Cell:
    route: str
    scale: str
    contrast: str
    profile: str
    skip: bool
    reason: str | None

    @property
    def name(self) -> str:
        return validate_name("capture", "-".join((self.route, self.scale, self.contrast, self.profile)))


def load(path: str | Path) -> Matrix:
    try:
        value = tomllib.loads(Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"reason=invalid_matrix detail={error}") from error
    header = value.get("matrix")
    routes = value.get("routes")
    settings = value.get("measure", {})
    if not isinstance(header, dict) or not isinstance(routes, dict) or not isinstance(settings, dict):
        raise ValueError("reason=invalid_matrix_schema")
    required = ("routes", "scales", "contrasts", "profiles")
    if any(not isinstance(header.get(key), list) or not header[key] for key in required):
        raise ValueError("reason=invalid_matrix_schema")
    name = validate_name("matrix", header.get("name", Path(path).stem))
    axes = {key: tuple(_names(key[:-1], item) for item in header[key]) for key in required}
    if any(scale not in ("100", "150", "200") for scale in axes["scales"]):
        raise ValueError("reason=invalid_matrix_scale")
    if any(contrast not in ("default", "hc") for contrast in axes["contrasts"]):
        raise ValueError("reason=invalid_matrix_contrast")
    definitions = {}
    for route_name in axes["routes"]:
        raw = routes.get(route_name)
        if not isinstance(raw, dict):
            raise ValueError(f"reason=missing_matrix_route route={route_name}")
        steps = raw.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError(f"reason=invalid_matrix_route route={route_name}")
        for step in steps:
            if step.get("op") not in ("input", "text") or set(step) != ({"op", "seq"} if step.get("op") == "input" else {"op", "value"}):
                raise ValueError(f"reason=invalid_matrix_step route={route_name}")
        measured_routes = settings.get("nodes_by_route", {})
        measured = measured_routes.get(route_name, {}) if isinstance(measured_routes, dict) else {}
        if not isinstance(measured, dict): raise ValueError(f"reason=invalid_matrix_measure route={route_name}")
        node_values = measured.get("nodes", raw.get("nodes"))
        nodes = None if node_values is None else frozenset(_names("node", item) for item in node_values)
        role = measured.get("role", raw.get("role"))
        if role is not None: validate_name("role", role)
        profiles = raw.get("profiles")
        if profiles is not None:
            profiles = frozenset(_names("profile", item) for item in profiles)
        skip = raw.get("skip", False)
        reason = raw.get("reason")
        if not isinstance(skip, bool) or (skip and not isinstance(reason, str)):
            raise ValueError(f"reason=invalid_matrix_skip route={route_name}")
        expect = raw.get("expect")
        if not skip and (not isinstance(expect, dict) or not isinstance(expect.get("screen"), str)):
            raise ValueError(f"reason=invalid_matrix_expect route={route_name}")
        if expect is not None:
            allowed = {"screen", "focused_prefix", "search_query"}
            if set(expect) - allowed or any(not isinstance(item, str) for item in expect.values()):
                raise ValueError(f"reason=invalid_matrix_expect route={route_name}")
            expect = dict(expect)
        definitions[route_name] = Route(route_name, tuple(steps), nodes, role, skip, reason, profiles, expect)
    return Matrix(name, axes["routes"], axes["scales"], axes["contrasts"], axes["profiles"],
                  definitions, int(settings.get("min_gap", 0)), float(settings.get("contrast_floor", 4.5)))


def _names(kind: str, value: object) -> str:
    if not isinstance(value, str): raise ValueError("reason=invalid_matrix_schema")
    return validate_name(kind, value)


def parse_only(expression: str | None) -> dict[str, str]:
    if not expression: return {}
    result = {}
    for term in expression.split(","):
        key, separator, value = term.partition("=")
        if not separator or key not in {"route", "scale", "contrast", "profile"} or key in result:
            raise ValueError("reason=invalid_matrix_filter")
        result[key] = validate_name(key, value)
    return result


def cells(spec: Matrix, only: dict[str, str] | None = None) -> list[Cell]:
    only = only or {}
    axes = {"route": spec.routes, "scale": spec.scales, "contrast": spec.contrasts, "profile": spec.profiles}
    for key, value in only.items():
        if value not in axes[key]: raise ValueError(f"reason=unknown_matrix_{key}")
    result = []
    for profile in spec.profiles:
        for scale in spec.scales:
            for contrast in spec.contrasts:
                for route_name in spec.routes:
                    values = {"route": route_name, "scale": scale, "contrast": contrast, "profile": profile}
                    if any(values[key] != value for key, value in only.items()): continue
                    route = spec.definitions[route_name]
                    skip = route.skip or route.profiles is not None and profile not in route.profiles
                    reason = route.reason if route.skip else ("route_not_applicable_to_profile" if skip else None)
                    result.append(Cell(route_name, scale, contrast, profile, skip, reason))
    return result


class Backend(Protocol):
    def start(self, profile: str, scale: str, contrast: str) -> None: ...
    def execute(self, step: dict) -> object: ...
    def observe(self) -> dict: ...
    def capture_and_measure(self, cell: Cell, route: Route, root: Path, spec: Matrix) -> dict: ...


class LiveMatrixBackend:
    def __init__(self, instance: str = "matrix"):
        self.instance = validate_name("instance", instance)
        self.live = LiveBackend(self.instance)

    def start(self, profile: str, scale: str, contrast: str) -> None:
        self.profile = profile
        self.live.start(profile, scale, contrast, True)

    def execute(self, step: dict) -> object:
        before = (self.live.automation.scene().get("revision", 0)
                  if step["op"] == "input" and self.profile != "degraded-authority" else None)
        try:
            result = self.live.execute(step)
        except RuntimeError as error:
            # This known profile deliberately has no authority socket. Its shell
            # continuously presents, so input's post-action idle wait times out
            # even though the action was accepted. Capture has the corresponding
            # bounded content-stability fallback and remains the source of truth.
            if self.profile == "degraded-authority" and str(error) == "reason=automation_error error=timeout":
                result = {"settled": "content-stable", "revision_churn": True}
            else:
                raise
        # The tap RPC completes when evdev receives the release, not when the
        # launcher has consumed it.  Its first wait_idle can consequently report
        # the pre-input frame.  Give the reader one dispatch interval, then put a
        # second idle barrier after the event.  Revision deltas cannot serve as
        # this barrier: degraded-authority deliberately churns revisions without
        # consuming input.
        if step["op"] == "input":
            # The headless launcher polls evdev on its presentation loop; under
            # load that loop can be several hundred milliseconds behind the tap
            # helper even though the automation socket itself is responsive.
            time.sleep(1.0)
            if before is not None:
                deadline = time.monotonic() + 3
                while self.live.automation.scene().get("revision", 0) <= before:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("reason=input_not_observed")
                    time.sleep(.02)
            else:
                # Revision churn makes the acknowledgement test meaningless for
                # this profile; the dispatch grace above remains the barrier.
                pass
            try:
                self.live.automation.wait_idle()
            except RuntimeError as error:
                if self.profile != "degraded-authority" or str(error) != "reason=automation_error error=timeout":
                    raise
        return result

    def observe(self) -> dict:
        return self.live.observe()[0]

    def capture_and_measure(self, cell: Cell, route: Route, root: Path, spec: Matrix) -> dict:
        png, sidecar = capture.capture(cell.name, self.instance)
        cell_root = safe_child(root / "cells", "cell", cell.name)
        cell_root.mkdir(parents=True, exist_ok=True)
        target = cell_root / "capture.png"
        shutil.copy2(png, target)
        shutil.copy2(png.with_suffix(".scene.json"), cell_root / "capture.scene.json")
        shutil.copy2(png.with_suffix(".json"), cell_root / "capture.json")
        measured = measure.run(target, cell_root / "capture.scene.json", cell_root / "measure",
                               node_ids=route.nodes, role=route.role, min_gap=spec.min_gap,
                               contrast_floor=spec.contrast_floor)
        failures = [name for name, check in measured["checks"].items() if check["status"] == "FAIL"]
        return {"status": measured["status"], "sha256": sidecar["sha256"],
                "settled": sidecar.get("settled"), "failures": failures,
                "capture": f"cells/{cell.name}/capture.png",
                "overlay": f"cells/{cell.name}/measure/overlay.png",
                "report": f"cells/{cell.name}/measure/report.md"}


def run(spec: Matrix, *, only=None, out: Path | None = None, repeat: int = 1,
        no_fail: bool = False, backend: Backend | None = None) -> tuple[int, dict, Path]:
    if repeat < 1: raise ValueError("reason=invalid_repeat")
    root = out.resolve() if out else safe_child(sim_home() / "matrices", "matrix", spec.name)
    root.mkdir(parents=True, exist_ok=True)
    selected = cells(spec, only)
    current = backend or LiveMatrixBackend()
    records = []
    grouped = {}
    for cell in selected:
        grouped.setdefault((cell.profile, cell.scale, cell.contrast), []).append(cell)
    for (profile, scale, contrast), group in grouped.items():
        runnable = [cell for cell in group if not cell.skip]
        if not runnable:
            records.extend(_skip_record(cell) for cell in group); continue
        current.start(profile, scale, contrast)
        # First-run is the initial presentation and must be observed before navigation.
        runnable.sort(key=lambda cell: cell.route != "first-run")
        for cell in group:
            if cell.skip: records.append(_skip_record(cell))
        for cell in runnable:
            route = spec.definitions[cell.route]
            hashes = []
            record = {"name": cell.name, "route": cell.route, "scale": cell.scale,
                      "contrast": cell.contrast, "profile": cell.profile, "status": "error"}
            try:
                if cell.route != "first-run":
                    _reset(current)
                for step in route.steps: current.execute(step)
                observed = current.observe()
                screen = _screen(observed)
                record.update(observed_screen=screen, observed_focused=observed.get("focused", ""))
                if not _matches(route.expect or {}, observed, screen):
                    expected = route.expect.get("screen") if route.expect else cell.route
                    raise RuntimeError(
                        f"reason=route_mismatch expected={expected} "
                        f"observed={screen}/{observed.get('focused', '')}"
                    )
                last = None
                for _ in range(repeat):
                    last = current.capture_and_measure(cell, route, root, spec); hashes.append(last["sha256"])
                record.update(last or {}, deterministic=len(set(hashes)) == 1)
            except Exception as error:
                record.update(reason=str(error), failures=[str(error)], deterministic=False)
            records.append(record)
    order = {cell.name: index for index, cell in enumerate(selected)}
    records.sort(key=lambda record: order[record["name"]])
    failed = sum(record["status"] in ("FAIL", "error") for record in records)
    skipped = sum(record["status"] == "skip" for record in records)
    deterministic = all(record.get("deterministic", True) for record in records)
    report = {"matrix": spec.name, "cells": records, "cell_count": len(records), "skipped": skipped,
              "failed": failed, "deterministic": deterministic, "repeat": repeat}
    (root / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (root / "report.md").write_text(render_markdown(report))
    (root / "index.html").write_text(render_html(report))
    status = failed == 0 and deterministic
    return (0 if status or no_fail else 1), report, root


_SCREEN_MARKERS = {
    "first-run": "first-run-panel",
    "quick": "quick-panel-surface",
    "details": "detail-title",
    "library": "library-search",
    "search-populated": "search-results-scroll-region",
    "home": "home-scroll-region",
}


def _node_ids(node: object):
    if not isinstance(node, dict):
        return
    node_id = node.get("id")
    if isinstance(node_id, str):
        yield node_id
    for child in node.get("children", []):
        yield from _node_ids(child)


def _screen(scene: dict) -> str:
    ids = set(_node_ids(scene.get("scene")))
    # Overlays must win over the underlying route nodes they intentionally retain.
    for name in ("first-run", "quick", "details", "library", "search-populated", "home"):
        if _SCREEN_MARKERS[name] in ids:
            return name
    return "unknown"


def _matches(expect: dict, scene: dict, screen: str) -> bool:
    return (screen == expect.get("screen")
            and ("focused_prefix" not in expect
                 or str(scene.get("focused", "")).startswith(expect["focused_prefix"]))
            and ("search_query" not in expect
                 or scene.get("search_query") == expect["search_query"]))


def _reset(backend: Backend) -> None:
    backend.execute({"op": "input", "seq": "SafeReturn"})
    for _ in range(8):
        scene = backend.observe()
        screen = _screen(scene)
        query = scene.get("search_query", "")
        if screen == "first-run":
            backend.execute({"op": "input", "seq": "Start"})
            continue
        if screen == "home" and query == "":
            return
        if screen == "home" and query:
            backend.execute({"op": "input", "seq": "Search.open"})
            backend.execute({"op": "text", "value": ""})
        backend.execute({"op": "input", "seq": "Back"})
    scene = backend.observe()
    raise RuntimeError(
        f"reason=route_reset_failed observed={_screen(scene)}/{scene.get('focused', '')} "
        f"search_query={scene.get('search_query', '')!r}"
    )


def _skip_record(cell: Cell) -> dict:
    return {"name": cell.name, "route": cell.route, "scale": cell.scale, "contrast": cell.contrast,
            "profile": cell.profile, "status": "skip", "reason": cell.reason, "deterministic": True}


def render_markdown(report: dict) -> str:
    lines = [f"# Matrix: {report['matrix']}", "", f"Deterministic: **{str(report['deterministic']).lower()}**", ""]
    for profile in dict.fromkeys(item["profile"] for item in report["cells"]):
        lines += [f"## {profile}", "", "| Route | Preset | Status | Settled | SHA-256 | Failures | Evidence |",
                  "|---|---|---|---|---|---|---|"]
        for item in (entry for entry in report["cells"] if entry["profile"] == profile):
            evidence = ""
            if item.get("capture"):
                evidence = f"[capture]({item['capture']}) [overlay]({item['overlay']}) [report]({item['report']})"
            failures = ", ".join(item.get("failures", [])) or item.get("reason", "") or ""
            lines.append(f"| {item['route']} | {item['scale']}/{item['contrast']} | {item['status']} | {item.get('settled', '') or ''} | {item.get('sha256', '')} | {failures} | {evidence} |")
        lines.append("")
    return "\n".join(lines)


def render_html(report: dict) -> str:
    cards = []
    for item in report["cells"]:
        title = html.escape(f"{item['route']} · {item['scale']}/{item['contrast']} · {item['profile']}")
        if item.get("capture"):
            path = html.escape(item["capture"], quote=True)
            overlay = html.escape(item["overlay"], quote=True)
            body = f'<a href="{overlay}"><img loading="lazy" src="{path}" alt="{title}"></a>'
        else: body = f'<div class="skip">{html.escape(item.get("reason", "skipped"))}</div>'
        cards.append(f'<article><h2>{title}</h2>{body}<p>{html.escape(item["status"])}</p></article>')
    return "<!doctype html><html><head><meta charset=\"utf-8\"><title>Matrix report</title><style>body{font:14px sans-serif;background:#16181d;color:#eee}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}article{background:#252932;padding:10px}h2{font-size:14px}img{width:100%;height:auto}.skip{height:140px;display:grid;place-items:center}</style></head><body><h1>" + html.escape(report["matrix"]) + "</h1><main>" + "".join(cards) + "</main></body></html>\n"
