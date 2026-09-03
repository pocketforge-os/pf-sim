# pf-sim — PocketForge virtual device simulator for GUI dev/test

`pf-sim` is the ONE sanctioned virtual-device loop for developing and testing the PocketForge
shell (`pf-shell`) off-hardware: the same shell binary, the same input map, the same guard suite,
driven interactively by an agent session, scriptably by CI, and later backed by the QEMU machine.

It packages the desktop rig as committed infrastructure-as-code: `pf-simctl up/down/status`,
named state profiles, controller-shaped input through a virtual gamepad, frame-complete captures
with scene JSON, scripted scenarios, controllable fixture apps, and a measure package that turns
captures into reviewable pass/fail audit reports.

**Relationship to [`pocketforge-os/sim`](https://github.com/pocketforge-os/sim):** `sim` is the
E5 honest-mock CI gate that runs the identical arm64 OCI app under `qemu-tsp` against a
descriptor-synthesized device. `pf-sim` complements it: it is the interactive GUI-development rig
for the shell itself. Neither replaces the other, and neither replaces the launcher repo's offscreen
evidence suite.

**Provenance rule:** launcher and runtime code is never vendored here. `pf-sim` consumes
`pocketforge-os/launcher` (and its pinned `runtime` rev) by rev pin or built artifact only.

Epic: `tsp-tcew` in `pocketforge-os/mission-control`.

## Quickstart

Python 3.10 or newer is required. Diagnose the host, build the revision-pinned launcher/runtime
toolchain, and start a fresh headless instance:

```sh
./pf-simctl doctor
./pf-simctl toolchain build
./pf-simctl up --display headless
./pf-simctl status --json
./pf-simctl down
```

Set `PF_SIM_HOME` to relocate machine-local state (the default is
`~/.local/state/pf-sim`). Use `--display windowed` when `DISPLAY` is available.

## Profiles

Committed profiles make first-run, normal seeded, and unavailable-authority states repeatable
without navigating the Settings UI. The default is `seeded-default`:

```sh
./pf-simctl profile list
./pf-simctl profile show first-run
./pf-simctl profile apply first-run
./pf-simctl profile apply seeded-default --scale 200 --contrast hc
./pf-simctl capture seeded-200-hc
```

`--scale 100|150|200` and `--contrast default|hc` compose with every profile. The
`power-status-present` and `controller-battery-low` profiles provide deterministic sysfs-backed
device status without exposing the host laptop's battery. This provides all
six visual presets by deterministic state writes rather than keying through Settings. `profile
snapshot NAME` saves sanitized state under `$PF_SIM_HOME/profiles/NAME`; `profile validate
NAME_OR_PATH` rejects live markers, sockets, and locks.

`capture NAME` waits for the shell's presented frame, asks the shell to capture that exact composed
frame, then writes `NAME.png`, `NAME.scene.json`, and an audited metadata sidecar. Use
`capture --repeat 2 NAME` to check byte determinism. `capture --raw NAME` is the legacy compositor
screenshot fallback. The raw `key KEYSYM...` fallback works only with `up --no-gamepad` in a
windowed Weston session.

## Input

pf-sim presents a Linux virtual gamepad so the shell receives the same evdev button codes and
uses the same `pf-input-map` bindings as the physical device. This avoids desktop key-symbol
stand-ins whose labels and behavior differ from the handheld controls. The device contract is
not copied into this repository: `toolchain build` copies `device.json` from the revision-pinned
launcher checkout into `$PF_SIM_HOME/toolchain/device-contract.json` and records its SHA-256 in
the toolchain manifest.

`up` creates the gamepad and connects it as the shell's only action source. Input commands wait for
the resulting frame by default (`--no-wait` is available for deliberately batched input). Inspect
controls and send controller-shaped input with:

```sh
./pf-simctl gamepad status [--instance default] [--json]
./pf-simctl input list
./pf-simctl input press east A BTN_EAST --hold-ms 60 --gap-ms 120
./pf-simctl input hold south --ms 500
./pf-simctl input action Move.down --context shell
./pf-simctl input seq "east Move.down south"
./pf-simctl input action Search.open
./pf-simctl text sun
./pf-simctl capture search-sun
./pf-simctl text --clear
./pf-simctl input action Move.down
```

The holder owns `/dev/uinput` and serves commands through the instance's `gamepad.sock`; the
device disappears when the holder exits. On CI or a host without a user ACL, enable access before
running tests with `sudo modprobe uinput && sudo chmod 666 /dev/uinput`. CI sets
`PF_SIM_REQUIRE_UINPUT=1`, making unavailable uinput support a failure rather than a skip.
Text entry uses the automation seam because the simulated device has no on-device keyboard;
`text --clear` clears the Search query.

## Layout

- `pf_sim/` contains the CLI, lifecycle supervisor, backend abstraction, and toolchain builder.
- `pins.toml` is the source-of-truth launcher revision; the runtime revision is derived from it.
- `fixtures/` contains simulator-owned catalog data.
- `profiles/` contains committed state-only simulator profiles.
- `tests/` contains hermetic `unittest` coverage and fake lifecycle components.
- `$PF_SIM_HOME/` holds generated binaries, run state, snapshots, and captures.

## Scenarios

TOML scenarios turn GUI flows into reviewable evidence. List and validate committed
scenarios, or run one repeatedly to compare every step's frame:

```sh
./pf-simctl scenario list
./pf-simctl scenario validate scenarios/search-filter.toml
./pf-simctl scenario run scenarios/launch-safe-return.toml --repeat 2
```

Each file has a `[scenario]` table (`name`, `description`, `profile`, `scale`, and
`contrast`) followed by `[[steps]]`. Supported operations are `profile`, `input`,
`text`, `launch`, `safe_return`, `app`, `wait_for`, `capture`, `assert`, and `sleep`.
Generated evidence lives under `$PF_SIM_HOME/scenarios/SCENARIO/`: each run has one
directory per step containing its PNG, `scene.json`, and `step.json`, with aggregate
`report.json` and `report.md` files at the scenario root. `sleep` is supported for
diagnostics but is called out as a report smell; prefer `wait_for` predicates.
Profile steps restart and reseed the shell; place them before navigation and repeat
navigation after each profile change. `home-matrix.toml` covers all six visual presets
on the gamepad-reachable Home route. Settings is not currently reachable through the
launcher's bound gamepad contract, so the runner does not use a private shortcut.
## Fixture apps and sessions

Every shipped profile uses pf-sim's session supervisor by default. Launch a deterministic
Wayland fixture without navigating the shell, inspect it, and exercise clean or crash
receipts through the same session-authority protocol used by the device:

```sh
./pf-simctl up --profile seeded-default
./pf-simctl launch ridgeline
./pf-simctl app status
./pf-simctl app crash
./pf-simctl history --json
./pf-simctl launch hollow-tides
./pf-simctl safe-return
```

`app list` prints fixture behaviours. Files in `fixtures/apps/` select `stay`,
`exit:<code>`, `crash`, or `instant-exit`, an optional launch delay, and a 1280×720
test pattern shown by `weston-image`. Set `[stack] supervisor = "shell"` in a custom
profile only when checking parity with the launcher's desktop-sim supervisor.
