#!/usr/bin/env python3
"""Wrapper script for itunes_cleanup audit phase — scan and classify library."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from itunes_cleanup.audit import main

if __name__ == "__main__":
    main()
