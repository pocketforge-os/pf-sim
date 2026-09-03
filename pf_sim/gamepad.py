from __future__ import annotations

import argparse
import fcntl
import json
import os
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


def pack_event(event_type: int, code: int, value: int) -> bytes:
    return INPUT_EVENT.pack(0, 0, event_type, code, value)


def pack_setup() -> bytes:
    name = DEVICE_NAME.encode().ljust(80, b"\0")
    return UINPUT_SETUP.pack(0x06, 0x1209, 0x5046, 1, name, 0)


def _named_event_nodes() -> set[str]:
    result = set()
    for name_file in Path("/sys/class/input").glob("event*/device/name"):
        try:
            if name_file.read_text().strip() == DEVICE_NAME:
                result.add(f"/dev/input/{name_file.parents[1].name}")
        except FileNotFoundError:
            pass
    return result


def find_event_node(timeout: float = 2.0, exclude: set[str] | None = None) -> str:
    deadline = time.monotonic() + timeout
    exclude = exclude or set()
    while time.monotonic() < deadline:
        candidates = _named_event_nodes() - exclude
        if candidates:
            return sorted(candidates)[0]
        time.sleep(0.02)
    raise RuntimeError("reason=event_node_timeout")


class UInputDevice:
    def __init__(self, codes: list[int]):
        self.fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in codes:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, pack_setup())
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

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
    alive = _alive(int(state["pid"]))
    present = Path(state["event_node"]).exists()
    return {**state, "state": "up" if alive and present else "degraded",
            "pid_alive": alive, "node_present": present}


def create(instance: str) -> dict:
    validate_instance(instance)
    current = status(instance)
    if current["state"] == "up":
        return current
    root = run_dir(instance)
    root.mkdir(parents=True, exist_ok=True)
    sock_path, state_path = _paths(instance)
    sock_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    _children[instance] = subprocess.Popen(
        [sys.executable, "-m", "pf_sim.gamepad", "--hold", "--instance", instance],
        start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = status(instance)
        if result["state"] == "up" and sock_path.exists():
            return result
        time.sleep(0.03)
    raise RuntimeError("reason=gamepad_create_failed")


def destroy(instance: str) -> bool:
    _, state_path = _paths(instance)
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    try:
        request(instance, {"command": "quit"})
    except (OSError, RuntimeError, json.JSONDecodeError):
        try:
            os.kill(int(state["pid"]), signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2
    while _alive(int(state["pid"])) and time.monotonic() < deadline:
        time.sleep(0.02)
    child = _children.pop(instance, None)
    if child is not None:
        try:
            child.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
    state_path.unlink(missing_ok=True)
    return True


def hold(instance: str) -> int:
    contract = DeviceContract.load()
    root = run_dir(instance)
    root.mkdir(parents=True, exist_ok=True)
    sock_path, state_path = _paths(instance)
    sock_path.unlink(missing_ok=True)
    existing_nodes = _named_event_nodes()
    device = UInputDevice([control.code for control in contract.controls])
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    running = True
    try:
        event_node = find_event_node(exclude=existing_nodes)
        server.bind(str(sock_path))
        server.listen(4)
        state_path.write_text(json.dumps({"pid": os.getpid(), "event_node": event_node,
                                          "sysfs_name": DEVICE_NAME,
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
                    response = {"status": "ok", "event_node": event_node}
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
    args = parser.parse_args(argv)
    return hold(validate_instance(args.instance))


if __name__ == "__main__":
    raise SystemExit(main())
