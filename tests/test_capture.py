import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from pf_sim.capture import capture, is_blank, sha256


class CaptureTests(unittest.TestCase):
    def test_frame_complete_capture_order_and_scene_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text(json.dumps({"instance":"default", "display":"headless"}))
            calls = []
            client = Mock()
            client.wait_idle.side_effect = lambda *args: calls.append("wait_idle")
            def write_capture(path):
                calls.append("capture"); Path(path).write_bytes(b"png")
                return {"ok":True, "frames":7, "revision":4}
            client.capture.side_effect = write_capture
            client.scene.side_effect = lambda: calls.append("scene") or {"ok":True,"frames":7,"revision":4,"scene":{}}
            with patch.dict(os.environ, {"PF_SIM_HOME":tmp}), patch("pf_sim.capture.AutomationClient", return_value=client):
                png, sidecar = capture("shot", "default")
            self.assertEqual(calls, ["wait_idle", "capture", "scene"])
            self.assertTrue(png.with_suffix(".scene.json").exists())
            self.assertEqual((sidecar["frames"], sidecar["revision"]), (7, 4))

    def test_frame_drift_retries_and_converges(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text('{"instance":"default"}')
            client = Mock()
            def write_capture(path):
                Path(path).write_bytes(b"png")
                return {"frames": 7, "revision": 4}
            client.capture.side_effect = write_capture
            client.scene.side_effect = [
                {"frames": 8, "revision": 5, "scene": {}},
                {"frames": 7, "revision": 4, "scene": {}},
            ]
            with patch.dict(os.environ, {"PF_SIM_HOME": tmp}), patch("pf_sim.capture.AutomationClient", return_value=client):
                _, sidecar = capture("shot", "default")
            self.assertEqual(client.wait_idle.call_count, 2)
            self.assertEqual(client.capture.call_count, 2)
            self.assertEqual(sidecar["capture_revision"], sidecar["scene_revision"])

    def test_frame_drift_fails_after_three_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text('{"instance":"default"}')
            client = Mock()
            def write_capture(path):
                Path(path).write_bytes(b"png")
                return {"frames": 7, "revision": 4}
            client.capture.side_effect = write_capture
            client.scene.return_value = {"frames": 8, "revision": 5, "scene": {}}
            with patch.dict(os.environ, {"PF_SIM_HOME": tmp}), patch("pf_sim.capture.AutomationClient", return_value=client):
                with self.assertRaisesRegex(RuntimeError, "reason=capture_frame_drift"):
                    capture("shot", "default")
            self.assertEqual(client.capture.call_count, 3)

    def test_headless_capture_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text(json.dumps({"instance":"default","profile":"first-run","scale":"100","contrast":"default","launcher_rev":"l","runtime_rev":"r","display":"headless","weston_socket":"pf-sim-default","xdg_runtime_dir":tmp}))
            fake = str(Path(__file__).parent / "fakebins")
            with patch.dict(os.environ, {"PF_SIM_HOME":tmp, "PATH":fake + os.pathsep + os.environ["PATH"]}):
                png, sidecar = capture("shot", "default", 0, raw=True)
            self.assertTrue(png.exists()); self.assertFalse(is_blank(png))
            self.assertEqual(sidecar["sha256"], sha256(png))
            self.assertEqual(json.loads(png.with_suffix(".json").read_text())["profile"], "first-run")

    def test_capture_rejects_unsafe_names_before_mutation(self):
        for name in ("/tmp/x", "../x", "a/b"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PF_SIM_HOME": tmp}):
                outside = Path(tmp).parent / "x.png"
                outside.write_text("keep")
                try:
                    with self.assertRaisesRegex(ValueError, "reason=invalid_capture"):
                        capture(name, "default", 0, raw=True)
                    self.assertEqual(outside.read_text(), "keep")
                    self.assertFalse((Path(tmp) / "captures").exists())
                finally:
                    outside.unlink(missing_ok=True)

    def test_capture_accepts_valid_dotted_name_without_replacing_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text(json.dumps({"instance":"default","profile":"first-run","scale":"100","contrast":"default","launcher_rev":"l","runtime_rev":"r","display":"headless","weston_socket":"pf-sim-default","xdg_runtime_dir":tmp}))
            fake = str(Path(__file__).parent / "fakebins")
            with patch.dict(os.environ, {"PF_SIM_HOME":tmp, "PATH":fake + os.pathsep + os.environ["PATH"]}):
                png, _ = capture("shot.v1", "default", 0, raw=True)
            self.assertEqual(png.name, "shot.v1.png")
