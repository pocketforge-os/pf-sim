import json
import socket
import struct
import threading
from pathlib import Path


class FakeAuthority:
    def __init__(self, path: Path):
        self.path = path; self.requests = []; self.entries = []; self.stop = threading.Event()

    def start(self):
        self.path.unlink(missing_ok=True); self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(self.path)); self.server.listen(); self.server.settimeout(.1)
        self.thread = threading.Thread(target=self._serve, daemon=True); self.thread.start(); return self

    def close(self):
        self.stop.set(); self.thread.join(1); self.server.close(); self.path.unlink(missing_ok=True)

    def _serve(self):
        while not self.stop.is_set():
            try: conn, _ = self.server.accept()
            except socket.timeout: continue
            with conn:
                size = struct.unpack(">I", conn.recv(4))[0]; body = b""
                while len(body) < size: body += conn.recv(size - len(body))
                request = json.loads(body); self.requests.append(request)
                response = {"result": "history", "entries": self.entries} if request["method"] == "history" else {"result": "ok"}
                data = json.dumps(response, separators=(",", ":")).encode(); conn.sendall(struct.pack(">I", len(data)) + data)
