# GUI development loop

The complete GUI workflow will land in P5. For now, the desktop simulator lifecycle is:

```sh
./pf-simctl doctor
./pf-simctl toolchain build
./pf-simctl up --display headless
./pf-simctl profile apply seeded-default --scale 150 --contrast default
./pf-simctl input action Search.open
./pf-simctl text sun
./pf-simctl capture current-screen
./pf-simctl text --clear
./pf-simctl input action Move.down
./pf-simctl status --json
./pf-simctl down
```

Use `--display windowed` from a desktop session when interactive viewing is needed.

Input travels through the virtual evdev gamepad and the launcher's real `pf-input-map`; each input
verb waits until the resulting shell frame is presented. Search text uses the automation-only
`text VALUE`/`text --clear` path because no on-device keyboard exists.

Use `profile apply` and the scale/contrast flags instead of driving Settings with keys. Alongside
the existing states, `power-status-present` and `controller-battery-low` render deterministic fake
power-supply trees. A normal capture is frame-complete and emits a PNG, verbatim `.scene.json`, and
metadata sidecar with frame/revision and content hashes. `capture --repeat 2 NAME` checks raster
determinism; `--raw` retains the old time-based compositor fallback.
## Deterministic session states

Use fixture sessions when a screenshot must capture a state rather than a timing
accident. `launch ridgeline` deliberately spends 1.5 seconds in `launching` before its
marker appears; it then stays in-app until an app verb or safe return ends it. Capture
the launch-dimmed state immediately after launch and poll `app status` for `running`
before capturing the in-app pattern.

`app quit` produces a clean return, `safe-return` exercises the authority's graceful
return path, and `app crash` terminates the fixture by SIGSEGV. The supervisor reports
running, terminal status, unit inactive, target released, selected owner active, and
presentation acknowledged in launcher order. Confirm the durable result with
`history --json`; crash sessions have a `Crash` receipt and safe returns have a
`Returned` receipt. These controls make launch, dim, in-app, return, and crash frames
repeatable in both headless and windowed loops.
