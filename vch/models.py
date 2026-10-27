"""Small domain types shared by the Vortex and browser sides.

Everything here is dependency-free so the rules can be tested without
Playwright, websocket-client, or a running Vortex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class ModKey:
    """A mod's real identity: (mod id, file id), never its name or dialog index."""

    mod_id: int
    file_id: int

    @classmethod
    def from_url(cls, url: Optional[str]) -> Optional["ModKey"]:
        url = url or ""
        match = re.search(r"/mods/(\d+)/files/(\d+)", url)
        if match:
            return cls(int(match.group(1)), int(match.group(2)))
        match = re.search(r"/mods/(\d+)(?:[/?]|$)", url)
        file_id = re.search(r"[?&]file_id=(\d+)", url)
        if match and file_id:
            return cls(int(match.group(1)), int(file_id.group(1)))
        return None

    def log_fragment(self) -> str:
        return "/mods/%d/files/%d" % (self.mod_id, self.file_id)

    def matches_log_line(self, line: str) -> bool:
        return re.search(re.escape(self.log_fragment()) + r"(?!\d)", line) is not None

    def __str__(self) -> str:
        return "%d/%d" % (self.mod_id, self.file_id)


@dataclass(frozen=True)
class Prompt:
    """The per-mod "Download mod X" dialog, as read from Vortex's DOM."""

    has_prompt: bool = False
    index: Optional[int] = None
    total: Optional[int] = None
    mod_name: Optional[str] = None
    text: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> "Prompt":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            has_prompt=bool(raw.get("hasPrompt")),
            index=raw.get("index"),
            total=raw.get("total"),
            mod_name=raw.get("modName"),
            text=raw.get("text") or "",
        )


class DownloadStatus(Enum):
    OK = "ok"
    LOGIN = "login"
    RATE_LIMITED = "rate-limited"
    CHALLENGE = "challenge"
    NO_BUTTON = "no-button"
    UNCERTAIN = "uncertain"
    NAV_FAILED = "nav-failed"


class HookState(Enum):
    INSTALLED = "installed"
    ALREADY = "already"
    NO_API = "no-api"

    @property
    def usable(self) -> bool:
        return self is not HookState.NO_API

    @classmethod
    def from_raw(cls, raw: object) -> "HookState":
        try:
            return cls(raw)
        except ValueError:
            return cls.NO_API


@dataclass(frozen=True)
class ClickResult:
    clicked: bool
    label: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> "ClickResult":
        text = str(raw or "")
        if text == "clicked":
            return cls(True)
        if text.startswith("clicked:"):
            return cls(True, text.split(":", 1)[1])
        return cls(False)


class Outcome(Enum):
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class Result:
    """What happened to one prompt, and whether the run should stop."""

    outcome: Outcome
    stop: bool = False
