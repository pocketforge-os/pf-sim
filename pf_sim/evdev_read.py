from __future__ import annotations

import argparse
import os
import selectors

from .gamepad import INPUT_EVENT


def read_events(path: str, count: int | None = None, ready=None):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    if ready is not None:
        ready.set()
    emitted = 0
    pending = b""
    try:
        while count is None or emitted < count:
            selector.select()
            pending += os.read(fd, INPUT_EVENT.size * 64)
            while len(pending) >= INPUT_EVENT.size and (count is None or emitted < count):
                raw, pending = pending[:INPUT_EVENT.size], pending[INPUT_EVENT.size:]
                _, _, event_type, code, value = INPUT_EVENT.unpack(raw)
                emitted += 1
                yield event_type, code, value
    finally:
        selector.close()
        os.close(fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_node")
    parser.add_argument("--count", type=int)
    args = parser.parse_args(argv)
    for event in read_events(args.event_node, args.count):
        print(*event, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
