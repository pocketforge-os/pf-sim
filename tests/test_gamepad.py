import json
import os
import socket
import stat
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
            listening = threading.Event()

            def fake_holder():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(path)); server.listen(1); server.settimeout(2)
                    listening.set()
                    connection, _ = server.accept()
                    with connection:
                        received.append(connection.recv(4096))
                        connection.sendall(json.dumps({"status": "ok"}).encode() + b"\n")

            thread = threading.Thread(target=fake_holder)
            thread.start()
            self.assertTrue(listening.wait(2), "fake holder did not start listening")
            self.assertEqual(gamepad.request("default", {"command": "press", "code": 305})["status"], "ok")
            thread.join(2)
            self.assertFalse(thread.is_alive(), "fake holder did not exit")
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


class PrivateEventFifoTests(unittest.TestCase):
    """Wave-1 private input route (tsp-ihne1.56.5).

    The holder serves native input_event frames over a run-private FIFO;
    nothing opens /dev/uinput or binds /dev/input/* on the runner host.
    Positive control: frames round-trip through the socket protocol.
    Negative control: hold() must not construct a kernel uinput device,
    and a write with no consumer must fail closed instead of blocking or
    silently succeeding.
    """

    def _seed_contract(self, home: Path) -> None:
        toolchain = home / "toolchain"
        toolchain.mkdir(parents=True, exist_ok=True)
        fixture = Path(__file__).parent / "fixtures" / "device-minimal.json"
        (toolchain / "device-contract.json").write_text(fixture.read_text())

    def test_fifo_writer_frames_round_trip(self):
        from pf_sim import event_fifo
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.fifo"
            os.mkfifo(path)
            received = []
            done = threading.Event()

            def reader():
                fd = os.open(path, os.O_RDONLY)
                try:
                    data = b""
                    while len(data) < 48:
                        data += os.read(fd, 48 - len(data))
                    received.append(data)
                finally:
                    os.close(fd)
                    done.set()

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            writer = event_fifo.FifoWriter(path)
            try:
                writer.write(event_fifo.pack_event(1, 305, 1)
                             + event_fifo.pack_event(0, 0, 0))
                self.assertTrue(done.wait(2), "fifo reader did not receive frames")
            finally:
                writer.close()
            self.assertEqual(received[0], gamepad.pack_event(1, 305, 1) + gamepad.pack_event(0, 0, 0))

    def test_fifo_writer_fails_closed_without_a_consumer(self):
        from pf_sim import event_fifo
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.fifo"
            os.mkfifo(path)
            writer = event_fifo.FifoWriter(path, open_timeout=0.2)
            try:
                with self.assertRaisesRegex(RuntimeError, "reason=input_fifo_not_open"):
                    writer.write(event_fifo.pack_event(1, 305, 1))
            finally:
                writer.close()

    def test_holder_serves_frames_over_run_private_fifo(self):
        from pf_sim import evdev_read
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            home = Path(tmp)
            self._seed_contract(home)
            instance = "fifo-int"
            state_path = home / "runs" / instance / "gamepad.json"
            try:
                gamepad.create(instance)
                state = json.loads(state_path.read_text())
                event_node = Path(state["event_node"])
                self.assertEqual(event_node, home / "runs" / instance / "input.fifo")
                self.assertTrue(stat.S_ISFIFO(event_node.stat().st_mode))
                self.assertFalse(str(event_node).startswith("/dev/input"))
                frames = []
                ready = threading.Event()

                def reader():
                    frames.extend(evdev_read.read_events(str(event_node), 4, ready=ready))

                thread = threading.Thread(target=reader, daemon=True)
                thread.start()
                self.assertTrue(ready.wait(2), "fifo consumer never became ready")
                response = gamepad.request(instance, {"command": "tap", "code": 305, "hold_ms": 10})
                self.assertEqual(response["status"], "ok")
                thread.join(2)
                self.assertEqual(frames, [(1, 305, 1), (0, 0, 0), (1, 305, 0), (0, 0, 0)])
            finally:
                gamepad.destroy(instance)
            self.assertFalse(state_path.exists())
            self.assertFalse((home / "runs" / instance / "input.fifo").exists(),
                             "holder left the fifo behind")

    def test_holder_tap_without_consumer_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            self._seed_contract(Path(tmp))
            instance = "fifo-noreader"
            try:
                gamepad.create(instance)
                with self.assertRaisesRegex(RuntimeError, "reason=input_fifo_not_open"):
                    gamepad.request(instance, {"command": "tap", "code": 305, "hold_ms": 10})
            finally:
                gamepad.destroy(instance)

    def test_hold_never_creates_a_kernel_device(self):
        import inspect
        source = inspect.getsource(gamepad.hold)
        for needle in ("UInputDevice", "guarded_open", "find_event_node", "uinput"):
            self.assertNotIn(needle, source)
