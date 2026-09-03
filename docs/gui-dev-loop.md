# GUI development loop

The complete GUI workflow will land in P5. For now, the desktop simulator lifecycle is:

```sh
./pf-simctl doctor
./pf-simctl toolchain build
./pf-simctl up --display headless
./pf-simctl profile apply seeded-default --scale 150 --contrast default
./pf-simctl capture current-screen
./pf-simctl status --json
./pf-simctl down
```

Use `--display windowed` from a desktop session when interactive viewing is needed.

Use `profile apply` and the scale/contrast flags instead of driving Settings with keys. The shipped
states are `first-run`, `seeded-default`, and `degraded-authority`; `profile list` also includes local
snapshots. P1 captures are raw: their settle delay is time-based, not frame synchronization.
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
