import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pf_sim.automation import AutomationClient, AutomationError, AutomationTimeout


class FakeServer:
    def __init__(self, root, responses):
        self.path = Path(root) / "automation.sock"; self.responses = iter(responses); self.requests = []
        self.server = socket.socket(socket.AF_UNIX); self.server.bind(str(self.path)); self.server.listen()
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()

    def run(self):
        for response in self.responses:
            connection, _ = self.server.accept()
            with connection:
                data = b""
                while not data.endswith(b"\n"): data += connection.recv(4096)
                self.requests.append(json.loads(data))
                if response == "timeout": time.sleep(.2)
                else: connection.sendall(json.dumps(response).encode() + b"\n")
        self.server.close()


class AutomationTests(unittest.TestCase):
    def test_all_operations_and_audit(self):
        responses = [{"ok":True,"frames":n,"revision":n} for n in range(1, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeServer(tmp, responses); client = AutomationClient(server.path)
            client.ping(); client.scene(); client.capture(Path(tmp)/"x.png"); client.text("e"); client.wait_idle(12, 34)
            server.thread.join(1)
            self.assertEqual([r["op"] for r in server.requests], ["ping","scene","capture","text","wait_idle"])
            self.assertEqual(server.requests[-1]["quiet_ms"], 12)
            self.assertEqual(len((Path(tmp)/"logs/automation.jsonl").read_text().splitlines()), 5)

    def test_error_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeServer(tmp, [{"ok":False,"error":"bad"}])
            with self.assertRaisesRegex(AutomationError, "bad"): AutomationClient(server.path).ping()

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeServer(tmp, ["timeout"])
            with self.assertRaises(AutomationTimeout): AutomationClient(server.path, timeout=.02).ping()
