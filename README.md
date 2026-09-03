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
