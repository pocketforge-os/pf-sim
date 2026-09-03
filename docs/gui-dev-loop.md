# GUI development loop

This is the fresh-session path. Run commands through the checkout’s `pf-simctl`; it is location-independent and preserves the caller’s working directory, so relative profile and output paths retain their normal meaning.

## Prerequisites and toolchain

Set a writable runtime directory, build the pinned launcher/runtime once, then make every required doctor row green. `DISPLAY` and event-node access are advisory unless you need windowed or controller input; CI sets `PF_SIM_REQUIRE_UINPUT=1` so missing uinput is fatal.

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
./pf-simctl toolchain build
./pf-simctl doctor
```

Doctor checks Python, Pillow, Weston and its kiosk/screenshot helpers, Cargo, xkbcommon, the runtime directory, toolchain manifest, uinput event-node readability, and orphaned pf-sim shells. Use a logind seat ACL, membership in `input`, or a udev rule narrowly matching `pocketforge-sim-gamepad:*` when the event node is unreadable.

## Bring-up, profiles, and presets

Headless pixman is the reproducible default; windowed mode needs `DISPLAY` and is for interactive observation.

```sh
./pf-simctl up --display headless
./pf-simctl up --replace --display windowed
./pf-simctl status --json
./pf-simctl down
```

`profile list/show/validate/apply/snapshot` manages state without navigating Settings. The committed profiles are `first-run`, `seeded-default`, `degraded-authority`, `power-status-present`, and `controller-battery-low`. Compose each with `--scale 100|150|200` and `--contrast default|hc`. Applying a profile reseeds and restarts affected components; snapshot output is sanitized and contains no live sockets, locks, or markers.

## Input and text

The default virtual gamepad sends evdev codes through the launcher’s real `pf-input-map` contract. Inspect it with `input list` and drive semantic actions with `input action`, physical controls with `input press/hold`, or an ordered expression with `input seq`. These commands wait for the resulting frame unless `--no-wait` is deliberate.

```sh
./pf-simctl input action Search.open
./pf-simctl input seq "east Move.down south"
./pf-simctl text e
./pf-simctl text --clear
```

Text uses an automation-only seam because the handheld has no text keyboard. `key KEYSYM...` is only a fallback after `up --no-gamepad --display windowed`; it is intentionally rejected headlessly.

## Frame-complete evidence and measurement

`capture NAME` waits for a presented frame and writes `NAME.png`, `NAME.scene.json`, and a metadata sidecar under `$PF_SIM_HOME/captures/INSTANCE`. The scene is the semantic assertion surface; for example, assert `search_query` and `search_result_ids`, not a hand-read screenshot. `capture --repeat 2` compares raster and semantic hashes. `--raw` is the legacy compositor fallback.

```sh
./pf-simctl capture search-e
./pf-simctl capture --repeat 2 stable-home
./pf-simctl measure search-e --role text --min-gap 8 --contrast-floor 4.5
./pf-simctl measure diff before after
```

Measurement emits an overlay plus `ink.json`, `gaps.json`, `contrast.json`, `report.json`, and `report.md`. Positive gaps mean space, zero means touching, negative means overlap; signed negative insets mean ink escaped its declared node. Contrast uses WCAG relative luminance. Threshold failure exits nonzero; reserve `--no-fail` for explicitly report-only work.

## Fixture apps and sessions

`app list` names deterministic fixtures. The canonical lifecycle covers launch-dim, in-app, graceful return, and crash receipts:

```sh
./pf-simctl launch ridgeline
./pf-simctl capture launch-dim
./pf-simctl app status
./pf-simctl capture in-app
./pf-simctl safe-return
./pf-simctl history --json
./pf-simctl launch hollow-tides
./pf-simctl app crash
./pf-simctl history --json
```

`launching` lasts until the fixture socket appears. `app quit` is a clean return, `safe-return` exercises authority ordering, and `app crash` yields a `Crash` receipt. Profiles use pf-sim’s supervisor; a custom profile may select the shell’s desktop-sim supervisor for parity checks.

## Scenarios and determinism

A scenario TOML has `[scenario]` metadata (`name`, `description`, `profile`, `scale`, `contrast`) and ordered `[[steps]]`. Operations are `profile`, `input`, `text`, `launch`, `safe_return`, `app`, `wait_for`, `capture`, `assert`, and diagnostic-only `sleep`. Predicates cover focus id/label, label presence, route, search query/result count, session/receipt, and app state. Prefer bounded predicates over sleeps. Put profile changes before navigation because they restart the shell.

```sh
./pf-simctl scenario validate scenarios/search-filter.toml
./pf-simctl scenario run scenarios/search-filter.toml --repeat 2
```

Every step records PNG, scene, timing, output, and errors; aggregate JSON/Markdown reports live under `$PF_SIM_HOME/scenarios/NAME`. Repeat mode fails on raster or semantic nondeterminism.

## Product-010 audits and matrix

The three committed audits are exact pinned-revision recipes. Their truthful gates are: `home200-footer-overlap=reproduced`, `pill-ink=partial`, and `settings-caption-gap=partial`. Partial means the unmodified historical revision had no native pre-fix renderer while its post-fix fixture reproduced; it is not permission to patch launcher source.

```sh
./pf-simctl audit run audits/product-010/home200-footer-overlap.toml
./pf-simctl audit run audits/product-010/pill-ink.toml
./pf-simctl audit run audits/product-010/settings-caption-gap.toml
./pf-simctl matrix run audits/product-010/matrix.toml --only scale=200,contrast=hc --repeat 2
```

The full matrix crosses route, scale, contrast, and profile, producing per-cell captures/measurements plus root JSON, Markdown, and offline HTML. Settings cells are explicit skips: at the pinned launcher revision `Settings.open` and `Room.*` are unbound, so Settings evidence comes only from the pinned `--settings-evidence` fixture. Do not invent a private navigation seam.

## CI

The reusable workflow builds a caller-selected launcher revision, runs scenarios and audits, runs the optionally filtered matrix, and uploads evidence. See [CI integration](ci-integration.md) for the exact launcher PR caller. `scripts/verify-clean-checkout.sh --dry-run` prints the epic checklist; without the flag it clones the current commit into a temporary directory with an empty `PF_SIM_HOME` and prints one final `verify_status=` plus its criterion table.

## Troubleshooting

Every CLI `reason=` belongs to one of these remedies (dynamic suffixes are shown in braces):

| Reason | Fix |
|---|---|
| `invalid_{kind}`, `invalid_app_step`, `invalid_audit`, `invalid_audit_expectation`, `invalid_audit_fixture`, `invalid_audit_mode`, `invalid_audit_operator`, `invalid_capture`, `invalid_hook_arguments`, `invalid_hook_command`, `invalid_launcher_rev`, `invalid_matrix`, `invalid_matrix_contrast`, `invalid_matrix_expect`, `invalid_matrix_filter`, `invalid_matrix_measure`, `invalid_matrix_route`, `invalid_matrix_scale`, `invalid_matrix_schema`, `invalid_matrix_skip`, `invalid_matrix_step`, `invalid_pattern`, `invalid_power_profile`, `invalid_predicate`, `invalid_profile_step`, `invalid_repeat`, `invalid_scenario`, `invalid_scenario_profile`, `invalid_scenario_schema`, `invalid_scenario_steps`, `invalid_supervisor`, `invalid_text_scale` | Correct the named CLI value or TOML field; names must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and repeats must be positive. |
| `profile_not_found`, `missing_matrix_route`, `unknown_matrix_{axis}`, `unknown_scenario_op`, `unknown_control`, `unknown_gamepad_command`, `unknown_input_code`, `unbound_action`, `unsupported_binding` | List the committed profiles/inputs, validate the file, and use an action actually bound by the pinned contract. |
| `device_contract_absent`, `shell_bin_missing`, `authorityd_bin_missing`, `launcher_source_dirty` | Run `toolchain build`; remove uncommitted files from its generated launcher checkout or use a new empty `PF_SIM_HOME`. |
| `xdg_runtime_dir_missing`, `display_missing`, `weston_died`, `authorityd_died`, `supervisor_died`, `shell_died`, `automation_socket_died` | Set the required display/runtime environment, run `doctor`, then inspect the component log path printed by `up`. |
| `instance_already_up`, `instance_not_running`, `stale_state`, `stale_marker`, `lock`, `socket` | Use `--replace`, target the right instance, or stop it cleanly. Never delete state outside `PF_SIM_HOME`. |
| `event_node_timeout`, `event_node_unreadable`, `uinput_sysname_missing`, `gamepad_create_failed`, `gamepad_holder_would_not_stop`, `gamepad_protocol_error`, `holder_token_mismatch` | Run `doctor`; restore uinput and event-node ACLs, then `down --reap-orphans` before retrying. |
| `automation_down`, `automation_error`, `automation_protocol_error`, `automation_timeout`, `authority_error`, `authority_request_too_large`, `authority_response_too_large`, `authority_truncated_frame` | Check instance status and component logs; restart the instance. Reduce an oversized request rather than bypassing the protocol. |
| `capture_never_settled`, `capture_frame_drift`, `screenshot_missing` | Check shell/Weston logs and retry from a stable scene. `degraded-authority` normally settles as `content-stable` with `revision_churn=true` because of launcher bug `tsp-cric`; that is not a pf-sim failure. |
| `assertion_failed`, `predicate_timeout`, `input_not_observed`, `route_mismatch`, `route_reset_failed`, `app_not_running`, `cell_error` | Inspect the step/cell report and scene JSON; correct navigation, expectation, or fixture ordering. |
| `diff_requires_two_captures`, `diff_size_mismatch` | Supply two captures with identical dimensions. |
| `headless_input_arrives_in_p2` | Use the gamepad input verbs, or use `key` only in windowed `--no-gamepad` mode. |
| `unsupported_matrix_jobs` | Use `--jobs 1`; parallel matrix execution is not implemented. |

If `down` says `not_running` but doctor reports `orphaned pf-sim shells=N`, run `./pf-simctl down --reap-orphans`. Reaping matches only `pf-shell --state-dir` paths contained under the current `$PF_SIM_HOME/runs`; it cannot target unrelated shells such as `/home/matt/pf-desktop-test`.

## What pf-sim does not prove

pf-sim is desktop evidence, not device evidence. It does not prove GPU-driver correctness, scanout, frame timing, latency, power behavior, kernel/input-device quirks, memory pressure, thermal behavior, suspend/resume, or performance on the handheld. It does not make an OCI app pass `pocketforge-os/sim`, and it does not supersede the launcher’s authoritative offscreen evidence suite for its covered rendering contracts. The hardware gate remains authoritative for physical-device acceptance.

The Settings fixture proves only the pinned renderer’s evidence surface; it does not prove controller reachability, because Settings is unreachable through the pinned gamepad contract. A deterministic raster proves repeatability of this software path, not equivalence to GPU output or timing on hardware.
