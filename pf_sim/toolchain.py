from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import sim_home
from .pins import derive_runtime, load_pins


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_path() -> Path:
    return sim_home() / "toolchain" / "manifest.json"


def read_manifest() -> dict | None:
    try:
        return json.loads(manifest_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build(force: bool = False) -> dict:
    pins = load_pins()
    root = sim_home() / "toolchain"
    source = root / "launcher" / pins["launcher_rev"] / "src"
    if force and source.exists():
        shutil.rmtree(source)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", pins["launcher_repo"], str(source)], check=True)
    subprocess.run(["git", "checkout", "--detach", pins["launcher_rev"]], cwd=source, check=True)
    runtime_repo, runtime_rev = derive_runtime((source / "Cargo.toml").read_text())
    target = root / "target"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    subprocess.run(
        ["cargo", "build", "--locked", "--release", "-p", "pf-shell", "--features", "wayland"],
        cwd=source, env=env, check=True,
    )
    runtime_root = root / "runtime" / runtime_rev
    install = ["cargo", "install", "--locked"]
    if force:
        install.append("--force")
    install.extend(["--git", runtime_repo, "--rev", runtime_rev, "--root", str(runtime_root),
                    "--bin", "pf-session-authorityd", "pf-session-authority"])
    subprocess.run(install, check=True)
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target / "release" / "pf-shell", bin_dir / "pf-shell")
    shutil.copy2(runtime_root / "bin" / "pf-session-authorityd", bin_dir / "pf-session-authorityd")
    manifest = {
        "launcher_rev": pins["launcher_rev"], "runtime_rev": runtime_rev,
        "pf_shell_sha256": sha256(bin_dir / "pf-shell"),
        "authorityd_sha256": sha256(bin_dir / "pf-session-authorityd"),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
