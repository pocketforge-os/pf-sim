from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import Backend
from ..config import repo_root, run_dir, sim_home
from ..pins import load_pins
from ..stack import seed_run_dir
from ..profiles import Profile, restart_plan, seed_profile
from ..toolchain import read_manifest, sha256
from ..automation import AutomationClient, AutomationError
from .. import gamepad

COMPONENTS = ("weston", "authorityd", "supervisor", "shell")


def proc_start(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError, PermissionError):
        return None


def alive(record: dict | None) -> bool:
    return bool(record and proc_start(int(record["pid"])) == int(record["start_time"]))


class DesktopBackend(Backend):
    def __init__(self, popen=subprocess.Popen, wait_timeout: float = 10.0, settle: float = 2.0):
        self.popen, self.wait_timeout, self.settle = popen, wait_timeout, settle
        self._processes: dict[int, subprocess.Popen] = {}

    def shell_display_env(self, socket: str) -> dict[str, str]:
        return {"WAYLAND_DISPLAY": socket}

    def capture_hint(self, instance: str) -> str:
        status = self.status(instance)
        return f"WAYLAND_DISPLAY={status.get('weston_socket', '')} weston-screenshooter"

    def _records(self, path: Path) -> dict:
        try:
            return json.loads((path / "pids.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def status(self, instance: str) -> dict:
        path = run_dir(instance)
        records = self._records(path)
        try:
            meta = json.loads((path / "run.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {}
        components = {name: {"alive": alive(records.get(name)), "pid": records.get(name, {}).get("pid")} for name in COMPONENTS}
        socket = meta.get("weston_socket")
        xdg = meta.get("xdg_runtime_dir")
        result = {
            "instance": instance, "components": components,
            "weston_socket": socket,
            "weston_socket_present": bool(xdg and socket and (Path(xdg) / socket).exists()),
            "authority_socket_present": (path / "session-authority.sock").exists(),
            "stale_markers": len(list((path / "authority" / "sessions").glob("*.running"))),
            "launcher_rev": meta.get("launcher_rev"), "runtime_rev": meta.get("runtime_rev"),
            "shell_bin": meta.get("shell_bin"), "authorityd_bin": meta.get("authorityd_bin"),
            "shell_sha256": meta.get("shell_sha256"), "authorityd_sha256": meta.get("authorityd_sha256"),
        }
        try:
            AutomationClient(path / "automation.sock", timeout=.25).ping()
            result["automation"] = "ok"
        except AutomationError:
            result["automation"] = "down"
        expected = ("weston", "shell") if meta.get("authority") is False else COMPONENTS
        count = sum(components[name]["alive"] for name in expected)
        degraded_reasons = [f"{name}_dead" for name, item in components.items() if not item["alive"]]
        if meta.get("authority") is False:
            degraded_reasons = [reason for reason in degraded_reasons if reason not in ("authorityd_dead", "supervisor_dead")]
        if not result["weston_socket_present"]:
            degraded_reasons.append("weston_socket_missing")
        if meta.get("authority") is not False and not result["authority_socket_present"]:
            degraded_reasons.append("authority_socket_missing")
        if count == 0:
            result["state"] = "down"
        elif count == len(expected) and not degraded_reasons:
            result["state"] = "up"
        else:
            result["state"] = "degraded"
        result["degraded_reasons"] = degraded_reasons if result["state"] == "degraded" else []
        result.update({key: meta.get(key) for key in ("profile", "scale", "contrast", "display", "authority")})
        return result

    def _spawn(self, name: str, command: list[str], path: Path, records: dict, env=None) -> subprocess.Popen:
        log = (path / "logs" / f"{name}.log").open("ab", buffering=0)
        process = self.popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        log.close()
        self._processes[process.pid] = process
        records[name] = {"pid": process.pid, "start_time": proc_start(process.pid)}
        (path / "pids.json").write_text(json.dumps(records, indent=2) + "\n")
        return process

    def _wait_socket(self, socket: Path, process: subprocess.Popen) -> bool:
        deadline = time.monotonic() + self.wait_timeout
        while time.monotonic() < deadline:
            if socket.exists():
                return True
            if process.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def _wait_automation(self, socket_path: Path, process: subprocess.Popen) -> bool:
        deadline = time.monotonic() + self.wait_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                AutomationClient(socket_path, timeout=.1).ping()
                return True
            except AutomationError:
                time.sleep(.05)
        return False

    def up(self, *, instance="default", display="headless", replace=False, shell_bin=None, authorityd_bin=None, seed=None,
           profile: Profile | None = None, scale: str | None = None, contrast: str | None = None,
           no_gamepad: bool = False) -> Path:
        current = self.status(instance)
        if current["state"] != "down":
            if not replace:
                raise RuntimeError("reason=instance_already_up")
            self.down(instance)
        xdg_value = os.environ.get("XDG_RUNTIME_DIR")
        if not xdg_value:
            raise RuntimeError("reason=xdg_runtime_dir_missing")
        if display == "windowed" and not os.environ.get("DISPLAY"):
            raise RuntimeError("reason=display_missing")
        manifest = read_manifest() or {}
        bins = sim_home() / "toolchain" / "bin"
        shell = Path(shell_bin or os.environ.get("PF_SIM_SHELL_BIN", bins / "pf-shell")).resolve()
        authority = Path(authorityd_bin or os.environ.get("PF_SIM_AUTHORITYD_BIN", bins / "pf-session-authorityd")).resolve()
        for label, binary in (("shell", shell), ("authorityd", authority)):
            if not binary.is_file():
                raise RuntimeError(f"reason={label}_bin_missing path={binary}")
        path = run_dir(instance)
        path.mkdir(parents=True, exist_ok=True)
        pad = None if no_gamepad else gamepad.create(instance)
        if profile is not None:
            seed = lambda run: seed_profile(run, profile, scale, contrast)
        seed_run_dir(path, seed)
        (path / "logs").mkdir(exist_ok=True)
        socket_name = f"pf-sim-{instance}"
        xdg = Path(xdg_value)
        authority_socket = path / "session-authority.sock"
        pins = load_pins()
        metadata = {
            "instance": instance, "display": display, "launcher_rev": manifest.get("launcher_rev", pins["launcher_rev"]),
            "runtime_rev": manifest.get("runtime_rev"), "shell_bin": str(shell), "authorityd_bin": str(authority),
            "shell_sha256": sha256(shell), "authorityd_sha256": sha256(authority),
            "started_at": datetime.now(timezone.utc).isoformat(), "weston_socket": socket_name,
            "xdg_runtime_dir": str(xdg),
            "profile": profile.name if profile else "seeded-default",
            "scale": scale or (profile.text_scale.removesuffix("%") if profile else "100"),
            "contrast": contrast or ("hc" if profile and profile.high_contrast else "default"),
            "authority": profile.authority if profile else True,
            "shell_extra_args": list(profile.extra_args) if profile else [],
            "supervisor": profile.supervisor if profile else "shell",
            "input_source": "wayland-keyboard" if no_gamepad else "evdev",
            "event_node": None if pad is None else pad["event_node"],
            "gamepad": None if pad is None else {key: pad.get(key) for key in ("pid", "start_time", "event_node")},
        }
        (path / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
        records: dict = {}
        processes = []
        try:
            weston = ["weston", f"--backend={'headless' if display == 'headless' else 'x11'}", "--shell=kiosk-shell.so",
                      "--debug", f"--socket={socket_name}", "--width=1280", "--height=720", "--idle-time=0"]
            if display == "headless":
                weston.insert(2, "--renderer=pixman")
            processes.append(("weston", self._spawn("weston", weston, path, records)))
            if not self._wait_socket(xdg / socket_name, processes[-1][1]):
                raise RuntimeError("reason=weston_died")
            if metadata["authority"]:
                ctl = repo_root() / "pf-simctl"
                hook = f"{ctl} app-hook"
                authority_command = [str(authority), "--command-preset", "desktop-sim", "--state-dir", str(path / "authority"), "--socket", str(authority_socket)]
                if metadata["supervisor"] == "pf-sim":
                    authority_command += ["--start-command", f"{hook} launch {{item_id}} {{session_id}} --run-dir {path}",
                                          "--graceful-stop-command", f"{hook} stop {{session_id}} --run-dir {path}",
                                          "--terminate-command", f"{hook} kill {{session_id}} --run-dir {path}",
                                          "--activate-owner-command", f"{hook} activate --run-dir {path}"]
                processes.append(("authorityd", self._spawn("authorityd", authority_command, path, records)))
                if not self._wait_socket(authority_socket, processes[-1][1]):
                    raise RuntimeError("reason=authorityd_died")
                supervisor_command = ([sys.executable, "-m", "pf_sim.supervisor", "--run-dir", str(path), "--authority-socket", str(authority_socket), "--wayland-display", socket_name]
                                      if metadata["supervisor"] == "pf-sim" else [str(shell), "--desktop-sim-supervise", str(path / "authority"), "--session-socket", str(authority_socket)])
                processes.append(("supervisor", self._spawn("supervisor", supervisor_command, path, records)))
                time.sleep(0.5)
                if processes[-1][1].poll() is not None:
                    raise RuntimeError("reason=supervisor_died")
            env = os.environ.copy(); env.update(self.shell_display_env(socket_name))
            env["PF_POWER_SUPPLY_ROOT"] = str(path / "power_supply")
            shell_command = [str(shell), "--wayland", "--device-fixtures", "--state-dir", str(path / "shell"), "--session-socket", str(authority_socket), "--catalog-snapshot", str(repo_root() / "fixtures" / "catalog-snapshot.json")] + metadata["shell_extra_args"]
            if not no_gamepad:
                env["PF_SHELL_AUTOMATION"] = "1"
                shell_command += ["--input", pad["event_node"], "--automation-socket", str(path / "automation.sock")]
            processes.append(("shell", self._spawn("shell", shell_command, path, records, env)))
            if not no_gamepad and not self._wait_automation(path / "automation.sock", processes[-1][1]):
                raise RuntimeError("reason=automation_socket_died")
            if no_gamepad:
                time.sleep(self.settle)
            dead = next((name for name, process in processes if process.poll() is not None), None)
            if dead:
                raise RuntimeError(f"reason={dead}_died")
            return path
        except Exception:
            self.down(instance)
            raise

    def apply(self, instance: str, profile: Profile, scale: str | None, contrast: str | None) -> Path:
        """Apply state while preserving Weston and restarting only affected managed components."""
        path = run_dir(instance)
        try: meta = json.loads((path / "run.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError): raise RuntimeError("reason=instance_not_running")
        if self.status(instance)["state"] == "down": raise RuntimeError("reason=instance_not_running")
        records = self._records(path)
        plan = restart_plan(
            bool(meta.get("authority", True)),
            str(meta.get("supervisor", "shell")),
            profile.authority,
            profile.supervisor,
        )
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for name in plan:
                record = records.get(name)
                if alive(record):
                    try: os.kill(int(record["pid"]), sig)
                    except ProcessLookupError: pass
            deadline = time.monotonic() + (3 if sig == signal.SIGTERM else .2)
            while time.monotonic() < deadline and any(alive(records.get(name)) for name in plan): time.sleep(.05)
        for name in plan:
            records.pop(name, None)
        (path / "pids.json").write_text(json.dumps(records, indent=2) + "\n")
        shutil.rmtree(path / "shell", ignore_errors=True); (path / "shell").mkdir()
        authority_changed = bool(meta.get("authority", True)) != profile.authority
        if authority_changed:
            shutil.rmtree(path / "authority", ignore_errors=True); (path / "authority").mkdir()
            (path / "session-authority.sock").unlink(missing_ok=True)
        seed_profile(path, profile, scale, contrast, include_authority=authority_changed)
        meta.update(profile=profile.name,
                    scale=scale or profile.text_scale.removesuffix("%"),
                    contrast=contrast or ("hc" if profile.high_contrast else "default"),
                    authority=profile.authority, shell_extra_args=list(profile.extra_args), supervisor=profile.supervisor)
        (path / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
        shell, authority = meta["shell_bin"], meta["authorityd_bin"]
        authority_socket = path / "session-authority.sock"
        if profile.authority and "authorityd" in plan:
            ctl = repo_root() / "pf-simctl"; hook = f"{ctl} app-hook"
            command = [authority, "--command-preset", "desktop-sim", "--state-dir", str(path / "authority"), "--socket", str(authority_socket)]
            if profile.supervisor == "pf-sim":
                command += ["--start-command", f"{hook} launch {{item_id}} {{session_id}} --run-dir {path}", "--graceful-stop-command", f"{hook} stop {{session_id}} --run-dir {path}", "--terminate-command", f"{hook} kill {{session_id}} --run-dir {path}", "--activate-owner-command", f"{hook} activate --run-dir {path}"]
            process = self._spawn("authorityd", command, path, records)
            if not self._wait_socket(authority_socket, process): raise RuntimeError("reason=authorityd_died")
            supervisor_command = ([sys.executable, "-m", "pf_sim.supervisor", "--run-dir", str(path), "--authority-socket", str(authority_socket), "--wayland-display", meta["weston_socket"]]
                                  if profile.supervisor == "pf-sim" else [shell, "--desktop-sim-supervise", str(path / "authority"), "--session-socket", str(authority_socket)])
            process = self._spawn("supervisor", supervisor_command, path, records)
            time.sleep(.5)
            if process.poll() is not None: raise RuntimeError("reason=supervisor_died")
        env = os.environ.copy(); env.update(self.shell_display_env(meta["weston_socket"]))
        env["XDG_RUNTIME_DIR"] = meta["xdg_runtime_dir"]
        env["PF_POWER_SUPPLY_ROOT"] = str(path / "power_supply")
        command = [shell, "--wayland", "--device-fixtures", "--state-dir", str(path / "shell"), "--session-socket", str(authority_socket), "--catalog-snapshot", str(repo_root() / "fixtures/catalog-snapshot.json")] + list(profile.extra_args)
        if meta.get("input_source") == "evdev":
            env["PF_SHELL_AUTOMATION"] = "1"
            command += ["--input", meta["event_node"], "--automation-socket", str(path / "automation.sock")]
        process = self._spawn("shell", command, path, records, env)
        if meta.get("input_source") == "evdev":
            if not self._wait_automation(path / "automation.sock", process):
                raise RuntimeError("reason=automation_socket_died")
        else:
            # The keyboard-only fallback has no presented-frame seam.
            time.sleep(max(self.settle, 4.0) if not profile.authority else self.settle)
        if process.poll() is not None: raise RuntimeError("reason=shell_died")
        return path

    def down(self, instance: str) -> bool:
        path = run_dir(instance)
        records = self._records(path)
        running = any(alive(records.get(name)) for name in COMPONENTS)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for name in reversed(COMPONENTS):
                record = records.get(name)
                if alive(record):
                    try: os.kill(int(record["pid"]), sig)
                    except ProcessLookupError: pass
            deadline = time.monotonic() + (3 if sig == signal.SIGTERM else 0.2)
            while time.monotonic() < deadline and any(alive(records.get(n)) for n in COMPONENTS):
                time.sleep(0.05)
        try:
            meta = json.loads((path / "run.json").read_text())
            xdg = meta.get("xdg_runtime_dir")
            if xdg: (Path(xdg) / meta.get("weston_socket", "__missing__")).unlink(missing_ok=True)
        except (FileNotFoundError, json.JSONDecodeError): pass
        (path / "session-authority.sock").unlink(missing_ok=True)
        (path / "automation.sock").unlink(missing_ok=True)
        (path / "pids.json").unlink(missing_ok=True)
        for record in records.values():
            process = self._processes.pop(int(record["pid"]), None)
            if process is not None:
                try: process.wait(timeout=0.2)
                except subprocess.TimeoutExpired: pass
        gamepad.destroy(instance)
        return running
