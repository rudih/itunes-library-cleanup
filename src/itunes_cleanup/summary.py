"""
summary.py — Write a human-readable summary report and append to the run log.

Called automatically at the end of any phase that modifies files, or manually:
    python summary.py --help

The run log (run_log.tsv) accumulates one line per run, forever.
Each summary report is a separate timestamped .txt file.
"""

import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from . import config

# ---------------------------------------------------------------------------
# Run result data structure
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """
    Populated by archive.py, fix_tags.py, or remove_library.py and passed
    to write_summary().  All counts default to 0 so callers only set what
    they have.
    """
    phase:       str            # "archive" | "fix_tags" | "remove_library" | "audit"
    started_at:  datetime = field(default_factory=datetime.now)
    finished_at: datetime = field(default_factory=datetime.now)

    # Archive / copy counts
    processed:  int = 0
    copied:     int = 0
    skipped:    int = 0
    renamed:    int = 0
    verified:   int = 0
    failed:     int = 0
    deleted:    int = 0
    data_bytes: int = 0         # total bytes successfully copied

    # Fix-tags counts
    tags_fixed: int = 0

    # Remove-library counts
    removed_from_library: int = 0
    trashed:              int = 0
    not_found:            int = 0

    # Errors: list of (filepath_or_label, message) tuples
    errors: list = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Summary report (.txt)
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_duration(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec}s"


def format_summary(result: RunResult) -> str:
    lines = []
    ts = result.started_at.strftime("%Y-%m-%d %H:%M:%S")
    lines.append("=" * 60)
    lines.append(f"itunes_cleanup — {result.phase.upper()} run")
    lines.append(f"Started:  {ts}")
    lines.append(f"Duration: {_fmt_duration(result.duration_s)}")
    lines.append("=" * 60)

    if result.phase == "archive":
        lines.append(f"  Files processed : {result.processed}")
        lines.append(f"  Copied          : {result.copied}")
        lines.append(f"  Verified        : {result.verified}")
        lines.append(f"  Skipped (dupe)  : {result.skipped}")
        lines.append(f"  Renamed (dupe)  : {result.renamed}")
        lines.append(f"  Deleted (src)   : {result.deleted}")
        lines.append(f"  Failed          : {result.failed}")
        lines.append(f"  Data moved      : {_fmt_bytes(result.data_bytes)}")

    elif result.phase == "fix_tags":
        lines.append(f"  Files processed : {result.processed}")
        lines.append(f"  Tags fixed      : {result.tags_fixed}")
        lines.append(f"  Failed          : {result.failed}")

    elif result.phase == "remove_library":
        lines.append(f"  Files processed      : {result.processed}")
        lines.append(f"  Removed from library : {result.removed_from_library}")
        lines.append(f"  Moved to Trash       : {result.trashed}")
        lines.append(f"  Not found in library : {result.not_found}")
        lines.append(f"  Errors               : {result.failed}")

    elif result.phase == "audit":
        lines.append(f"  Files scanned   : {result.processed}")

    if result.errors:
        lines.append("")
        lines.append(f"ERRORS ({len(result.errors)}):")
        for label, msg in result.errors:
            lines.append(f"  {label}")
            lines.append(f"    → {msg}")
    else:
        lines.append("")
        lines.append("No errors.")

    lines.append("=" * 60)
    return "\n".join(lines) + "\n"


def write_summary(result: RunResult, log_dir: Path = config.LOG_DIR) -> Path:
    """
    Write a timestamped summary .txt to log_dir and append a line to run_log.tsv.
    Returns the path of the summary file written.
    """
    log_dir = Path(log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    # --- summary .txt ---
    ts = result.started_at.strftime("%Y%m%d_%H%M%S")
    summary_path = log_dir / f"summary_{result.phase}_{ts}.txt"
    summary_path.write_text(format_summary(result), encoding="utf-8")

    # --- run_log.tsv (append) ---
    log_path = log_dir / "run_log.tsv"
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        if is_new:
            writer.writerow([
                "timestamp", "phase",
                "processed", "copied", "skipped", "renamed",
                "verified", "failed", "deleted",
                "tags_fixed",
                "removed_from_library", "trashed", "not_found",
                "data_mb", "duration_s", "error_count",
            ])
        writer.writerow([
            result.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            result.phase,
            result.processed,
            result.copied,
            result.skipped,
            result.renamed,
            result.verified,
            result.failed,
            result.deleted,
            result.tags_fixed,
            result.removed_from_library,
            result.trashed,
            result.not_found,
            f"{result.data_bytes / (1024*1024):.2f}",
            f"{result.duration_s:.1f}",
            len(result.errors),
        ])

    return summary_path
