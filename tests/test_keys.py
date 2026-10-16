import inspect
import unittest
from unittest.mock import patch

from pf_sim import keys


class KeysTests(unittest.TestCase):
    """Wave-1 keyboard fallback (tsp-ihne1.56.5): same run-private FIFO route.

    Negative controls: no xdotool, no window activation, no host display
    metadata; a mutant restoring any of them must fail these tests.
    """

    def test_send_taps_mapped_codes_over_the_private_route(self):
        with patch.object(keys, "request") as request:
            keys.send(["a", "Return", "Up"], "default", delay=0)
        codes = [call.args[1]["code"] for call in request.call_args_list]
        self.assertEqual(codes, [30, 28, 103])
        for call in request.call_args_list:
            self.assertEqual(call.args[0], "default")
            self.assertEqual(call.args[1]["command"], "tap")

    def test_unknown_keysym_fails_closed(self):
        with patch.object(keys, "request") as request:
            with self.assertRaisesRegex(RuntimeError, "reason=unsupported_keysym keysym=NoSuchKey"):
                keys.send(["NoSuchKey"], "default", delay=0)
        request.assert_not_called()

    def test_source_has_no_host_display_routes(self):
        source = inspect.getsource(keys)
        for needle in ("xdotool", "DISPLAY", "windowactivate", "Xauthority",
                       "subprocess", "headless_input_arrives_in_p2"):
            self.assertNotIn(needle, source)
