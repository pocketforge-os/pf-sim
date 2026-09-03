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
