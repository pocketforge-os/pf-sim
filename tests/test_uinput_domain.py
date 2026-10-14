import csv
import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from pf_sim import gamepad
from pf_sim import uinput_domain_guard as guard

ROOT = Path(__file__).resolve().parents[1]


class UinputDomainTest(unittest.TestCase):
    def test_systemd_detect_virt_timeout_is_typed_and_refuses(self):
        with mock.patch.object(guard.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("systemd-detect-virt", 2)) as run:
            probe = guard.probe_host()

        self.assertEqual(probe.container, guard.Check.ERROR)
        with self.assertRaisesRegex(
                guard.UnsafeUinputDomain,
                r"reason=unsafe_uinput_domain domain=probe-error probe=systemd-detect-virt"):
            guard.require_safe(probe)
        self.assertEqual(run.call_args.kwargs["timeout"], 2.0)

    def test_loginctl_timeout_is_typed_and_refuses(self):
        calls = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        calls[0].stdout = ""
        calls[1].stdout = ""
        with mock.patch.object(guard, "_probe_dt", return_value=("missing", frozenset())), \
                mock.patch.object(guard, "_probe_marker", return_value="valid"), \
                mock.patch.object(guard.subprocess, "run",
                                  side_effect=(*calls,
                                               subprocess.TimeoutExpired("loginctl", 2))) as run:
            probe = guard.probe_host()

        self.assertEqual(probe.logind, "unreadable")
        with self.assertRaisesRegex(
                guard.UnsafeUinputDomain,
                r"reason=unsafe_uinput_domain domain=probe-error probe=loginctl"):
            guard.require_safe(probe)
        self.assertEqual(run.call_args.kwargs["timeout"], 2.0)

    def test_gamepad_creator_refuses_before_its_opener_and_allows_guest(self):
        bare = guard.Probe(guard.Check.NO, guard.Check.NO, "missing", frozenset(),
                           "missing", "not-probed")
        guest = guard.Probe(guard.Check.NO, guard.Check.YES, "ok",
                            frozenset(("pocketforge,tsp", "allwinner,sun50i-a133",
                                       "allwinner,sun50i-a100")), "missing", "not-probed")
        calls = []
        with self.assertRaisesRegex(guard.UnsafeUinputDomain, "reason=unsafe_uinput_domain"):
            gamepad.UInputDevice([1], "negative", opener=lambda *args: calls.append(args) or 62,
                                 domain_probe=bare)
        self.assertEqual(calls, [])

        def fake_ioctl(_fd, operation, argument=0, mutate=False):
            if operation == gamepad.UI_GET_SYSNAME:
                argument[:11] = b"input-test\0"
            return 0

        with mock.patch.object(gamepad.fcntl, "ioctl", side_effect=fake_ioctl):
            device = gamepad.UInputDevice([1], "positive",
                                          opener=lambda *args: calls.append(args) or 62,
                                          domain_probe=guest)
        self.assertEqual(device.sysname, "input-test")
        self.assertEqual(len(calls), 1)

    def test_shared_fixture_and_mocked_opener(self):
        fixture = ROOT / "tests/fixtures/uinput-domain-v1.tsv"
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),
                         "6f58e75f72b48a3e426417a55056b688b9c1e4cba2cf7a9e92fea686e47a050d")
        with fixture.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(rows), 18)
        for row in rows:
            probe = guard.Probe(guard.Check(row["container"]), guard.Check(row["vm"]), row["dt"],
                frozenset() if row["compatibles"] == "-" else frozenset(row["compatibles"].split(";")),
                row["marker"], row["logind"])
            got = guard.evaluate(probe)
            self.assertEqual((got.allowed, got.reason, got.domain.value),
                             (row["verdict"] == "allow", row["reason"], row["domain"]), row["case"])
            calls = []
            if got.allowed:
                self.assertEqual(guard.guarded_open("mock", 0, probe=probe,
                    opener=lambda *args: calls.append(args) or 52), 52)
            else:
                with self.assertRaisesRegex(guard.UnsafeUinputDomain, "reason=unsafe_uinput_domain"):
                    guard.guarded_open("mock", 0, probe=probe,
                                       opener=lambda *args: calls.append(args) or 52)
            self.assertEqual(len(calls), int(got.allowed), row["case"])


if __name__ == "__main__":
    unittest.main()
