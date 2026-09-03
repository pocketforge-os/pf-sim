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

## Measured audits

Run `pf-simctl measure CAPTURE` after a frame-complete capture. The overlay is the visual
index into the machine-readable files; ink extents are half-open pixel boxes, and their
signed insets are negative when ink escapes a node's declared bounds. Each gaps-matrix
entry reports horizontal and vertical separation for both declared and raster-ink boxes:
positive means clear space, zero means touching, and negative means overlap. Contrast is
measured from the most contrasting sufficiently represented ink colour and the dominant
fill inside the text bounds; the surrounding ring excludes rounded-corner page bleed.
No qualifying ink is reported as `NO_INK`. Ratios use WCAG relative luminance. The reports preserve the capture hash, launcher/runtime revisions,
profile, scale, and contrast mode from the capture sidecar.

To add a regression audit, create a TOML recipe under `audits/`. Give it a validated audit
name, profile, optional scale/contrast, and one or more phases with pinned launcher
commits. A `scene` phase names exact scene node ids. A `fixture` phase names the
revision's own fixture (`settings`, `home`, or `sim-frame`) and pixel regions as
`name/x/y/w/h`; the report records both the mode and exact fixture command. Each phase declares measurable
expectations (`gap`, `check_status`, `negative_inset`, `all_insets_nonnegative`, or
`ink_height`); use numeric `eq`, `lt`, `le`, `gt`, or `ge` operators where applicable.
Run it with `pf-simctl audit run PATH`. The runner builds the pinned source, starts only the
local headless simulator for scene phases or invokes the pinned binary's revision-native
renderer for fixture phases. Launcher source is never patched. If no native renderer can
produce the historical state, use `mode = "unreproducible"` with a reason and
`historical = true` measurements; a passing post-fix phase then yields `audit_status=partial`.
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
Each `profile` step reseeds state and restarts the shell, so put it before navigation
and repeat the navigation after every profile change.

The shipped preset matrix captures Home rather than Settings. The current gamepad
contract does not bind the launcher's `Room.next`/`Room.previous` actions, and its
room-tab nodes are not reachable with the bound directional actions. Extending that
launcher input contract is deferred; the scenario runner does not invent an
automation-only route around the user input contract.

`scenario run FILE --repeat N` starts a replaced headless instance for each run,
unless `--keep-instance` is requested. Every completed step produces a frame and
semantic scene in `scenarios/NAME/run-NNN/NN-op/`; `step.json` records timing, output,
and errors. A failure marks later steps skipped. The root reports include a step table,
capture hashes, and every discouraged `sleep` step. Repeats are deterministic only
when the corresponding capture SHA-256 is identical in every run.
