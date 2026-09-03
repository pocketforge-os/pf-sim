from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import sim_home
from .evdev_codes import CODES


@dataclass(frozen=True)
class Control:
    position: str
    printed_label: str
    code_name: str
    code: int


class DeviceContract:
    def __init__(self, controls: list[Control], mappings: list[dict]):
        self.controls = controls
        self.mappings = mappings

    @classmethod
    def load(cls, path: Path | None = None) -> "DeviceContract":
        path = path or sim_home() / "toolchain" / "device-contract.json"
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError as error:
            raise RuntimeError("reason=device_contract_absent hint=run_toolchain_build") from error
        controls = []
        for item in data["physical_controls"]:
            name = item["input_code"]
            if name not in CODES:
                raise RuntimeError(f"reason=unknown_input_code code={name}")
            controls.append(Control(item["position"], item["printed_label"], name, CODES[name]))
        return cls(controls, data["effective_map"])

    def resolve_control(self, value: str) -> Control:
        folded = value.casefold()
        matches = [c for c in self.controls if folded in
                   (c.position.casefold(), c.printed_label.casefold(), c.code_name.casefold())]
        if not matches:
            raise RuntimeError(f"reason=unknown_control control={value}")
        return matches[0]

    def resolve_action(self, action: str, context: str = "shell") -> Control:
        # Global bindings apply in every context; prefer an exact-context binding.
        matches = [m for m in self.mappings if m["action"] == action and
                   m["context"] in (context, "global")]
        matches.sort(key=lambda m: m["context"] != context)
        if not matches:
            raise RuntimeError(f"reason=unbound_action action={action} context={context}")
        binding = matches[0]["binding"]
        if binding.get("shape") != "single_press" or len(binding.get("controls", [])) != 1:
            raise RuntimeError(f"reason=unsupported_binding action={action}")
        return self.resolve_control(binding["controls"][0])

    def actions_for(self, position: str) -> list[str]:
        return [f'{m["context"]}:{m["action"]}' for m in self.mappings
                if position in m.get("binding", {}).get("controls", [])]
