from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

from PIL import Image

from .config import safe_child, sim_home, validate_name
from .measure import gaps, ink


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
        if pair is None:
            return False, "missing_pair"
        measured = pair[expectation.get("source", "ink")][expectation["axis"]]
    else:
        node = json.loads((artifacts / "ink.json").read_text()).get(expectation["node"])
        if node is None:
            return False, "missing_node"
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
    operators = {"eq": measured == value, "lt": measured < value, "le": measured <= value,
                 "gt": measured > value, "ge": measured >= value}
    if operator not in operators:
        raise ValueError("reason=invalid_audit_operator")
    return operators[operator], measured


def _fixture(phase: dict, phase_root: Path, env: dict[str, str]) -> tuple[Path, Path, list[str]]:
    binary = sim_home() / "toolchain/bin/pf-shell"
    output = phase_root / "fixture"
    output.mkdir(parents=True, exist_ok=True)
    fixture = phase["fixture"]
    if fixture == "settings":
        command = [str(binary), "--settings-evidence", "--out", str(output)]
        if phase.get("scale"):
            command += ["--text-scale", str(phase["scale"])]
        _run(command, env)
        png = output / "settings.png"
    elif fixture == "home":
        command = [str(binary), "--out", str(output)]
        if phase.get("scale"):
            command += ["--text-scale", str(phase["scale"])]
        _run(command, env)
        png = output / "boot-home.png"
    elif fixture == "sim-frame":
        raw = output / "frame.bgra"
        raw.write_bytes(b"\0" * (1280 * 720 * 4))
        command = [str(binary), "--sim-frame", "--device", str(raw)]
        _run(command, env)
        png = output / "frame.png"
        Image.frombytes("RGB", (1280, 720), raw.read_bytes(), "raw", "BGRX").save(png)
    else:
        raise ValueError("reason=invalid_audit_fixture")
    nodes = []
    for region in phase.get("region", []):
        name = validate_name("audit_region", region["name"])
        nodes.append({"id": name, "bounds": [region[key] for key in ("x", "y", "w", "h")]})
    image = Image.open(png).convert("RGB")
    measured = {node["id"]: ink.measure_node(image, node) for node in nodes}
    artifacts = phase_root / "measure"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "ink.json").write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n")
    (artifacts / "gaps.json").write_text(json.dumps(gaps.matrix(measured, int(phase.get("min_gap", 0))), indent=2, sort_keys=True) + "\n")
    return artifacts, png, command


def run(path: Path) -> tuple[str, list[dict]]:
    spec = tomllib.loads(path.read_text())
    audit_name = validate_name("audit", spec["name"])
    instance = validate_name("instance", spec.get("instance", "default"))
    results: list[dict] = []
    env = os.environ.copy()
    ctl = str(Path(__file__).resolve().parent.parent / "pf-simctl")
    audit_root = safe_child(sim_home() / "audits", "audit", audit_name)
    audit_root.mkdir(parents=True, exist_ok=True)
    for phase in spec["phase"]:
        phase_name = validate_name("audit_phase", phase["name"])
        mode = phase["mode"]
        if mode == "unreproducible":
            results.append({"phase": phase_name, "mode": mode, "reason": phase["reason"],
                            "historical": phase.get("historical", []), "reproduced": None})
            continue
        phase_root = safe_child(audit_root, "audit_phase", phase_name)
        _run([ctl, "toolchain", "build", "--launcher-rev", phase["launcher_rev"]], env)
        fixture_command = None
        if mode == "fixture":
            artifacts, png, fixture_command = _fixture(phase, phase_root, env)
            provenance = {"mode": mode, "launcher_rev": phase["launcher_rev"],
                          "fixture_command": fixture_command, "capture": str(png)}
        elif mode == "scene":
            capture = validate_name("capture", f"{audit_name}-{phase_name}")
            subprocess.run([ctl, "down", "--instance", instance], env=env, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            command = [ctl, "up", "--instance", instance, "--profile", spec["profile"]]
            if spec.get("scale"):
                command += ["--scale", str(spec["scale"])]
            if spec.get("contrast"):
                command += ["--contrast", spec["contrast"]]
            _run(command, env)
            try:
                _run([ctl, "capture", capture, "--instance", instance], env)
                measure = [ctl, "measure", capture, "--instance", instance, "--no-fail"]
                if spec.get("nodes"):
                    measure += ["--nodes", ",".join(spec["nodes"])]
                if spec.get("min_gap") is not None:
                    measure += ["--min-gap", str(spec["min_gap"])]
                _run(measure, env)
            finally:
                subprocess.run([ctl, "down", "--instance", instance], env=env, check=False)
            artifacts = safe_child(sim_home() / "captures", "instance", instance) / f"{capture}.measure"
            provenance = {"mode": mode, "launcher_rev": phase["launcher_rev"], "capture": capture}
        else:
            raise ValueError("reason=invalid_audit_mode")
        outcomes = []
        for expectation in phase["expect"]:
            passed, measured = _expectation(expectation, artifacts)
            outcomes.append({"kind": expectation["kind"], "expected": expectation,
                             "measured": measured, "reproduced": passed})
        result = {"phase": phase_name, **provenance, "expectations": outcomes,
                  "reproduced": all(item["reproduced"] for item in outcomes)}
        (phase_root / "audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        results.append(result)
    measured_ok = all(item["reproduced"] is not False for item in results)
    partial = any(item["mode"] == "unreproducible" for item in results)
    return ("partial" if measured_ok and partial else "reproduced" if measured_ok else "not_reproduced"), results
