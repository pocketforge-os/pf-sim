import subprocess
import tempfile
import unittest
from pathlib import Path


class VerifyScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = Path(__file__).resolve().parents[1] / "scripts/verify-clean-checkout.sh"

    def test_dry_run_lists_every_epic_criterion(self):
        result = subprocess.run([str(self.script), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        criteria = [line.removeprefix("criterion=") for line in result.stdout.splitlines()
                    if line.startswith("criterion=")]
        self.assertEqual(criteria, [
            "doctor", "toolchain-build", "all-profiles", "text-filtered-capture",
            "scenario-repeat-2", "audit-home200-footer-overlap", "audit-pill-ink",
            "audit-settings-caption-gap", "reduced-matrix", "no-vendored-rust",
            "single-launcher-pin", "no-orphan-shells",
        ])

    def check_audit(self, recipe, expected, transcript):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as output:
            output.write(transcript)
            output.flush()
            return subprocess.run(
                [str(self.script), "--check-audit-output", recipe, expected, output.name],
                capture_output=True, text=True,
            )

    def test_real_audit_transcripts_pass(self):
        transcripts = {
            "home200-footer-overlap": (
                "reproduced",
                "phase=pre-fix mode=fixture reproduced=True\n"
                "phase=post-fix mode=fixture reproduced=True\n"
                "audit_status=reproduced\n",
            ),
            "pill-ink": (
                "partial",
                "phase=pre-fix mode=unreproducible reproduced=None reason=fixture unavailable\n"
                "phase=post-fix mode=fixture reproduced=True\n"
                "audit_status=partial\n",
            ),
            "settings-caption-gap": (
                "partial",
                "phase=pre-fix mode=unreproducible reproduced=None reason=line break differs\n"
                "phase=post-fix mode=fixture reproduced=True\n"
                "audit_status=partial\n",
            ),
        }
        for recipe, (expected, transcript) in transcripts.items():
            with self.subTest(recipe=recipe):
                result = self.check_audit(recipe, expected, transcript)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_audit_rejects_reproduced_status(self):
        transcript = (
            "phase=pre-fix mode=unreproducible reproduced=None reason=fixture unavailable\n"
            "phase=post-fix mode=fixture reproduced=True\n"
            "audit_status=reproduced\n"
        )
        result = self.check_audit("pill-ink", "partial", transcript)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
