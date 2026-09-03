from __future__ import annotations

import importlib.util
import grp
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .toolchain import manifest_path


def event_node_access() -> bool:
    """Report whether the current user should read root:input 0660 event nodes."""
    try:
        input_gid = grp.getgrnam("input").gr_gid
    except KeyError:
        return False
    return os.geteuid() == 0 or input_gid == os.getegid() or input_gid in os.getgroups()


def checks() -> list[tuple[str, bool, str, bool]]:
    weston = shutil.which("weston")
    modules = [Path("/usr/lib/x86_64-linux-gnu/weston/kiosk-shell.so"), Path("/usr/lib/weston/kiosk-shell.so")]
    access = event_node_access()
    return [
        ("python >= 3.10", sys.version_info >= (3, 10), "install Python 3.10 or newer", True),
        ("Pillow", importlib.util.find_spec("PIL") is not None, "install python3-pil", True),
        ("weston", weston is not None, "install weston", True),
        ("kiosk-shell.so", any(p.exists() for p in modules), "install weston kiosk shell modules", True),
        ("weston-screenshooter", shutil.which("weston-screenshooter") is not None, "install weston", True),
        ("cargo", shutil.which("cargo") is not None, "install Rust cargo", True),
        ("libxkbcommon headers", subprocess.run(["pkg-config", "--exists", "xkbcommon"], check=False).returncode == 0 if shutil.which("pkg-config") else False, "install libxkbcommon-dev and pkg-config", True),
        ("XDG_RUNTIME_DIR", bool(os.environ.get("XDG_RUNTIME_DIR")), "export XDG_RUNTIME_DIR to a writable runtime directory", True),
        (f"event_node_access={'ok' if access else 'unreadable'}", access,
         "add your user to the 'input' group or install the udev rule in docs/gui-dev-loop.md", False),
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
