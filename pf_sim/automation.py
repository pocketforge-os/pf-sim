from __future__ import annotations

import json
import socket
from pathlib import Path


class AutomationError(RuntimeError):
    pass


class AutomationTimeout(AutomationError):
    pass


class AutomationClient:
    def __init__(self, socket_path: Path, timeout: float = 5.0, audit_path: Path | None = None):
        self.socket_path = Path(socket_path)
        self.timeout = timeout
        self.audit_path = audit_path or self.socket_path.parent / "logs/automation.jsonl"

    def request(self, payload: dict, timeout: float | None = None) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout if timeout is None else timeout)
                client.connect(str(self.socket_path))
                client.sendall(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    data += chunk
        except socket.timeout as error:
            raise AutomationTimeout("reason=automation_timeout") from error
        except OSError as error:
            raise AutomationError(f"reason=automation_down detail={error}") from error
        try:
            response = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AutomationError("reason=automation_protocol_error") from error
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as audit:
            audit.write(json.dumps(response, separators=(",", ":")) + "\n")
        if not response.get("ok"):
            raise AutomationError(f"reason=automation_error error={response.get('error', 'unknown')}")
        return response

    def ping(self): return self.request({"op": "ping"})
    def scene(self): return self.request({"op": "scene"})
    def capture(self, path: Path): return self.request({"op": "capture", "path": str(Path(path).resolve())})
    def text(self, value: str): return self.request({"op": "text", "value": value})
    def wait_idle(self, quiet_ms: int = 150, timeout_ms: int = 5000):
        return self.request({"op": "wait_idle", "quiet_ms": quiet_ms, "timeout_ms": timeout_ms}, timeout_ms / 1000 + 1)
