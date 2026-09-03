from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pf_sim import toolchain


class ToolchainCleanSourceTests(unittest.TestCase):
    def test_build_leaves_launcher_source_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            seed = home / "seed"
            seed.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=seed, check=True)
            (seed / "Cargo.toml").write_text("runtime = 'https://example.invalid/runtime?rev=1234567'\n")
            contract = seed / "crates/pf-shell/fixtures/device.json"
            contract.parent.mkdir(parents=True); contract.write_text("{}")
            subprocess.run(["git", "add", "."], cwd=seed, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=seed, check=True)
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=seed, check=True,
                                      capture_output=True, text=True).stdout.strip()
            source = home / f"toolchain/launcher/{revision}/src"
            target = home / "toolchain/target/release"; target.mkdir(parents=True)
            (target / "pf-shell").write_bytes(b"shell")
            runtime_bin = home / "toolchain/runtime/1234567/bin"; runtime_bin.mkdir(parents=True)
            (runtime_bin / "pf-session-authorityd").write_bytes(b"authority")

            real_run = subprocess.run
            def run(command, *args, **kwargs):
                if command[0] == "cargo":
                    return subprocess.CompletedProcess(command, 0)
                return real_run(command, *args, **kwargs)

            pins = {"launcher_rev": revision, "launcher_repo": str(seed)}
            with patch.dict("os.environ", {"PF_SIM_HOME": str(home)}), \
                 patch("pf_sim.toolchain.load_pins", return_value=pins), \
                 patch("pf_sim.toolchain.derive_runtime", return_value=("unused", "1234567")), \
                 patch("pf_sim.toolchain.subprocess.run", side_effect=run):
                toolchain.build()
            status = real_run(["git", "status", "--porcelain"], cwd=source, check=True,
                              capture_output=True, text=True).stdout
            self.assertEqual(status, "")
