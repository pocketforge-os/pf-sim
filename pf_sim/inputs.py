from __future__ import annotations

import time

from .contract import DeviceContract
from .gamepad import request


def send_control(instance: str, control, hold_ms: int = 60) -> None:
    request(instance, {"command": "tap", "code": control.code, "hold_ms": hold_ms})


def press(instance: str, values: list[str], hold_ms: int = 60, gap_ms: int = 120,
          contract: DeviceContract | None = None) -> None:
    contract = contract or DeviceContract.load()
    for index, value in enumerate(values):
        send_control(instance, contract.resolve_control(value), hold_ms)
        if index + 1 < len(values):
            time.sleep(max(0, gap_ms) / 1000)


def hold(instance: str, value: str, milliseconds: int,
         contract: DeviceContract | None = None) -> None:
    contract = contract or DeviceContract.load()
    send_control(instance, contract.resolve_control(value), milliseconds)


def action(instance: str, value: str, context: str = "shell", hold_ms: int = 60,
           contract: DeviceContract | None = None) -> None:
    contract = contract or DeviceContract.load()
    send_control(instance, contract.resolve_action(value, context), hold_ms)


def sequence(instance: str, expression: str, context: str = "shell", hold_ms: int = 60,
             gap_ms: int = 120, contract: DeviceContract | None = None) -> None:
    contract = contract or DeviceContract.load()
    controls = []
    for token in expression.split():
        try:
            controls.append(contract.resolve_control(token))
        except RuntimeError as error:
            if not str(error).startswith("reason=unknown_control"):
                raise
            controls.append(contract.resolve_action(token, context))
    for index, control in enumerate(controls):
        send_control(instance, control, hold_ms)
        if index + 1 < len(controls):
            time.sleep(max(0, gap_ms) / 1000)


def list_rows(contract: DeviceContract | None = None) -> list[tuple[str, str, str, str]]:
    contract = contract or DeviceContract.load()
    return [(c.position, c.printed_label, f"{c.code_name}({c.code})",
             ",".join(contract.actions_for(c.position))) for c in contract.controls]
