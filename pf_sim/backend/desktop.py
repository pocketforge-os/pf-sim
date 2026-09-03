from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import Backend
from ..config import repo_root, run_dir, sim_home
from ..pins import load_pins
from ..stack import seed_run_dir
from ..toolchain import read_manifest, sha256

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
        xdg = os.environ.get("XDG_RUNTIME_DIR")
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
        count = sum(item["alive"] for item in components.values())
        result["state"] = "up" if count == len(COMPONENTS) else ("down" if count == 0 else "degraded")
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

    def up(self, *, instance="default", display="headless", replace=False, shell_bin=None, authorityd_bin=None, seed=None) -> Path:
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
        }
        (path / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
        records: dict = {}
        processes = []
        try:
            weston = ["weston", f"--backend={'headless' if display == 'headless' else 'x11'}", "--shell=kiosk-shell.so",
                      f"--socket={socket_name}", "--width=1280", "--height=720", "--idle-time=0"]
            if display == "headless":
                weston.insert(2, "--renderer=pixman")
            processes.append(("weston", self._spawn("weston", weston, path, records)))
            if not self._wait_socket(xdg / socket_name, processes[-1][1]):
                raise RuntimeError("reason=weston_died")
            processes.append(("authorityd", self._spawn("authorityd", [str(authority), "--command-preset", "desktop-sim", "--state-dir", str(path / "authority"), "--socket", str(authority_socket)], path, records)))
            if not self._wait_socket(authority_socket, processes[-1][1]):
                raise RuntimeError("reason=authorityd_died")
            processes.append(("supervisor", self._spawn("supervisor", [str(shell), "--desktop-sim-supervise", str(path / "authority"), "--session-socket", str(authority_socket)], path, records)))
            time.sleep(0.5)
            if processes[-1][1].poll() is not None:
                raise RuntimeError("reason=supervisor_died")
            env = os.environ.copy(); env.update(self.shell_display_env(socket_name))
            processes.append(("shell", self._spawn("shell", [str(shell), "--wayland", "--device-fixtures", "--state-dir", str(path / "shell"), "--session-socket", str(authority_socket), "--catalog-snapshot", str(repo_root() / "fixtures" / "catalog-snapshot.json")], path, records, env)))
            time.sleep(self.settle)
            dead = next((name for name, process in processes if process.poll() is not None), None)
            if dead:
                raise RuntimeError(f"reason={dead}_died")
            return path
        except Exception:
            self.down(instance)
            raise

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
            xdg = os.environ.get("XDG_RUNTIME_DIR")
            if xdg: (Path(xdg) / meta.get("weston_socket", "__missing__")).unlink(missing_ok=True)
        except (FileNotFoundError, json.JSONDecodeError): pass
        (path / "session-authority.sock").unlink(missing_ok=True)
        (path / "pids.json").unlink(missing_ok=True)
        for record in records.values():
            process = self._processes.pop(int(record["pid"]), None)
            if process is not None:
                try: process.wait(timeout=0.2)
                except subprocess.TimeoutExpired: pass
        return running
