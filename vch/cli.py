"""Command line entry point: parse options, wire the two sides, run."""

import argparse
import os
import traceback
from typing import Optional, Sequence

from .runner import RunOptions
from .session import SessionOptions, run_session
from .util import make_logger

LOG_NAME = "vortex_collection_helper.log"


def _parse_args(argv: Optional[Sequence[str]], here: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate the free-tier Vortex collection download loop.",
        epilog="The GUI is also available with: uv run python -m vch.ui",
    )
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument(
        "--vortex-exe",
        default=None,
        help="full path to Vortex.exe (default: found via the nxm:// handler)",
    )
    parser.add_argument(
        "--profile",
        default=os.path.join(
            os.environ.get("LOCALAPPDATA", here),
            "vortex-collection-helper",
            "profile",
        ),
    )
    parser.add_argument(
        "--channel",
        choices=["msedge", "chromium"],
        default="msedge",
        help="msedge (default) or chromium",
    )
    parser.add_argument(
        "--recycle-every",
        type=int,
        default=3,
        help="close and reopen the browser tab every N downloads",
    )
    parser.add_argument(
        "--idle-exit",
        type=int,
        default=180,
        help="seconds without a prompt before declaring the run finished",
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=1800,
        help="max seconds to wait for Vortex to download+install one mod",
    )
    parser.add_argument(
        "--on-failure",
        choices=["pause", "skip"],
        default="pause",
        help="pause and ask (default), or keep going",
    )
    parser.add_argument(
        "--once", action="store_true", help="process a single mod, then stop"
    )
    parser.add_argument(
        "--restart-vortex",
        action="store_true",
        help="force-close a running Vortex and relaunch it with the debug port",
    )
    parser.add_argument(
        "--ui", action="store_true", help="open the Tkinter interface"
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None, here: Optional[str] = None) -> int:
    here = here or os.getcwd()
    args = _parse_args(argv, here)

    if args.ui:
        from .ui import run_ui

        return run_ui(here)

    log = make_logger(os.path.join(here, LOG_NAME))
    log("=" * 68)
    log("vortex collection helper starting")

    options = SessionOptions(
        port=args.port,
        profile=args.profile,
        channel=args.channel,
        vortex_exe=args.vortex_exe,
        restart_vortex=args.restart_vortex,
        run=RunOptions(
            idle_exit=args.idle_exit,
            download_timeout=args.download_timeout,
            on_failure=args.on_failure,
            once=args.once,
            recycle_every=args.recycle_every,
        ),
    )

    try:
        return 0 if run_session(options, log) else 1
    except KeyboardInterrupt:
        log("interrupted by user")
        return 0
    except Exception:
        log("unexpected error:")
        for line in traceback.format_exc().splitlines():
            log("  " + line)
        return 1
