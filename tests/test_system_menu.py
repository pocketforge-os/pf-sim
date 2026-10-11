import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim import scenario, system_menu
from pf_sim.cli import main


class SystemMenuTests(unittest.TestCase):
    REVISION = "95302865bc584ce5e1c96e09df387aa5f58455f6"
    SHELL_SHA256 = "a" * 64

    def contract_data(self, action="SystemMenu", control="guide"):
        return {
            "physical_controls": [
                {"position": "guide", "printed_label": "", "input_code": "BTN_MODE"},
                {"position": "south", "printed_label": "B", "input_code": "BTN_SOUTH"},
            ],
            "effective_map": [
                {"context": "global", "action": action,
                 "binding": {"shape": "single_press", "controls": [control]}},
            ],
        }

    def write_contract(self, root, action="SystemMenu", control="guide"):
        data = (json.dumps(self.contract_data(action, control), sort_keys=True) + "\n").encode()
        path = Path(root) / "toolchain/device-contract.json"
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def bind_contract(self, root, action="SystemMenu", control="guide"):
        digest = self.write_contract(root, action, control)
        manifest_path = Path(root) / "toolchain/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["device_contract_sha256"] = digest
        manifest_path.write_text(json.dumps(manifest) + "\n")

    def run_dir(self, root):
        path = Path(root) / "runs/default"
        path.mkdir(parents=True)
        path.joinpath("run.json").write_text(
            json.dumps({"launcher_rev": self.REVISION,
                        "shell_sha256": self.SHELL_SHA256}) + "\n")
        toolchain = Path(root) / "toolchain"
        toolchain.mkdir()
        contract_sha256 = self.write_contract(root)
        toolchain.joinpath("manifest.json").write_text(json.dumps({
            "launcher_rev": self.REVISION,
            "pf_shell_sha256": self.SHELL_SHA256,
            "device_contract_sha256": contract_sha256,
        }) + "\n")
        return path

    def test_send_verifies_selected_contract_and_reports_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)
            result = system_menu.send("default")
        sequence.assert_called_once_with("default", "BTN_MODE", "global", 60, 120,
                                         contract=unittest.mock.ANY)
        automation.return_value.wait_idle.assert_called_once_with()
        self.assertEqual(result["launcher_rev"], self.REVISION)
        self.assertEqual(result["action"], "SystemMenu")
        self.assertNotIn("fallback", result)

    def test_legacy_safe_return_mapping_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)
            self.bind_contract(tmp, action="SafeReturn")
            with self.assertRaisesRegex(RuntimeError, "system_menu_contract_absent"):
                system_menu.send("default")
        sequence.assert_not_called()
        automation.assert_not_called()

    def test_wrong_system_menu_control_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)
            self.bind_contract(tmp, control="south")
            with self.assertRaisesRegex(RuntimeError, "system_menu_contract_mismatch"):
                system_menu.send("default")
        sequence.assert_not_called()
        automation.assert_not_called()

    def test_missing_launcher_provenance_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            with self.assertRaisesRegex(RuntimeError, "system_menu_provenance_absent"):
                system_menu.send("default")
        sequence.assert_not_called()
        automation.assert_not_called()

    def test_interrupted_fresh_and_cache_activation_fail_closed_for_both_callers(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)

            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["system-menu"]), 0)
            self.assertEqual(
                scenario.LiveBackend("default").execute({"op": "system_menu"})["action"],
                "SystemMenu",
            )
            self.assertEqual(sequence.call_count, 2)
            self.assertEqual(automation.return_value.wait_idle.call_count, 2)

            mismatched_contracts = {
                "fresh": (json.dumps(self.contract_data(control="south"),
                                     sort_keys=True) + "\n").encode(),
                "cache": (json.dumps(self.contract_data(), indent=2,
                                     sort_keys=True) + "\n").encode(),
            }
            for activation, content in mismatched_contracts.items():
                with self.subTest(activation=activation):
                    # Model an interrupted activation: valid revision-B bytes land
                    # while manifest and the running shell remain revision A.
                    (Path(tmp) / "toolchain/device-contract.json").write_bytes(content)
                    sequence.reset_mock()
                    automation.reset_mock()
                    with patch("sys.stderr", new=io.StringIO()) as stderr:
                        self.assertEqual(main(["system-menu"]), 1)
                    self.assertIn("reason=system_menu_provenance_mismatch",
                                  stderr.getvalue())
                    with self.assertRaisesRegex(RuntimeError,
                                                "system_menu_provenance_mismatch"):
                        scenario.LiveBackend("default").execute(
                            {"op": "system_menu"}
                        )
                    sequence.assert_not_called()
                    automation.assert_not_called()
