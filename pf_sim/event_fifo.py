"""Run-private input FIFO (tsp-ihne1.56.5 wave-1 private input route).

The gamepad holder writes native ``input_event`` frames into a per-instance
FIFO under the run directory; pf-shell consumes it through ``--input``.
Nothing here opens a kernel input facility, binds a host device node, or
touches the host display: the FIFO is created 0600 inside the run-private
directory and every write fails closed when no consumer has opened it.
"""
from __future__ import annotations

import os
import stat
import struct
import threading

from .config import run_dir, validate_instance

FIFO_NAME = "input.fifo"
INPUT_EVENT = struct.Struct("@llHHi")
OPEN_TIMEOUT = 1.0


def pack_event(type_: int, code: int, value: int) -> bytes:
    """Encode one native input_event frame (zeroed timestamps)."""
    return INPUT_EVENT.pack(0, 0, type_, code, value)


def fifo_path(instance: str):
    return run_dir(validate_instance(instance)) / FIFO_NAME


def create(instance: str):
    path = fifo_path(instance)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not stat.S_ISFIFO(path.stat().st_mode):
            raise RuntimeError("reason=input_fifo_path_not_a_fifo")
    else:
        os.mkfifo(path, 0o600)
    return path


def remove(instance: str) -> None:
    fifo_path(instance).unlink(missing_ok=True)


class FifoWriter:
    """Write-side holder for the run-private FIFO.

    Opening a FIFO for writing blocks until a consumer opens the read end,
    so the open happens on a daemon thread. ``write`` fails closed with
    ``reason=input_fifo_not_open`` when no consumer has attached within
    ``open_timeout`` instead of blocking the command loop forever.
    """

    def __init__(self, path, open_timeout: float = OPEN_TIMEOUT):
        self.path = str(path)
        self.open_timeout = open_timeout
        self._fd = -1
        self._ready = threading.Event()
        self._opener = threading.Thread(target=self._open, daemon=True)
        self._opener.start()

    def _open(self) -> None:
        try:
            fd = os.open(self.path, os.O_WRONLY)
        except OSError:
            return
        self._fd = fd
        self._ready.set()

    def write(self, frames: bytes) -> None:
        if not self._ready.wait(self.open_timeout) or self._fd < 0:
            raise RuntimeError("reason=input_fifo_not_open")
        os.write(self._fd, frames)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
