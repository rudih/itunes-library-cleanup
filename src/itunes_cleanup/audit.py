"""
audit.py — Scan the iTunes library, classify every audio file, write a TSV report.

This phase is read-only: no files are moved or modified.

Usage:
    python audit.py
    python audit.py --library ~/path/to/iTunes/Media/Music --output ~/Desktop
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.aiff import AIFF
from mutagen.wave import WAVE

from . import config

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Priority order mirrors REQUIREMENTS §3:
#   voice_memo > long_audio > bounce > mix_demo > dirty_tag(flag only) > clean

def _has_url(value: str) -> bool:
    """Return True if value contains any known URL pattern."""
    v = value.lower()
    return any(pat.lower() in v for pat in config.URL_PATTERNS)


def _is_dirty_tag(artist: str, album: str) -> bool:
    return _has_url(artist) or _has_url(album)


def _is_voice_memo(path: Path, artist: str) -> bool:
    parts_lower = [p.lower() for p in path.parts]
    return (
        "voice memos" in parts_lower
        or artist.lower() in {name.lower() for name in config.VOICE_MEMO_ARTISTS}
    )


def _is_long_audio(duration_s: float | None) -> bool:
    if duration_s is None:
        return False
    return duration_s >= config.LONG_AUDIO_THRESHOLD_MINUTES * 60


def _is_bounce(path: Path, library_root: Path = config.LIBRARY_ROOT, reliable_only: bool = False) -> bool:
    """
    Return True if this file should be classified as a production bounce.

    reliable_only=True checks only signals that are definitive regardless of
    filename (folder membership, LANDR prefix, own-artist folder).  This tier
    runs before mix_demo in classify() so that folder signals always win.

    reliable_only=False (default) additionally checks Unknown Artist +
    production filename patterns.  This tier runs AFTER mix_demo so that a
    file with both a version number and a mix keyword goes to mix_demo.
    """
    parts_lower = [p.lower() for p in path.parts]

    # Reliable signal 1: already organised into a production bounces folder
    if "production bounces" in parts_lower:
        return True

    # Reliable signal 2: LANDR- prefix — always a mastered bounce export
    if path.name.lower().startswith("landr-"):
        return True

    try:
        rel = path.relative_to(library_root)
        top = rel.parts[0].lower() if rel.parts else ""

        # Reliable signal 3: user's own artist folder, not a finished release
        if top in {f.lower() for f in config.BOUNCE_ARTIST_FOLDERS}:
            if config.BOUNCE_RELEASED_MARKER.lower() not in path.stem.lower():
                return True

        # Pattern-based signal: Unknown Artist + production filename patterns.
        # Only checked when reliable_only=False (after mix_demo in priority order).
        if not reliable_only and top == "unknown artist":
            stem = path.stem
            if any(re.search(pat, stem, re.I) for pat in config.BOUNCE_PRODUCTION_PATTERNS):
                return True

    except ValueError:
        pass

    # Pattern-based signal: date-stamped or track-numbered bounce extension.
    if not reliable_only and path.suffix.lower() in config.BOUNCE_EXTENSIONS:
        stem = path.stem.lower()
        if stem.startswith("track ") or stem[:2].isdigit():
            return True

    return False


def _is_mix_demo(path: Path) -> bool:
    parts_lower = [p.lower() for p in path.parts]
    if "my mixes" in " ".join(parts_lower):
        return True
    # Strip parenthetical and bracketed version labels like "(Original Mix)",
    # "[Tube & Berger Remix]", "(DJ MATUYA REMIX)" so standard dance track
    # suffixes don't match. Replace underscores with spaces so aug_mix_
    # alternative is still found. Use word-boundary matching so "Remix" and
    # "remixed" don't trigger on the "mix" substring.
    stem = path.stem.lower()
    stem = re.sub(r"\([^)]*\)", "", stem)   # strip (...)
    stem = re.sub(r"\[[^\]]*\]", "", stem)  # strip [...]
    stem = stem.replace("_", " ").strip()
    # MIX_KEYWORDS are stored as regex patterns
    return any(re.search(kw, stem, re.I) for kw in config.MIX_KEYWORDS)


def classify(
    path: Path,
    artist: str,
    album: str,
    duration_s: float | None,
    library_root: Path = config.LIBRARY_ROOT,
) -> str:
    """
    Return the movement classification for a file.
    Priority: manual_override > voice_memo > long_audio > bounce > mix_demo > clean
    """
    stem_lower = path.stem.lower()
    for pattern, override in config.MANUAL_OVERRIDES.items():
        if pattern.lower() == stem_lower:
            return override

    if _is_voice_memo(path, artist):
        return "voice_memo"
    if _is_long_audio(duration_s):
        return "long_audio"
    if _is_bounce(path, library_root, reliable_only=True):
        return "bounce"
    if _is_mix_demo(path):
        return "mix_demo"
    if _is_bounce(path, library_root, reliable_only=False):
        return "bounce"
    return "clean"


# ---------------------------------------------------------------------------
# Tag reading
# ---------------------------------------------------------------------------

def _read_tags(path: Path) -> dict:
    """
    Extract artist, title, album, and duration from an audio file.
    Returns a dict with string values; empty string if tag is absent.
    Duration is in seconds (float) or None if unreadable.
    """
    result = {"artist": "", "title": "", "album": "", "duration_s": None}
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return result

        def _first(tag_values) -> str:
            if tag_values:
                return str(tag_values[0]).strip()
            return ""

        result["artist"]   = _first(audio.get("artist"))
        result["title"]    = _first(audio.get("title"))
        result["album"]    = _first(audio.get("album"))

        if hasattr(audio, "info") and hasattr(audio.info, "length"):
            result["duration_s"] = audio.info.length
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_library(library_root: Path) -> list[dict]:
    """
    Recursively scan library_root for audio files.
    Returns a list of row dicts ready for TSV output.
    """
    rows = []
    files = [
        p for p in library_root.rglob("*")
        if p.is_file() and p.suffix.lower() in config.AUDIO_EXTENSIONS
    ]

    total = len(files)
    for i, path in enumerate(sorted(files), 1):
        if i % 500 == 0 or i == total:
            print(f"  Scanning {i}/{total}...", end="\r", flush=True)

        tags = _read_tags(path)
        classification = classify(
            path,
            tags["artist"],
            tags["album"],
            tags["duration_s"],
        )
        dirty = _is_dirty_tag(tags["artist"], tags["album"])

        rows.append({
            "filepath":       str(path),
            "classification": classification,
            "dirty_tag":      "1" if dirty else "0",
            "artist":         tags["artist"],
            "title":          tags["title"],
            "album":          tags["album"],
            "duration_s":     f"{tags['duration_s']:.1f}" if tags["duration_s"] is not None else "",
            "size_bytes":     str(path.stat().st_size),
        })

    print()  # newline after progress line
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "filepath",
    "classification",
    "dirty_tag",
    "artist",
    "title",
    "album",
    "duration_s",
    "size_bytes",
]


def write_report(rows: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"audit_{timestamp}.tsv"

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    return report_path


def print_summary(rows: list[dict]) -> None:
    from collections import Counter
    counts = Counter(r["classification"] for r in rows)
    dirty  = sum(1 for r in rows if r["dirty_tag"] == "1")
    total  = len(rows)

    print(f"\nAudit complete — {total} files scanned")
    print(f"  voice_memo  : {counts['voice_memo']:>5}")
    print(f"  long_audio  : {counts['long_audio']:>5}")
    print(f"  bounce      : {counts['bounce']:>5}")
    print(f"  mix_demo    : {counts['mix_demo']:>5}")
    print(f"  clean       : {counts['clean']:>5}")
    print(f"  dirty_tag   : {dirty:>5}  (flag — may overlap with above)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan the iTunes library and produce a classification report."
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=config.LIBRARY_ROOT,
        help="Path to iTunes Media/Music folder (default: from config.py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=config.LOG_DIR,
        help="Directory to write the audit TSV (default: LOG_DIR from config.py)",
    )
    args = parser.parse_args()

    library = args.library.expanduser()
    output  = args.output.expanduser()

    if not library.exists():
        print(f"Error: library path does not exist: {library}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {library}")
    rows = scan_library(library)

    report_path = write_report(rows, output)
    print_summary(rows)
    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    main()
