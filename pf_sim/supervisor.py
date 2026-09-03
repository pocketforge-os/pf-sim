from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .authority import AuthorityClient
from .config import validate_name
from .fixture_app import send_command

RETURN_CHAIN = ("unit_inactive", "target_released", "selected_owner_active", "presentation_acknowledged")


class Supervisor:
    def __init__(self, run: Path, authority_socket: Path, wayland_display: str = ""):
        self.run, self.client, self.wayland_display = run, AuthorityClient(authority_socket), wayland_display
        self.children: dict[str, subprocess.Popen] = {}; self.lock = threading.Lock(); self.stop_event = threading.Event()

    def marker(self, session: str) -> Path:
        validate_name("session", session)
        return (self.run / "authority/sessions" / (session + ".running")).resolve()

    def app_socket(self, session: str) -> Path:
        validate_name("session", session)
        return (self.run / "apps" / (session + ".sock")).resolve()

    def launch(self, item: str, session: str) -> None:
        validate_name("item", item); validate_name("session", session)
        env = os.environ.copy(); env["WAYLAND_DISPLAY"] = self.wayland_display
        process = subprocess.Popen([sys.executable, "-m", "pf_sim.fixture_app", "--run-dir", str(self.run), "--session", session, "--item", item], env=env, start_new_session=True)
        with self.lock: self.children[session] = process
        threading.Thread(target=self._watch, args=(session, process), daemon=True).start()

    def observe(self, kind: str, **fields) -> None:
        try: self.client.observe(kind, **fields)
        except RuntimeError as error:
            if "InvalidObservation" not in str(error): raise

    def _watch(self, session: str, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + 30
        while process.poll() is None and not self.marker(session).exists() and time.monotonic() < deadline: time.sleep(.02)
        if process.poll() is None and self.marker(session).exists(): self.observe("session_running")
        code = process.wait(); self.marker(session).unlink(missing_ok=True); self.app_socket(session).unlink(missing_ok=True)
        entries = self.client.history()
        active = next((entry for entry in entries if entry.get("receipt") is None), None)
        returning = bool(active and active.get("ended_at") is not None)
        if not returning:
            if code == 0: self.observe("session_exited_cleanly")
            elif code < 0:
                name = signal.Signals(-code).name
                self.observe("session_crashed", summary=f"signal {name}")
            else: self.observe("session_crashed", summary=f"exit {code}")
        for kind in RETURN_CHAIN: self.observe(kind)
        with self.lock: self.children.pop(session, None)

    def command(self, request: dict) -> dict:
        command = request.get("command")
        if command == "activate":
            (self.run / "authority/shell-selected").touch(); return {"status": "ok"}
        session = validate_name("session", request.get("session_id", ""))
        if command == "launch":
            self.launch(validate_name("item", request.get("item_id", "")), session); return {"status": "ok"}
        with self.lock: process = self.children.get(session)
        if process is None: return {"status": "not_running"}
        if command == "stop":
            def stop_when_ready():
                deadline = time.monotonic() + 3
                while process.poll() is None and time.monotonic() < deadline:
                    try:
                        send_command(self.app_socket(session), {"command": "quit"}); return
                    except (FileNotFoundError, ConnectionError): time.sleep(.02)
            threading.Thread(target=stop_when_ready, daemon=True).start()
        elif command == "kill":
            try: os.kill(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        else: raise ValueError("reason=invalid_hook_command")
        return {"status": "ok"}

    def reconcile(self) -> None:
        entries = self.client.history()
        active = next((e for e in reversed(entries) if e.get("receipt") is None), None)
        markers = list((self.run / "authority/sessions").glob("*.running"))
        if active and not markers:
            if active.get("ended_at") is None: self.observe("session_exited_cleanly")
            for kind in RETURN_CHAIN: self.observe(kind)
        elif active and markers:
            if active.get("started_at") is None: self.observe("session_running")
            marker = markers[0]
            def watch_adopted_marker():
                while marker.exists() and not self.stop_event.wait(.05): pass
                if self.stop_event.is_set(): return
                current = next((e for e in self.client.history() if e.get("receipt") is None), None)
                if current and current.get("ended_at") is None: self.observe("session_exited_cleanly")
                for kind in RETURN_CHAIN: self.observe(kind)
            threading.Thread(target=watch_adopted_marker, daemon=True).start()
        elif not active:
            for marker in markers: marker.unlink(missing_ok=True)

    def serve(self) -> None:
        path = self.run / "supervisor.sock"; path.unlink(missing_ok=True); path.parent.mkdir(parents=True, exist_ok=True)
        server = socket.socket(socket.AF_UNIX); server.bind(str(path)); server.listen(); server.settimeout(.1)
        self.reconcile()
        def accept_commands():
            while not self.stop_event.is_set():
                try: conn, _ = server.accept()
                except (socket.timeout, OSError): continue
                with conn:
                    try: response = self.command(json.loads(conn.makefile("rb").readline()))
                    except (ValueError, KeyError) as error: response = {"status": "error", "reason": str(error)}
                    conn.sendall(json.dumps(response).encode() + b"\n")
        command_thread = threading.Thread(target=accept_commands, daemon=True); command_thread.start()
        try:
            while not self.stop_event.is_set():
                self.client.tick(); self.stop_event.wait(.05)
        finally:
            server.close(); command_thread.join(1); path.unlink(missing_ok=True)
            with self.lock: children = list(self.children.values())
            for process in children:
                if process.poll() is None: process.terminate()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and any(p.poll() is None for p in children): time.sleep(.02)
            for process in children:
                if process.poll() is None: process.kill()


def hook(socket_path: Path, request: dict) -> dict:
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(str(socket_path)); client.sendall(json.dumps(request).encode() + b"\n")
        return json.loads(client.makefile("rb").readline())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--authority-socket", required=True, type=Path); parser.add_argument("--wayland-display", default="")
    args = parser.parse_args(argv); supervisor = Supervisor(args.run_dir.resolve(), args.authority_socket, args.wayland_display)
    signal.signal(signal.SIGTERM, lambda *_: supervisor.stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: supervisor.stop_event.set())
    supervisor.serve(); return 0


if __name__ == "__main__": raise SystemExit(main())
