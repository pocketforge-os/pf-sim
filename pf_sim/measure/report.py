from __future__ import annotations

import json
from pathlib import Path


def build(provenance: dict, ink: dict, gaps: dict, contrast: dict, thresholds: dict) -> dict:
    gap_failures = [p for p in gaps["pairs"] if p["under_min_gap"]]
    contrast_failures = [dict(node=node, **value) for node, value in contrast.items() if value and value["status"] == "FAIL"]
    checks = {
        "minimum_gap": {"status": "FAIL" if gap_failures else "PASS", "failures": gap_failures},
        "text_contrast": {"status": "FAIL" if contrast_failures else "PASS", "failures": contrast_failures},
    }
    return {"status": "FAIL" if any(v["status"] == "FAIL" for v in checks.values()) else "PASS",
            "provenance": provenance, "thresholds": thresholds, "checks": checks, "node_count": len(ink)}


def write(directory: Path, value: dict) -> None:
    (directory / "report.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lines = ["# Measurement report", "", f"Overall: **{value['status']}**", "", "## Provenance", ""]
    lines.extend(f"- {key}: `{item}`" for key, item in value["provenance"].items())
    lines += ["", "## Checks", ""]
    for name, check in value["checks"].items():
        lines.append(f"- {name}: **{check['status']}**")
        for failure in check["failures"]:
            lines.append(f"  - `{json.dumps(failure, sort_keys=True)}`")
    (directory / "report.md").write_text("\n".join(lines) + "\n")

