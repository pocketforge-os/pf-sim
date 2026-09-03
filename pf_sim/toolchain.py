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


AUTOMATION_ADAPTER_REVS = (
    "99a95c27c5b9b1faed8110902e3fb0d95dcdf2a3",
    "41ccb5c7d9f9b25a6063633a05da3b32c4b08763",
)


def build(force: bool = False, launcher_rev: str | None = None, automation_adapter: bool = False) -> dict:
    pins = load_pins()
    if launcher_rev is not None:
        if not all(character in "0123456789abcdefABCDEF" for character in launcher_rev) or not 7 <= len(launcher_rev) <= 40:
            raise ValueError("reason=invalid_launcher_rev")
        pins["launcher_rev"] = launcher_rev.lower()
    root = sim_home() / "toolchain"
    cache_name = pins["launcher_rev"] + ("-automation" if automation_adapter else "")
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
    if automation_adapter and "--automation-socket" not in (source / "crates/pf-shell/src/main.rs").read_text():
        subprocess.run(["git", "fetch", "origin", *AUTOMATION_ADAPTER_REVS], cwd=source, check=True)
        subprocess.run(["git", "cherry-pick", *AUTOMATION_ADAPTER_REVS], cwd=source, check=True)
    if automation_adapter:
        action_patch = Path(__file__).resolve().parent.parent / "patches" / "automation-action.patch"
        subprocess.run(["git", "apply", "--check", str(action_patch)], cwd=source, check=True)
        subprocess.run(["git", "apply", str(action_patch)], cwd=source, check=True)
        automation_source = source / "crates/pf-shell/src/automation.rs"
        body = automation_source.read_text()
        # The scene adapter landed just after fixed_paint_scale was added to the
        # runtime Node. Older audited layouts use the preceding Node shape.
        if not any("fixed_paint_scale" in path.read_text() for path in
                   (source / "crates/pf-shell-core/src").glob("*.rs")):
            body = body.replace('"fixed_paint_scale":value.fixed_paint_scale,', "")
            automation_source.write_text(body)
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
    if automation_adapter:
        manifest["automation_adapter_revs"] = list(AUTOMATION_ADAPTER_REVS)
        manifest["automation_action_patch_sha256"] = sha256(Path(__file__).resolve().parent.parent / "patches" / "automation-action.patch")
    revision_cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bin_dir / "pf-shell", revision_cache / "pf-shell")
    shutil.copy2(bin_dir / "pf-session-authorityd", revision_cache / "pf-session-authorityd")
    shutil.copy2(contract_target, revision_cache / "device-contract.json")
    (revision_cache / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
