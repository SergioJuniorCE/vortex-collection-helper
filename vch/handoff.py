"""Vortex's own log is the authority on whether a download handoff happened."""

import os
from dataclasses import dataclass
from typing import Callable, Optional

from .models import ModKey
from .util import wait_until

DEFAULT_LOG = os.path.join(os.environ.get("APPDATA", ""), "Vortex", "vortex.log")


def _created(stat_result: os.stat_result) -> float:
    # On Windows st_ctime is creation time and is deprecated since 3.12.
    return getattr(stat_result, "st_birthtime", stat_result.st_ctime)


TAIL_BYTES = 64


def _tail(path: str, size: int) -> bytes:
    if size <= 0:
        return b""
    start = max(0, size - TAIL_BYTES)
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            return handle.read(size - start)
    except OSError:
        return b""


@dataclass(frozen=True)
class LogMark:
    """A byte offset plus enough identity to notice the file was rewritten.

    The saved tail catches an in-place truncation that has already grown back
    past the old offset by the time we look; the creation time catches the
    file being replaced outright.
    """

    size: int
    created: float
    tail: bytes = b""

    @classmethod
    def take(cls, path: str) -> "LogMark":
        try:
            stat_result = os.stat(path)
        except OSError:
            return cls(0, 0.0)
        return cls(
            stat_result.st_size,
            _created(stat_result),
            _tail(path, stat_result.st_size),
        )


class VortexLog:
    """Detects the `handling url .../mods/<id>/files/<fid>` handoff line."""

    def __init__(self, path: str = DEFAULT_LOG, poll: float = 3.0):
        self.path = path
        self.poll = poll

    def mark(self) -> LogMark:
        return LogMark.take(self.path)

    def saw_handoff(self, mark: LogMark, key: Optional[ModKey]) -> bool:
        if key is None:
            return False
        try:
            stat_result = os.stat(self.path)
        except OSError:
            return False

        offset = mark.size
        if _created(stat_result) != mark.created or stat_result.st_size < mark.size:
            # The file was replaced or truncated, so the saved offset is
            # meaningless. Search the whole file instead of going blind.
            offset = 0
        elif mark.tail and _tail(self.path, offset) != mark.tail:
            # Same file, but the bytes before the saved offset changed: an
            # in-place rewrite already grew back past the old size.
            offset = 0

        try:
            with open(self.path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read().decode("utf-8", "replace")
        except OSError:
            return False

        return any(
            "handling url" in line and key.matches_log_line(line)
            for line in chunk.splitlines()
        )

    def wait_handoff(
        self,
        mark: LogMark,
        key: Optional[ModKey],
        seconds: float,
        log: Callable[[str], None],
    ) -> bool:
        if key is None:
            return False
        found = wait_until(
            lambda: self.saw_handoff(mark, key),
            timeout=seconds,
            interval=self.poll,
        )
        if found:
            log("  Vortex received the download")
        return bool(found)
