#!/usr/bin/env python3
"""Automates the free-account Vortex collection download loop.

See README.md for the mechanism, requirements, and failure modes.
"""

import os
import sys

from vch.cli import main


if __name__ == "__main__":
    sys.exit(main(here=os.path.dirname(os.path.abspath(__file__))))
