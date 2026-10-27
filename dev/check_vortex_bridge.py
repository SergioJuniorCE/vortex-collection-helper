"""Check the Vortex side: attach, hook, read the prompt, restore."""

import json
from dataclasses import asdict

from vch.discovery import port_open, vortex_running
from vch.vortex import VortexBridge

PORT = 9222


def main() -> None:
    print("port_open(%d):" % PORT, port_open(PORT))
    print("vortex_running():", vortex_running())

    bridge = VortexBridge(PORT, print)
    bridge.connect()
    state = None
    try:
        state = bridge.hook()
        print("hook ->", state.value)
        assert state.usable, "openUrl hook was not installed"
        print("prompt ->", json.dumps(asdict(bridge.prompt())))
        print("take_urls ->", bridge.take_urls())
    finally:
        if state is not None and state.usable:
            print("unhook ->", bridge.unhook())


if __name__ == "__main__":
    main()
