import os
import signal
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fake_authority import FakeAuthority
from pf_sim.supervisor import RETURN_CHAIN, Supervisor


class SupervisorTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=3):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline and not predicate(): time.sleep(.02)
        self.assertTrue(predicate())

    def observations(self, fake):
        return [r["observation"] for r in fake.requests if r["method"]=="observe"]

    def test_launch_running_and_clean_return_chain(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"PF_SIM_NO_WESTON_IMAGE":"1"}):
            run=Path(tmp); fake=FakeAuthority(run/"authority.sock").start(); supervisor=Supervisor(run,fake.path)
            try:
                supervisor.launch("hollow-tides","clean1")
                self.wait_for(lambda:any(o["kind"]=="session_running" for o in self.observations(fake)))
                self.assertEqual(supervisor.command({"command":"stop","session_id":"clean1"})["status"],"ok")
                self.wait_for(lambda:len(self.observations(fake))>=6)
                self.assertEqual([o["kind"] for o in self.observations(fake)], ["session_running","session_exited_cleanly",*RETURN_CHAIN])
            finally: fake.close()

    def test_kill_reports_signal_and_removes_marker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"PF_SIM_NO_WESTON_IMAGE":"1"}):
            run=Path(tmp); fake=FakeAuthority(run/"authority.sock").start(); supervisor=Supervisor(run,fake.path)
            try:
                supervisor.launch("hollow-tides","crash1"); marker=run/"authority/sessions/crash1.running"
                self.wait_for(marker.exists)
                supervisor.command({"command":"kill","session_id":"crash1"})
                self.wait_for(lambda:any(o["kind"]=="session_crashed" for o in self.observations(fake)))
                crash=next(o for o in self.observations(fake) if o["kind"]=="session_crashed")
                self.assertEqual(crash["summary"],"signal SIGKILL"); self.assertFalse(marker.exists())
                self.assertEqual([o["kind"] for o in self.observations(fake)][-4:],list(RETURN_CHAIN))
            finally: fake.close()

    def test_hook_name_validation_precedes_process_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); fake=FakeAuthority(run/"authority.sock").start(); supervisor=Supervisor(run,fake.path)
            try:
                for field,request in (("session",{"command":"kill","session_id":"../x"}), ("item",{"command":"launch","item_id":"../x","session_id":"ok"})):
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError,"invalid_"+field): supervisor.command(request)
            finally: fake.close()

    def test_startup_reconcile_reports_interrupted_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); fake=FakeAuthority(run/"authority.sock").start()
            fake.entries=[{"session_id":"old1","item_id":"hollow-tides","receipt":None,"started_at":None,"ended_at":None}]
            try:
                Supervisor(run,fake.path).reconcile()
                self.assertEqual([o["kind"] for o in self.observations(fake)], ["session_exited_cleanly",*RETURN_CHAIN])
            finally: fake.close()
