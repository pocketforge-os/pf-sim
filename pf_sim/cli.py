from __future__ import annotations

import argparse
import json
import sys

from .backend import DesktopBackend
from .config import run_dir
from . import doctor, toolchain


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
        if name == "status": command.add_argument("--json", action="store_true")
    tools = commands.add_parser("toolchain").add_subparsers(dest="toolchain_command", required=True)
    build = tools.add_parser("build"); build.add_argument("--force", action="store_true")
    build.add_argument("--backend", choices=["desktop"], default="desktop")
    status = tools.add_parser("status"); status.add_argument("--json", action="store_true")
    status.add_argument("--backend", choices=["desktop"], default="desktop")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor": return doctor.run()
        if args.command == "toolchain":
            if args.toolchain_command == "build":
                print(json.dumps(toolchain.build(args.force), sort_keys=True)); return 0
            manifest = toolchain.read_manifest()
            if manifest is None:
                print("toolchain_status=absent", file=sys.stderr); return 3
            print(json.dumps(manifest, indent=2 if args.json else None, sort_keys=True)); return 0
        impl = backend(args.backend)
        if args.command == "up":
            path = impl.up(instance=args.instance, display=args.display, replace=args.replace, shell_bin=args.shell_bin, authorityd_bin=args.authorityd_bin)
            print(f"up_status=ready instance={args.instance} display={args.display} run_dir={path} weston_socket=pf-sim-{args.instance}")
            return 0
        if args.command == "down":
            stopped = impl.down(args.instance)
            print(f"down_status={'stopped' if stopped else 'not_running'} instance={args.instance}"); return 0
        result = impl.status(args.instance)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else " ".join([f"status={result['state']}", f"instance={args.instance}"] + [f"{n}={'alive' if v['alive'] else 'dead'}" for n, v in result['components'].items()]))
        return {"up": 0, "down": 3, "degraded": 4}[result["state"]]
    except RuntimeError as error:
        reason = str(error)
        hint = ""
        if "_died" in reason and args.command == "up":
            component = reason.split("reason=", 1)[-1].removesuffix("_died")
            hint = f" hint={run_dir(args.instance) / 'logs' / (component + '.log')}"
        print(f"up_status=failed {reason}{hint}", file=sys.stderr)
        return 1
