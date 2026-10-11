from __future__ import annotations

import json

from . import inputs
from .automation import AutomationClient
from .authority import (SYSTEM_MENU_ACK_TIMEOUT_MS, SYSTEM_MENU_CONTRACT,
                        SYSTEM_MENU_CONTROL)
from .config import run_dir
from .contract import DeviceContract
from .toolchain import read_manifest


def send(instance: str, contract: DeviceContract | None = None) -> dict:
    """Send Menu only after proving the selected launcher's effective binding."""
    path = run_dir(instance)
    try:
        metadata = json.loads((path / "run.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("reason=system_menu_provenance_absent") from error
    launcher_rev = metadata.get("launcher_rev")
    shell_sha256 = metadata.get("shell_sha256")
    manifest = read_manifest()
    if (not isinstance(launcher_rev, str) or not launcher_rev
            or not isinstance(shell_sha256, str) or not shell_sha256
            or not isinstance(manifest, dict)
            or not isinstance(manifest.get("launcher_rev"), str)
            or not isinstance(manifest.get("pf_shell_sha256"), str)):
        raise RuntimeError("reason=system_menu_provenance_absent")
    if (launcher_rev != manifest["launcher_rev"]
            or shell_sha256 != manifest["pf_shell_sha256"]):
        raise RuntimeError(
            f"reason=system_menu_provenance_mismatch launcher_rev={launcher_rev}"
        )

    contract = contract or DeviceContract.load()
    physical = contract.resolve_control(SYSTEM_MENU_CONTROL)
    try:
        semantic = contract.resolve_action("SystemMenu", "global")
    except RuntimeError as error:
        raise RuntimeError(
            f"reason=system_menu_contract_absent launcher_rev={launcher_rev}"
        ) from error
    if semantic.code != physical.code:
        raise RuntimeError(
            f"reason=system_menu_contract_mismatch launcher_rev={launcher_rev}"
        )

    inputs.sequence(instance, SYSTEM_MENU_CONTROL, "global", 60, 120,
                    contract=contract)
    AutomationClient(path / "automation.sock").wait_idle()
    return {
        "action": "SystemMenu",
        "control": SYSTEM_MENU_CONTROL,
        "launcher_rev": launcher_rev,
        "configured_ack_timeout_ms": SYSTEM_MENU_ACK_TIMEOUT_MS,
        "contract": SYSTEM_MENU_CONTRACT,
    }
