import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class StrictResolverFixtureTests(unittest.TestCase):
    def test_install_refuses_collisions_and_remove_requires_markers(self):
        script = Path(__file__).parents[1] / "scripts/strict-resolver-fixtures.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([script, "install", root], check=True)
            for app_id in ("ridgeline", "hollow-tides", "signal-decay"):
                app = root / "opt/pocketforge/apps" / app_id
                self.assertIn(f'id = "{app_id}"', app.joinpath("app.toml").read_text())
                self.assertTrue(os.access(app / "fixture", os.X_OK))
            self.assertTrue(
                root.joinpath("usr/share/pocketforge/platform-capabilities.toml").is_file()
            )

            collision = subprocess.run(
                [script, "install", root], capture_output=True, text=True
            )
            self.assertNotEqual(collision.returncode, 0)
            self.assertIn("strict_resolver_apps_target_exists", collision.stderr)

            subprocess.run([script, "remove", root], check=True)
            self.assertFalse(root.joinpath("opt/pocketforge/apps").exists())
            missing = subprocess.run(
                [script, "remove", root], capture_output=True, text=True
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("strict_resolver_fixture_marker_absent", missing.stderr)
