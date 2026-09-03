from __future__ import annotations

import os
from pathlib import Path


def sim_home() -> Path:
    return Path(os.environ.get("PF_SIM_HOME", "~/.local/state/pf-sim")).expanduser().resolve()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_dir(instance: str) -> Path:
    return sim_home() / "runs" / instance
