import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim.cli import main


class CliStatusTests(unittest.TestCase):
    def test_status_exit_code_matrix(self):
        for state, expected in (("up", 0), ("down", 3), ("degraded", 4)):
            result = {"state": state, "components": {n: {"alive": state == "up"} for n in ("weston", "authorityd", "supervisor", "shell")}}
            with self.subTest(state=state), patch("pf_sim.cli.backend") as factory, patch("sys.stdout", new=io.StringIO()):
                factory.return_value.status.return_value = result
                self.assertEqual(main(["status", "--json"]), expected)

    def test_instance_validation_for_every_instance_verb(self):
        invalid = ("../../x", "a/b", ".", "..", "", "x" * 65)
        for verb in ("up", "down", "status"):
            for instance in invalid:
                with self.subTest(verb=verb, instance=instance), patch("pf_sim.cli.backend") as factory, patch("sys.stderr", new=io.StringIO()) as stderr:
                    self.assertEqual(main([verb, "--instance", instance]), 2)
                    self.assertIn("reason=invalid_instance", stderr.getvalue())
                    factory.assert_not_called()

    def test_valid_instances_reach_backend(self):
        for instance in ("default", "dev-1", "run.2"):
            result = {"state": "down", "components": {}}
            with self.subTest(instance=instance), patch("pf_sim.cli.backend") as factory, patch("sys.stdout", new=io.StringIO()):
                factory.return_value.status.return_value = result
                self.assertEqual(main(["status", "--instance", instance]), 3)
                factory.return_value.status.assert_called_once_with(instance)

    def test_invalid_instance_cannot_mutate_outside_runs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}), patch("pf_sim.backend.desktop.seed_run_dir") as seed, patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(main(["up", "--instance", "../../x"]), 2)
            seed.assert_not_called()
            self.assertFalse((Path(tmp).parent / "x").exists())

    def test_invalid_profile_and_capture_names_exit_two(self):
        cases = ((["profile", "snapshot", "../../x"], "invalid_profile"),
                 (["profile", "apply", "a/b"], "invalid_profile"),
                 (["profile", "show", "/tmp/x"], "invalid_profile"),
                 (["profile", "validate", "../x"], "invalid_profile"),
                 (["up", "--profile", "../x"], "invalid_profile"),
                 (["capture", "../x"], "invalid_capture"))
        for argv, reason in cases:
            with self.subTest(argv=argv), patch("sys.stderr", new=io.StringIO()) as stderr:
                self.assertEqual(main(argv), 2)
                self.assertIn("reason=" + reason, stderr.getvalue())

    def test_invalid_fixture_item_name_exits_two_before_rpc(self):
        with patch("pf_sim.cli.AuthorityClient") as client, patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(main(["launch", "../bad"]), 2)
            self.assertIn("reason=invalid_item", stderr.getvalue()); client.assert_not_called()
