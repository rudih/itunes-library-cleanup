"""pytest configuration — add src/ to path for itunes_cleanup imports."""

import sys
from pathlib import Path

# Add src/ to path so tests can import itunes_cleanup
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))
