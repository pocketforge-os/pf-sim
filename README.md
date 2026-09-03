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

`--scale 100|150|200` and `--contrast default|hc` compose with every profile. This provides all
six visual presets by deterministic state writes rather than keying through Settings. `profile
snapshot NAME` saves sanitized state under `$PF_SIM_HOME/profiles/NAME`; `profile validate
NAME_OR_PATH` rejects live markers, sockets, and locks. `capture` is raw and not frame-synchronized.
The raw `key KEYSYM...` fallback works only for windowed Weston; controller input arrives in P2.

## Layout

- `pf_sim/` contains the CLI, lifecycle supervisor, backend abstraction, and toolchain builder.
- `pins.toml` is the source-of-truth launcher revision; the runtime revision is derived from it.
- `fixtures/` contains simulator-owned catalog data.
- `profiles/` contains committed state-only simulator profiles.
- `tests/` contains hermetic `unittest` coverage and fake lifecycle components.
- `$PF_SIM_HOME/` holds generated binaries, run state, snapshots, and captures.
