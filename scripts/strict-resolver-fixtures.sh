#!/bin/sh
set -eu

usage() {
    echo "usage: $0 install|remove ABSOLUTE_ROOT" >&2
    exit 2
}

[ "$#" -eq 2 ] || usage
operation=$1
root=$2
case "$root" in
    /*) ;;
    *) usage ;;
esac

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../fixtures/strict-resolver" && pwd)
apps_root="${root%/}/opt/pocketforge/apps"
platform_root="${root%/}/usr/share/pocketforge"
platform_contract="$platform_root/platform-capabilities.toml"
apps_marker="$apps_root/.pf-sim-fixtures"
platform_marker="$platform_root/.pf-sim-fixtures"
app_ids="org.pocketforge.ridgeline org.pocketforge.hollow-tides org.pocketforge.signal-decay"

install_fixtures() {
    [ ! -e "$apps_root" ] || {
        echo "reason=strict_resolver_apps_target_exists path=$apps_root" >&2
        exit 1
    }
    [ ! -e "$platform_contract" ] && [ ! -e "$platform_marker" ] || {
        echo "reason=strict_resolver_platform_target_exists path=$platform_contract" >&2
        exit 1
    }
    install -d -m 0755 "$apps_root" "$platform_root"
    for app_id in $app_ids; do
        target="$apps_root/$app_id"
        install -d -m 0755 "$target"
        install -m 0644 "$source_root/apps/$app_id/app.toml" "$target/app.toml"
        install -m 0755 "$source_root/apps/$app_id/fixture" "$target/fixture"
    done
    install -m 0644 "$source_root/platform-capabilities.toml" "$platform_contract"
    install -m 0644 /dev/null "$apps_marker"
    install -m 0644 /dev/null "$platform_marker"
}

remove_fixtures() {
    [ -f "$apps_marker" ] && [ -f "$platform_marker" ] || {
        echo "reason=strict_resolver_fixture_marker_absent" >&2
        exit 1
    }
    for app_id in $app_ids; do
        target="$apps_root/$app_id"
        find "$target" -mindepth 1 -delete
        rmdir "$target"
    done
    unlink "$apps_marker"
    rmdir "$apps_root"
    unlink "$platform_contract"
    unlink "$platform_marker"
}

case "$operation" in
    install) install_fixtures ;;
    remove) remove_fixtures ;;
    *) usage ;;
esac
