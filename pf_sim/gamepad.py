from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import secrets
import signal
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import run_dir, validate_instance
from .contract import DeviceContract
from .evdev_codes import EV_KEY, EV_SYN, SYN_REPORT

DEVICE_NAME = "pocketforge-sim-gamepad"
UINPUT_PATH = "/dev/uinput"
SYSNAME_SIZE = 80
INPUT_EVENT = struct.Struct("@llHHi")
UINPUT_SETUP = struct.Struct("@HHHH80sI")
_children: dict[str, subprocess.Popen] = {}


def _ioc(direction: int, kind: int, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (kind << 8) | number


UI_SET_EVBIT = _ioc(1, ord("U"), 100, 4)
UI_SET_KEYBIT = _ioc(1, ord("U"), 101, 4)
UI_DEV_CREATE = _ioc(0, ord("U"), 1, 0)
UI_DEV_DESTROY = _ioc(0, ord("U"), 2, 0)
UI_DEV_SETUP = _ioc(1, ord("U"), 3, UINPUT_SETUP.size)
UI_GET_SYSNAME = _ioc(2, ord("U"), 44, SYSNAME_SIZE)


def pack_event(event_type: int, code: int, value: int) -> bytes:
    return INPUT_EVENT.pack(0, 0, event_type, code, value)


def device_name(instance: str) -> str:
    return f"{DEVICE_NAME}:{instance}"


def pack_setup(instance: str = "default") -> bytes:
    name = device_name(instance).encode()[:79].ljust(80, b"\0")
    return UINPUT_SETUP.pack(0x06, 0x1209, 0x5046, 1, name, 0)


def find_event_node(sysname: str, timeout: float = 2.0,
                    sysfs_root: Path = Path("/sys"), dev_root: Path = Path("/dev/input")) -> str:
    """Resolve only the event node belonging to the uinput fd's kernel sysname."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for input_dir in (sysfs_root / "devices/virtual/input" / sysname,
                          sysfs_root / "class/input" / sysname):
            candidates = sorted(input_dir.glob("event*"))
            if candidates:
                return str(dev_root / candidates[0].name)
        time.sleep(0.02)
    raise RuntimeError("reason=event_node_timeout")


class UInputDevice:
    def __init__(self, codes: list[int], instance: str):
        self.fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in codes:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, pack_setup(instance))
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        buffer = bytearray(SYSNAME_SIZE)
        fcntl.ioctl(self.fd, UI_GET_SYSNAME, buffer, True)
        self.sysname = bytes(buffer).split(b"\0", 1)[0].decode("ascii")
        if not self.sysname:
            self.close()
            raise RuntimeError("reason=uinput_sysname_missing")

    def emit(self, code: int, value: int) -> None:
        os.write(self.fd, pack_event(EV_KEY, code, value) + pack_event(EV_SYN, SYN_REPORT, 0))

    def close(self) -> None:
        if self.fd >= 0:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            finally:
                os.close(self.fd)
                self.fd = -1


def _paths(instance: str) -> tuple[Path, Path]:
    root = run_dir(instance)
    return root / "gamepad.sock", root / "gamepad.json"


@contextlib.contextmanager
def _lifecycle_lock(instance: str):
    root = run_dir(instance)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "gamepad.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def proc_start(pid: int) -> int | None:
    """Return Linux /proc starttime (field 22), which is stable across PID reuse."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError, PermissionError):
        return None


def _identity_matches(state: dict) -> bool:
    try:
        return proc_start(int(state["pid"])) == int(state["start_time"])
    except (KeyError, TypeError, ValueError):
        return False


def request(instance: str, command: dict, timeout: float = 3.0) -> dict:
    sock_path, _ = _paths(instance)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(sock_path))
        client.sendall(json.dumps(command).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
    response = json.loads(data)
    if response.get("status") != "ok":
        raise RuntimeError(response.get("reason", "reason=gamepad_protocol_error"))
    return response


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def status(instance: str) -> dict:
    _, state_path = _paths(instance)
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"state": "absent", "pid_alive": False, "node_present": False}
    alive = _identity_matches(state)
    present = bool(state.get("event_node")) and Path(state["event_node"]).exists()
    authenticated = False
    if alive and present and state.get("token"):
        try:
            authenticated = request(instance, {"command": "status"}, timeout=0.25).get("token") == state["token"]
        except (OSError, RuntimeError, json.JSONDecodeError):
            pass
    return {**state, "state": "up" if alive and present and authenticated else "degraded",
            "pid_alive": alive, "node_present": present}


def _wait_dead(pid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        child = next((item for item in _children.values() if item.pid == pid), None)
        if child is not None:
            child.poll()
        else:
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, ProcessLookupError):
                pass
        if not _alive(pid):
            return True
        time.sleep(0.02)
    return not _alive(pid)


def _stop_recorded_holder(instance: str, state: dict) -> bool:
    """Stop only the process whose non-reusable identity is recorded in state."""
    if not _identity_matches(state):
        return False
    pid = int(state["pid"])
    token = state.get("token")
    try:
        response = request(instance, {"command": "quit"}, timeout=0.5)
        if not token or response.get("token") != token:
            raise RuntimeError("reason=holder_token_mismatch")
    except (OSError, RuntimeError, json.JSONDecodeError):
        # Recheck immediately before signalling: the holder could have exited and
        # its PID could have been recycled while the socket request was failing.
        if _identity_matches(state):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    if not _wait_dead(pid):
        raise RuntimeError("reason=gamepad_holder_would_not_stop")
    _children.pop(instance, None)
    return True


def create(instance: str) -> dict:
    validate_instance(instance)
    with _lifecycle_lock(instance):
        current = status(instance)
        if current["state"] == "up":
            return current
        sock_path, state_path = _paths(instance)
        if current.get("pid_alive"):
            _stop_recorded_holder(instance, current)
        sock_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        token = secrets.token_hex(16)
        child = subprocess.Popen(
            [sys.executable, "-m", "pf_sim.gamepad", "--hold", "--instance", instance,
             "--token", token],
            start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
        _children[instance] = child
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = status(instance)
            if result["state"] == "up" and result.get("token") == token:
                return result
            time.sleep(0.03)
        # A timeout must not turn the attempted create into an unreachable device.
        # The process object supplies the identity even when state publication failed.
        spawned = {"pid": child.pid, "start_time": proc_start(child.pid), "token": token}
        if spawned["start_time"] is not None:
            _stop_recorded_holder(instance, spawned)
        sock_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        raise RuntimeError("reason=gamepad_create_failed")


def destroy(instance: str) -> str:
    validate_instance(instance)
    with _lifecycle_lock(instance):
        sock_path, state_path = _paths(instance)
        try:
            state = json.loads(state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return "absent"
        stopped = _stop_recorded_holder(instance, state)
        # At this point a matching holder is verified dead. With a stale identity,
        # the recorded PID was deliberately left untouched.
        sock_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        return "destroyed" if stopped else "stale_cleaned"


def hold(instance: str, token: str) -> int:
    contract = DeviceContract.load()
    root = run_dir(instance)
    root.mkdir(parents=True, exist_ok=True)
    sock_path, state_path = _paths(instance)
    sock_path.unlink(missing_ok=True)
    name = device_name(instance)
    device = UInputDevice([control.code for control in contract.controls], instance)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    running = True
    try:
        event_node = find_event_node(device.sysname)
        server.bind(str(sock_path))
        server.listen(4)
        state_path.write_text(json.dumps({"pid": os.getpid(), "start_time": proc_start(os.getpid()),
                                          "token": token, "event_node": event_node,
                                          "sysfs_name": name,
                                          "created_at": datetime.now(timezone.utc).isoformat()},
                                         sort_keys=True) + "\n")
        while running:
            connection, _ = server.accept()
            with connection, connection.makefile("r", encoding="utf-8") as reader:
                try:
                    command = json.loads(reader.readline())
                    kind = command.get("command")
                    if kind in ("press", "release"):
                        device.emit(int(command["code"]), 1 if kind == "press" else 0)
                    elif kind == "tap":
                        device.emit(int(command["code"]), 1)
                        time.sleep(max(0, int(command.get("hold_ms", 60))) / 1000)
                        device.emit(int(command["code"]), 0)
                    elif kind == "status":
                        pass
                    elif kind == "quit":
                        running = False
                    else:
                        raise ValueError("reason=unknown_gamepad_command")
                    response = {"status": "ok", "event_node": event_node, "token": token}
                except (ValueError, KeyError, TypeError) as error:
                    response = {"status": "error", "reason": str(error)}
                connection.sendall(json.dumps(response).encode() + b"\n")
    finally:
        server.close()
        device.close()
        sock_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold", action="store_true", required=True)
    parser.add_argument("--instance", default="default")
    parser.add_argument("--token", required=True)
    args = parser.parse_args(argv)
    return hold(validate_instance(args.instance), args.token)


if __name__ == "__main__":
    raise SystemExit(main())
