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
    def __init__(self, statuses=None, hashes=None):
        self.starts = []; self.steps = []; self.captures = []
        self.statuses = statuses or {}; self.hashes = hashes or {}

    def start(self, profile, scale, contrast): self.starts.append((profile, scale, contrast))
    def execute(self, step): self.steps.append(step)
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

    def test_cli_rejects_unsafe_matrix_names_before_backend(self):
        bad = self.root / "bad.toml"
        bad.write_text('[matrix]\nroutes=["../bad"]\nscales=["100"]\ncontrasts=["default"]\nprofiles=["seeded-default"]\n[routes."../bad"]\nsteps=[]\n')
        with patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(main(["matrix", "run", str(bad)]), 1)
        self.assertIn("invalid_route", stderr.getvalue())
