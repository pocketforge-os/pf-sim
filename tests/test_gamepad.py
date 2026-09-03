import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim import gamepad


class PackingTests(unittest.TestCase):
    def test_input_event_is_byte_exact(self):
        self.assertEqual(gamepad.pack_event(1, 305, 1),
                         b"\0" * 16 + b"\x01\x00\x31\x01\x01\x00\x00\x00")

    def test_uinput_setup_is_byte_exact(self):
        packed = gamepad.pack_setup()
        self.assertEqual(len(packed), 92)
        self.assertEqual(packed[:8], b"\x06\x00\x09\x12\x46\x50\x01\x00")
        self.assertEqual(packed[8:31], b"pocketforge-sim-gamepad")
        self.assertEqual(packed[31:], b"\0" * 61)


class ProtocolTests(unittest.TestCase):
    def test_request_sends_newline_json_and_reads_response(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"PF_SIM_HOME": tmp}):
            root = Path(tmp) / "runs" / "default"
            root.mkdir(parents=True)
            path = root / "gamepad.sock"
            received = []

            def fake_holder():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(path)); server.listen(1)
                    connection, _ = server.accept()
                    with connection:
                        received.append(connection.recv(4096))
                        connection.sendall(json.dumps({"status": "ok"}).encode() + b"\n")

            thread = threading.Thread(target=fake_holder)
            thread.start()
            while not path.exists(): pass
            self.assertEqual(gamepad.request("default", {"command": "press", "code": 305})["status"], "ok")
            thread.join()
            self.assertTrue(received[0].endswith(b"\n"))
            self.assertEqual(json.loads(received[0]), {"command": "press", "code": 305})
