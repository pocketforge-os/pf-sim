from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import run_dir, sim_home


def sha256(png: str | Path) -> str:
    return hashlib.sha256(Path(png).read_bytes()).hexdigest()


def is_blank(png: str | Path) -> bool:
    with Image.open(png) as image:
        colors = image.convert("RGB").getcolors(maxcolors=2)
        return colors is not None and len(colors) <= 1


def _xwd_to_png(source: Path, target: Path) -> None:
    data = source.read_bytes(); header = struct.unpack(">25I", data[:100])
    size, width, height, bpl, colors = header[0], header[4], header[5], header[12], header[19]
    offset = size + colors * 12
    Image.frombytes("RGB", (width, height), data[offset:offset + height*bpl], "raw", "BGRX", bpl).save(target)


def capture(name: str, instance: str, settle: float = .5) -> tuple[Path, dict]:
    meta = json.loads((run_dir(instance) / "run.json").read_text())
    target_dir = sim_home() / "captures" / instance; target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{name}.png"; time.sleep(settle)
    with tempfile.TemporaryDirectory() as temporary:
        cwd = Path(temporary)
        if meta["display"] == "headless":
            env = os.environ.copy(); env["WAYLAND_DISPLAY"] = meta["weston_socket"]
            env["XDG_RUNTIME_DIR"] = meta["xdg_runtime_dir"]
            subprocess.run(["weston-screenshooter"], cwd=cwd, env=env, check=True)
            shots = sorted(cwd.glob("wayland-screenshot-*.png"))
            if not shots: raise RuntimeError("reason=screenshot_missing")
            shutil.move(shots[-1], target)
        else:
            window = subprocess.check_output(["xdotool", "search", "--class", "weston"], text=True).splitlines()[-1]
            xwd = cwd / "capture.xwd"
            with xwd.open("wb") as output: subprocess.run(["xwd", "-id", window, "-silent"], stdout=output, check=True)
            _xwd_to_png(xwd, target)
    sidecar = {key: meta.get(key) for key in ("instance", "profile", "scale", "contrast", "launcher_rev", "runtime_rev", "display")}
    sidecar.update(captured_at=datetime.now(timezone.utc).isoformat(), sha256=sha256(target))
    target.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    return target, sidecar
