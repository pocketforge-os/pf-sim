import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from pf_sim.fixture_app import fixture_config, send_command


class FixtureAppTests(unittest.TestCase):
    def spawn(self, run, session="s1", delay=0):
        env = os.environ.copy(); env["PF_SIM_NO_WESTON_IMAGE"] = "1"
        return subprocess.Popen([sys.executable, "-m", "pf_sim.fixture_app", "--run-dir", str(run), "--session", session, "--item", "hollow-tides", "--launch-delay-ms", str(delay)], env=env)

    def wait(self, path, timeout=2):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline and not path.exists(): time.sleep(.01)
        self.assertTrue(path.exists())

    def test_marker_delay_status_and_normal_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); process=self.spawn(run, delay=150); marker=run/"authority/sessions/s1.running"; sock=run/"apps/s1.sock"
            self.assertFalse(marker.exists()); self.wait(sock)
            self.assertEqual(send_command(sock,{"command":"status"})["status"],"running")
            send_command(sock,{"command":"exit","code":7}); self.assertEqual(process.wait(),7); self.assertFalse(marker.exists())

    def test_crash_exits_by_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); process=self.spawn(run); sock=run/"apps/s1.sock"; self.wait(sock)
            send_command(sock,{"command":"crash"}); self.assertEqual(process.wait(),-11)

    def test_rejects_unsafe_session_and_item_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for flag in ("--session","--item"):
                args=[sys.executable,"-m","pf_sim.fixture_app","--run-dir",tmp,"--session","ok","--item","hollow-tides"]
                args[args.index(flag)+1]="../bad"
                self.assertNotEqual(subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0)

    def test_catalog_launch_targets_use_qualified_fixture_ids(self):
        root = Path(__file__).parents[1]
        catalog = json.loads(root.joinpath("fixtures/catalog-snapshot.json").read_text())
        items = {item["id"]: item for item in catalog["items"]}
        for fixture_id in ("ridgeline", "hollow-tides", "signal-decay"):
            with self.subTest(fixture_id=fixture_id):
                target = items[fixture_id]["variants"][0]["launch_target"]["app_id"]
                self.assertEqual(target, f"org.pocketforge.{fixture_id}")
                self.assertEqual(fixture_config(target), fixture_config(fixture_id))
