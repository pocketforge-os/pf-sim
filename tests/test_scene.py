import json
import unittest
from pathlib import Path

from pf_sim.scene import find, focused_id, iter_nodes, node_bounds


class SceneTests(unittest.TestCase):
    scene = json.loads((Path(__file__).parent / "fixtures/sample-scene.json").read_text())

    def test_helpers(self):
        self.assertEqual(focused_id(self.scene), "item-ridgeline")
        self.assertEqual(find(self.scene, role="button", label="Ridgeline")["id"], "item-ridgeline")
        self.assertEqual(find(self.scene, role="text", label="Library")["id"], "title")
        self.assertEqual(node_bounds(next(iter(iter_nodes(self.scene)))), (0, 0, 1280, 720))
        self.assertEqual(len(list(iter_nodes(self.scene))), 3)
