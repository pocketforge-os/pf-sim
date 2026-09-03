import tempfile
import unittest
from pathlib import Path

from pf_sim.pins import derive_runtime, load_pins


class PinsTests(unittest.TestCase):
    def test_load_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pins.toml"
            path.write_text('[launcher]\nrepo="https://example/launcher.git"\nrev="abc123"\n')
            self.assertEqual(load_pins(path), {"launcher_repo": "https://example/launcher.git", "launcher_rev": "abc123"})

    def test_derive_runtime_rev(self):
        text = 'pf-runtime = { git = "https://github.com/pocketforge-os/runtime.git", rev = "deadbeef" }'
        self.assertEqual(derive_runtime(text), ("https://github.com/pocketforge-os/runtime.git", "deadbeef"))

    def test_missing_runtime_pin_rejected(self):
        with self.assertRaises(ValueError): derive_runtime("[package]\nname='launcher'")
