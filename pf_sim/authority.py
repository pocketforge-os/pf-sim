from __future__ import annotations

import json
import socket
import struct
from pathlib import Path

MAX_BODY = 64 * 1024


class AuthorityClient:
    def __init__(self, socket_path: Path):
        self.socket_path = Path(socket_path)

    def call(self, request: dict) -> dict:
        body = json.dumps(request, separators=(",", ":")).encode()
        if len(body) > MAX_BODY:
            raise ValueError("reason=authority_request_too_large")
        with socket.socket(socket.AF_UNIX) as stream:
            stream.connect(str(self.socket_path))
            stream.sendall(struct.pack(">I", len(body)) + body)
            size = struct.unpack(">I", self._read_exact(stream, 4))[0]
            if size > MAX_BODY:
                raise RuntimeError("reason=authority_response_too_large")
            response = json.loads(self._read_exact(stream, size))
        if response.get("result") == "error":
            raise RuntimeError(f"reason=authority_error message={response.get('message', '')}")
        return response

    @staticmethod
    def _read_exact(stream: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = stream.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("reason=authority_truncated_frame")
            chunks.extend(chunk)
        return bytes(chunks)

    def launch(self, item_id: str) -> dict:
        return self.call({"method": "launch", "item_id": item_id})

    def safe_return(self) -> dict:
        return self.call({"method": "safe_return"})

    def history(self) -> list[dict]:
        return self.call({"method": "history"}).get("entries", [])

    def observe(self, kind: str, **fields) -> dict:
        return self.call({"method": "observe", "observation": {"kind": kind, **fields}})

    def tick(self) -> dict:
        return self.call({"method": "tick"})
