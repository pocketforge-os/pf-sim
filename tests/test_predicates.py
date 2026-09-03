import unittest

from pf_sim import predicates


class PredicateTests(unittest.TestCase):
    def setUp(self):
        self.scene = {"focused": "tile-1", "route": "Home", "search_query": "e",
                      "search_result_ids": ["one", "two"], "scene": {"id": "root", "children": [
                          {"id": "tile-1", "label": "Ridgeline"}, {"id": "other", "content": {"text": "Settings"}}]}}
        self.history = [{"session_id": "s1", "receipt": {"kind": "Returned"}}]

    def test_scene_and_history_predicates(self):
        for expression in ('focused_id == "tile-1"', 'focused_label == "Ridgeline"',
                           'label_present "Settings"', 'label_absent "Missing"', 'route == "Home"',
                           'search_query == "e"', "result_count < 3", "last_receipt == Returned",
                           "app_state == none", "session_state == idle"):
            self.assertTrue(predicates.evaluate(expression, self.scene, self.history, {"app_state": "none", "session_state": "idle"}), expression)

    def test_unknown_predicate_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_predicate"): predicates.parse("pixels are blue")
