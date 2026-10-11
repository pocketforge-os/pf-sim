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
        return Path("/tmp/profile-result") if step["op"] == "profile" else {"ok": True}
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

    def test_system_menu_is_physical_and_safe_return_op_is_rejected(self):
        system_menu = VALID.replace('op="capture"\nname="final"', 'op="system_menu"')
        safe_return = VALID.replace('op="capture"\nname="final"', 'op="safe_return"')
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(scenario.load(self.write(tmp, system_menu)).steps[0]["op"],
                             "system_menu")
            with self.assertRaisesRegex(ValueError, "unknown_scenario_op"):
                scenario.load(self.write(tmp, safe_return, "unsafe-bypass.toml"))
        evidence = {"action": "SystemMenu", "control": "BTN_MODE",
                    "launcher_rev": "95302865bc584ce5e1c96e09df387aa5f58455f6",
                    "configured_ack_timeout_ms": 250, "contract": "tsp-ihne1.36"}
        with patch("pf_sim.scenario.system_menu.send", return_value=evidence) as send, \
                patch("pf_sim.scenario.AuthorityClient") as authority:
            result = scenario.LiveBackend("default").execute({"op": "system_menu"})
        send.assert_called_once_with("default")
        authority.assert_not_called()
        self.assertEqual(result["contract"], "tsp-ihne1.36")
        self.assertEqual(result["configured_ack_timeout_ms"], 250)
        self.assertEqual(result["control"], "BTN_MODE")
        self.assertNotIn("provider", result)
        self.assertNotIn("fallback", result)

    def test_providerless_system_menu_scenario_cites_in_ipc(self):
        path = Path(__file__).parents[1] / "scenarios" / "launch-system-menu-fallback.toml"
        item = scenario.load(path)
        self.assertIn("tsp-ihne1.36", item.description)
        self.assertEqual(
            item.steps[0],
            {"op": "launch", "item": "org.pocketforge.ridgeline"},
        )
        self.assertIn("system_menu", [step["op"] for step in item.steps])
        self.assertNotIn("safe_return", [step["op"] for step in item.steps])

    def test_live_launch_accepts_only_an_authority_accepted_result(self):
        backend = scenario.LiveBackend("default")
        with patch("pf_sim.scenario.AuthorityClient") as authority:
            authority.return_value.launch.return_value = {
                "result": "accepted", "session_id": "session-1"
            }
            self.assertEqual(
                backend.execute({"op": "launch", "item": "ridgeline"})["result"],
                "accepted",
            )
            authority.return_value.launch.return_value = {"result": "item_unavailable"}
            with self.assertRaisesRegex(RuntimeError,
                                        "launch_rejected result=item_unavailable"):
                backend.execute({"op": "launch", "item": "ridgeline"})

    def test_launch_crash_uses_runtime_qualified_app_id(self):
        path = Path(__file__).parents[1] / "scenarios" / "launch-crash.toml"
        item = scenario.load(path)
        launch = next(step for step in item.steps if step["op"] == "launch")
        self.assertEqual(launch["item"], "org.pocketforge.ridgeline")

    def test_value_types_are_reported_as_validation_errors(self):
        cases = (
            (VALID.replace('name="tiny"', 'name=1'), "field=scenario.name expected=string"),
            (VALID.replace('op="capture"\nname="final"', 'op="assert"\npredicate=1'), "field=steps[0].predicate expected=string"),
            ('steps=[1]\n[scenario]\nname="tiny"\ndescription="test"\nprofile="seeded-default"\nscale="100"\ncontrast="default"\n',
             "field=steps[0] expected=table"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for number, (text, message) in enumerate(cases):
                with self.subTest(message=message):
                    pattern = message.replace("[", r"\[").replace("]", r"\]")
                    with self.assertRaisesRegex(ValueError, pattern):
                        scenario.load(self.write(tmp, text, f"bad-{number}.toml"))

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

    def test_profile_backend_path_is_serialized_in_report(self):
        text = VALID.replace('op="capture"\nname="final"',
                             'op="profile"\nname="seeded-default"\nscale="100"\ncontrast="default"')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            code, _, _ = scenario.run(scenario.load(self.write(tmp, text)), out=out, backend=FakeBackend())
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((out / "report.json").read_text())["runs"][0]["steps"][0]["output"],
                             "/tmp/profile-result")

    def test_live_observe_tolerates_missing_authority_socket(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("pf_sim.scenario.run_dir", return_value=Path(tmp)), \
                patch("pf_sim.scenario.AutomationClient") as automation, \
                patch("pf_sim.scenario.AuthorityClient") as authority:
            automation.return_value.ping.return_value = {"ok": True}
            automation.return_value.scene.return_value = {"scene": {"id": "home-scroll-region"}}
            scene, history, ping = scenario.LiveBackend("default").observe()
            self.assertEqual(history, [])
            self.assertEqual(ping["authority"], "unavailable")
            self.assertEqual(ping["session_state"], "idle")
            authority.return_value.history.assert_not_called()
            self.assertIn("route", scene)
