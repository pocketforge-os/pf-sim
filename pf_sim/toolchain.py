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


def _copy_atomic(source: Path, target: Path) -> None:
    """Activate a binary without truncating an executable used by another instance."""
    temporary = target.with_name(target.name + ".new")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


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


def build(force: bool = False, launcher_rev: str | None = None) -> dict:
    pins = load_pins()
    if launcher_rev is not None:
        if not all(character in "0123456789abcdefABCDEF" for character in launcher_rev) or not 7 <= len(launcher_rev) <= 40:
            raise ValueError("reason=invalid_launcher_rev")
        pins["launcher_rev"] = launcher_rev.lower()
    root = sim_home() / "toolchain"
    cache_name = pins["launcher_rev"]
    revision_cache = root / "builds" / cache_name
    cached_manifest = revision_cache / "manifest.json"
    if cached_manifest.exists() and not force:
        manifest = json.loads(cached_manifest.read_text())
        bin_dir = root / "bin"; bin_dir.mkdir(parents=True, exist_ok=True)
        _copy_atomic(revision_cache / "pf-shell", bin_dir / "pf-shell")
        _copy_atomic(revision_cache / "pf-session-authorityd", bin_dir / "pf-session-authorityd")
        _copy_atomic(revision_cache / "device-contract.json", root / "device-contract.json")
        manifest_path().parent.mkdir(parents=True, exist_ok=True)
        manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest
    source = root / "launcher" / pins["launcher_rev"] / "src"
    if force and source.exists():
        shutil.rmtree(source)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", pins["launcher_repo"], str(source)], check=True)
    subprocess.run(["git", "reset", "--hard"], cwd=source, check=True,
                   stdout=subprocess.DEVNULL)
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
    _copy_atomic(target / "release" / "pf-shell", bin_dir / "pf-shell")
    _copy_atomic(runtime_root / "bin" / "pf-session-authorityd", bin_dir / "pf-session-authorityd")
    contract_source = source / "crates" / "pf-shell" / "fixtures" / "device.json"
    contract_target = root / "device-contract.json"
    shutil.copy2(contract_source, contract_target)
    manifest = {
        "launcher_rev": pins["launcher_rev"], "runtime_rev": runtime_rev,
        "pf_shell_sha256": sha256(bin_dir / "pf-shell"),
        "authorityd_sha256": sha256(bin_dir / "pf-session-authorityd"),
        "device_contract_sha256": sha256(contract_target),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=source, check=True,
                           capture_output=True, text=True).stdout
    if dirty:
        raise RuntimeError("reason=launcher_source_dirty")
    revision_cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bin_dir / "pf-shell", revision_cache / "pf-shell")
    shutil.copy2(bin_dir / "pf-session-authorityd", revision_cache / "pf-session-authorityd")
    shutil.copy2(contract_target, revision_cache / "device-contract.json")
    (revision_cache / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
