"""Shared startup and wiring for the CLI and the Tk UI."""

from dataclasses import dataclass
from threading import Event
from typing import Callable, Optional

from .browser import BrowserSide
from .discovery import ensure_running, find_vortex_exe
from .runner import Progress, Runner, RunOptions
from .util import Stopped
from .vortex import HookUnavailable, VortexBridge


@dataclass(frozen=True)
class SessionOptions:
    port: int
    profile: str
    channel: str
    run: RunOptions
    vortex_exe: Optional[str] = None
    restart_vortex: bool = False


def run_session(
    options: SessionOptions,
    log: Callable[[str], None],
    stop: Optional[Event] = None,
    confirm: Optional[Callable[[str], bool]] = None,
    on_progress: Optional[Callable[[Progress], None]] = None,
) -> bool:
    """Run one session. Returns False if it stopped or could not start."""

    vortex_exe = options.vortex_exe or find_vortex_exe()
    if not vortex_exe:
        log("could not find Vortex.exe - pass --vortex-exe with its full path")
        return False

    try:
        if not ensure_running(
            vortex_exe, options.port, options.restart_vortex, log, stop=stop
        ):
            return False

        bridge = VortexBridge(options.port, log, stop=stop)
        try:
            bridge.connect()
        except Exception as exc:
            log("vortex: could not attach to the debug port: %s" % str(exc)[:140])
            return False

        log("browser: profile %s" % options.profile)
        with bridge.hooked():
            with BrowserSide(
                options.profile,
                options.channel,
                log,
                stop=stop,
                confirm=confirm,
            ) as browser:
                Runner(
                    bridge,
                    browser,
                    log,
                    options.run,
                    stop=stop,
                    confirm=confirm,
                    on_progress=on_progress,
                ).run()
    except Stopped:
        log("stopped by user")
        return False
    except HookUnavailable as exc:
        log("vortex: %s" % exc)
        return False
    except RuntimeError as exc:
        log("error: %s" % str(exc)[:200])
        return False

    return True
