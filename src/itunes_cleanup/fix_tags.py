"""
fix_tags.py — Write corrected tags directly to audio files via mutagen.

Does NOT require Music.app to be running.

Dry-run (default): writes a preview TSV showing proposed changes.
Execute mode:      writes tags to files; does not move anything.

Usage:
    python fix_tags.py --input phase4_fixes.tsv              # dry-run → preview TSV
    python fix_tags.py --input phase4_fixes.tsv --execute    # write tags
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    TIT2, TPE1, TALB, TCON,
)
from mutagen.mp4 import MP4
from mutagen.flac import FLAC

from . import config

# ---------------------------------------------------------------------------
# Tag reading (current state, for preview)
# ---------------------------------------------------------------------------

def current_tags(path: Path) -> dict:
    """
    Return the current artist, title, album, genre tags for a file.
    Returns empty strings for absent or unreadable tags.
    """
    result = {"artist": "", "title": "", "album": "", "genre": ""}
    ext = path.suffix.lower()
    try:
        if ext in {".mp3", ".wav", ".aif", ".aiff"}:
            try:
                tags = ID3(str(path))
            except ID3NoHeaderError:
                return result
            result["artist"] = str(tags.get("TPE1", ""))
            result["title"]  = str(tags.get("TIT2", ""))
            result["album"]  = str(tags.get("TALB", ""))
            result["genre"]  = str(tags.get("TCON", ""))
        elif ext == ".m4a":
            audio = MP4(str(path))
            result["artist"] = (audio.get("\xa9ART") or [""])[0]
            result["title"]  = (audio.get("\xa9nam") or [""])[0]
            result["album"]  = (audio.get("\xa9alb") or [""])[0]
            result["genre"]  = (audio.get("\xa9gen") or [""])[0]
        elif ext == ".flac":
            audio = FLAC(str(path))
            result["artist"] = (audio.get("artist") or [""])[0]
            result["title"]  = (audio.get("title")  or [""])[0]
            result["album"]  = (audio.get("album")  or [""])[0]
            result["genre"]  = (audio.get("genre")  or [""])[0]
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Tag writing
# ---------------------------------------------------------------------------

def write_tags_to_file(
    path: Path,
    new_artist: str,
    new_title: str,
    clear_album: bool,
) -> dict:
    """
    Write corrected tags to an audio file.

    - new_artist / new_title: written only when non-empty
    - clear_album=True: sets album to "" and genre to "Dance"

    Returns {"ok": bool, "error": str|None}
    """
    result = {"ok": False, "error": None}
    ext = path.suffix.lower()
    try:
        if ext in {".mp3", ".wav", ".aif", ".aiff"}:
            _write_id3(path, new_artist, new_title, clear_album)
        elif ext == ".m4a":
            _write_mp4(path, new_artist, new_title, clear_album)
        elif ext == ".flac":
            _write_flac(path, new_artist, new_title, clear_album)
        else:
            result["error"] = f"Unsupported extension: {ext}"
            return result
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _write_id3(path: Path, new_artist: str, new_title: str, clear_album: bool) -> None:
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    if new_artist:
        tags.add(TPE1(encoding=3, text=[new_artist]))
    if new_title:
        tags.add(TIT2(encoding=3, text=[new_title]))
    if clear_album:
        tags.add(TALB(encoding=3, text=[""]))
        tags.add(TCON(encoding=3, text=["Dance"]))
    tags.save(str(path))


def _write_mp4(path: Path, new_artist: str, new_title: str, clear_album: bool) -> None:
    audio = MP4(str(path))
    if new_artist:
        audio["\xa9ART"] = [new_artist]
    if new_title:
        audio["\xa9nam"] = [new_title]
    if clear_album:
        audio["\xa9alb"] = [""]
        audio["\xa9gen"] = ["Dance"]
    audio.save()


def _write_flac(path: Path, new_artist: str, new_title: str, clear_album: bool) -> None:
    audio = FLAC(str(path))
    if new_artist:
        audio["artist"] = [new_artist]
    if new_title:
        audio["title"] = [new_title]
    if clear_album:
        audio["album"] = [""]
        audio["genre"] = ["Dance"]
    audio.save()


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------

FIELDNAMES = ["filepath", "new_artist", "new_title", "clear_album"]


def parse_fixes_tsv(tsv_path: Path) -> list[dict]:
    """
    Parse a fixes TSV file (same format as phase4_fixes.tsv).
    Returns a list of dicts with keys: filepath, new_artist, new_title, clear_album.
    Skips blank lines and lines starting with #.
    """
    rows = []
    with open(tsv_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            rows.append({
                "filepath":    parts[0].strip(),
                "new_artist":  parts[1].strip(),
                "new_title":   parts[2].strip(),
                "clear_album": parts[3].strip(),
            })
    return rows


# ---------------------------------------------------------------------------
# Artist-title splitting heuristic
# ---------------------------------------------------------------------------

def split_artist_from_title(title: str) -> tuple[str, str]:
    """
    If title contains ' - ', treat the left side as the artist and the right
    side as the actual title.  Returns (artist, title).

    Examples:
      "Some Artist - Some Track Part II" → ("Some Artist", "Some Track Part II")
      "Normal Title"                     → ("", "Normal Title")
    """
    if " - " in title:
        artist_part, title_part = title.split(" - ", 1)
        return artist_part.strip(), title_part.strip()
    return "", title


# ---------------------------------------------------------------------------
# Preview TSV
# ---------------------------------------------------------------------------

PREVIEW_FIELDNAMES = [
    "filepath",
    "current_artist", "new_artist",
    "current_title",  "new_title",
    "current_album",  "clear_album",
]


def generate_preview_tsv(fixes: list[dict], output_dir: Path) -> Path:
    """
    Write a preview TSV showing current tags alongside proposed changes.
    Output filename: fix_tags_preview_YYYYMMDD_HHMMSS.tsv
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"fix_tags_preview_{timestamp}.tsv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PREVIEW_FIELDNAMES, delimiter="\t")
        writer.writeheader()
        for fix in fixes:
            p = Path(fix["filepath"])
            cur = current_tags(p) if p.exists() else {"artist": "", "title": "", "album": "", "genre": ""}
            writer.writerow({
                "filepath":       fix["filepath"],
                "current_artist": cur["artist"],
                "new_artist":     fix["new_artist"],
                "current_title":  cur["title"],
                "new_title":      fix["new_title"],
                "current_album":  cur["album"],
                "clear_album":    fix["clear_album"],
            })
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fix URL-contaminated tags in audio files."
    )
    parser.add_argument("--input",   required=True, type=Path,
                        help="TSV file: filepath|new_artist|new_title|clear_album")
    parser.add_argument("--execute", action="store_true",
                        help="Write tags (default is dry-run → preview TSV)")
    parser.add_argument("--output",  type=Path, default=config.LOG_DIR,
                        help="Directory for preview TSV (default: LOG_DIR)")
    args = parser.parse_args()

    fixes = parse_fixes_tsv(args.input)

    if not args.execute:
        preview = generate_preview_tsv(fixes, args.output.expanduser())
        print(f"Dry run — preview written to: {preview}")
        print(f"Review the file, edit if needed, then re-run with --execute.")
        return

    counts = {"fixed": 0, "skipped": 0, "failed": 0}
    errors = []

    for fix in fixes:
        path = Path(fix["filepath"])
        if not path.exists():
            print(f"  MISSING  {path.name}")
            counts["failed"] += 1
            errors.append(f"Missing: {path}")
            continue

        clear = fix["clear_album"] == "1"
        result = write_tags_to_file(path, fix["new_artist"], fix["new_title"], clear)
        if result["ok"]:
            counts["fixed"] += 1
            print(f"  FIXED    {path.name[:70]}")
        else:
            counts["failed"] += 1
            errors.append(f"{path}: {result['error']}")
            print(f"  FAILED   {path.name[:70]}  — {result['error']}")

    print(f"\nDone — fixed:{counts['fixed']}  failed:{counts['failed']}")
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
