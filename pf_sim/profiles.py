from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import repo_root, safe_child, sim_home, validate_name

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
    supervisor: str
    batteries: tuple[dict, ...]


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
                   bool(prefs.get("first_run_complete", True)), source,
                   data.get("stack", {}).get("supervisor", "pf-sim"),
                   tuple(data.get("power", {}).get("batteries", [])))


def render_power_supply(run_dir: Path, profile: Profile) -> None:
    root = run_dir / "power_supply"
    batteries = [(validate_name("power_supply", str(item["name"])), item) for item in profile.batteries]
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for name, battery in batteries:
        target = safe_child(root, "power_supply", name)
        target.mkdir()
        values = {"type": "Battery", "capacity": int(battery["capacity"]),
                  "status": battery["status"], "scope": battery["scope"]}
        for key, value in values.items():
            (target / key).write_text(str(value) + "\n")


def resolve_profile(name_or_path: str, *, allow_path: bool = False) -> Profile:
    candidate = Path(name_or_path)
    if allow_path and candidate.is_dir():
        return load_profile(candidate.resolve())
    validate_name("profile", name_or_path)
    for root, source in reversed(profile_roots()):
        path = safe_child(root, "profile", name_or_path)
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
    for item in profile.batteries:
        validate_name("power_supply", str(item["name"]))
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
    render_power_supply(run_dir, profile)


def validate_profile(profile: Profile) -> None:
    if profile.supervisor not in ("pf-sim", "shell"):
        raise ValueError("reason=invalid_supervisor")
    for item in profile.batteries:
        validate_name("power_supply", str(item["name"]))
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
    profiles_root = sim_home() / "profiles"
    target = safe_child(profiles_root, "profile", name)
    meta = json.loads((run_dir / "run.json").read_text())
    prefs_path = run_dir / "shell/prefs.json"
    if prefs_path.exists():
        prefs = json.loads(prefs_path.read_text())
        first_run_complete = bool(prefs.get("firstRunComplete", True))
        text_scale = prefs.get("textScale", "100%")
        high_contrast = bool(prefs.get("highContrast", False))
        if text_scale not in SCALES.values():
            raise ValueError("reason=invalid_text_scale")
    else:
        first_run_complete = False
        text_scale = SCALES.get(str(meta.get("scale")), "100%")
        high_contrast = meta.get("contrast") == "hc"
    authority_enabled = bool(meta.get("authority", True))
    source_profile = str(meta.get("profile", "unknown"))
    source_scale = str(meta.get("scale", text_scale.removesuffix("%")))
    source_contrast = str(meta.get("contrast", "hc" if high_contrast else "default"))
    description = f"Snapshot of {source_profile} at scale={source_scale} contrast={source_contrast}"
    shutil.rmtree(target, ignore_errors=True); (target / "state").mkdir(parents=True)
    if (run_dir / "shell").exists(): shutil.copytree(run_dir / "shell", target / "state/shell")
    authority = run_dir / "authority/authority.json"
    if authority.exists():
        (target / "state/authority").mkdir(); shutil.copy2(authority, target / "state/authority/authority.json")
    sanitize_tree(target / "state")
    (target / "profile.toml").write_text(
        f'[profile]\nname = {json.dumps(name)}\ndescription = {json.dumps(description)}\n\n'
        f'[stack]\nauthority = {str(authority_enabled).lower()}\nsupervisor = "pf-sim"\n\n[shell]\nextra_args = []\n\n'
        f'[prefs]\ntext_scale = {json.dumps(text_scale)}\nhigh_contrast = {str(high_contrast).lower()}\n'
        f'first_run_complete = {str(first_run_complete).lower()}\n')
    result = load_profile(target, "home"); validate_profile(result); return result


def restart_plan(old_authority: bool, old_supervisor: str,
                 new_authority: bool, new_supervisor: str) -> tuple[str, ...]:
    if old_authority == new_authority and old_supervisor == new_supervisor:
        return ("shell",)
    return ("shell", "supervisor", "authorityd")
