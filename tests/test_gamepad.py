import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pf_sim import gamepad


class PackingTests(unittest.TestCase):
    def test_input_event_is_byte_exact(self):
        self.assertEqual(gamepad.pack_event(1, 305, 1),
                         b"\0" * 16 + b"\x01\x00\x31\x01\x01\x00\x00\x00")

    def test_uinput_setup_is_byte_exact(self):
        packed = gamepad.pack_setup()
        self.assertEqual(len(packed), 92)
        self.assertEqual(packed[:8], b"\x06\x00\x09\x12\x46\x50\x01\x00")
        self.assertEqual(packed[8:39], b"pocketforge-sim-gamepad:default")
        self.assertEqual(packed[39:], b"\0" * 53)

    def test_ui_get_sysname_ioctl_is_byte_exact(self):
        self.assertEqual(gamepad.UI_GET_SYSNAME, 0x8050552c)

    def test_resolves_event_node_within_own_sysfs_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysfs = Path(tmp) / "sys"
            own = sysfs / "devices" / "virtual" / "input" / "input123" / "event17"
            other = sysfs / "devices" / "virtual" / "input" / "input124" / "event18"
            own.mkdir(parents=True)
            other.mkdir(parents=True)
            self.assertEqual(
                gamepad.find_event_node("input123", timeout=0.1, sysfs_root=sysfs,
                                        dev_root=Path("/dev/input")),
                "/dev/input/event17")


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


class LifecycleTests(unittest.TestCase):
    def test_create_rejects_unreadable_event_node_and_cleans_holder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            child = Mock(pid=123)
            state = {"state": "up", "pid_alive": True, "node_present": True,
                     "pid": 123, "start_time": 456, "token": "placeholder",
                     "event_node": "/dev/input/event-test"}

            def fake_popen(command, **_kwargs):
                state["token"] = command[-1]
                return child

            with patch.object(gamepad.subprocess, "Popen", side_effect=fake_popen), \
                    patch.object(gamepad, "status", side_effect=[
                        {"state": "absent", "pid_alive": False, "node_present": False}, state]), \
                    patch.object(gamepad, "wait_event_node_readable", return_value=False), \
                    patch.object(gamepad, "_stop_recorded_holder", return_value=True) as stop, \
                    self.assertRaisesRegex(RuntimeError, "reason=event_node_unreadable"):
                gamepad.create("unreadable")
            stop.assert_called_once_with("unreadable", state)
            root = Path(tmp) / "runs/unreadable"
            self.assertFalse((root / "gamepad.sock").exists())
            self.assertFalse((root / "gamepad.json").exists())

    def test_two_concurrent_creates_start_exactly_one_holder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            root = Path(tmp) / "runs" / "race"
            spawns = []

            def fake_popen(command, **_kwargs):
                token = command[-1]
                spawns.append(token)
                root.mkdir(parents=True, exist_ok=True)
                (root / "gamepad.json").write_text(json.dumps({"pid": 123, "start_time": 456,
                    "token": token, "event_node": "/dev/input/event-test"}))
                return Mock(pid=123)

            def fake_status(_instance):
                if not spawns:
                    return {"state": "absent", "pid_alive": False, "node_present": False}
                return {"state": "up", "pid_alive": True, "node_present": True,
                        "pid": 123, "start_time": 456, "token": spawns[0],
                        "event_node": "/dev/input/event-test"}

            results = []
            with patch.object(gamepad.subprocess, "Popen", side_effect=fake_popen), \
                 patch.object(gamepad, "status", side_effect=fake_status), \
                 patch.object(gamepad, "wait_event_node_readable", return_value=True):
                threads = [threading.Thread(target=lambda: results.append(gamepad.create("race")))
                           for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
            self.assertEqual(len(results), 2)
            self.assertEqual(len(spawns), 1)
            self.assertTrue((root / "gamepad.json").is_file())

    def test_create_degraded_stops_old_holder_before_replacement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            old = subprocess.Popen(["sleep", "30"])
            old_state = {"state": "degraded", "pid_alive": True, "node_present": False,
                         "pid": old.pid, "start_time": gamepad.proc_start(old.pid), "token": "old",
                         "event_node": "/missing"}
            replacement = Mock(pid=987654)
            replacement.poll.return_value = None
            states = [old_state, {"state": "up", "pid_alive": True, "node_present": True,
                                  "pid": replacement.pid, "start_time": 1, "token": "new",
                                  "event_node": "/dev/input/event-test"}]

            def fake_popen(command, **_kwargs):
                states[1]["token"] = command[-1]
                self.assertIsNotNone(old.poll(), "replacement started before old holder died")
                return replacement

            try:
                with patch.object(gamepad, "status", side_effect=states), \
                     patch.object(gamepad, "request", side_effect=FileNotFoundError), \
                     patch.object(gamepad, "wait_event_node_readable", return_value=True), \
                     patch.object(gamepad.subprocess, "Popen", side_effect=fake_popen):
                    result = gamepad.create("degraded")
                self.assertEqual(result["pid"], replacement.pid)
                self.assertIsNotNone(old.poll())
            finally:
                if old.poll() is None:
                    old.terminate()
                    old.wait()

    def test_destroy_does_not_signal_reused_pid(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            decoy = subprocess.Popen(["sleep", "30"])
            root = Path(tmp) / "runs" / "stale"
            root.mkdir(parents=True)
            (root / "gamepad.json").write_text(json.dumps({"pid": decoy.pid,
                "start_time": gamepad.proc_start(decoy.pid) + 1, "token": "stale",
                "event_node": "/missing"}))
            try:
                self.assertEqual(gamepad.destroy("stale"), "stale_cleaned")
                self.assertIsNone(decoy.poll(), "destroy signalled a mismatched PID")
            finally:
                decoy.terminate()
                decoy.wait()

    def test_destroy_terminates_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            holder = subprocess.Popen(["sleep", "30"])
            root = Path(tmp) / "runs" / "matching"
            root.mkdir(parents=True)
            (root / "gamepad.json").write_text(json.dumps({"pid": holder.pid,
                "start_time": gamepad.proc_start(holder.pid), "token": "matching",
                "event_node": "/missing"}))
            with patch.object(gamepad, "request", side_effect=FileNotFoundError):
                self.assertEqual(gamepad.destroy("matching"), "destroyed")
            self.assertIsNotNone(holder.poll())
