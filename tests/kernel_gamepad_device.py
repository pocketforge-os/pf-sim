"""Kernel-fidelity (K) gamepad device suite — STOPPED on runner hosts, wave 1.

tsp-ihne1.56: a runner-host uinput device is host-global and typed into the
owner's laptop; nothing in ordinary CI may create one any more. This file is
deliberately NOT named test*.py, so `unittest discover -s tests` never picks
it up on a runner host — it is stopped, not skipped based on host state, and
there is no environment escape hatch (tsp-ihne1.56.5 wave 1).

Wave 2 (gated on the tsp-ihne1.56.4 guest E2E) registers this suite in the
pfvd guest CI suite, where the kernel uinput path is the guest's own and the
sudo provisioning below is available. It exercises the dormant guarded
creator in pf_sim.gamepad (UInputDevice), which the wave-1 scenario route no
longer uses — scenarios run over the run-private FIFO in pf_sim.event_fifo.

Run manually ONLY inside a sanctioned kernel-path environment (pfvd guest):
    python3 -m unittest tests.kernel_gamepad_device -v
"""
import os
import selectors
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from pf_sim import gamepad
from pf_sim.contract import DeviceContract
from pf_sim.evdev_read import read_events


FIXTURE = Path(__file__).parent / "fixtures" / "device-minimal.json"


class KernelGamepadDeviceTests(unittest.TestCase):
    def setUp(self):
        if not os.access(gamepad.UINPUT_PATH, os.W_OK):
            self.fail(f"kernel creator is not writable here ({gamepad.UINPUT_PATH});"
                      " this suite runs only in the sanctioned guest environment")

    def make_event_node_readable(self, event_node):
        # uinput access alone does not change distro udev permissions on the
        # newly-created evdev node; the guest suite provisions passwordless
        # sudo for this setup step and a failure is a hard failure (stopped
        # suites get no skips).
        subprocess.run(["udevadm", "settle"], check=False)
        result = subprocess.run(["sudo", "-n", "chmod", "666", event_node], check=False)
        if result.returncode:
            self.fail(f"created event node is not readable: {event_node}")

    def test_kernel_device_emits_contract_frames(self):
        contract = DeviceContract.load(FIXTURE)
        codes = [control.code for control in contract.controls]
        self.assertIn(305, codes)
        with tempfile.TemporaryDirectory() as tmp:
            device = gamepad.UInputDevice(codes, "kernel-int")
            try:
                event_node = gamepad.find_event_node(device.sysname)
                self.assertTrue(gamepad.wait_event_node_readable(event_node))
                self.make_event_node_readable(event_node)
                events = []
                reader_ready = threading.Event()
                reader = threading.Thread(
                    target=lambda: events.extend(read_events(event_node, 4, reader_ready)))
                reader.start()
                self.assertTrue(reader_ready.wait(1), "event reader did not start")
                device.emit(305, 1)
                device.emit(305, 0)
                reader.join(3)
                self.assertFalse(reader.is_alive(), "timed out reading kernel events")
                self.assertEqual(events, [(1, 305, 1), (0, 0, 0),
                                          (1, 305, 0), (0, 0, 0)])
            finally:
                device.close()

    def test_concurrent_kernel_devices_are_isolated(self):
        contract = DeviceContract.load(FIXTURE)
        codes = [control.code for control in contract.controls]
        devices = {}
        try:
            devices["a"] = gamepad.UInputDevice(codes, "kernel-a")
            devices["b"] = gamepad.UInputDevice(codes, "kernel-b")
            node_a = gamepad.find_event_node(devices["a"].sysname)
            node_b = gamepad.find_event_node(devices["b"].sysname)
            self.assertNotEqual(node_a, node_b)
            for node in (node_a, node_b):
                gamepad.wait_event_node_readable(node)
                self.make_event_node_readable(node)

            fd_a = os.open(node_a, os.O_RDONLY | os.O_NONBLOCK)
            selector = selectors.DefaultSelector()
            selector.register(fd_a, selectors.EVENT_READ)
            events_b = []
            reader_ready = threading.Event()
            reader = threading.Thread(
                target=lambda: events_b.extend(read_events(node_b, 4, reader_ready)))
            try:
                reader.start()
                self.assertTrue(reader_ready.wait(1), "instance b event reader did not start")
                devices["b"].emit(305, 1)
                devices["b"].emit(305, 0)
                reader.join(3)
                self.assertFalse(reader.is_alive(), "timed out reading instance b events")
                self.assertEqual(events_b, [(1, 305, 1), (0, 0, 0),
                                            (1, 305, 0), (0, 0, 0)])
                self.assertEqual(selector.select(timeout=0.2), [],
                                 "instance a saw frames emitted on instance b")
            finally:
                selector.close()
                os.close(fd_a)
        finally:
            for device in devices.values():
                device.close()


if __name__ == "__main__":
    unittest.main()
