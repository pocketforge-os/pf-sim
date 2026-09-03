import os
import selectors
import tempfile
import threading
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from pf_sim import gamepad, inputs
from pf_sim.contract import DeviceContract
from pf_sim.evdev_read import read_events


FIXTURE = Path(__file__).parent / "fixtures" / "device-minimal.json"


class GamepadDeviceTests(unittest.TestCase):
    def require_uinput(self):
        if os.access(gamepad.UINPUT_PATH, os.W_OK):
            return
        reason = "/dev/uinput is not writable"
        if os.environ.get("PF_SIM_REQUIRE_UINPUT") == "1":
            self.fail(reason)
        self.skipTest(reason)

    def make_event_node_readable(self, event_node):
        subprocess.run(["udevadm", "settle"], check=False)
        result = subprocess.run(["sudo", "-n", "chmod", "666", event_node], check=False)
        if result.returncode and os.environ.get("PF_SIM_REQUIRE_UINPUT") == "1":
            self.fail(f"created event node is not readable: {event_node}")
        if result.returncode:
            self.skipTest(f"created event node is not readable: {event_node}")

    def test_real_uinput_device_and_input_verbs(self):
        self.require_uinput()

        contract = DeviceContract.load(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            # The holder loads the normal generated path; seed the simulator-owned
            # minimal contract so this test does not depend on a toolchain build.
            target = Path(tmp) / "toolchain" / "device-contract.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(FIXTURE.read_bytes())
            state = gamepad.create("integration")
            event_node = state["event_node"]
            # uinput access alone does not change distro udev permissions on the
            # newly-created evdev node. CI and this sanctioned local test
            # environment both provide passwordless sudo for this setup step.
            self.make_event_node_readable(event_node)
            events = []
            reader_ready = threading.Event()

            def collect():
                events.extend(read_events(event_node, 8, reader_ready))

            reader = threading.Thread(target=collect)
            reader.start()
            self.assertTrue(reader_ready.wait(1), "event reader did not start")
            try:
                inputs.press("integration", ["east"], gap_ms=0, contract=contract)
                inputs.action("integration", "Move.down", "shell", contract=contract)
                reader.join(3)
                self.assertFalse(reader.is_alive(), "timed out reading gamepad events")
                self.assertEqual(events, [(1, 305, 1), (0, 0, 0), (1, 305, 0), (0, 0, 0),
                                          (1, 108, 1), (0, 0, 0), (1, 108, 0), (0, 0, 0)])
            finally:
                gamepad.destroy("integration")

    def test_concurrent_instances_have_isolated_event_nodes(self):
        self.require_uinput()
        contract = DeviceContract.load(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
            target = Path(tmp) / "toolchain" / "device-contract.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(FIXTURE.read_bytes())
            states = {}
            errors = []

            def create(instance):
                try:
                    states[instance] = gamepad.create(instance)
                except Exception as error:  # propagate thread failures to the test
                    errors.append(error)

            threads = [threading.Thread(target=create, args=(instance,)) for instance in ("a", "b")]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(5)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertFalse(errors)
                self.assertNotEqual(states["a"]["event_node"], states["b"]["event_node"])
                for state in states.values():
                    self.make_event_node_readable(state["event_node"])

                fd_a = os.open(states["a"]["event_node"], os.O_RDONLY | os.O_NONBLOCK)
                selector = selectors.DefaultSelector()
                selector.register(fd_a, selectors.EVENT_READ)
                events_b = []
                reader_ready = threading.Event()
                reader = threading.Thread(target=lambda: events_b.extend(
                    read_events(states["b"]["event_node"], 4, reader_ready)))
                try:
                    reader.start()
                    self.assertTrue(reader_ready.wait(1), "instance b event reader did not start")
                    inputs.press("b", ["east"], gap_ms=0, contract=contract)
                    reader.join(3)
                    self.assertFalse(reader.is_alive(), "timed out reading instance b events")
                    self.assertEqual(events_b, [(1, 305, 1), (0, 0, 0),
                                                (1, 305, 0), (0, 0, 0)])
                    self.assertEqual(selector.select(timeout=0.2), [])
                finally:
                    selector.close()
                    os.close(fd_a)

                self.assertEqual(gamepad.destroy("a"), "destroyed")
                self.assertEqual(gamepad.status("b")["state"], "up")
            finally:
                gamepad.destroy("a")
                gamepad.destroy("b")
