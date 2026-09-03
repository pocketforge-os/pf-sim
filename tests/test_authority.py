import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from fake_authority import FakeAuthority
from pf_sim.authority import AuthorityClient


class AuthorityTests(unittest.TestCase):
    def test_byte_exact_frame_and_partial_response_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authority.sock"; server = socket.socket(socket.AF_UNIX); server.bind(str(path)); server.listen()
            captured = []
            def serve():
                conn, _ = server.accept()
                with conn:
                    captured.append(conn.recv(4096)); body = b'{"result":"accepted","session_id":"s1"}'
                    frame = struct.pack(">I", len(body)) + body
                    for byte in frame: conn.send(bytes([byte]))
            thread = threading.Thread(target=serve); thread.start()
            self.assertEqual(AuthorityClient(path).launch("ridgeline")["session_id"], "s1")
            thread.join(); server.close()
            body = b'{"method":"launch","item_id":"ridgeline"}'
            self.assertEqual(captured[0], struct.pack(">I", len(body)) + body)

    def test_methods_match_wire_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeAuthority(Path(tmp) / "a.sock").start(); client = AuthorityClient(fake.path)
            try: client.safe_return(); client.history(); client.observe("session_running"); client.tick()
            finally: fake.close()
            self.assertEqual([r["method"] for r in fake.requests], ["safe_return", "history", "observe", "tick"])
