import unittest
from pathlib import Path

from pf_sim.config import sim_home
from pf_sim.contract import DeviceContract


FALLBACK_FIXTURE = Path(__file__).parent / "fixtures" / "device-minimal.json"


def contract_path():
    generated = sim_home() / "toolchain" / "device-contract.json"
    return generated if generated.exists() else FALLBACK_FIXTURE


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = DeviceContract.load(contract_path())

    def test_controls_resolve_by_position_label_and_code_name(self):
        for value in ("east", "A", "BTN_EAST", "btn_east"):
            self.assertEqual(self.contract.resolve_control(value).code, 305)

    def test_action_context_and_global_fallback(self):
        self.assertEqual(self.contract.resolve_action("Move.down", "shell").code, 108)
        self.assertEqual(self.contract.resolve_action("Activate", "library").code, 305)

    def test_unbound_action_has_stable_reason(self):
        with self.assertRaisesRegex(RuntimeError, "reason=unbound_action"):
            self.contract.resolve_action("Move.down", "library")
