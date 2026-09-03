import os
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
    def test_real_uinput_device_and_input_verbs(self):
        reason = None
        if not os.access(gamepad.UINPUT_PATH, os.W_OK):
            reason = "/dev/uinput is not writable"
        if reason:
            if os.environ.get("PF_SIM_REQUIRE_UINPUT") == "1":
                self.fail(reason)
            self.skipTest(reason)

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
            subprocess.run(["udevadm", "settle"], check=False)
            result = subprocess.run(["sudo", "-n", "chmod", "666", event_node], check=False)
            if result.returncode and os.environ.get("PF_SIM_REQUIRE_UINPUT") == "1":
                self.fail(f"created event node is not readable: {event_node}")
            if result.returncode:
                gamepad.destroy("integration")
                self.skipTest(f"created event node is not readable: {event_node}")
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
