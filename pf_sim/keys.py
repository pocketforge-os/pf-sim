from __future__ import annotations

import json
import subprocess
import time

from .config import run_dir


def send(keysyms: list[str], instance: str, delay: float = .35) -> None:
    meta = json.loads((run_dir(instance) / "run.json").read_text())
    if meta["display"] == "headless":
        raise RuntimeError("reason=headless_input_arrives_in_p2")
    window = subprocess.check_output(["xdotool", "search", "--class", "weston"], text=True).splitlines()[-1]
    subprocess.run(["xdotool", "windowactivate", "--sync", window], check=True)
    for keysym in keysyms:
        subprocess.run(["xdotool", "key", "--clearmodifiers", keysym], check=True); time.sleep(delay)
