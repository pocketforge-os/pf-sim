from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import run_dir, safe_child, sim_home
from .automation import AutomationClient


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


def capture(name: str, instance: str, settle: float = .5, *, raw=False, quiet_ms=150, timeout_ms=5000) -> tuple[Path, dict]:
    target_dir = safe_child(sim_home() / "captures", "instance", instance)
    validated_target = safe_child(target_dir, "capture", name)
    target = validated_target.parent / f"{validated_target.name}.png"
    # The suffix operation must not weaken the direct-child containment invariant.
    if not target.resolve().is_relative_to(target_dir.resolve()):
        raise ValueError("reason=invalid_capture")
    meta = json.loads((run_dir(instance) / "run.json").read_text())
    target_dir.mkdir(parents=True, exist_ok=True)
    if not raw:
        client = AutomationClient(run_dir(instance) / "automation.sock")
        for _attempt in range(3):
            client.wait_idle(quiet_ms, timeout_ms)
            result = client.capture(target)
            scene = client.scene()
            if (result["frames"], result["revision"]) == (scene["frames"], scene["revision"]):
                break
        else:
            raise RuntimeError("reason=capture_frame_drift")
        scene_path = target.with_suffix(".scene.json")
        scene_path.write_text(json.dumps(scene, indent=2, sort_keys=True) + "\n")
        sidecar = {key: meta.get(key) for key in ("instance", "profile", "scale", "contrast", "launcher_rev", "runtime_rev", "display")}
        sidecar.update(captured_at=datetime.now(timezone.utc).isoformat(), png_sha256=sha256(target),
                       scene_sha256=sha256(scene_path), frames=result["frames"], revision=result["revision"],
                       capture_frames=result["frames"], capture_revision=result["revision"],
                       scene_frames=scene["frames"], scene_revision=scene["revision"])
        sidecar["sha256"] = sidecar["png_sha256"]
        target.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
        return target, sidecar
    import time
    time.sleep(settle)
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
