import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim.capture import capture, is_blank, sha256


class CaptureTests(unittest.TestCase):
    def test_headless_capture_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / "runs/default"; run.mkdir(parents=True)
            run.joinpath("run.json").write_text(json.dumps({"instance":"default","profile":"first-run","scale":"100","contrast":"default","launcher_rev":"l","runtime_rev":"r","display":"headless","weston_socket":"pf-sim-default","xdg_runtime_dir":tmp}))
            fake = str(Path(__file__).parent / "fakebins")
            with patch.dict(os.environ, {"PF_SIM_HOME":tmp, "PATH":fake + os.pathsep + os.environ["PATH"]}):
                png, sidecar = capture("shot", "default", 0)
            self.assertTrue(png.exists()); self.assertFalse(is_blank(png))
            self.assertEqual(sidecar["sha256"], sha256(png))
            self.assertEqual(json.loads(png.with_suffix(".json").read_text())["profile"], "first-run")
