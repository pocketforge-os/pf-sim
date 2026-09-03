from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

from .config import validate_name
from .automation import AutomationClient
from .config import run_dir


def _run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def _expectation(expectation: dict, artifacts: Path) -> tuple[bool, object]:
    kind = expectation["kind"]
    if kind == "node_absent":
        present = expectation["node"] in json.loads((artifacts / "ink.json").read_text())
        return not present, {"present": present}
    if kind == "check_status":
        measured = json.loads((artifacts / "report.json").read_text())["checks"][expectation["check"]]["status"]
        return measured == expectation["value"], measured
    if kind == "gap":
        pairs = json.loads((artifacts / "gaps.json").read_text())["pairs"]
        pair = next((p for p in pairs if {p["a"], p["b"]} == {expectation["a"], expectation["b"]}), None)
        if pair is None: return False, "missing_pair"
        measured = pair[expectation.get("source", "ink")][expectation["axis"]]
    else:
        node = json.loads((artifacts / "ink.json").read_text()).get(expectation["node"])
        if node is None: return False, "missing_node"
        if kind == "all_insets_nonnegative":
            measured = node["insets"]
            return all(value >= 0 for value in measured.values()), measured
        if kind == "negative_inset":
            measured = node["insets"]
            return any(value < 0 for value in measured.values()), measured
        if kind == "ink_height":
            measured = node["ink_extents"]["height"]
        else:
            raise ValueError("reason=invalid_audit_expectation")
    operator, value = expectation.get("operator", "eq"), expectation["value"]
    passed = {"eq": measured == value, "lt": measured < value, "le": measured <= value,
              "gt": measured > value, "ge": measured >= value}.get(operator)
    if passed is None: raise ValueError("reason=invalid_audit_operator")
    return passed, measured


def run(path: Path) -> tuple[bool, list[dict]]:
    spec = tomllib.loads(path.read_text())
    validate_name("audit", spec["name"])
    instance = validate_name("instance", spec.get("instance", "default"))
    results = []
    env = os.environ.copy()
    ctl = str(Path(__file__).resolve().parent.parent / "pf-simctl")
    for phase in spec["phase"]:
        phase_name = validate_name("audit_phase", phase["name"])
        capture = validate_name("capture", f"{spec['name']}-{phase_name}")
        subprocess.run([ctl, "down", "--instance", instance], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _run([ctl, "toolchain", "build", "--launcher-rev", phase["launcher_rev"], "--automation-adapter"], env)
        command = [ctl, "up", "--instance", instance, "--profile", spec["profile"]]
        if spec.get("scale"): command += ["--scale", str(spec["scale"])]
        if spec.get("contrast"): command += ["--contrast", spec["contrast"]]
        _run(command, env)
        try:
            for action in spec.get("action", []):
                if action.startswith("Room."):
                    AutomationClient(run_dir(instance) / "automation.sock").action(action)
                    AutomationClient(run_dir(instance) / "automation.sock").wait_idle()
                else:
                    _run([ctl, "input", "action", action, "--instance", instance], env)
            _run([ctl, "capture", capture, "--instance", instance], env)
            measure = [ctl, "measure", capture, "--instance", instance, "--no-fail"]
            if spec.get("nodes"): measure += ["--nodes", ",".join(spec["nodes"])]
            if spec.get("min_gap") is not None: measure += ["--min-gap", str(spec["min_gap"])]
            _run(measure, env)
            root = Path(env.get("PF_SIM_HOME", "~/.local/state/pf-sim")).expanduser() / "captures" / instance
            artifacts = root / f"{capture}.measure"
            outcomes = []
            for expectation in phase["expect"]:
                passed, measured = _expectation(expectation, artifacts)
                outcomes.append({"kind": expectation["kind"], "expected": expectation, "measured": measured,
                                 "reproduced": passed})
            results.append({"phase": phase_name, "expectations": outcomes,
                            "reproduced": all(item["reproduced"] for item in outcomes)})
        finally:
            subprocess.run([ctl, "down", "--instance", instance], env=env, check=False)
    return all(item["reproduced"] for item in results), results
