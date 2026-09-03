import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim.contract import DeviceContract
from pf_sim import inputs


FIXTURE = Path(__file__).parent / "fixtures" / "device-minimal.json"


class InputTests(unittest.TestCase):
    def setUp(self):
        self.contract = DeviceContract.load(FIXTURE)

    @patch("pf_sim.inputs.request")
    def test_press_accepts_all_control_names(self, request):
        inputs.press("default", ["east", "A", "BTN_EAST"], 7, 0, self.contract)
        self.assertEqual([call.args[1]["code"] for call in request.call_args_list], [305, 305, 305])

    @patch("pf_sim.inputs.request")
    def test_action_resolves_to_control(self, request):
        inputs.action("default", "Move.down", "shell", contract=self.contract)
        self.assertEqual(request.call_args.args[1]["code"], 108)
