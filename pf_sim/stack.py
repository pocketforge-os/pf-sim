from __future__ import annotations

import json
import shutil
from pathlib import Path


class StaleStateError(RuntimeError):
    pass


def assert_clean_run_dir(run_dir: Path) -> None:
    stale = [
        path
        for subtree in (run_dir / "authority", run_dir / "shell")
        for path in subtree.rglob("*")
        if path.name.endswith((".running", ".sock", ".lock"))
    ]
    authority_socket = run_dir / "session-authority.sock"
    if authority_socket.exists():
        stale.append(authority_socket)
    if stale:
        raise StaleStateError("reason=stale_state paths=" + ",".join(map(str, stale)))


def seed_run_dir(run_dir: Path, seed=None) -> None:
    """Create pristine state. `seed` is the profile hook used by tsp-tcew.2."""
    for name in ("authority", "shell"):
        shutil.rmtree(run_dir / name, ignore_errors=True)
    (run_dir / "authority").mkdir(parents=True, exist_ok=True)
    (run_dir / "shell").mkdir(parents=True, exist_ok=True)
    (run_dir / "session-authority.sock").unlink(missing_ok=True)
    if seed is None:
        (run_dir / "shell" / "prefs.json").write_text(
            json.dumps({"schemaVersion": 2, "firstRunComplete": True}, separators=(",", ":")) + "\n"
        )
    else:
        seed(run_dir)
    assert_clean_run_dir(run_dir)
