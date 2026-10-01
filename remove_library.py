#!/usr/bin/env python3
"""Wrapper script for itunes_cleanup phase 3 — remove tracks from Music.app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from itunes_cleanup.remove_library import main

if __name__ == "__main__":
    main()
