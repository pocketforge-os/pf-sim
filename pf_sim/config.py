from __future__ import annotations

import os
import re
from pathlib import Path


INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_instance(instance: str) -> str:
    if not INSTANCE_RE.fullmatch(instance):
        raise ValueError("reason=invalid_instance")
    return instance


def sim_home() -> Path:
    return Path(os.environ.get("PF_SIM_HOME", "~/.local/state/pf-sim")).expanduser().resolve()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_dir(instance: str) -> Path:
    return sim_home() / "runs" / validate_instance(instance)
