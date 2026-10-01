"""
archive.py — Copy → verify → delete for classified audio files.

Core operations (used by tests and the CLI):
  hash_file(path)              → SHA-256 hex digest
  verify_copy(source, dest)    → True if hashes match
  resolve_destination(source, dest_dir) → (dest_path, action)
  copy_and_verify(source, dest_dir)     → result dict

CLI (phase 2):
  python archive.py --input audit.tsv [--classes voice_memo,bounce] [--execute]
  Default is dry-run; --execute is required to copy and delete.
"""

import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import config

# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

CHUNK = 1 << 20  # 1 MB read chunks


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_copy(source: Path, dest: Path) -> bool:
    """
    Return True if source and dest exist and have identical SHA-256 hashes.
    Returns False (without raising) if either file is missing or unreadable.
    """
    try:
        return hash_file(source) == hash_file(dest)
    except (FileNotFoundError, OSError):
        return False


# ---------------------------------------------------------------------------
# Destination resolution
# ---------------------------------------------------------------------------

def resolve_destination(source: Path, dest_dir: Path) -> tuple[Path, str]:
    """
    Determine the actual destination path for copying source into dest_dir.

    Returns (dest_path, action) where action is one of:
      "copy"   — no filename conflict; proceed normally
      "skip"   — an archived file with this name (or one of its
                 "(potential duplicate N)" variants) has identical contents
                 (SHA-256); the source is already archived
      "rename" — files with this name exist but none has identical contents;
                 dest_path has a "(potential duplicate N)" suffix to avoid
                 clobbering
    """
    candidate = dest_dir / source.name
    if not candidate.exists():
        return candidate, "copy"

    stem = source.stem
    suffix = source.suffix
    n = 0
    while candidate.exists():
        # The "existing copy" must be a separate file. If it is the source
        # itself (dest_dir is the source's folder, or a symlink/hard link to
        # it), there is no archive copy, so treating it as "already
        # archived" would queue the only copy for removal.
        if os.path.samefile(source, candidate):
            raise ValueError(f"Archive destination {candidate} is the source file itself")
        # Size is a cheap pre-check; only hash when sizes match.
        if candidate.stat().st_size == source.stat().st_size and verify_copy(source, candidate):
            return candidate, "skip"
        n += 1
        candidate = dest_dir / f"{stem} (potential duplicate {n}){suffix}"
    return candidate, "rename"


# ---------------------------------------------------------------------------
# Copy and verify (single file)
# ---------------------------------------------------------------------------

def copy_and_verify(source: Path, dest_dir: Path) -> dict:
    """
    Copy source to dest_dir, verify the copy, delete source if verified.

    Returns a result dict:
      {
        "source":   Path,
        "dest":     Path,
        "action":   "copied" | "skipped" | "renamed" | "failed",
        "verified": bool,
        "deleted":  bool,
        "error":    str | None,
      }
    """
    result = {
        "source":   source,
        "dest":     None,
        "action":   None,
        "verified": False,
        "deleted":  False,
        "error":    None,
    }

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path, resolution = resolve_destination(source, dest_dir)
        result["dest"] = dest_path

        if resolution == "skip":
            result["action"] = "skipped"
            result["verified"] = True   # existing copy has identical SHA-256
            result["deleted"] = False   # caller handles library removal
            return result

        shutil.copy2(source, dest_path)

        if verify_copy(source, dest_path):
            result["action"] = "renamed" if resolution == "rename" else "copied"
            result["verified"] = True
            # Unlink is best-effort: permission errors (e.g. files owned by a
            # different user account) are non-fatal — the verified copy is safe
            # and remove_library.py will handle deletion via Finder/Trash.
            try:
                source.unlink()
                result["deleted"] = True
            except PermissionError:
                result["deleted"] = False
        else:
            dest_path.unlink(missing_ok=True)
            result["action"] = "failed"
            result["error"] = "Hash mismatch after copy — source preserved"

    except Exception as exc:
        result["action"] = "failed"
        result["error"] = str(exc)

    return result


def check_destinations(dest_dirs, library_root: Path) -> list[str]:
    """
    Return an error message for each archive destination that lies inside
    the music library. Archiving into the library would leave the "archive"
    copy where the cleanup (and Music.app) can still find and remove it.
    """
    root = library_root.expanduser().resolve()
    errors = []
    for d in dest_dirs:
        resolved = Path(d).expanduser().resolve()
        if resolved == root or root in resolved.parents:
            errors.append(f"Archive destination {d} is inside the library ({library_root})")
    return errors


# ---------------------------------------------------------------------------
# Destination map
# ---------------------------------------------------------------------------

DEST_MAP = {
    "voice_memo": config.ARCHIVE_VOICE,
    "long_audio": config.ARCHIVE_LONG_AUDIO,
    "bounce":     config.ARCHIVE_BOUNCES,
    "mix_demo":   config.ARCHIVE_MIXES,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Archive classified audio files: copy → verify → delete."
    )
    parser.add_argument("--input",   required=True, type=Path,
                        help="Audit TSV produced by audit.py")
    parser.add_argument("--classes", default=",".join(DEST_MAP.keys()),
                        help="Comma-separated classifications to archive "
                             f"(default: all — {','.join(DEST_MAP.keys())})")
    parser.add_argument("--execute", action="store_true",
                        help="Actually copy and delete (default is dry-run)")
    args = parser.parse_args()

    wanted = {c.strip() for c in args.classes.split(",")}
    unknown = wanted - set(DEST_MAP)
    if unknown:
        print(f"Error: unknown class(es): {', '.join(unknown)}", file=sys.stderr)
        sys.exit(1)

    dest_errors = check_destinations({DEST_MAP[c] for c in wanted}, config.LIBRARY_ROOT)
    if dest_errors:
        for e in dest_errors:
            print(f"Error: {e}", file=sys.stderr)
        print("Change the ARCHIVE_* paths in config.py / local_config.py.", file=sys.stderr)
        sys.exit(1)

    rows = list(csv.DictReader(open(args.input), delimiter="\t"))
    targets = [r for r in rows if r["classification"] in wanted]

    if not args.execute:
        print(f"DRY RUN — would archive {len(targets)} files:")
        for r in targets:
            dest = DEST_MAP[r["classification"]]
            print(f"  [{r['classification']:<12}] {Path(r['filepath']).name[:60]}  →  {dest}")
        print("\nRe-run with --execute to proceed.")
        return

    counts = {"copied": 0, "skipped": 0, "renamed": 0, "failed": 0}
    errors = []
    # Paths confirmed safe in destination — written to tracks_to_remove file
    # for the subsequent remove_library phase.
    # Includes: copied+verified, renamed+verified, skipped (identical copy already archived).
    ready_to_remove: list[str] = []

    for i, row in enumerate(targets, 1):
        source = Path(row["filepath"])
        dest_dir = DEST_MAP[row["classification"]]
        print(f"  [{i}/{len(targets)}] {source.name[:60]}", end=" ... ", flush=True)

        if not source.exists():
            print("MISSING")
            counts["failed"] += 1
            errors.append(f"Source missing: {source}")
            continue

        result = copy_and_verify(source, dest_dir)
        counts[result["action"]] += 1
        print(result["action"].upper())
        if result["error"]:
            errors.append(f"{source}: {result['error']}")
        if result["action"] in {"copied", "renamed", "skipped"}:
            ready_to_remove.append(str(source))

    # Write tracks_to_remove file — input for remove_library.py
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = config.LOG_DIR.expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    remove_path = log_dir / f"tracks_to_remove_{timestamp}.txt"
    remove_path.write_text("\n".join(ready_to_remove) + "\n", encoding="utf-8")

    print(f"\nDone — copied:{counts['copied']}  skipped:{counts['skipped']}  "
          f"renamed:{counts['renamed']}  failed:{counts['failed']}")
    print(f"Tracks queued for library removal: {len(ready_to_remove)}")
    print(f"Remove list written to: {remove_path}")
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
