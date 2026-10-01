"""
config.py — All paths and thresholds for itunes_cleanup.

Edit this file to adapt the package to a different library layout.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Library source
# ---------------------------------------------------------------------------

LIBRARY_ROOT = Path("~/Music/Music/iTunes/iTunes Media/Music").expanduser()

# ---------------------------------------------------------------------------
# Archive destinations
# ---------------------------------------------------------------------------

ARCHIVE_VOICE      = Path("~/Documents/Voice Notes").expanduser()
ARCHIVE_LONG_AUDIO = Path("~/Music/Archive/Long Audio Files").expanduser()
ARCHIVE_BOUNCES    = Path("~/Music/Archive/Production Bounces").expanduser()
ARCHIVE_MIXES      = Path("~/Music/Archive/My Mixes and Demos").expanduser()

# ---------------------------------------------------------------------------
# Logs and reports
# ---------------------------------------------------------------------------

LOG_DIR = Path("~/Music/Archive/logs").expanduser()

# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------

# Files at or above this duration are classified as long_audio
LONG_AUDIO_THRESHOLD_MINUTES = 10

# Keywords triggering mix_demo classification (matched case-insensitively
# against the filename stem)
# Stored as regex patterns so each keyword can control its own boundaries.
# "vol" uses \bvol\d*\b to match vol, vol1, vol2 etc.
MIX_KEYWORDS = [
    r"\bmix\b",
    r"\bdemo\b",
    r"\bset\b",
    r"\bvol\d*\b",
    r"\bdj\s+set\b",
]

# Extensions treated as likely production bounces when found outside an
# already-tagged bounce folder
BOUNCE_EXTENSIONS = {".wav", ".aiff", ".aif"}

# Top-level artist folder names (under LIBRARY_ROOT) that contain the user's
# own productions. Files here are treated as bounces unless they contain
# BOUNCE_RELEASED_MARKER in the filename stem (those are finished releases).
# Example: {"your artist name", "your artist name feat. someone"}
BOUNCE_ARTIST_FOLDERS: set[str] = set()

# Files in a BOUNCE_ARTIST_FOLDER whose stem contains this string
# (case-insensitive) are kept as clean — they are finished releases.
BOUNCE_RELEASED_MARKER = "released"

# Regex patterns matched against the filename stem (case-insensitive).
# A file in the Unknown Artist folder matching ANY of these is a bounce.
BOUNCE_PRODUCTION_PATTERNS = [
    r"^landr-",                      # LANDR mastered export
    r"\bv\d+[\d\.]*[a-z]?\b",       # version numbers: v1, v3.2, v5.10b
    r"\b(ozone|groovestation|rough|wip|bounce|instrumental)\b",
    r"\balt\s+edit\b",
]

# ---------------------------------------------------------------------------
# Tag contamination patterns (dirty_tag detection)
# ---------------------------------------------------------------------------

# If any of these strings appear in the artist or album tag the file is
# flagged dirty_tag = True.  Checked case-insensitively.
URL_PATTERNS = [
    "http",
    "www.",
    ".com",
    ".net",
    ".org",
    ".uk",
    ".blogspot",
]

# ---------------------------------------------------------------------------
# Voice memo detection
# ---------------------------------------------------------------------------

# Files under a "Voice Memos" folder are always voice memos. Voice memos synced
# from a phone may instead carry the device name as the artist tag; list those
# names here (matched case-insensitively), e.g. {"alex's iphone"}.
VOICE_MEMO_ARTISTS: set[str] = set()

# ---------------------------------------------------------------------------
# Manual classification overrides
# ---------------------------------------------------------------------------

# Matched against the file stem (filename without extension), case-insensitively.
# Applied before any other rule, so entries here win over duration, path, and
# keyword checks. Use this for genuine long tracks that should stay in the
# library ("clean"), or productions that should go to a specific destination
# despite not matching the automatic patterns.
#
# Valid values: "clean", "voice_memo", "long_audio", "bounce", "mix_demo"
# Example:
#     "Some Artist - Long Album Track": "clean",   # genuine long release, keep it
#     "My Track v3":                    "bounce",  # production file
MANUAL_OVERRIDES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aiff", ".aif", ".flac"}

# ---------------------------------------------------------------------------
# Personal overrides
# ---------------------------------------------------------------------------

# Put your own library-specific values (artist folders, overrides, device
# names, paths) in local_config.py next to this file. It is git-ignored, so
# your settings stay out of the repository and survive updates. Any name
# defined there replaces the default above.
try:
    from .local_config import *  # noqa: F401,F403
except ImportError:
    pass
