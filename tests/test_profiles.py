import json
import tempfile
import unittest
from pathlib import Path

from pf_sim.profiles import effective_prefs, load_profile, restart_plan, sanitize_tree, snapshot, validate_profile


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(Path("profiles/seeded-default"))

    def test_all_six_preset_renderings(self):
        for scale in ("100", "150", "200"):
            for contrast in ("default", "hc"):
                with self.subTest(scale=scale, contrast=contrast):
                    prefs = effective_prefs(self.profile, scale, contrast)
                    self.assertEqual(prefs["textScale"], scale + "%")
                    self.assertEqual(prefs["highContrast"], contrast == "hc")

    def test_restart_plan(self):
        self.assertEqual(restart_plan(True, True), ("shell",))
        self.assertEqual(restart_plan(True, False), ("shell", "supervisor", "authorityd"))
        self.assertEqual(restart_plan(False, True), ("shell", "supervisor", "authorityd"))

    def test_validation_rejection_matrix(self):
        for relative, reason in (("x.running", "stale_marker"), ("x.sock", "socket"), ("x.lock", "lock"), ("pids.json", "stale_marker"), ("authority/sessions/x", "stale_marker")):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root / "state" / Path(relative).parent).mkdir(parents=True)
                (root / "state" / relative).write_text("x")
                (root / "profile.toml").write_text('[profile]\nname="x"\n[stack]\nauthority=true\n[prefs]\ntext_scale="100%"\nhigh_contrast=false\nfirst_run_complete=true\n')
                with self.assertRaisesRegex(ValueError, reason): validate_profile(load_profile(root))

    def test_snapshot_sanitization_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "shell").mkdir(); (root / "authority/sessions").mkdir(parents=True)
            (root / "shell/prefs.json").write_text(json.dumps({"firstRunComplete": True}))
            (root / "shell/x.lock").touch(); (root / "authority/sessions/x.running").touch()
            sanitize_tree(root)
            self.assertFalse(any(p.name.endswith((".lock", ".running")) for p in root.rglob("*")))
