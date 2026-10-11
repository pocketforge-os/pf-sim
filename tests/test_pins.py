import tempfile
import unittest
from pathlib import Path

from pf_sim.pins import derive_runtime, load_pins


class PinsTests(unittest.TestCase):
    def test_default_launcher_pin_has_system_menu_contract(self):
        path = Path(__file__).parents[1] / "pins.toml"
        self.assertEqual(load_pins(path)["launcher_rev"],
                         "95302865bc584ce5e1c96e09df387aa5f58455f6")

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
