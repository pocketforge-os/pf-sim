from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from threading import Event
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import run_dir, safe_child, sim_home
from .automation import AutomationClient, AutomationError, AutomationTimeout


def sha256(png: str | Path) -> str:
    return hashlib.sha256(Path(png).read_bytes()).hexdigest()


def is_blank(png: str | Path) -> bool:
    with Image.open(png) as image:
        colors = image.convert("RGB").getcolors(maxcolors=2)
        return colors is not None and len(colors) <= 1


def scene_body(scene: dict) -> dict:
    """Return the semantic scene response without presentation counters."""
    return {key: value for key, value in scene.items() if key not in {"frames", "revision"}}


def scene_body_sha256(scene: dict) -> str:
    encoded = json.dumps(scene_body(scene), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_idle_timeout(error: AutomationError) -> bool:
    return isinstance(error, AutomationTimeout) or "timeout" in str(error).lower()


def _content_stable(client: AutomationClient, quiet_ms: int, timeout_ms: int) -> tuple[float, float]:
    started = time.monotonic()
    deadline = started + timeout_ms / 1000
    previous = client.scene()
    first_revision = previous.get("revision", 0)
    last_revision = first_revision
    waiter = Event()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("reason=capture_never_settled")
        waiter.wait(min(quiet_ms / 1000, remaining))
        current = client.scene()
        last_revision = current.get("revision", last_revision)
        if scene_body(previous) == scene_body(current):
            elapsed = max(time.monotonic() - started, 1e-9)
            return (last_revision - first_revision) / elapsed, deadline
        previous = current


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
        settled = "idle"
        revision_churn = False
        revision_rate_hz = 0.0
        try:
            # A churning presenter can never satisfy wait_idle. Bound the fast-path
            # probe so the content-stability fallback remains useful interactively;
            # timeout_ms still bounds the subsequent settling search.
            client.wait_idle(quiet_ms, min(timeout_ms, 1000))
        except AutomationError as error:
            if not _is_idle_timeout(error):
                raise
            settled = "content-stable"
            revision_churn = True
            revision_rate_hz, deadline = _content_stable(client, quiet_ms, timeout_ms)

        for attempt in range(3):
            if attempt and not revision_churn:
                client.wait_idle(quiet_ms, timeout_ms)
            if revision_churn and time.monotonic() >= deadline:
                raise RuntimeError("reason=capture_never_settled")
            result = client.capture(target)
            scene = client.scene()
            if revision_churn:
                confirming_scene = client.scene()
                if scene_body(scene) == scene_body(confirming_scene):
                    break
            elif (result["frames"], result["revision"]) == (scene["frames"], scene["revision"]):
                break
        else:
            reason = "capture_never_settled" if revision_churn else "capture_frame_drift"
            raise RuntimeError(f"reason={reason}")
        scene_path = target.with_suffix(".scene.json")
        scene_path.write_text(json.dumps(scene, indent=2, sort_keys=True) + "\n")
        sidecar = {key: meta.get(key) for key in ("instance", "profile", "scale", "contrast", "launcher_rev", "runtime_rev", "display")}
        sidecar.update(captured_at=datetime.now(timezone.utc).isoformat(), png_sha256=sha256(target),
                       scene_sha256=sha256(scene_path), frames=result["frames"], revision=result["revision"],
                       capture_frames=result["frames"], capture_revision=result["revision"],
                       scene_frames=scene["frames"], scene_revision=scene["revision"],
                       scene_body_sha256=scene_body_sha256(scene), settled=settled,
                       revision_churn=revision_churn, revision_rate_hz=revision_rate_hz)
        sidecar["sha256"] = sidecar["png_sha256"]
        target.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
        return target, sidecar
    # tsp-ihne1.56.5: the host-desktop raw branch (window activation plus an
    # X dump of the compositor window) is deleted. Raw capture only reads the
    # instance's own headless compositor socket; the automation route above
    # already captures the exact instance and stays the supported path.
    if meta["display"] != "headless":
        raise RuntimeError("reason=raw_capture_requires_headless")
    time.sleep(settle)
    with tempfile.TemporaryDirectory() as temporary:
        cwd = Path(temporary)
        env = os.environ.copy(); env["WAYLAND_DISPLAY"] = meta["weston_socket"]
        env["XDG_RUNTIME_DIR"] = meta["xdg_runtime_dir"]
        subprocess.run(["weston-screenshooter"], cwd=cwd, env=env, check=True)
        shots = sorted(cwd.glob("wayland-screenshot-*.png"))
        if not shots: raise RuntimeError("reason=screenshot_missing")
        shutil.move(shots[-1], target)
    sidecar = {key: meta.get(key) for key in ("instance", "profile", "scale", "contrast", "launcher_rev", "runtime_rev", "display")}
    sidecar.update(captured_at=datetime.now(timezone.utc).isoformat(), sha256=sha256(target))
    target.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    return target, sidecar
