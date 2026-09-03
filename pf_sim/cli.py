from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .backend import DesktopBackend
from .config import run_dir, validate_instance, validate_name
from . import audit, capture, doctor, gamepad, inputs, keys, matrix, profiles, scenario, toolchain
from . import measure
from .config import repo_root, safe_child, sim_home
from .automation import AutomationClient
from .authority import AuthorityClient
from .fixture_app import fixture_config, send_command
from .supervisor import hook


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
            command.add_argument("--no-gamepad", action="store_true")
        if name == "status": command.add_argument("--json", action="store_true")
    tools = commands.add_parser("toolchain").add_subparsers(dest="toolchain_command", required=True)
    build = tools.add_parser("build"); build.add_argument("--force", action="store_true")
    build.add_argument("--launcher-rev")
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
    cap = commands.add_parser("capture", help="frame-complete shell capture")
    cap.add_argument("name"); cap.add_argument("--instance", default="default"); cap.add_argument("--settle", type=float, default=.5)
    cap.add_argument("--raw", action="store_true"); cap.add_argument("--quiet-ms", type=int, default=150)
    cap.add_argument("--timeout-ms", type=int, default=5000); cap.add_argument("--repeat", type=int, default=1)
    measuring = commands.add_parser("measure", help="measure a capture, or diff two captures")
    measuring.add_argument("target"); measuring.add_argument("other", nargs="?"); measuring.add_argument("second", nargs="?")
    measuring.add_argument("--scene", type=Path); measuring.add_argument("--other-scene", type=Path)
    measuring.add_argument("--nodes"); measuring.add_argument("--role")
    measuring.add_argument("--min-gap", type=int, default=0); measuring.add_argument("--contrast-floor", type=float, default=4.5)
    measuring.add_argument("--out", type=Path); measuring.add_argument("--instance", default="default")
    measuring.add_argument("--no-fail", action="store_true")
    audits = commands.add_parser("audit").add_subparsers(dest="audit_command", required=True)
    audit_run = audits.add_parser("run"); audit_run.add_argument("path", type=Path)
    text_command = commands.add_parser("text")
    text_command.add_argument("value", nargs="?", default=""); text_command.add_argument("--clear", action="store_true")
    text_command.add_argument("--instance", default="default")
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
    for command in (press, hold, action, sequence):
        command.add_argument("--no-wait", action="store_true")
    listing = input_commands.add_parser("list"); listing.add_argument("--instance", default="default")
    for name in ("launch", "safe-return", "history"):
        command = commands.add_parser(name); command.add_argument("--instance", default="default")
        if name == "launch": command.add_argument("item_id")
        if name == "history": command.add_argument("--json", action="store_true")
    app = commands.add_parser("app").add_subparsers(dest="app_command", required=True)
    for name in ("status", "exit", "crash", "quit", "list"):
        command = app.add_parser(name); command.add_argument("--instance", default="default")
        if name == "exit": command.add_argument("code", type=int)
    app_hook = commands.add_parser("app-hook")
    app_hook.add_argument("hook_command", choices=("launch", "stop", "kill", "activate")); app_hook.add_argument("values", nargs="*")
    app_hook.add_argument("--run-dir", required=True, type=Path)
    scenarios = commands.add_parser("scenario").add_subparsers(dest="scenario_command", required=True)
    scenarios.add_parser("list").add_argument("--dir", type=Path, default=Path("scenarios"))
    scenario_validate = scenarios.add_parser("validate"); scenario_validate.add_argument("file", type=Path)
    scenario_run = scenarios.add_parser("run"); scenario_run.add_argument("file", type=Path)
    scenario_run.add_argument("--repeat", type=int, default=1); scenario_run.add_argument("--out", type=Path)
    scenario_run.add_argument("--instance", default="default"); scenario_run.add_argument("--keep-instance", action="store_true")
    matrices = commands.add_parser("matrix").add_subparsers(dest="matrix_command", required=True)
    matrix_run = matrices.add_parser("run"); matrix_run.add_argument("file", type=Path)
    matrix_run.add_argument("--only"); matrix_run.add_argument("--out", type=Path)
    matrix_run.add_argument("--jobs", type=int, default=1); matrix_run.add_argument("--repeat", type=int, default=1)
    matrix_run.add_argument("--no-fail", action="store_true")
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
        elif args.command == "launch":
            validate_name("item", args.item_id)
        elif args.command == "measure":
            if args.target != "diff" and not args.target.lower().endswith(".png"):
                validate_name("capture", args.target)
            if args.target == "diff":
                if args.other is None or args.second is None: raise ValueError("reason=diff_requires_two_captures")
                for value in (args.other, args.second):
                    if not value.lower().endswith(".png"): validate_name("capture", value)
        elif args.command == "audit":
            validate_name("audit", args.path.stem)
            if not args.path.resolve().is_relative_to((repo_root() / "audits").resolve()):
                raise ValueError("reason=invalid_audit")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        if args.command == "matrix":
            if args.jobs != 1: raise ValueError("reason=unsupported_matrix_jobs")
            spec = matrix.load(args.file)
            code, report, out = matrix.run(spec, only=matrix.parse_only(args.only), out=args.out,
                                           repeat=args.repeat, no_fail=args.no_fail)
            status = "pass" if code == 0 else "fail"
            print(f"matrix_status={status} cells={report['cell_count']} skipped={report['skipped']} failed={report['failed']} out={out}"
                  + (f" deterministic={str(report['deterministic']).lower()}" if args.repeat > 1 else ""))
            return code
        if args.command == "scenario":
            if args.scenario_command == "list":
                try: items = scenario.list_scenarios(args.dir)
                except ValueError as error: print(str(error), file=sys.stderr); return 2
                for item in items: print(f"scenario={item.name} description={item.description}")
                return 0
            try: item = scenario.load(args.file)
            except ValueError as error: print(str(error), file=sys.stderr); return 2
            if args.scenario_command == "validate": print(f"validate_status=ok scenario={item.name}"); return 0
            code, report, _ = scenario.run(item, args.repeat, args.out, args.instance, args.keep_instance)
            print(f"scenario_status={report['status']} deterministic={str(report['deterministic']).lower()} runs={args.repeat}")
            return code
        if args.command == "doctor": return doctor.run()
        if args.command == "measure":
            capture_root = safe_child(sim_home() / "captures", "instance", args.instance)
            def resolve(value: str) -> Path:
                candidate = Path(value)
                if candidate.suffix.lower() == ".png": return candidate.resolve()
                name = validate_name("capture", value)
                return capture_root / f"{name}.png"
            if args.target == "diff":
                a, b = resolve(args.other), resolve(args.second)
                out = args.out.resolve() if args.out else capture_root / f"{a.stem}-{b.stem}.diff"
                value = measure.run_diff(a, b, args.scene or a.with_suffix(".scene.json"),
                                         args.other_scene or b.with_suffix(".scene.json"), out)
                print(f"diff_status=ok moved_nodes={','.join(value['moved_nodes'])} out={out}"); return 0
            png = resolve(args.target); scene_path = args.scene.resolve() if args.scene else png.with_suffix(".scene.json")
            node_ids = None
            if args.nodes:
                node_ids = {validate_name("node", item) for item in args.nodes.split(",") if item}
            out = args.out.resolve() if args.out else png.parent / f"{png.stem}.measure"
            value = measure.run(png, scene_path, out, node_ids=node_ids, role=args.role,
                                min_gap=args.min_gap, contrast_floor=args.contrast_floor)
            print(f"measure_status={value['status'].lower()} out={out}")
            return 1 if value["status"] == "FAIL" and not args.no_fail else 0
        if args.command == "audit":
            status, values = audit.run(args.path.resolve())
            print(json.dumps(values, sort_keys=True))
            for value in values:
                print(f"phase={value['phase']} mode={value['mode']} reproduced={value['reproduced']}"
                      + (f" reason={value['reason']}" if value['mode'] == 'unreproducible' else ""))
            print(f"audit_status={status}")
            return 0 if status in ("reproduced", "partial") else 1
        if args.command == "app-hook":
            request = {"command": args.hook_command}
            if args.hook_command == "launch":
                if len(args.values) != 2: raise ValueError("reason=invalid_hook_arguments")
                request.update(item_id=validate_name("item", args.values[0]), session_id=validate_name("session", args.values[1]))
            elif args.hook_command in ("stop", "kill"):
                if len(args.values) != 1: raise ValueError("reason=invalid_hook_arguments")
                request["session_id"] = validate_name("session", args.values[0])
            elif args.values: raise ValueError("reason=invalid_hook_arguments")
            response = hook(args.run_dir.resolve() / "supervisor.sock", request)
            return 0 if response.get("status") in ("ok", "not_running") else 1
        if args.command == "app" and args.app_command == "list":
            items = json.loads((Path(__file__).parent.parent / "fixtures/catalog-snapshot.json").read_text())["items"]
            print("\n".join(f"item={i['id']} behaviour={fixture_config(i['id'])['behaviour']}" for i in items))
            return 0
        if args.command in ("launch", "safe-return", "history", "app"):
            path = run_dir(args.instance); client = AuthorityClient(path / "session-authority.sock")
            if args.command == "launch":
                result = client.launch(args.item_id); status = result.get("result")
                print(f"launch_status={'ok' if status == 'accepted' else status}"
                      + (f" session={result['session_id']}" if "session_id" in result else ""))
                return 0 if status == "accepted" else 1
            if args.command == "safe-return": client.safe_return(); print("safe_return_status=ok"); return 0
            entries = client.history()
            if args.command == "history":
                print(json.dumps(entries, indent=2, sort_keys=True) if args.json else "\n".join(_history_line(e) for e in entries)); return 0
            active = next((e for e in reversed(entries) if e.get("receipt") is None), None)
            if active is None: print("app_status=none"); return 3 if args.app_command == "status" else 1
            session = validate_name("session", active["session_id"])
            socket_path = path / "apps" / (session + ".sock")
            marker = path / "authority/sessions" / (session + ".running")
            if args.app_command == "status":
                state = "running" if socket_path.exists() else "launching" if marker.exists() or active else "none"
                print(f"app_status={state} session={session} item={active.get('item_id', '')}"); return 0
            response = send_command(socket_path, {"command": args.app_command, **({"code": args.code} if args.app_command == "exit" else {})})
            print(f"app_status={args.app_command} session={session}"); return 0
        if args.command == "toolchain":
            if args.toolchain_command == "build":
                print(json.dumps(toolchain.build(args.force, args.launcher_rev), sort_keys=True)); return 0
            manifest = toolchain.read_manifest()
            if manifest is None:
                print("toolchain_status=absent", file=sys.stderr); return 3
            print(json.dumps(manifest, indent=2 if args.json else None, sort_keys=True)); return 0
        if args.command == "profile":
            if args.profile_command == "list":
                items = [{"name": p.name, "description": p.description, "source": p.source} for p in profiles.list_profiles()]
                print(json.dumps(items, indent=2) if args.json else "\n".join(f"profile={p['name']} source={p['source']} description={p['description']}" for p in items)); return 0
            if args.profile_command == "show":
                p = profiles.resolve_profile(args.name); print(json.dumps({"name": p.name, "description": p.description, "source": p.source, "authority": p.authority, "supervisor": p.supervisor, "text_scale": p.text_scale, "high_contrast": p.high_contrast, "first_run_complete": p.first_run_complete}, indent=2)); return 0
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
            if args.repeat < 1: raise ValueError("reason=invalid_repeat")
            results = [capture.capture(args.name, args.instance, args.settle, raw=args.raw,
                       quiet_ms=args.quiet_ms, timeout_ms=args.timeout_ms) for _ in range(args.repeat)]
            path, sidecar = results[-1]
            deterministic = len({(item[1]["sha256"], item[1].get("scene_body_sha256")) for item in results}) == 1
            suffix = f" deterministic={str(deterministic).lower()}" if args.repeat > 1 else ""
            settled = f" settled={sidecar['settled']}" if "settled" in sidecar else ""
            print(f"capture_status=ok path={path} sha256={sidecar['sha256']} frames={sidecar.get('frames', 'raw')} revision={sidecar.get('revision', 'raw')}{settled}{suffix}"); return 0
        if args.command == "text":
            result = AutomationClient(run_dir(args.instance) / "automation.sock").text("" if args.clear else args.value)
            print(f"text_status=ok frames={result['frames']} revision={result['revision']}"); return 0
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
            if not args.no_wait:
                AutomationClient(run_dir(args.instance) / "automation.sock").wait_idle()
            print("input_status=ok")
            return 0
        impl = backend(args.backend)
        if args.command == "up":
            selected = profiles.resolve_profile(args.profile)
            path = impl.up(instance=args.instance, display=args.display, replace=args.replace, shell_bin=args.shell_bin, authorityd_bin=args.authorityd_bin,
                           profile=selected, scale=args.scale, contrast=args.contrast, no_gamepad=args.no_gamepad)
            source = "wayland-keyboard" if args.no_gamepad else "evdev"
            automation = "down" if args.no_gamepad else "ready"
            print(f"up_status=ready instance={args.instance} display={args.display} run_dir={path} weston_socket=pf-sim-{args.instance} input_source={source} automation={automation}")
            return 0
        if args.command == "down":
            stopped = impl.down(args.instance)
            print(f"down_status={'stopped' if stopped else 'not_running'} instance={args.instance}"); return 0
        result = impl.status(args.instance)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else " ".join(
            [f"status={result['state']}", f"instance={args.instance}", f"automation={result.get('automation', 'down')}"]
            + [f"{n}={'alive' if v['alive'] else 'dead'}" for n, v in result['components'].items()]))
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


def _history_line(entry: dict) -> str:
    receipt = entry.get("receipt")
    if isinstance(receipt, dict): receipt = receipt.get("kind", next(iter(receipt), "none"))
    return f"session={entry.get('session_id', '')} item={entry.get('item_id', '')} receipt={receipt or 'open'}"
