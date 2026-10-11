import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim import system_menu
from pf_sim.contract import Control, DeviceContract


class SystemMenuTests(unittest.TestCase):
    REVISION = "95302865bc584ce5e1c96e09df387aa5f58455f6"

    def contract(self, action="SystemMenu"):
        return DeviceContract(
            [Control("guide", "", "BTN_MODE", 316),
             Control("south", "B", "BTN_SOUTH", 305)],
            [{"context": "global", "action": action,
              "binding": {"shape": "single_press", "controls": ["guide"]}}],
        )

    def run_dir(self, root):
        path = Path(root) / "runs/default"
        path.mkdir(parents=True)
        path.joinpath("run.json").write_text(
            json.dumps({"launcher_rev": self.REVISION}) + "\n")
        return path

    def test_send_verifies_selected_contract_and_reports_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)
            contract = self.contract()
            result = system_menu.send("default", contract)
        sequence.assert_called_once_with("default", "BTN_MODE", "global", 60, 120,
                                         contract=contract)
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
            with self.assertRaisesRegex(RuntimeError, "system_menu_contract_absent"):
                system_menu.send("default", self.contract("SafeReturn"))
        sequence.assert_not_called()
        automation.assert_not_called()

    def test_wrong_system_menu_control_is_rejected_before_input(self):
        contract = DeviceContract(
            [Control("guide", "", "BTN_MODE", 316),
             Control("south", "B", "BTN_SOUTH", 305)],
            [{"context": "global", "action": "SystemMenu",
              "binding": {"shape": "single_press", "controls": ["south"]}}],
        )
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            self.run_dir(tmp)
            with self.assertRaisesRegex(RuntimeError, "system_menu_contract_mismatch"):
                system_menu.send("default", contract)
        sequence.assert_not_called()
        automation.assert_not_called()

    def test_missing_launcher_provenance_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"PF_SIM_HOME": tmp}), \
                patch("pf_sim.system_menu.inputs.sequence") as sequence, \
                patch("pf_sim.system_menu.AutomationClient") as automation:
            with self.assertRaisesRegex(RuntimeError, "system_menu_provenance_absent"):
                system_menu.send("default", self.contract())
        sequence.assert_not_called()
        automation.assert_not_called()
