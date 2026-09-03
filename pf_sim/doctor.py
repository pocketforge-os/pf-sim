from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .gamepad import (
    UINPUT_PATH,
    UInputDevice,
    contract_codes,
    find_event_node,
    wait_event_node_readable,
)
from .toolchain import manifest_path


def event_node_access() -> str:
    """Probe access to the event node udev creates for this process."""
    if not os.access(UINPUT_PATH, os.W_OK):
        return "unknown"
    try:
        codes = contract_codes()
    except (FileNotFoundError, ValueError):
        return "unknown (toolchain not built)"
    device = UInputDevice(codes, "doctor-probe")
    try:
        event_node = find_event_node(device.sysname)
        return "ok" if wait_event_node_readable(event_node) else "unreadable"
    finally:
        device.close()


def checks() -> list[tuple[str, bool, str, bool]]:
    weston = shutil.which("weston")
    modules = [Path("/usr/lib/x86_64-linux-gnu/weston/kiosk-shell.so"), Path("/usr/lib/weston/kiosk-shell.so")]
    access = event_node_access()
    event_ok = access == "ok"
    event_hint = (
        "uinput not writable" if access == "unknown" else
        "add your user to the 'input' group, or install the udev rule from "
        "docs/gui-dev-loop.md, or run from a logind seat session (uaccess ACL)"
    )
    return [
        ("python >= 3.10", sys.version_info >= (3, 10), "install Python 3.10 or newer", True),
        ("Pillow", importlib.util.find_spec("PIL") is not None, "install python3-pil", True),
        ("weston", weston is not None, "install weston", True),
        ("kiosk-shell.so", any(p.exists() for p in modules), "install weston kiosk shell modules", True),
        ("weston-screenshooter", shutil.which("weston-screenshooter") is not None, "install weston", True),
        ("cargo", shutil.which("cargo") is not None, "install Rust cargo", True),
        ("libxkbcommon headers", subprocess.run(["pkg-config", "--exists", "xkbcommon"], check=False).returncode == 0 if shutil.which("pkg-config") else False, "install libxkbcommon-dev and pkg-config", True),
        ("XDG_RUNTIME_DIR", bool(os.environ.get("XDG_RUNTIME_DIR")), "export XDG_RUNTIME_DIR to a writable runtime directory", True),
        (f"event_node_access={access}", event_ok, event_hint, False),
        ("DISPLAY", bool(os.environ.get("DISPLAY")), "export DISPLAY before using --display windowed", False),
        ("toolchain manifest", manifest_path().is_file(), "run ./pf-simctl toolchain build", True),
    ]


def run() -> int:
    failed = False
    for name, ok, fix, required in checks():
        mark = "✓" if ok else ("✗" if required else "!")
        print(f"{mark} {name}" + ("" if ok else f": {fix}"))
        failed |= required and not ok
    return 1 if failed else 0
