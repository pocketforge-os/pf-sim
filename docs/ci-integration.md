# CI integration

The reusable workflow builds the requested launcher commit, runs the selected scenarios headlessly, runs the product-010 audits and reduced matrix, and uploads the reports. A launcher pull-request workflow calls it like this:

```yaml
jobs:
  pf-sim:
    uses: pocketforge-os/pf-sim/.github/workflows/pf-sim-scenarios.yml@main
    with:
      launcher_ref: ${{ github.event.pull_request.head.sha }}
      scenarios: "scenarios/*.toml"
      matrix_only: "scale=200,contrast=hc"
      repeat: 2
```

The caller does not copy pf-sim steps or source into the launcher. A separate launcher-side pin-bump PR updates `pins.toml` when pf-sim should adopt a new launcher revision; this workflow's `launcher_ref` input lets a launcher PR test its own commit before that bump.

The workflow can also be run manually. `launcher_ref` defaults to the revision in `pins.toml`, `scenarios` defaults to `scenarios/*.toml`, `repeat` defaults to `1`, and an empty `matrix_only` runs the complete matrix.
