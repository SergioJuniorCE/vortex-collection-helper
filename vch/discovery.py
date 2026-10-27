"""Find Vortex, and make sure its debug port is reachable."""

import os
import re
import subprocess
import time
import urllib.request
from threading import Event
from typing import Callable, Optional

from .util import Stopped, wait_until

START_TIMEOUT = 40


def find_vortex_exe() -> Optional[str]:
    """Locate Vortex.exe without assuming one machine's install folder.

    The nxm:// protocol handler is the authoritative answer - it is the exact
    executable Windows launches when a download link is handed over.
    """
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg is not None:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                    hive, r"Software\Classes\nxm\shell\open\command"
                ) as key:
                    command = winreg.QueryValueEx(key, "")[0]
            except OSError:
                continue
            match = re.search(r'"([^"]*Vortex\.exe)"', command, re.I) or re.search(
                r"(\S*Vortex\.exe)", command, re.I
            )
            if match and os.path.exists(match.group(1)):
                return match.group(1)
    for candidate in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Vortex", "Vortex.exe"),
        r"C:\Program Files\Vortex\Vortex.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def port_open(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/json/version" % port, timeout=2
        ):
            return True
    except Exception:
        return False


def vortex_running() -> bool:
    try:
        output = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Vortex.exe"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        return "Vortex.exe" in output
    except Exception:
        return False


def ensure_running(
    vortex_exe: str,
    port: int,
    restart: bool,
    log: Callable[[str], None],
    stop: Optional[Event] = None,
) -> bool:
    if stop is not None and stop.is_set():
        raise Stopped()

    if port_open(port):
        log("vortex: debug port %d reachable" % port)
        return True

    if not os.path.exists(vortex_exe):
        log("Vortex.exe not found at %s" % vortex_exe)
        log("Pass --vortex-exe with the full path to Vortex.exe")
        return False

    if vortex_running():
        if not restart:
            log("Vortex is running WITHOUT the debug port.")
            log("Close Vortex and rerun, or rerun with --restart-vortex")
            log("(that force-closes the running Vortex).")
            return False
        log("force-closing the running Vortex...")
        subprocess.run(["taskkill", "/IM", "Vortex.exe", "/F"], capture_output=True)
        if stop is not None:
            if stop.wait(5):
                raise Stopped()
        else:
            time.sleep(5)

    if stop is not None and stop.is_set():
        raise Stopped()

    log("starting Vortex with --remote-debugging-port=%d" % port)
    try:
        subprocess.Popen([vortex_exe, "--remote-debugging-port=%d" % port])
    except OSError as exc:
        log("could not start Vortex: %s" % str(exc)[:140])
        return False
    should_stop = stop.is_set if stop is not None else None
    if not wait_until(
        lambda: port_open(port),
        timeout=START_TIMEOUT,
        interval=1,
        should_stop=should_stop,
    ):
        log("Vortex did not come up with the debug port. Start it manually:")
        log('   "%s" --remote-debugging-port=%d' % (vortex_exe, port))
        return False
    log("vortex: debug port %d reachable" % port)
    return True
