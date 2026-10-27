"""Process-wide utilities: logging, polling, and co-operative cancellation."""

import atexit
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


class Stopped(Exception):
    """Raised when the caller asked the session to stop."""


def make_logger(path: str, echo: bool = True) -> Callable[[str], None]:
    """Open an append-only log. echo=False is for GUI runs."""

    handle = open(path, "a", encoding="utf-8")
    atexit.register(handle.close)

    def log(message: str) -> None:
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), message)
        if echo:
            print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    return log


def wait_until(
    probe: Callable[[], Optional[T]],
    timeout: Optional[float] = None,
    interval: float = 1.0,
    on_tick: Optional[Callable[[float], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Optional[T]:
    """Poll probe() until it returns something truthy, or timeout elapses.

    Returns the truthy value, or None on timeout. timeout=None waits forever;
    the probe then owns the stopping condition. on_tick(elapsed) runs after
    every failed probe. If should_stop() becomes true, raises Stopped.
    """

    started = time.monotonic()
    while True:
        if should_stop is not None and should_stop():
            raise Stopped()
        value = probe()
        if value:
            return value
        elapsed = time.monotonic() - started
        if timeout is not None and elapsed >= timeout:
            return None
        if on_tick is not None:
            on_tick(elapsed)
        time.sleep(interval)
