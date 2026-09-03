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

The simulator user must be able to read the udev-created `/dev/input/event*` node. A
desktop login normally grants this through systemd-logind's `uaccess` ACL. When running
outside a logind seat session, add the user to the `input` group and start a new login
session:

```sh
sudo usermod -aG input "$USER"
```

For CI or another intentionally shared simulator host, install this narrowly matched
udev rule, then reload it:

```sh
echo 'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="pocketforge-sim-gamepad:*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-pf-sim-gamepad.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input
```

Thus the supported access routes are a logind seat `uaccess` ACL, `input` group
membership, or the narrowly matched udev rule. `pf-simctl doctor` creates a temporary
gamepad and reports `event_node_access=ok|unreadable` from its actual event node (or
`unknown` when `/dev/uinput` is not writable); `gamepad create` also fails with a direct
remediation hint if the actual node is unreadable.

Input travels through the virtual evdev gamepad and the launcher's real `pf-input-map`; each input
verb waits until the resulting shell frame is presented. Search text uses the automation-only
`text VALUE`/`text --clear` path because no on-device keyboard exists.

Use `profile apply` and the scale/contrast flags instead of driving Settings with keys. Alongside
the existing states, `power-status-present` and `controller-battery-low` render deterministic fake
power-supply trees. A normal capture is frame-complete and emits a PNG, verbatim `.scene.json`, and
metadata sidecar with frame/revision and content hashes. `capture --repeat 2 NAME` checks raster
and semantic-scene determinism; `--raw` retains the old time-based compositor fallback. Capture
normally reports `settled=idle`. If the shell continuously re-presents an unchanged scene (the
known `degraded-authority` case), capture falls back to bounded content-stability sampling and
reports `settled=content-stable`, `revision_churn=true`, and the observed revision rate in its
metadata sidecar.
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

## Scenario files and determinism

A scenario is TOML with a `[scenario]` header and ordered `[[steps]]`. Input steps use
the `input seq` grammar; `wait_for` and `assert` accept `focused_label`, `focused_id`,
`label_present`, `label_absent`, `route`, `search_query`, `result_count`,
`session_state`, `last_receipt`, and `app_state` predicates. `wait_for` polls the
automation idle seam and current scene/session history until its bounded timeout.

`scenario run FILE --repeat N` starts a replaced headless instance for each run,
unless `--keep-instance` is requested. Every completed step produces a frame and
semantic scene in `scenarios/NAME/run-NNN/NN-op/`; `step.json` records timing, output,
and errors. A failure marks later steps skipped. The root reports include a step table,
capture hashes, and every discouraged `sleep` step. Repeats are deterministic only
when the corresponding capture SHA-256 is identical in every run.
