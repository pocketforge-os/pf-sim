import io
import unittest
from unittest.mock import patch

from pf_sim.cli import main


class CliStatusTests(unittest.TestCase):
    def test_status_exit_code_matrix(self):
        for state, expected in (("up", 0), ("down", 3), ("degraded", 4)):
            result = {"state": state, "components": {n: {"alive": state == "up"} for n in ("weston", "authorityd", "supervisor", "shell")}}
            with self.subTest(state=state), patch("pf_sim.cli.backend") as factory, patch("sys.stdout", new=io.StringIO()):
                factory.return_value.status.return_value = result
                self.assertEqual(main(["status", "--json"]), expected)
