import tempfile
import unittest
from pathlib import Path

from pf_sim.stack import StaleStateError, seed_run_dir


class HygieneTests(unittest.TestCase):
    def test_seed_removes_marker_socket_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for rel in ("authority/sessions/session-2.running", "shell/old.sock", "authority/old.lock"):
                path = run / rel; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            seed_run_dir(run)
            self.assertFalse(any(run.rglob("*.running")))
            self.assertFalse(any(run.rglob("*.sock")))
            self.assertFalse(any(run.rglob("*.lock")))
            self.assertEqual((run / "shell/prefs.json").read_text(), '{"schemaVersion":2,"firstRunComplete":true}\n')

    def test_post_seed_assertion_rejects_bad_seed(self):
        def bad_seed(run): (run / "authority/bad.running").touch()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(StaleStateError):
            seed_run_dir(Path(tmp), bad_seed)
