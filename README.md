# pf-sim

`pf-sim` is PocketForge’s reproducible, off-device GUI development loop for the real revision-pinned launcher shell: it supplies named state, controller-shaped input, deterministic fixture sessions, frame-complete captures, scenarios, and measured evidence without pretending a desktop compositor is handheld hardware.

`pf-sim` complements [`pocketforge-os/sim`](https://github.com/pocketforge-os/sim), the honest-mock app/runtime gate. Neither replaces the launcher’s offscreen evidence suite or its hardware acceptance gate. Launcher and runtime source are never vendored here: `pins.toml` names the launcher revision, the runtime revision is derived from it, and generated binaries remain under `PF_SIM_HOME`.

## Quickstart

Python 3.10+ and the dependencies reported by `doctor` are required. The wrapper resolves its own checkout, so it works from any directory and may be symlinked into `~/.local/bin`.

```sh
/path/to/pf-sim/pf-simctl toolchain build
XDG_RUNTIME_DIR=/run/user/$(id -u) /path/to/pf-sim/pf-simctl doctor
/path/to/pf-sim/pf-simctl up --display headless
/path/to/pf-sim/pf-simctl input action Search.open
/path/to/pf-sim/pf-simctl text sun
/path/to/pf-sim/pf-simctl capture search-sun
/path/to/pf-sim/pf-simctl down --reap-orphans
```

Machine-local state defaults to `~/.local/state/pf-sim`; set `PF_SIM_HOME` to isolate it. See the canonical [GUI development loop](docs/gui-dev-loop.md) and [CI integration guide](docs/ci-integration.md).
