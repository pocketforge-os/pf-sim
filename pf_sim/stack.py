from __future__ import annotations

import json
import shutil
from pathlib import Path


class StaleStateError(RuntimeError):
    pass


def assert_clean_run_dir(run_dir: Path) -> None:
    stale = [p for p in run_dir.rglob("*") if p.name.endswith((".running", ".sock", ".lock"))]
    if stale:
        raise StaleStateError("reason=stale_state paths=" + ",".join(map(str, stale)))


def seed_run_dir(run_dir: Path, seed=None) -> None:
    """Create pristine state. `seed` is the profile hook used by tsp-tcew.2."""
    for name in ("authority", "shell"):
        shutil.rmtree(run_dir / name, ignore_errors=True)
    (run_dir / "authority").mkdir(parents=True, exist_ok=True)
    (run_dir / "shell").mkdir(parents=True, exist_ok=True)
    if seed is None:
        (run_dir / "shell" / "prefs.json").write_text(
            json.dumps({"schemaVersion": 2, "firstRunComplete": True}, separators=(",", ":")) + "\n"
        )
    else:
        seed(run_dir)
    assert_clean_run_dir(run_dir)
