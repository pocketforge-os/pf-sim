from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from pf_sim import matrix
from pf_sim.cli import main


class FakeBackend:
    def __init__(self, statuses=None, hashes=None, leaked_query=False):
        self.starts = []; self.steps = []; self.captures = []
        self.statuses = statuses or {}; self.hashes = hashes or {}
        self.screen = "home"; self.focused = "item-ridgeline"
        self.query = "leaked" if leaked_query else ""

    def start(self, profile, scale, contrast):
        self.starts.append((profile, scale, contrast))
        self.screen = "first-run" if profile == "first-run" else "home"
        self.focused = "comfort-0" if profile == "first-run" else "item-ridgeline"
    def execute(self, step):
        self.steps.append(step)
        value = step.get("seq")
        if step["op"] == "text": self.query = step["value"]; self.focused = "search-result-ridgeline"
        elif value == "Back": self.screen = "home"; self.focused = "item-ridgeline"
        elif value == "Search.open": self.screen = "search-populated"; self.focused = "search-result-ridgeline"
        elif value == "Quick": self.screen = "quick"; self.focused = "quick-0"
        elif value.startswith("Move.up") and self.screen == "quick": self.focused = "quick-0"
        elif value == "Start" and self.screen == "first-run": self.screen = "home"; self.focused = "item-ridgeline"
        elif value == "Move.down" and self.screen == "quick": self.focused = "quick-1"
        elif value == "Activate" and self.screen == "quick": self.screen = "library"; self.focused = "library-search"
        elif value == "Move.down" and self.screen == "library": self.focused = "library-item-ridgeline"
        elif value == "Activate" and self.screen == "library": self.screen = "details"; self.focused = "detail-variant-0"
        elif value == "Activate" and self.screen == "search-populated":
            self.screen = "details"; self.focused = "detail-pin"
    def observe(self):
        marker = {"home": "home-scroll-region", "library": "library-search",
                  "details": "detail-title", "search-populated": "search-results-scroll-region",
                  "quick": "quick-panel-surface", "first-run": "first-run-panel"}[self.screen]
        return {"focused": self.focused, "search_query": self.query,
                "scene": {"id": "quiet-console", "children": [{"id": marker, "children": []}]}}
    def capture_and_measure(self, cell, route, root, spec):
        self.captures.append(cell.name)
        cell_root = root / "cells" / cell.name; (cell_root / "measure").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 3), "black").save(cell_root / "capture.png")
        (cell_root / "measure" / "overlay.png").write_bytes(b"overlay")
        (cell_root / "measure" / "report.md").write_text("ok\n")
        status = self.statuses.get(cell.route, "PASS")
        return {"status": status, "sha256": self.hashes.get(cell.route, "abc"), "settled": "idle",
                "failures": [] if status == "PASS" else ["text_contrast"],
                "capture": f"cells/{cell.name}/capture.png", "overlay": f"cells/{cell.name}/measure/overlay.png",
                "report": f"cells/{cell.name}/measure/report.md"}


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.root = Path(self.temporary.name)
        self.path = Path(__file__).parent.parent / "audits/product-010/matrix.toml"
        self.spec = matrix.load(self.path)

    def tearDown(self): self.temporary.cleanup()

    def test_parse_and_enumerate_full_matrix_with_skip_rules(self):
        cells = matrix.cells(self.spec)
        self.assertEqual(len(cells), 210)
        self.assertEqual(sum(cell.skip for cell in cells), 54)  # 30 Settings + 24 non-first-run cells.
        settings = next(cell for cell in cells if cell.route == "settings")
        self.assertIn("unreachable", settings.reason)
        first_run = next(cell for cell in cells if cell.route == "first-run" and cell.profile == "seeded-default")
        self.assertTrue(first_run.skip); self.assertEqual(first_run.reason, "route_not_applicable_to_profile")

    def test_filters_and_unknown_filter(self):
        cells = matrix.cells(self.spec, matrix.parse_only("scale=200,contrast=hc"))
        self.assertEqual(len(cells), 35)
        with self.assertRaisesRegex(ValueError, "unknown_matrix_route"):
            matrix.cells(self.spec, {"route": "bogus"})

    def test_runner_reuses_start_and_renders_artifacts(self):
        fake = FakeBackend()
        code, report, out = matrix.run(self.spec, only={"profile": "seeded-default", "scale": "100", "contrast": "default"},
                                       out=self.root / "report", backend=fake)
        self.assertEqual(code, 0); self.assertEqual(len(fake.starts), 1)
        self.assertEqual(report["cell_count"], 7); self.assertEqual(report["skipped"], 2)
        self.assertEqual(len(fake.captures), 5)
        self.assertTrue((out / "report.json").exists()); self.assertTrue((out / "report.md").exists())
        page = (out / "index.html").read_text()
        self.assertEqual(page.count("<img "), 5); self.assertEqual(page.count("<article>"), 7)

    def test_runner_failure_exit_no_fail_and_repeat_determinism(self):
        selection = {"route": "home", "profile": "seeded-default"}
        code, report, _ = matrix.run(self.spec, only=selection, out=self.root / "fail",
                                     backend=FakeBackend({"home": "FAIL"}))
        self.assertEqual(code, 1); self.assertEqual(report["failed"], 6)
        code, _, _ = matrix.run(self.spec, only=selection, out=self.root / "nofail",
                                no_fail=True, backend=FakeBackend({"home": "FAIL"}))
        self.assertEqual(code, 0)
        code, report, _ = matrix.run(self.spec, only={"route": "home", "profile": "seeded-default", "scale": "100", "contrast": "default"},
                                     out=self.root / "repeat", repeat=2, backend=FakeBackend())
        self.assertEqual(code, 0); self.assertTrue(report["deterministic"])

    def test_route_mismatch_fails_before_measure(self):
        class WrongScreen(FakeBackend):
            def observe(self):
                scene = super().observe()
                scene["scene"]["children"][0]["id"] = "quick-panel-surface"
                scene["focused"] = "quick-0"
                return scene
        fake = WrongScreen()
        code, report, _ = matrix.run(
            self.spec,
            only={"route": "first-run", "profile": "first-run", "scale": "100", "contrast": "default"},
            out=self.root / "mismatch", backend=fake,
        )
        self.assertEqual(code, 1)
        self.assertEqual(fake.captures, [])
        self.assertIn("reason=route_mismatch expected=first-run observed=quick/quick-0", report["cells"][0]["reason"])

    def test_leaked_search_query_is_cleared_during_reset(self):
        fake = FakeBackend(leaked_query=True)
        code, report, _ = matrix.run(
            self.spec,
            only={"route": "home", "profile": "seeded-default", "scale": "100", "contrast": "default"},
            out=self.root / "reset", backend=fake,
        )
        self.assertEqual(code, 0)
        self.assertEqual(report["cells"][0]["observed_screen"], "home")
        self.assertIn({"op": "text", "value": ""}, fake.steps)

    def test_cli_rejects_unsafe_matrix_names_before_backend(self):
        bad = self.root / "bad.toml"
        bad.write_text('[matrix]\nroutes=["../bad"]\nscales=["100"]\ncontrasts=["default"]\nprofiles=["seeded-default"]\n[routes."../bad"]\nsteps=[]\n')
        with patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(main(["matrix", "run", str(bad)]), 1)
        self.assertIn("invalid_route", stderr.getvalue())
