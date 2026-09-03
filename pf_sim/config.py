from __future__ import annotations

import os
import re
from pathlib import Path


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_name(kind: str, value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"reason=invalid_{kind}")
    return value


def validate_instance(instance: str) -> str:
    return validate_name("instance", instance)


def safe_child(root: Path, kind: str, value: str) -> Path:
    """Return a validated direct child and enforce containment defensively."""
    target = (root / validate_name(kind, value)).resolve()
    resolved_root = root.resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError(f"reason=invalid_{kind}")
    return target


def sim_home() -> Path:
    return Path(os.environ.get("PF_SIM_HOME", "~/.local/state/pf-sim")).expanduser().resolve()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_dir(instance: str) -> Path:
    return sim_home() / "runs" / validate_instance(instance)
