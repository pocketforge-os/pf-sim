"""Keyboard fallback over the instance's run-private input FIFO.

Wave-1 migration (tsp-ihne1.56.5): keysyms are mapped to Linux input event
codes and tapped through the same private gamepad route as the input verbs.
Headless and windowed runs share this one API — there is no host display
projection, no window activation and no synthetic-events tool involved.
"""
from __future__ import annotations

import time

from .gamepad import request

KEY_CODES = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10,
    "0": 11,
    "minus": 12, "equal": 13, "comma": 51, "dot": 52, "slash": 53,
    "return": 28, "escape": 1, "space": 57, "tab": 15, "backspace": 14,
    "up": 103, "down": 108, "left": 105, "right": 106,
}
KEY_ALIASES = {
    "enter": "return", "esc": "escape", " ": "space", "spc": "space",
    "backspace": "backspace", "bs": "backspace", "period": "dot",
    "kp_enter": "return",
}


def resolve(keysym: str) -> int:
    canonical = KEY_ALIASES.get(keysym, KEY_ALIASES.get(keysym.lower(), keysym.lower()))
    if canonical not in KEY_CODES:
        raise RuntimeError(f"reason=unsupported_keysym keysym={keysym}")
    return KEY_CODES[canonical]


def send(keysyms: list[str], instance: str, delay: float = .35) -> None:
    for keysym in keysyms:
        request(instance, {"command": "tap", "code": resolve(keysym), "hold_ms": 60})
        time.sleep(delay)
