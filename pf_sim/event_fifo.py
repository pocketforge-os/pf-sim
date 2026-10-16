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
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        os.mkfifo(path, 0o600)
        return path
    if stat.S_ISLNK(mode) or not stat.S_ISFIFO(mode):
        # A stale or planted symlink (even one pointing at another FIFO)
        # would let the holder write outside the run-private directory, so
        # it is refused instead of followed (pf-sim#12 review note).
        raise RuntimeError("reason=input_fifo_path_not_a_fifo")
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
            # O_NOFOLLOW: the run-private FIFO must be opened as-is; a
            # symlink swapped in after create() is refused (ELOOP) rather
            # than followed out of the instance run directory (pf-sim#12
            # review note). The failure stays closed: write() then raises
            # reason=input_fifo_not_open.
            fd = os.open(self.path, os.O_WRONLY | os.O_NOFOLLOW)
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
