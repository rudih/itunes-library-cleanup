"""
tests/test_summary.py — Tests for summary report generation and run log.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from itunes_cleanup.summary import RunResult, format_summary, write_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_result(phase="archive", **kwargs) -> RunResult:
    now = datetime(2026, 3, 22, 10, 0, 0)
    r = RunResult(
        phase=phase,
        started_at=now,
        finished_at=now + timedelta(seconds=kwargs.pop("duration_s", 30)),
        **kwargs,
    )
    return r


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def test_contains_phase_name(self):
        out = format_summary(make_result(phase="archive"))
        assert "ARCHIVE" in out

    def test_contains_timestamp(self):
        out = format_summary(make_result())
        assert "2026-03-22" in out

    def test_contains_duration(self):
        out = format_summary(make_result(duration_s=90))
        assert "1m 30s" in out

    def test_archive_shows_all_counts(self):
        r = make_result(
            phase="archive",
            processed=100, copied=80, skipped=10,
            renamed=5, verified=85, failed=5,
            deleted=85, data_bytes=50 * 1024 * 1024,
        )
        out = format_summary(r)
        assert "100" in out   # processed
        assert "80"  in out   # copied
        assert "50.0 MB" in out

    def test_fix_tags_shows_tags_fixed(self):
        r = make_result(phase="fix_tags", processed=42, tags_fixed=40, failed=2)
        out = format_summary(r)
        assert "40" in out
        assert "fix_tags" in out.lower()

    def test_remove_library_shows_removal_counts(self):
        r = make_result(
            phase="remove_library",
            processed=31, removed_from_library=30, trashed=30, not_found=1,
        )
        out = format_summary(r)
        assert "30" in out
        assert "Not found" in out

    def test_errors_listed_when_present(self):
        r = make_result(errors=[("/some/track.mp3", "Hash mismatch")])
        out = format_summary(r)
        assert "ERRORS" in out
        assert "Hash mismatch" in out
        assert "/some/track.mp3" in out

    def test_no_errors_message_when_clean(self):
        out = format_summary(make_result())
        assert "No errors." in out

    def test_data_bytes_formatted_as_mb(self):
        r = make_result(data_bytes=2 * 1024 * 1024)
        assert "2.0 MB" in format_summary(r)

    def test_data_bytes_formatted_as_gb(self):
        r = make_result(data_bytes=2 * 1024 * 1024 * 1024)
        assert "2.0 GB" in format_summary(r)

    def test_short_duration_shown_in_seconds(self):
        assert "45.0s" in format_summary(make_result(duration_s=45))


# ---------------------------------------------------------------------------
# write_summary — file creation
# ---------------------------------------------------------------------------

class TestWriteSummary:
    def test_creates_summary_txt(self, tmp_path):
        r = make_result(phase="archive", copied=5)
        write_summary(r, log_dir=tmp_path)
        files = list(tmp_path.glob("summary_archive_*.txt"))
        assert len(files) == 1

    def test_summary_txt_contains_expected_content(self, tmp_path):
        r = make_result(phase="archive", copied=5, failed=1)
        path = write_summary(r, log_dir=tmp_path)
        content = path.read_text()
        assert "ARCHIVE" in content
        assert "5" in content

    def test_creates_run_log_tsv(self, tmp_path):
        write_summary(make_result(), log_dir=tmp_path)
        assert (tmp_path / "run_log.tsv").exists()

    def test_run_log_has_header_row(self, tmp_path):
        write_summary(make_result(), log_dir=tmp_path)
        rows = list(csv.reader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        assert rows[0][0] == "timestamp"
        assert "phase" in rows[0]

    def test_run_log_appends_one_row_per_call(self, tmp_path):
        write_summary(make_result(phase="archive"),   log_dir=tmp_path)
        write_summary(make_result(phase="fix_tags"),  log_dir=tmp_path)
        write_summary(make_result(phase="archive"),   log_dir=tmp_path)
        rows = list(csv.reader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        assert len(rows) == 4   # header + 3 data rows

    def test_run_log_header_written_only_once(self, tmp_path):
        for _ in range(3):
            write_summary(make_result(), log_dir=tmp_path)
        rows = list(csv.reader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        headers = [r for r in rows if r[0] == "timestamp"]
        assert len(headers) == 1

    def test_run_log_records_phase(self, tmp_path):
        write_summary(make_result(phase="fix_tags"), log_dir=tmp_path)
        rows = list(csv.DictReader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        assert rows[0]["phase"] == "fix_tags"

    def test_run_log_records_error_count(self, tmp_path):
        r = make_result(errors=[("f1", "e1"), ("f2", "e2")])
        write_summary(r, log_dir=tmp_path)
        rows = list(csv.DictReader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        assert rows[0]["error_count"] == "2"

    def test_run_log_records_data_mb(self, tmp_path):
        r = make_result(data_bytes=10 * 1024 * 1024)
        write_summary(r, log_dir=tmp_path)
        rows = list(csv.DictReader(open(tmp_path / "run_log.tsv"), delimiter="\t"))
        assert rows[0]["data_mb"] == "10.00"

    def test_creates_log_dir_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        write_summary(make_result(), log_dir=nested)
        assert nested.exists()
