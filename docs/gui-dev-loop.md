# GUI development loop

The complete GUI workflow will land in P5. For now, the desktop simulator lifecycle is:

```sh
./pf-simctl doctor
./pf-simctl toolchain build
./pf-simctl up --display headless
./pf-simctl status --json
./pf-simctl down
```

Use `--display windowed` from a desktop session when interactive viewing is needed.
