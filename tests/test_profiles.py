import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pf_sim.profiles import effective_prefs, load_profile, render_power_supply, restart_plan, sanitize_tree, seed_profile, snapshot, validate_profile


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

    def test_power_profile_renders_fake_sysfs_tree(self):
        profile = load_profile(Path("profiles/controller-battery-low"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); seed_profile(root, profile)
            self.assertEqual((root / "power_supply/BAT0/type").read_text(), "Battery\n")
            self.assertEqual((root / "power_supply/controller/capacity").read_text(), "15\n")
            self.assertEqual((root / "power_supply/controller/scope").read_text(), "Device\n")

    def test_invalid_power_name_rejected_before_tree_mutation(self):
        profile = load_profile(Path("profiles/seeded-default"))
        profile = __import__("dataclasses").replace(profile, batteries=({"name":"../bad","capacity":1,"status":"Discharging","scope":"Device"},))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sentinel = root / "power_supply/keep"; sentinel.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "invalid_power_profile field=name"):
                seed_profile(root, profile)
            self.assertTrue(sentinel.exists())

    def test_missing_capacity_rejected_before_tree_mutation(self):
        profile = __import__("dataclasses").replace(
            self.profile, batteries=({"name": "BAT0", "status": "Discharging", "scope": "System"},))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sentinel = root / "power_supply/keep"; sentinel.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "invalid_power_profile field=capacity battery=BAT0"):
                render_power_supply(root, profile)
            self.assertTrue(sentinel.exists())

    def test_invalid_power_scope_rejected_by_profile_validation(self):
        profile = __import__("dataclasses").replace(
            self.profile, batteries=({"name": "controller", "capacity": 15,
                                      "status": "Discharging", "scope": "Wireless"},))
        with self.assertRaisesRegex(ValueError, "invalid_power_profile field=scope battery=controller"):
            validate_profile(profile)

    def test_restart_plan(self):
        expected_restart = ("shell", "supervisor", "authorityd")
        for old, new, expected in (
            ("pf-sim", "pf-sim", ("shell",)),
            ("pf-sim", "shell", expected_restart),
            ("shell", "pf-sim", expected_restart),
            ("shell", "shell", ("shell",)),
        ):
            with self.subTest(old=old, new=new):
                self.assertEqual(restart_plan(True, old, True, new), expected)

        self.assertEqual(restart_plan(True, "pf-sim", False, "pf-sim"), expected_restart)
        self.assertEqual(restart_plan(False, "pf-sim", True, "pf-sim"), expected_restart)

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

    def _snapshot_run(self, root, *, profile, authority, prefs):
        run = root / "runs/default"
        (run / "shell").mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({
            "profile": profile, "authority": authority,
            "scale": "150", "contrast": "hc",
        }))
        if prefs is not None:
            (run / "shell/prefs.json").write_text(json.dumps(prefs))
        return run

    def test_snapshot_preserves_live_prefs_when_reseeded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"PF_SIM_HOME": tmp}):
            root = Path(tmp)
            prefs = {"schemaVersion": 2, "firstRunComplete": True, "textScale": "150%", "highContrast": True}
            profile = snapshot("snap150", self._snapshot_run(root, profile="seeded-default", authority=True, prefs=prefs))
            reapplied = root / "reapplied"
            seed_profile(reapplied, profile)
            self.assertEqual(json.loads((reapplied / "shell/prefs.json").read_text()), prefs)
            self.assertIn("seeded-default at scale=150 contrast=hc", profile.description)

    def test_snapshot_preserves_first_run_and_degraded_authority(self):
        for source, authority, prefs in (("first-run", True, None), ("degraded-authority", False, {
            "schemaVersion": 2, "firstRunComplete": True, "textScale": "100%", "highContrast": False,
        })):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"PF_SIM_HOME": tmp}):
                root = Path(tmp)
                profile = snapshot("saved", self._snapshot_run(root, profile=source, authority=authority, prefs=prefs))
                self.assertEqual(profile.authority, authority)
                reapplied = root / "reapplied"
                seed_profile(reapplied, profile)
                self.assertEqual((reapplied / "shell/prefs.json").exists(), prefs is not None)

    def test_snapshot_rejects_unsafe_names_before_mutation(self):
        for name in ("/tmp/x", "../../x", "a/b"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"PF_SIM_HOME": tmp}):
                root = Path(tmp)
                run = self._snapshot_run(root, profile="seeded-default", authority=True, prefs=None)
                sentinel = root.parent / "x"
                sentinel.mkdir(exist_ok=True)
                marker = sentinel / "sentinel"
                marker.write_text("keep")
                try:
                    with self.assertRaisesRegex(ValueError, "reason=invalid_profile"):
                        snapshot(name, run)
                    self.assertEqual(marker.read_text(), "keep")
                finally:
                    marker.unlink(missing_ok=True)
                    sentinel.rmdir()

    def test_snapshot_accepts_valid_names(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"PF_SIM_HOME": tmp}):
            root = Path(tmp)
            run = self._snapshot_run(root, profile="first-run", authority=True, prefs=None)
            for name in ("snap", "snap-1", "snap.v2", "snap_name"):
                self.assertEqual(snapshot(name, run).name, name)
