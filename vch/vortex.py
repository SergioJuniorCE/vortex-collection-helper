"""Chrome DevTools Protocol client for Vortex's renderer."""

import json
import time
import urllib.request
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional

import websocket

from .js import (
    JS_CLICK_DOWNLOAD_MANUALLY,
    JS_CLICK_INSTALLER,
    JS_CLICK_SKIP_MOD,
    JS_HOOK,
    JS_PROMPT,
    JS_TAKE_URLS,
    JS_UNHOOK,
)
from .models import ClickResult, HookState, Prompt
from .util import Stopped

HOOK_READY_TRIES = 20


class HookUnavailable(RuntimeError):
    """Vortex's preload API is not available, so no URL can be captured."""


class VortexBridge:
    def __init__(self, port: int, log: Callable[[str], None], stop=None):
        self.port = port
        self.log = log
        self.stop = stop
        self.ws: Optional[websocket.WebSocket] = None
        self._id = 0

    def connect(self) -> "VortexBridge":
        url = "http://127.0.0.1:%d/json/list" % self.port
        with urllib.request.urlopen(url, timeout=5) as response:
            targets = json.load(response)
        pages = [target for target in targets if target.get("type") == "page"]
        if not pages:
            raise RuntimeError("Vortex is reachable but exposes no page target")
        self.ws = websocket.create_connection(
            pages[0]["webSocketDebuggerUrl"], timeout=30, suppress_origin=True
        )
        return self

    def _evaluate(self, expression: str, timeout: float) -> object:
        if self.ws is None:
            raise RuntimeError("Vortex's debug connection is not open")
        self._id += 1
        message_id = self._id
        self.ws.settimeout(timeout)
        self.ws.send(
            json.dumps(
                {
                    "id": message_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != message_id:
                continue
            result = message.get("result", {})
            if "exceptionDetails" in result:
                details = result["exceptionDetails"]
                raise RuntimeError(
                    details.get("exception", {}).get("description", "JS error")
                )
            return result.get("result", {}).get("value")

    def js(self, expression: str, timeout: float = 30) -> object:
        """Evaluate an expression, reconnecting once if the socket died."""
        if self.ws is None:
            self.connect()
        try:
            return self._evaluate(expression, timeout)
        except (websocket.WebSocketException, OSError):
            self.ws = None
            self.connect()
            return self._evaluate(expression, timeout)

    def hook(self) -> HookState:
        """Install the openUrl hook, waiting for a freshly started renderer."""
        for attempt in range(HOOK_READY_TRIES + 1):
            if self.stop is not None and self.stop.is_set():
                raise Stopped()
            state = HookState.from_raw(self.js(JS_HOOK))
            if state.usable:
                return state
            if attempt < HOOK_READY_TRIES:
                time.sleep(1)
        return HookState.NO_API

    def unhook(self) -> str:
        return str(self.js(JS_UNHOOK) or "")

    @contextmanager
    def hooked(self) -> Iterator[HookState]:
        """Own the hook for the whole run, and always put it back."""
        try:
            state = self.hook()
        except Stopped:
            raise
        except Exception as exc:
            raise HookUnavailable(
                "could not reach Vortex's renderer: %s" % str(exc)[:140]
            ) from exc
        if not state.usable:
            raise HookUnavailable(
                "Vortex's renderer API is not available - is Vortex fully started?"
            )
        self.log("vortex: hooked openUrl -> %s" % state.value)
        try:
            yield state
        finally:
            try:
                result = self.unhook()
                self.log("vortex: openUrl restored -> %s" % result)
            except Exception as exc:
                self.log("vortex: could not restore openUrl: %s" % str(exc)[:140])

    def prompt(self) -> Prompt:
        return Prompt.from_raw(self.js(JS_PROMPT))

    def click_installer(self) -> ClickResult:
        return ClickResult.from_raw(self.js(JS_CLICK_INSTALLER))

    def click_skip_mod(self) -> ClickResult:
        return ClickResult.from_raw(self.js(JS_CLICK_SKIP_MOD))

    def click_download_manually(self) -> ClickResult:
        return ClickResult.from_raw(self.js(JS_CLICK_DOWNLOAD_MANUALLY))

    def take_urls(self) -> List[str]:
        value = self.js(JS_TAKE_URLS)
        return [str(item) for item in value] if isinstance(value, list) else []
