from __future__ import annotations

import hashlib
import json
import shutil
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from . import inputs, predicates, profiles
from .automation import AutomationClient
from .authority import AuthorityClient
from .backend import DesktopBackend
from .config import run_dir, safe_child, sim_home, validate_name
from .fixture_app import send_command
from .scene import route


OPS = {"profile", "input", "text", "launch", "safe_return", "app", "wait_for", "capture", "assert", "sleep"}
FIELDS = {
    "profile": {"name", "scale", "contrast"}, "input": {"seq"}, "text": {"value"},
    "launch": {"item"}, "safe_return": set(), "app": {"verb", "code"},
    "wait_for": {"predicate", "timeout_ms"}, "capture": {"name"},
    "assert": {"predicate"}, "sleep": {"ms"},
}


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    profile: str
    scale: str
    contrast: str
    steps: list[dict]
    path: Path


def load(path: str | Path) -> Scenario:
    path = Path(path)
    try:
        document = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"reason=invalid_scenario detail={error}") from error
    top = set(document) - {"scenario", "steps"}
    header = document.get("scenario")
    if top or not isinstance(header, dict) or set(header) != {"name", "description", "profile", "scale", "contrast"}:
        raise ValueError("reason=invalid_scenario_schema")
    for field in ("name", "description", "profile", "scale", "contrast"):
        _expect_type(header[field], str, f"scenario.{field}", "string")
    name = validate_name("scenario", header["name"])
    validate_name("profile", header["profile"])
    if header["scale"] not in profiles.SCALES or header["contrast"] not in ("default", "hc"):
        raise ValueError("reason=invalid_scenario_profile")
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("reason=invalid_scenario_steps")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"reason=invalid_scenario field=steps[{index}] expected=table")
        _validate_step(step, index)
    return Scenario(name, header["description"], header["profile"], header["scale"], header["contrast"], steps, path)


def _expect_type(value: object, expected: type, field: str, label: str) -> None:
    if not isinstance(value, expected):
        raise ValueError(f"reason=invalid_scenario field={field} expected={label}")


def _validate_step(step: dict, index: int = 0) -> None:
    if "op" in step:
        _expect_type(step["op"], str, f"steps[{index}].op", "string")
    if step.get("op") not in OPS:
        raise ValueError("reason=unknown_scenario_op")
    op = step["op"]
    required = FIELDS[op] - ({"code"} if op == "app" else {"timeout_ms"} if op == "wait_for" else set())
    if set(step) - ({"op"} | FIELDS[op]) or not required <= set(step):
        raise ValueError(f"reason=invalid_{op}_step")
    string_fields = {
        "profile": ("name", "scale", "contrast"), "input": ("seq",),
        "text": ("value",), "launch": ("item",), "app": ("verb",),
        "wait_for": ("predicate",), "capture": ("name",),
        "assert": ("predicate",),
    }
    for field in string_fields.get(op, ()):
        _expect_type(step[field], str, f"steps[{index}].{field}", "string")
    if "predicate" in step:
        predicates.parse(step["predicate"])
    if op == "profile":
        validate_name("profile", step["name"])
        if step["scale"] not in profiles.SCALES or step["contrast"] not in ("default", "hc"):
            raise ValueError("reason=invalid_profile_step")
    if op == "capture": validate_name("capture", step["name"])
    if op == "launch": validate_name("item", step["item"])
    if op == "app" and step["verb"] not in ("status", "exit", "crash", "quit"):
        raise ValueError("reason=invalid_app_step")
    if op == "app" and step["verb"] == "exit" and not isinstance(step.get("code"), int):
        raise ValueError("reason=invalid_app_step")
    for field in ("timeout_ms", "ms"):
        if field in step and (not isinstance(step[field], int) or step[field] < 0):
            raise ValueError(f"reason=invalid_{op}_step")


class Backend(Protocol):
    def start(self, profile: str, scale: str, contrast: str, replace: bool) -> None: ...
    def execute(self, step: dict) -> object: ...
    def observe(self) -> tuple[dict, list[dict], dict]: ...
    def capture(self, png: Path) -> dict: ...


class LiveBackend:
    def __init__(self, instance: str):
        self.instance = validate_name("instance", instance)
        self.desktop = DesktopBackend()

    def start(self, profile: str, scale: str, contrast: str, replace: bool) -> None:
        self.desktop.up(instance=self.instance, display="headless", replace=replace,
                        profile=profiles.resolve_profile(profile), scale=scale, contrast=contrast)

    @property
    def automation(self): return AutomationClient(run_dir(self.instance) / "automation.sock")
    @property
    def authority(self): return AuthorityClient(run_dir(self.instance) / "session-authority.sock")

    def observe(self):
        ping = self.automation.ping(); history = self.authority.history()
        self._add_session_state(ping, history)
        scene = self.automation.scene()
        scene.setdefault("route", route(scene))
        return scene, history, ping

    def _add_session_state(self, ping, history):
        active = next((entry for entry in reversed(history) if not entry.get("receipt")), None)
        if active:
            session = validate_name("session", active["session_id"])
            socket_path = run_dir(self.instance) / "apps" / f"{session}.sock"
            ping["app_state"] = "running" if socket_path.exists() else "launching"
            ping["session_state"] = ping["app_state"]
        else:
            ping.update(app_state="none", session_state="idle")

    def execute(self, step: dict):
        op = step["op"]
        if op == "profile":
            selected = profiles.resolve_profile(step["name"])
            return self.desktop.apply(self.instance, selected, step["scale"], step["contrast"])
        if op == "input":
            inputs.sequence(self.instance, step["seq"], "shell", 60, 120); return self.automation.wait_idle()
        if op == "text": return self.automation.text(step["value"])
        if op == "launch": return self.authority.launch(step["item"])
        if op == "safe_return": return self.authority.safe_return()
        if op == "app":
            scene, history, ping = self.observe()
            active = next((entry for entry in reversed(history) if not entry.get("receipt")), None)
            if step["verb"] == "status": return ping
            if active is None: raise RuntimeError("reason=app_not_running")
            session = validate_name("session", active["session_id"])
            payload = {"command": step["verb"]}
            if "code" in step: payload["code"] = step["code"]
            return send_command(run_dir(self.instance) / "apps" / f"{session}.sock", payload)
        if op == "sleep": time.sleep(step["ms"] / 1000); return {"slept_ms": step["ms"]}
        if op in ("assert", "wait_for"):
            return self._predicate(step["predicate"], step.get("timeout_ms", 5000 if op == "wait_for" else 0), op == "wait_for")
        return {"name": step["name"]}

    def _predicate(self, expression: str, timeout_ms: int, wait: bool):
        deadline = time.monotonic() + timeout_ms / 1000
        kind, _ = predicates.parse(expression)
        session_only = kind in ("session_state", "app_state", "last_receipt")
        while True:
            if wait and not session_only:
                try: self.automation.wait_idle(timeout_ms=max(1, min(250, timeout_ms)))
                except RuntimeError: pass
            if session_only:
                history = self.authority.history(); ping = {}; self._add_session_state(ping, history); scene = {}
            else:
                scene, history, ping = self.observe()
            if predicates.evaluate(expression, scene, history, ping): return {"predicate": expression, "matched": True}
            if not wait or time.monotonic() >= deadline: raise RuntimeError("reason=predicate_timeout" if wait else "reason=assertion_failed")
            time.sleep(.05)

    def capture(self, png: Path):
        # An in-app surface can leave the shell semantically stable while its
        # presenter never declares idle. The capture RPC still snapshots the
        # composed frame, so treat idle timeout as the bounded fallback.
        try: self.automation.wait_idle(timeout_ms=1000)
        except RuntimeError as error:
            if "timeout" not in str(error): raise
        response = self.automation.capture(png)
        scene = self.automation.scene()
        scene.setdefault("route", route(scene))
        png.with_name("scene.json").write_text(json.dumps(scene, indent=2, sort_keys=True) + "\n")
        return {"sha256": hashlib.sha256(png.read_bytes()).hexdigest(), **response}


def run(scenario: Scenario, repeat: int = 1, out: Path | None = None, instance: str = "default",
        keep_instance: bool = False, backend: Backend | None = None) -> tuple[int, dict, Path]:
    if repeat < 1: raise ValueError("reason=invalid_repeat")
    root = out.resolve() if out else safe_child(sim_home() / "scenarios", "scenario", scenario.name)
    root.mkdir(parents=True, exist_ok=True)
    runs = []
    for number in range(1, repeat + 1):
        run_id = validate_name("run", f"run-{number:03d}")
        run_root = safe_child(root, "run", run_id)
        if run_root.exists(): shutil.rmtree(run_root)
        run_root.mkdir()
        current = backend or LiveBackend(instance)
        current.start(scenario.profile, scenario.scale, scenario.contrast, not keep_instance)
        failed = False; records = []
        for index, step in enumerate(scenario.steps, 1):
            record = {"op": step["op"], "args": {k: v for k, v in step.items() if k != "op"}}
            step_root = run_root / f"{index:02d}-{step['op'].replace('_', '-')}"; step_root.mkdir()
            if failed:
                record.update(result="skipped", error=None, started=None, ended=None, duration_ms=0)
            else:
                started = datetime.now(timezone.utc); tick = time.monotonic()
                try:
                    result = current.execute(step)
                    name = step.get("name", "capture") if step["op"] == "capture" else "screen"
                    png = step_root / f"{validate_name('capture', name)}.png"
                    capture_result = current.capture(png)
                    record.update(result="pass", error=None, capture_sha256=capture_result["sha256"])
                    if result is not None: record["output"] = result
                except Exception as error:  # The report is the scenario's error boundary.
                    record.update(result="fail", error=str(error)); failed = True
                ended = datetime.now(timezone.utc)
                record.update(started=started.isoformat(), ended=ended.isoformat(), duration_ms=round((time.monotonic()-tick)*1000, 3))
            (step_root / "step.json").write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
            records.append(record)
        runs.append({"run_id": run_id, "status": "fail" if failed else "pass", "steps": records})
    deterministic = all(len({run["steps"][i].get("capture_sha256") for run in runs}) == 1
                        for i in range(len(scenario.steps)))
    passed = all(run["status"] == "pass" for run in runs)
    report = {"scenario": scenario.name, "description": scenario.description, "status": "pass" if passed else "fail",
              "deterministic": deterministic, "runs": runs, "smells": [i+1 for i, step in enumerate(scenario.steps) if step["op"] == "sleep"]}
    (root / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    (root / "report.md").write_text(render_report(report))
    return (0 if passed and deterministic else 1), report, root


def render_report(report: dict) -> str:
    lines = [f"# Scenario: {report['scenario']}", "", f"Status: **{report['status'].upper()}**", "",
             "| Run | Step | Op | Status | Duration (ms) | Capture SHA-256 |", "|---|---:|---|---|---:|---|"]
    for run_item in report["runs"]:
        for i, step in enumerate(run_item["steps"], 1):
            lines.append(f"| {run_item['run_id']} | {i} | {step['op']} | {step['result'].upper()} | {step['duration_ms']} | {step.get('capture_sha256', '')} |")
    smells = report.get("smells", [])
    lines += ["", "## Smells", "", ("Sleep steps: " + ", ".join(map(str, smells))) if smells else "None.", ""]
    return "\n".join(lines)


def list_scenarios(directory: Path) -> list[Scenario]:
    return [load(path) for path in sorted(directory.glob("*.toml"))]
