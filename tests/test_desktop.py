import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from pf_sim.backend.desktop import COMPONENTS, DesktopBackend, proc_start
from pf_sim.profiles import resolve_profile


FAKE = Path(__file__).parent / "fakebins" / "fake-component"


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"; self.xdg.mkdir()
        self.bin = self.root / "bin"; self.bin.mkdir()
        for name in ("weston", "pf-shell", "pf-session-authorityd"):
            (self.bin / name).symlink_to(FAKE)
        self.trace = self.root / "trace"
        self.env = patch.dict(os.environ, {
            "PF_SIM_HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.xdg),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "PF_FAKE_TRACE": str(self.trace),
        }, clear=False)
        self.env.start()
        self.backend = DesktopBackend(wait_timeout=1, settle=0.15)

    def tearDown(self):
        self.backend.down("default")
        self.env.stop(); self.tmp.cleanup()

    def up(self):
        return self.backend.up(shell_bin=self.bin / "pf-shell", authorityd_bin=self.bin / "pf-session-authorityd", no_gamepad=True)

    def test_process_order_readiness_and_teardown(self):
        self.up()
        self.assertEqual(self.trace.read_text().splitlines(), list(COMPONENTS))
        self.assertEqual(self.backend.status("default")["state"], "up")
        self.assertTrue(self.backend.down("default"))
        self.assertEqual(self.backend.status("default")["state"], "down")

    def test_down_uses_recorded_runtime_directory(self):
        self.up()
        socket_path = self.xdg / "pf-sim-default"
        self.assertTrue(socket_path.exists())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            self.assertTrue(self.backend.down("default"))
        self.assertFalse(socket_path.exists())

    def test_failure_tears_down_started_components(self):
        with patch.dict(os.environ, {"PF_FAKE_DIE": "shell"}), self.assertRaisesRegex(RuntimeError, "shell_died"):
            self.up()
        self.assertEqual(self.backend.status("default")["state"], "down")

    def test_failure_after_gamepad_creation_destroys_holder(self):
        pad = {"pid": 123, "start_time": 456, "event_node": "/dev/input/event-test"}
        with patch("pf_sim.backend.desktop.gamepad.create", return_value=pad), \
                patch("pf_sim.backend.desktop.gamepad.destroy") as destroy, \
                patch("pf_sim.backend.desktop.seed_run_dir", side_effect=RuntimeError("seed failed")), \
                self.assertRaisesRegex(RuntimeError, "seed failed"):
            self.backend.up(shell_bin=self.bin / "pf-shell", authorityd_bin=self.bin / "pf-session-authorityd")
        destroy.assert_called_once_with("default")
        self.assertFalse((self.home / "runs/default/gamepad.json").exists())

    def test_up_refuses_when_already_up(self):
        self.up()
        with self.assertRaisesRegex(RuntimeError, "instance_already_up"): self.up()

    def test_up_succeeds_with_gamepad_control_files_present(self):
        run = self.home / "runs/default"
        run.mkdir(parents=True)
        for name in ("gamepad.lock", "gamepad.json", "gamepad.sock"):
            (run / name).touch()
        self.up()
        self.assertEqual(self.backend.status("default")["state"], "up")
        for name in ("gamepad.lock", "gamepad.json", "gamepad.sock"):
            self.assertTrue((run / name).exists())

    def test_status_state_matrix(self):
        self.assertEqual(self.backend.status("default")["state"], "down")
        process = subprocess.Popen(["sleep", "30"])
        try:
            run = self.home / "runs/default"; run.mkdir(parents=True)
            (run / "pids.json").write_text(json.dumps({"weston": {"pid": process.pid, "start_time": proc_start(process.pid)}}))
            self.assertEqual(self.backend.status("default")["state"], "degraded")
            record = {"pid": process.pid, "start_time": proc_start(process.pid)}
            (run / "pids.json").write_text(json.dumps({name: record for name in COMPONENTS}))
            (run / "run.json").write_text(json.dumps({"weston_socket": "pf-sim-default", "xdg_runtime_dir": str(self.xdg)}))
            (self.xdg / "pf-sim-default").touch()
            (run / "session-authority.sock").touch()
            self.assertEqual(self.backend.status("default")["state"], "up")

            (run / "session-authority.sock").unlink()
            status = self.backend.status("default")
            self.assertEqual(status["state"], "degraded")
            self.assertIn("authority_socket_missing", status["degraded_reasons"])

            (run / "session-authority.sock").touch()
            (self.xdg / "pf-sim-default").unlink()
            status = self.backend.status("default")
            self.assertEqual(status["state"], "degraded")
            self.assertIn("weston_socket_missing", status["degraded_reasons"])
        finally:
            process.terminate(); process.wait()

    def test_pf_sim_supervisor_authority_overrides(self):
        commands = []
        process = Mock(pid=os.getpid()); process.poll.return_value = None
        def spawn(name, command, path, records, env=None):
            commands.append((name, command)); return process
        with patch.object(self.backend, "_spawn", side_effect=spawn), patch.object(self.backend, "_wait_socket", return_value=True):
            self.backend.up(shell_bin=self.bin/"pf-shell", authorityd_bin=self.bin/"pf-session-authorityd", profile=resolve_profile("seeded-default"), no_gamepad=True)
        authority = next(command for name,command in commands if name=="authorityd")
        supervisor = next(command for name,command in commands if name=="supervisor")
        for flag in ("--start-command","--graceful-stop-command","--terminate-command","--activate-owner-command"):
            self.assertIn(flag,authority)
        self.assertEqual(supervisor[1:3],["-m","pf_sim.supervisor"])

    def test_apply_supervisor_change_restarts_supervisor_and_authority(self):
        self.backend.up(
            shell_bin=self.bin / "pf-shell",
            authorityd_bin=self.bin / "pf-session-authorityd",
            profile=resolve_profile("seeded-default"),
            no_gamepad=True,
        )
        run = self.home / "runs/default"
        before = json.loads((run / "pids.json").read_text())

        shell_profile = replace(resolve_profile("seeded-default"), supervisor="shell")
        self.backend.apply("default", shell_profile, None, None)

        after = json.loads((run / "pids.json").read_text())
        self.assertNotEqual(after["authorityd"]["pid"], before["authorityd"]["pid"])
        self.assertNotEqual(after["supervisor"]["pid"], before["supervisor"]["pid"])
        command = Path(f"/proc/{after['supervisor']['pid']}/cmdline").read_bytes().split(b"\0")
        self.assertIn(b"--desktop-sim-supervise", command)
