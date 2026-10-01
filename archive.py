#!/usr/bin/env python3
"""Wrapper script for itunes_cleanup archive phase — copy, verify, and delete."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from itunes_cleanup.archive import main

if __name__ == "__main__":
    main()
