"""
remove_library.py — Remove archived tracks from Music.app via osascript.

Builds a single batched AppleScript containing all file paths and executes it
in one osascript call, avoiding the per-track IPC overhead of the previous
AppleScript approach.

Requires macOS and Music.app.  All other phases are platform-agnostic.

Usage:
    python remove_library.py --input tracks_to_remove.txt           # dry-run
    python remove_library.py --input tracks_to_remove.txt --execute # remove
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config
from .summary import RunResult, write_summary

# ---------------------------------------------------------------------------
# Batch size: number of paths per osascript call.
# Keeping batches at ~150 avoids hitting AppleScript list-size edge cases
# while still being far fewer round-trips than one call per track.
# ---------------------------------------------------------------------------
BATCH_SIZE = 150

# ---------------------------------------------------------------------------
# Input file
# ---------------------------------------------------------------------------

def read_paths_file(path: Path) -> list[str]:
    """
    Read a newline-delimited list of file paths.
    Skips blank lines and lines starting with #.
    """
    paths = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                paths.append(line)
    return paths


# ---------------------------------------------------------------------------
# AppleScript generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# APPLESCRIPT SAFETY RULES — read before editing build_applescript()
#
# Inside a `tell application "Music"` block, EVERY unqualified command is
# dispatched to Music.app, not to the OS.  This causes silent, dangerous bugs:
#
#   exists POSIX file p   →  Music.app returns false for ALL paths (no `exists`)
#   do shell script "..."  →  sent to Music.app, fails silently
#   aPath as string        →  Music.app type coercion, result ≠ plain text
#
# Rules:
#   • Pre-process path strings with `as text` BEFORE the tell block.
#   • Never check file existence inside the tell block; do it in Python first.
#   • Never run shell commands inside the tell block.
#   • Use `as text` (not `as string`) for AppleScript type coercion.
# ---------------------------------------------------------------------------


def _as_escape(path: str) -> str:
    """Escape a path for use inside an AppleScript double-quoted string."""
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_applescript(paths: list[str]) -> str:
    """
    Build an AppleScript that removes all paths from Music.app in one pass.

    Iterates all library tracks ONCE, checking each track's POSIX path against
    the target list (in-memory comparisons).  This avoids both the unreliable
    `whose location is POSIX file` filter predicate AND the O(paths × tracks)
    IPC overhead of the previous nested-loop approach.

    Key correctness fix: target paths are pre-processed as AppleScript `text`
    BEFORE the `tell application "Music"` block.  Inside a tell block, `as
    string` is dispatched to Music.app's type system and returns a value that
    does not compare equal to a plain text string, causing all matches to fail.

    Returns a structured result string:
      REMOVED:N<<<SEP>>>TRASHED:N<<<SEP>>>NOT_FOUND:N[<<<SEP>>>ERROR:path ...]
    """
    items = ", ".join(f'"{_as_escape(p)}"' for p in paths)

    return f"""\
-- Pre-process target paths as native AppleScript text BEFORE entering the
-- tell block.  Inside `tell application "Music"`, `as string` is coerced by
-- Music.app and produces a value that does not compare equal to plain text.
set rawPaths to {{{items}}}
set targetPaths to {{}}
repeat with rawRef in rawPaths
    set end of targetPaths to rawRef as text
end repeat

set removedCount to 0
set trashedCount to 0
set foundCount to 0
set errorLines to {{}}
set SEP to "<<<SEP>>>"

tell application "Music"
    set lib to library playlist 1
    set allTracks to every track of lib
    -- Single pass over the library: for each track, check whether its POSIX
    -- path appears in targetPaths (in-memory comparison — no extra IPC calls).
    repeat with aTrack in allTracks
        try
            set tLoc to location of aTrack
            if tLoc is not missing value then
                set p to POSIX path of tLoc
                set matchedPath to ""
                repeat with i from 1 to (count of targetPaths)
                    if p is item i of targetPaths then
                        set matchedPath to p
                        exit repeat
                    end if
                end repeat
                if matchedPath is not "" then
                    set foundCount to foundCount + 1
                    try
                        delete aTrack
                        set removedCount to removedCount + 1
                    on error errMsg
                        set end of errorLines to "ERROR:" & matchedPath & " - " & errMsg
                    end try
                    try
                        tell application "Finder"
                            move (POSIX file matchedPath as alias) to trash
                        end tell
                        set trashedCount to trashedCount + 1
                    on error
                        set end of errorLines to "TRASH_ERROR:" & matchedPath
                    end try
                end if
            end if
        on error
            -- URL track or inaccessible track — skip silently
        end try
    end repeat
end tell

set notFoundCount to (count of targetPaths) - foundCount
set resultStr to "REMOVED:" & removedCount & SEP & "TRASHED:" & trashedCount & SEP & "NOT_FOUND:" & notFoundCount
repeat with errLine in errorLines
    set resultStr to resultStr & SEP & errLine
end repeat
return resultStr
"""


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

SEP = "<<<SEP>>>"


def parse_applescript_result(output: str) -> dict:
    """
    Parse the structured string returned by build_applescript().

    Returns:
      {"removed": int, "trashed": int, "not_found": int, "errors": [str]}
    """
    result = {"removed": 0, "trashed": 0, "not_found": 0, "errors": []}
    for part in output.strip().split(SEP):
        part = part.strip()
        if part.startswith("REMOVED:"):
            result["removed"] = int(part[8:])
        elif part.startswith("TRASHED:"):
            result["trashed"] = int(part[8:])
        elif part.startswith("NOT_FOUND:"):
            result["not_found"] = int(part[10:])
        elif part.startswith(("ERROR:", "TRASH_ERROR:")):
            result["errors"].append(part)
    return result


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_batch(paths: list[str]) -> dict:
    """
    Execute one batch of paths via a single osascript call.
    Returns a parsed result dict (see parse_applescript_result).
    """
    script = build_applescript(paths)

    # Write to a temp file — avoids shell-escaping the entire script string
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".applescript", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(script)
        tf_path = tf.name

    try:
        proc = subprocess.run(
            ["osascript", tf_path],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {
                "removed": 0, "trashed": 0, "not_found": 0,
                "errors": [f"osascript error: {proc.stderr.strip()}"],
            }
        return parse_applescript_result(proc.stdout)
    finally:
        Path(tf_path).unlink(missing_ok=True)


def remove_from_library(
    paths: list[str],
    execute: bool = False,
    log_dir: Path = config.LOG_DIR,
) -> RunResult:
    """
    Remove a list of file paths from Music.app.

    execute=False (default): dry-run only, no osascript called.
    execute=True: runs in batches of BATCH_SIZE, writes summary + log.
    """
    from datetime import datetime
    result = RunResult(phase="remove_library", started_at=datetime.now())
    result.processed = len(paths)

    if not execute:
        print(f"DRY RUN — would remove {len(paths)} tracks from Music.app")
        for p in paths:
            print(f"  {Path(p).name[:80]}")
        print("\nRe-run with --execute to proceed.")
        return result

    # Process in batches
    batches = [paths[i:i + BATCH_SIZE] for i in range(0, len(paths), BATCH_SIZE)]
    print(f"Removing {len(paths)} tracks in {len(batches)} batch(es)...")

    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} ({len(batch)} tracks)...", flush=True)
        batch_result = run_batch(batch)
        result.removed_from_library += batch_result["removed"]
        result.trashed              += batch_result["trashed"]
        result.not_found            += batch_result["not_found"]
        for err in batch_result["errors"]:
            result.failed += 1
            result.errors.append(("(batch)", err))

    result.finished_at = datetime.now()

    summary_path = write_summary(result, log_dir)
    print(f"\nRemoved from library : {result.removed_from_library}")
    print(f"Moved to Trash       : {result.trashed}")
    print(f"Not found            : {result.not_found}")
    print(f"Errors               : {result.failed}")
    print(f"Summary written to   : {summary_path}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Remove archived tracks from Music.app."
    )
    parser.add_argument("--input",   required=True, type=Path,
                        help="File containing one path per line")
    parser.add_argument("--execute", action="store_true",
                        help="Actually remove tracks (default is dry-run)")
    parser.add_argument("--log-dir", type=Path, default=config.LOG_DIR,
                        help="Directory for summary + run log")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    paths = read_paths_file(args.input)
    if not paths:
        print("No paths found in input file.")
        sys.exit(0)

    remove_from_library(paths, execute=args.execute, log_dir=args.log_dir.expanduser())


if __name__ == "__main__":
    main()
