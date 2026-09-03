from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import time
import tomllib
from pathlib import Path

from .config import repo_root, validate_name


def fixture_config(item: str) -> dict:
    validate_name("item", item)
    path = (repo_root() / "fixtures/apps" / (item + ".toml")).resolve()
    data = tomllib.loads(path.read_text()) if path.is_file() else {}
    pattern = data.get("pattern")
    if pattern is None:
        own = (repo_root() / "fixtures/patterns" / (item + ".png")).resolve()
        pattern = own if own.is_file() else repo_root() / "fixtures/patterns/default.png"
    else:
        pattern = (repo_root() / str(pattern)).resolve()
        if not pattern.is_relative_to(repo_root()):
            raise ValueError("reason=invalid_pattern")
    return {"behaviour": data.get("behaviour", "stay"), "launch_delay_ms": int(data.get("launch_delay_ms", 0)), "pattern": Path(pattern)}


def send_command(path: Path, command: dict, timeout: float = 2.0) -> dict:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout); client.connect(str(path))
        client.sendall(json.dumps(command, separators=(",", ":")).encode() + b"\n")
        return json.loads(client.makefile("rb").readline())


def run(run: Path, session: str, item: str, delay_ms: int | None, pattern: Path | None, behaviour: str | None) -> int:
    validate_name("session", session); validate_name("item", item)
    config = fixture_config(item)
    delay_ms = config["launch_delay_ms"] if delay_ms is None else delay_ms
    behaviour = behaviour or config["behaviour"]; pattern = pattern or config["pattern"]
    marker = (run / "authority/sessions" / (session + ".running")).resolve()
    app_socket = (run / "apps" / (session + ".sock")).resolve()
    marker.parent.mkdir(parents=True, exist_ok=True); app_socket.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(delay_ms / 1000); marker.touch()
    if behaviour == "instant-exit": marker.unlink(missing_ok=True); return 0
    if behaviour == "crash": os.kill(os.getpid(), signal.SIGSEGV)
    if behaviour.startswith("exit:"):
        marker.unlink(missing_ok=True); return int(behaviour.split(":", 1)[1])
    child = None
    if pattern and pattern.is_file() and os.environ.get("PF_SIM_NO_WESTON_IMAGE") != "1":
        child = subprocess.Popen(["weston-image", str(pattern)], start_new_session=True)
    server = socket.socket(socket.AF_UNIX); app_socket.unlink(missing_ok=True); server.bind(str(app_socket)); server.listen()
    code = 0
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                request = json.loads(conn.makefile("rb").readline())
                command = request.get("command")
                conn.sendall(json.dumps({"status": "running", "session": session, "item": item}).encode() + b"\n")
            if command in ("quit", "exit"): code = int(request.get("code", 0)); break
            if command == "crash": os.kill(os.getpid(), signal.SIGSEGV)
    finally:
        server.close(); app_socket.unlink(missing_ok=True)
        if child is not None:
            child.terminate()
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired: child.kill()
        marker.unlink(missing_ok=True)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--session", required=True); parser.add_argument("--item", required=True)
    parser.add_argument("--launch-delay-ms", type=int); parser.add_argument("--pattern", type=Path)
    parser.add_argument("--behaviour")
    args = parser.parse_args(argv)
    return run(args.run_dir.resolve(), args.session, args.item, args.launch_delay_ms, args.pattern, args.behaviour)


if __name__ == "__main__": raise SystemExit(main())
