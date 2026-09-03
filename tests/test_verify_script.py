import subprocess
import unittest
from pathlib import Path


class VerifyScriptTests(unittest.TestCase):
    def test_dry_run_lists_every_epic_criterion(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify-clean-checkout.sh"
        result = subprocess.run([str(script), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        criteria = [line.removeprefix("criterion=") for line in result.stdout.splitlines()
                    if line.startswith("criterion=")]
        self.assertEqual(criteria, [
            "doctor", "toolchain-build", "all-profiles", "text-filtered-capture",
            "scenario-repeat-2", "audit-home200-footer-overlap", "audit-pill-ink",
            "audit-settings-caption-gap", "reduced-matrix", "no-vendored-rust",
            "single-launcher-pin", "no-orphan-shells",
        ])


if __name__ == "__main__":
    unittest.main()
