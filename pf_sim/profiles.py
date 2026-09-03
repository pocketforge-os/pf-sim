from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import repo_root, sim_home

SCALES = {"100": "100%", "150": "150%", "200": "200%"}


@dataclass(frozen=True)
class Profile:
    path: Path
    name: str
    description: str
    authority: bool
    extra_args: tuple[str, ...]
    text_scale: str
    high_contrast: bool
    first_run_complete: bool
    source: str


def profile_roots() -> tuple[tuple[Path, str], ...]:
    return ((repo_root() / "profiles", "repo"), (sim_home() / "profiles", "home"))


def load_profile(path: Path, source: str = "path") -> Profile:
    data = tomllib.loads((path / "profile.toml").read_text())
    prefs = data.get("prefs", {})
    scale = prefs.get("text_scale", "100%")
    if scale not in SCALES.values():
        raise ValueError("reason=invalid_text_scale")
    return Profile(path, data["profile"]["name"], data["profile"].get("description", ""),
                   bool(data.get("stack", {}).get("authority", True)),
                   tuple(data.get("shell", {}).get("extra_args", [])), scale,
                   bool(prefs.get("high_contrast", False)),
                   bool(prefs.get("first_run_complete", True)), source)


def resolve_profile(name_or_path: str) -> Profile:
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return load_profile(candidate.resolve())
    for root, source in reversed(profile_roots()):
        path = root / name_or_path
        if path.is_dir():
            return load_profile(path, source)
    raise FileNotFoundError(f"reason=profile_not_found profile={name_or_path}")


def list_profiles() -> list[Profile]:
    found: dict[str, Profile] = {}
    for root, source in profile_roots():
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if (path / "profile.toml").is_file():
                    found[path.name] = load_profile(path, source)
    return sorted(found.values(), key=lambda item: item.name)


def effective_prefs(profile: Profile, scale: str | None = None, contrast: str | None = None) -> dict | None:
    if not profile.first_run_complete and scale is None and contrast is None:
        return None
    return {"schemaVersion": 2, "firstRunComplete": True,
            "textScale": SCALES.get(scale, profile.text_scale),
            "highContrast": profile.high_contrast if contrast is None else contrast == "hc"}


def seed_profile(run_dir: Path, profile: Profile, scale: str | None = None, contrast: str | None = None,
                 include_authority: bool = True) -> None:
    state = profile.path / "state"
    if state.is_dir():
        for item in state.iterdir():
            if item.name == "authority" and not include_authority: continue
            target = run_dir / item.name
            if item.is_dir(): shutil.copytree(item, target, dirs_exist_ok=True)
            else: shutil.copy2(item, target)
    shell = run_dir / "shell"; shell.mkdir(parents=True, exist_ok=True)
    prefs = effective_prefs(profile, scale, contrast)
    (shell / "prefs.json").unlink(missing_ok=True)
    if prefs is not None:
        (shell / "prefs.json").write_text(json.dumps(prefs, separators=(",", ":")) + "\n")


def validate_profile(profile: Profile) -> None:
    state = profile.path / "state"
    if not state.exists(): return
    for path in state.rglob("*"):
        relative = path.relative_to(state)
        if relative.parts[:2] == ("authority", "sessions"):
            raise ValueError("reason=stale_marker")
        if path.name in ("pids.json", "run.json") or path.name.endswith(".running"):
            raise ValueError("reason=stale_marker")
        if path.name.endswith(".sock"):
            raise ValueError("reason=socket")
        if path.name.endswith(".lock"):
            raise ValueError("reason=lock")


def sanitize_tree(path: Path) -> None:
    for item in sorted(path.rglob("*"), reverse=True):
        rel = item.relative_to(path)
        bad = (rel.parts[:2] == ("authority", "sessions") or item.name in ("pids.json", "run.json")
               or item.name.endswith((".running", ".sock", ".lock")))
        if bad:
            shutil.rmtree(item) if item.is_dir() else item.unlink(missing_ok=True)


def snapshot(name: str, run_dir: Path) -> Profile:
    target = sim_home() / "profiles" / name
    shutil.rmtree(target, ignore_errors=True); (target / "state").mkdir(parents=True)
    if (run_dir / "shell").exists(): shutil.copytree(run_dir / "shell", target / "state/shell")
    authority = run_dir / "authority/authority.json"
    if authority.exists():
        (target / "state/authority").mkdir(); shutil.copy2(authority, target / "state/authority/authority.json")
    sanitize_tree(target / "state")
    (target / "profile.toml").write_text(
        f'[profile]\nname = "{name}"\ndescription = "Snapshot of running instance"\n\n'
        '[stack]\nauthority = true\n\n[shell]\nextra_args = []\n\n'
        '[prefs]\ntext_scale = "100%"\nhigh_contrast = false\nfirst_run_complete = true\n')
    result = load_profile(target, "home"); validate_profile(result); return result


def restart_plan(old_authority: bool, new_authority: bool) -> tuple[str, ...]:
    if old_authority == new_authority: return ("shell",)
    return ("shell", "supervisor", "authorityd")
