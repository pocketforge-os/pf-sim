#!/bin/sh
set -u

criteria='doctor
toolchain-build
all-profiles
text-filtered-capture
scenario-repeat-2
audit-home200-footer-overlap
audit-pill-ink
audit-settings-caption-gap
reduced-matrix
no-vendored-rust
single-launcher-pin
no-orphan-shells'

if [ "${1:-}" = "--dry-run" ]; then
    echo "Clean-checkout verification plan"
    printf '%s\n' "$criteria" | while IFS= read -r name; do printf 'criterion=%s\n' "$name"; done
    exit 0
fi
if [ "$#" -ne 0 ]; then echo "usage: $0 [--dry-run]" >&2; exit 2; fi

started=$(date +%s)
tmp=$(mktemp -d)
rows="$tmp/rows"
touch "$rows"
checkout="$tmp/pf-sim"
source_root=$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "$0")")/.." && pwd)
origin=$(git -C "$source_root" remote get-url origin)
commit=$(git -C "$source_root" rev-parse HEAD)
verify_home="$tmp/empty-home"
xdg="$tmp/xdg"
mkdir -p "$verify_home" "$xdg"
log="$tmp/verify.log"
overall=pass

cleanup() {
    if [ -x "$checkout/pf-simctl" ]; then
        (cd "$tmp" && PF_SIM_HOME="$verify_home" "$checkout/pf-simctl" down --reap-orphans) >/dev/null 2>&1 || true
    fi
    rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM

record() {
    name=$1; shift
    before=$(date +%s)
    if "$@" >>"$log" 2>&1; then status=PASS; else status=FAIL; overall=fail; fi
    elapsed=$(( $(date +%s) - before ))
    printf '%s\t%s\t%ss\n' "$name" "$status" "$elapsed" >>"$rows"
}

clone_checkout() {
    git clone --quiet "$origin" "$checkout" && git -C "$checkout" checkout --quiet "$commit"
}
run_ctl() { (cd "$tmp" && PF_SIM_HOME="$verify_home" XDG_RUNTIME_DIR="$xdg" "$checkout/pf-simctl" "$@"); }
build_toolchain() { run_ctl toolchain build; }
doctor_check() { run_ctl doctor; }
profiles_check() {
    run_ctl up --display headless
    for profile in first-run seeded-default degraded-authority power-status-present controller-battery-low; do
        run_ctl profile apply "$profile"
    done
    run_ctl down
}
capture_check() {
    run_ctl up --display headless
    run_ctl input action Search.open
    run_ctl text e
    run_ctl capture verify-filter
    PF_SIM_HOME="$verify_home" python3 - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.environ['PF_SIM_HOME'])/'captures/default/verify-filter.scene.json'
s = json.loads(p.read_text())
assert s['search_query'] == 'e'
assert s['search_result_ids']
PY
    run_ctl down
}
scenarios_check() {
    for file in "$checkout"/scenarios/*.toml; do run_ctl scenario run "$file" --repeat 2; done
}
audit_check() {
    recipe=$1 expected=$2
    out="$tmp/$(basename "$recipe").audit"
    run_ctl audit run "$checkout/audits/product-010/$recipe.toml" >"$out"
    grep -qx "audit_status=$expected" "$out"
    case "$recipe" in
      home200-footer-overlap) grep -q '^phase=.* mode=fixture reproduced=True' "$out" ;;
      pill-ink|settings-caption-gap) grep -q '^phase=.* mode=unreproducible reproduced=False reason=' "$out" && grep -q '^phase=.* mode=fixture reproduced=True' "$out" ;;
    esac
}
matrix_check() { run_ctl matrix run "$checkout/audits/product-010/matrix.toml" --only scale=200,contrast=hc --out "$tmp/matrix"; }
no_rust_check() { [ -z "$(find "$checkout/pf_sim" -name '*.rs' -print -quit)" ]; }
pin_check() {
    rev=$(sed -n 's/^rev = "\([0-9a-f]\{40\}\)"$/\1/p' "$checkout/pins.toml")
    [ -n "$rev" ] && ! grep -R -l --exclude=pins.toml --exclude='*manifest*.json' \
        --exclude-dir=.git --exclude-dir=audits "$rev" "$checkout" | grep -q .
}
orphan_check() {
    run_ctl down --reap-orphans
    [ "$(PF_SIM_HOME="$verify_home" python3 -c 'from pf_sim.backend.desktop import orphan_shell_pids; print(len(orphan_shell_pids()))' 2>/dev/null)" = 0 ]
}

if ! clone_checkout >>"$log" 2>&1; then
    printf '%-34s %-6s %s\n' CRITERION STATUS WALL_TIME
    printf '%-34s %-6s %s\n' clone-checkout FAIL 0s
    echo "verify_status=fail wall_time=$(( $(date +%s) - started ))s"
    exit 1
fi
cd "$checkout" || exit 1
record toolchain-build build_toolchain
record doctor doctor_check
record all-profiles profiles_check
record text-filtered-capture capture_check
record scenario-repeat-2 scenarios_check
record audit-home200-footer-overlap audit_check home200-footer-overlap reproduced
record audit-pill-ink audit_check pill-ink partial
record audit-settings-caption-gap audit_check settings-caption-gap partial
record reduced-matrix matrix_check
record no-vendored-rust no_rust_check
record single-launcher-pin pin_check
record no-orphan-shells orphan_check

printf '%-34s %-6s %s\n' CRITERION STATUS WALL_TIME
cat "$rows"
echo "verify_status=$overall wall_time=$(( $(date +%s) - started ))s"
[ "$overall" = pass ]
