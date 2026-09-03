from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .config import repo_root


def load_pins(path: Path | None = None) -> dict[str, str]:
    with (path or repo_root() / "pins.toml").open("rb") as handle:
        launcher = tomllib.load(handle)["launcher"]
    return {"launcher_repo": launcher["repo"], "launcher_rev": launcher["rev"]}


def derive_runtime(text: str) -> tuple[str, str]:
    match = re.search(
        r'git\s*=\s*"(?P<repo>[^"]*runtime\.git)"\s*,\s*rev\s*=\s*"(?P<rev>[0-9a-f]+)"',
        text,
    )
    if not match:
        raise ValueError("launcher Cargo.toml has no pinned runtime dependency")
    return match.group("repo"), match.group("rev")
