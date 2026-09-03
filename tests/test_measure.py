from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pf_sim import cli, measure
from pf_sim.measure import contrast, diff, gaps, ink, overlay, report


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.root = Path(self.temporary.name)
        self.image = Image.new("RGB", (80, 40), "white"); draw = ImageDraw.Draw(self.image)
        draw.rectangle((5, 5, 14, 14), fill="black")
        draw.rectangle((22, 5, 31, 14), fill="black")       # seven-pixel gap
        draw.rectangle((29, 22, 38, 31), fill="black")      # three-pixel overlap with node b in x
        self.nodes = [
            {"id": "a", "role": "text", "bounds": [3, 3, 14, 14]},
            {"id": "b", "role": "text", "bounds": [20, 3, 14, 14]},
            {"id": "c", "role": "text", "bounds": [27, 20, 14, 14]},
        ]

    def tearDown(self): self.temporary.cleanup()

    def test_ink_extents_and_insets(self):
        value = ink.measure_node(self.image, self.nodes[0])
        self.assertEqual(value["ink_extents"], {"x": 5, "y": 5, "width": 10, "height": 10})
        self.assertEqual(value["insets"], {"left": 2, "top": 2, "right": 2, "bottom": 2})

    def test_known_gaps_and_overlap(self):
        values = {node["id"]: ink.measure_node(self.image, node) for node in self.nodes}
        result = gaps.matrix(values, 8)
        ab = next(p for p in result["pairs"] if (p["a"], p["b"]) == ("a", "b"))
        bc = next(p for p in result["pairs"] if (p["a"], p["b"]) == ("b", "c"))
        self.assertEqual(ab["ink"]["horizontal"], 7)
        self.assertEqual(bc["ink"]["horizontal"], -3)
        self.assertTrue(ab["under_min_gap"])

    def test_contrast_pairs_straddle_floor(self):
        low = contrast.ratio((119, 119, 119), (255, 255, 255))
        high = contrast.ratio((116, 116, 116), (255, 255, 255))
        self.assertAlmostEqual(low, 4.48, places=2); self.assertLess(low, 4.5)
        self.assertAlmostEqual(high, 4.67, places=2); self.assertGreater(high, 4.5)

    def test_contrast_uses_box_fill_and_excludes_rounded_corner_bleed(self):
        image = Image.new("RGB", (50, 30), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 44, 24), radius=7, fill=(220, 220, 220))
        draw.rectangle((17, 12, 32, 16), fill=(100, 100, 100))
        node = {"id": "rounded", "role": "text", "bounds": [5, 5, 40, 20]}
        value = contrast.measure(image, ink.measure_node(image, node), 4.5)
        self.assertEqual(value["background_color"], [220, 220, 220])
        self.assertEqual(value["ink_color"], [100, 100, 100])

    def test_contrast_empty_box_is_no_ink(self):
        image = Image.new("RGB", (30, 20), (80, 80, 80))
        node = {"id": "empty", "role": "text", "bounds": [5, 5, 20, 10]}
        value = contrast.measure(image, ink.measure_node(image, node), 4.5)
        self.assertEqual(value["status"], "NO_INK")
        self.assertIsNone(value["ratio"])

    def test_overlay_and_report_status(self):
        rendered = overlay.render(self.image, self.nodes, "b")
        self.assertEqual(rendered.size, self.image.size)
        value = report.build({}, {}, {"pairs": [{"under_min_gap": True}]}, {}, {"min_gap": 8})
        self.assertEqual(value["status"], "FAIL")

    def test_diff_lists_moved_node(self):
        moved = Image.new("RGB", self.image.size, "white")
        ImageDraw.Draw(moved).rectangle((6, 5, 15, 14), fill="black")
        a = {"a": ink.measure_node(self.image, self.nodes[0])}
        b = {"a": ink.measure_node(moved, self.nodes[0])}
        raster, nodes = diff.compare(self.image, moved, a, b)
        self.assertEqual(nodes, ["a"]); self.assertIsNotNone(raster.getbbox())

    def test_end_to_end_artifacts(self):
        png = self.root / "frame.png"; self.image.save(png)
        scene = self.root / "frame.scene.json"
        scene.write_text(json.dumps({"focused": "b", "scene": {"id": "root", "bounds": [0, 0, 80, 40], "children": self.nodes}}))
        out = self.root / "result"
        value = measure.run(png, scene, out, min_gap=0)
        self.assertIn(value["status"], {"PASS", "FAIL"})
        for name in ("overlay.png", "ink.json", "gaps.json", "contrast.json", "report.md", "report.json"):
            self.assertTrue((out / name).exists(), name)

    def test_measure_rejects_invalid_capture_name(self):
        old = os.environ.get("PF_SIM_HOME"); os.environ["PF_SIM_HOME"] = str(self.root)
        try: self.assertEqual(cli.main(["measure", "../escape"]), 2)
        finally:
            if old is None: os.environ.pop("PF_SIM_HOME", None)
            else: os.environ["PF_SIM_HOME"] = old

    def test_diff_rejects_invalid_capture_name(self):
        self.assertEqual(cli.main(["measure", "diff", "ok", "../escape"]), 2)

    def test_audit_rejects_invalid_name(self):
        self.assertEqual(cli.main(["audit", "run", "../escape.toml"]), 2)
