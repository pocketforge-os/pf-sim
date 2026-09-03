import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pf_sim import scenario
from pf_sim.cli import main


VALID = '''[scenario]
name="tiny"
description="test"
profile="seeded-default"
scale="100"
contrast="default"
[[steps]]
op="capture"
name="final"
'''


class FakeBackend:
    def __init__(self, fail=False, changing=False): self.calls=[]; self.fail=fail; self.changing=changing; self.n=0
    def start(self, *args): self.calls.append(("start", args))
    def execute(self, step):
        self.calls.append(("execute", step["op"]))
        if self.fail: raise RuntimeError("boom")
        return {"ok": True}
    def capture(self, png):
        self.n += 1; png.write_bytes(b"stable" + (str(self.n).encode() if self.changing else b""))
        png.with_name("scene.json").write_text("{}\n")
        import hashlib
        return {"sha256": hashlib.sha256(png.read_bytes()).hexdigest()}


class ScenarioTests(unittest.TestCase):
    def write(self, root, text=VALID, name="scenario.toml"):
        path=Path(root)/name; path.write_text(text); return path

    def test_parse_validate_and_unsafe_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(scenario.load(self.write(tmp)).name, "tiny")
            with self.assertRaisesRegex(ValueError, "unknown_scenario_op"):
                scenario.load(self.write(tmp, VALID.replace('op="capture"', 'op="wat"'), "bad.toml"))
            with self.assertRaisesRegex(ValueError, "invalid_scenario"):
                unsafe = self.write(tmp, VALID.replace('name="tiny"', 'name="../bad"'), "unsafe.toml")
                scenario.load(unsafe)
            with self.assertRaisesRegex(ValueError, "invalid_predicate"):
                scenario.load(self.write(tmp, VALID.replace('op="capture"\nname="final"', 'op="assert"\npredicate="bad"'), "predicate.toml"))
            self.assertEqual(main(["scenario", "validate", str(unsafe)]), 2)

    def test_artifacts_order_failure_skip_and_report(self):
        text=VALID + '[[steps]]\nop="capture"\nname="later"\n'
        with tempfile.TemporaryDirectory() as tmp:
            item=scenario.load(self.write(tmp,text)); out=Path(tmp)/"out"; fake=FakeBackend(fail=True)
            code, report, _=scenario.run(item, out=out, backend=fake)
            self.assertEqual(code,1); self.assertEqual([x["result"] for x in report["runs"][0]["steps"]],["fail","skipped"])
            self.assertTrue((out/"run-001/01-capture/step.json").exists()); self.assertTrue((out/"report.md").exists())

    def test_repeat_determinism_and_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=scenario.load(self.write(tmp)); out=Path(tmp)/"out"; fake=FakeBackend()
            code, report, _=scenario.run(item, repeat=2, out=out, backend=fake)
            self.assertEqual(code,0); self.assertTrue(report["deterministic"])
            self.assertIn("| run-001 | 1 | capture | PASS", scenario.render_report(report))
            code, report, _=scenario.run(item, repeat=2, out=Path(tmp)/"changed", backend=FakeBackend(changing=True))
            self.assertEqual(code,1); self.assertFalse(report["deterministic"])
