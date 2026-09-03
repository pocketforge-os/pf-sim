from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .backend import DesktopBackend
from .config import run_dir, validate_instance, validate_name
from . import capture, doctor, gamepad, inputs, keys, profiles, toolchain


def backend(name: str):
    if name == "desktop": return DesktopBackend()
    raise ValueError(name)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pf-simctl")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("up", "down", "status", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("--backend", choices=["desktop"], default="desktop")
        if name in ("up", "down", "status"): command.add_argument("--instance", default="default")
        if name == "up":
            command.add_argument("--display", choices=["headless", "windowed"], default="headless")
            command.add_argument("--replace", action="store_true")
            command.add_argument("--shell-bin")
            command.add_argument("--authorityd-bin")
            command.add_argument("--profile", default="seeded-default")
            command.add_argument("--scale", choices=profiles.SCALES)
            command.add_argument("--contrast", choices=("default", "hc"))
        if name == "status": command.add_argument("--json", action="store_true")
    tools = commands.add_parser("toolchain").add_subparsers(dest="toolchain_command", required=True)
    build = tools.add_parser("build"); build.add_argument("--force", action="store_true")
    build.add_argument("--backend", choices=["desktop"], default="desktop")
    status = tools.add_parser("status"); status.add_argument("--json", action="store_true")
    status.add_argument("--backend", choices=["desktop"], default="desktop")
    profile = commands.add_parser("profile").add_subparsers(dest="profile_command", required=True)
    listing = profile.add_parser("list"); listing.add_argument("--json", action="store_true")
    show = profile.add_parser("show"); show.add_argument("name")
    validate = profile.add_parser("validate"); validate.add_argument("name")
    apply = profile.add_parser("apply"); apply.add_argument("name"); apply.add_argument("--instance", default="default")
    apply.add_argument("--scale", choices=profiles.SCALES); apply.add_argument("--contrast", choices=("default", "hc"))
    snapshot = profile.add_parser("snapshot"); snapshot.add_argument("name"); snapshot.add_argument("--instance", default="default")
    cap = commands.add_parser("capture", help="raw, non-frame-synchronized P1 capture")
    cap.add_argument("name"); cap.add_argument("--instance", default="default"); cap.add_argument("--settle", type=float, default=.5)
    key = commands.add_parser("key", help="raw windowed keyboard fallback")
    key.add_argument("keysyms", nargs="+"); key.add_argument("--instance", default="default"); key.add_argument("--delay", type=float, default=.35)
    pads = commands.add_parser("gamepad").add_subparsers(dest="gamepad_command", required=True)
    for name in ("create", "destroy", "status"):
        command = pads.add_parser(name)
        command.add_argument("--instance", default="default")
        if name == "status": command.add_argument("--json", action="store_true")
    input_commands = commands.add_parser("input").add_subparsers(dest="input_command", required=True)
    press = input_commands.add_parser("press")
    press.add_argument("control", nargs="+")
    press.add_argument("--instance", default="default")
    press.add_argument("--hold-ms", type=int, default=60)
    press.add_argument("--gap-ms", type=int, default=120)
    hold = input_commands.add_parser("hold")
    hold.add_argument("control"); hold.add_argument("--ms", type=int, required=True)
    hold.add_argument("--instance", default="default")
    action = input_commands.add_parser("action")
    action.add_argument("action"); action.add_argument("--context", choices=["shell", "library", "global"], default="shell")
    action.add_argument("--instance", default="default")
    sequence = input_commands.add_parser("seq")
    sequence.add_argument("tokens"); sequence.add_argument("--context", choices=["shell", "library", "global"], default="shell")
    sequence.add_argument("--instance", default="default")
    sequence.add_argument("--hold-ms", type=int, default=60); sequence.add_argument("--gap-ms", type=int, default=120)
    listing = input_commands.add_parser("list"); listing.add_argument("--instance", default="default")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if hasattr(args, "instance"):
        try:
            validate_instance(args.instance)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
    try:
        if args.command == "capture":
            validate_name("capture", args.name)
        elif args.command == "profile" and args.profile_command in ("show", "apply", "snapshot"):
            validate_name("profile", args.name)
        elif args.command == "profile" and args.profile_command == "validate" and not Path(args.name).is_dir():
            validate_name("profile", args.name)
        elif args.command == "up":
            validate_name("profile", args.profile)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        if args.command == "doctor": return doctor.run()
        if args.command == "toolchain":
            if args.toolchain_command == "build":
                print(json.dumps(toolchain.build(args.force), sort_keys=True)); return 0
            manifest = toolchain.read_manifest()
            if manifest is None:
                print("toolchain_status=absent", file=sys.stderr); return 3
            print(json.dumps(manifest, indent=2 if args.json else None, sort_keys=True)); return 0
        if args.command == "profile":
            if args.profile_command == "list":
                items = [{"name": p.name, "description": p.description, "source": p.source} for p in profiles.list_profiles()]
                print(json.dumps(items, indent=2) if args.json else "\n".join(f"profile={p['name']} source={p['source']} description={p['description']}" for p in items)); return 0
            if args.profile_command == "show":
                p = profiles.resolve_profile(args.name); print(json.dumps({"name": p.name, "description": p.description, "source": p.source, "authority": p.authority, "text_scale": p.text_scale, "high_contrast": p.high_contrast, "first_run_complete": p.first_run_complete}, indent=2)); return 0
            if args.profile_command == "validate":
                profiles.validate_profile(profiles.resolve_profile(args.name, allow_path=True)); print(f"validate_status=ok profile={args.name}"); return 0
            if args.profile_command == "snapshot":
                p = profiles.snapshot(args.name, run_dir(args.instance)); print(f"snapshot_status=ok profile={p.name} path={p.path}"); return 0
            p = profiles.resolve_profile(args.name); impl = backend("desktop"); impl.apply(args.instance, p, args.scale, args.contrast)
            effective = profiles.effective_prefs(p, args.scale, args.contrast)
            scale = (effective or {"textScale": p.text_scale})["textScale"].removesuffix("%")
            contrast = "hc" if (effective or {}).get("highContrast", p.high_contrast) else "default"
            print(f"apply_status=applied profile={p.name} scale={scale} contrast={contrast}"); return 0
        if args.command == "capture":
            path, sidecar = capture.capture(args.name, args.instance, args.settle)
            print(f"capture_status=ok path={path} sha256={sidecar['sha256']}"); return 0
        if args.command == "key":
            try: keys.send(args.keysyms, args.instance, args.delay)
            except RuntimeError as error:
                if str(error) == "reason=headless_input_arrives_in_p2":
                    print("key_status=unsupported reason=headless_input_arrives_in_p2"); return 2
                raise
            print(f"key_status=ok count={len(args.keysyms)}"); return 0
        if args.command == "gamepad":
            if args.gamepad_command == "create":
                result = gamepad.create(args.instance)
                print(f"gamepad_status=created event_node={result['event_node']}")
                return 0
            if args.gamepad_command == "destroy":
                print(f"gamepad_status={gamepad.destroy(args.instance)}")
                return 0
            result = gamepad.status(args.instance)
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"gamepad_status={result['state']} pid_alive={str(result['pid_alive']).lower()} node_present={str(result['node_present']).lower()}")
            return 0 if result["state"] == "up" else 3
        if args.command == "input":
            if args.input_command == "press":
                inputs.press(args.instance, args.control, args.hold_ms, args.gap_ms)
            elif args.input_command == "hold":
                inputs.hold(args.instance, args.control, args.ms)
            elif args.input_command == "action":
                inputs.action(args.instance, args.action, args.context)
            elif args.input_command == "seq":
                inputs.sequence(args.instance, args.tokens, args.context, args.hold_ms, args.gap_ms)
            else:
                print("POSITION\tLABEL\tCODE\tBOUND ACTIONS")
                for row in inputs.list_rows(): print("\t".join(row))
                return 0
            print("input_status=ok")
            return 0
        impl = backend(args.backend)
        if args.command == "up":
            selected = profiles.resolve_profile(args.profile)
            path = impl.up(instance=args.instance, display=args.display, replace=args.replace, shell_bin=args.shell_bin, authorityd_bin=args.authorityd_bin,
                           profile=selected, scale=args.scale, contrast=args.contrast)
            print(f"up_status=ready instance={args.instance} display={args.display} run_dir={path} weston_socket=pf-sim-{args.instance}")
            return 0
        if args.command == "down":
            stopped = impl.down(args.instance)
            print(f"down_status={'stopped' if stopped else 'not_running'} instance={args.instance}"); return 0
        result = impl.status(args.instance)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else " ".join([f"status={result['state']}", f"instance={args.instance}"] + [f"{n}={'alive' if v['alive'] else 'dead'}" for n, v in result['components'].items()]))
        return {"up": 0, "down": 3, "degraded": 4}[result["state"]]
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        reason = str(error)
        hint = ""
        if "_died" in reason and args.command == "up":
            component = reason.split("reason=", 1)[-1].removesuffix("_died")
            hint = f" hint={run_dir(args.instance) / 'logs' / (component + '.log')}"
        prefix = "up_status=failed" if args.command == "up" else "command_status=failed"
        print(f"{prefix} {reason}{hint}", file=sys.stderr)
        return 1
