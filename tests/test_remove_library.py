"""
tests/test_remove_library.py

Tests for the parts of remove_library.py that don't require Music.app:
  - read_paths_file        (input parsing)
  - _as_escape             (AppleScript string escaping)
  - build_applescript      (script structure)
  - parse_applescript_result (output parsing)
  - batching logic

osascript execution is NOT tested here — it requires macOS + Music.app running.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import itunes_cleanup.remove_library as rl


# ---------------------------------------------------------------------------
# read_paths_file
# ---------------------------------------------------------------------------

class TestReadPathsFile:
    def test_reads_plain_paths(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("/a/b/track1.mp3\n/a/b/track2.mp3\n")
        assert rl.read_paths_file(f) == ["/a/b/track1.mp3", "/a/b/track2.mp3"]

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("/a/track1.mp3\n\n/a/track2.mp3\n\n")
        assert len(rl.read_paths_file(f)) == 2

    def test_skips_comment_lines(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("# header comment\n/a/track1.mp3\n# another comment\n/a/track2.mp3\n")
        result = rl.read_paths_file(f)
        assert result == ["/a/track1.mp3", "/a/track2.mp3"]

    def test_strips_trailing_whitespace(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("/a/track1.mp3  \n/a/track2.mp3\t\n")
        assert rl.read_paths_file(f) == ["/a/track1.mp3", "/a/track2.mp3"]

    def test_empty_file_returns_empty_list(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("")
        assert rl.read_paths_file(f) == []

    def test_paths_with_spaces(self, tmp_path):
        f = tmp_path / "paths.txt"
        f.write_text("/Users/alex/Music/My Mix.mp3\n")
        assert rl.read_paths_file(f) == ["/Users/alex/Music/My Mix.mp3"]


# ---------------------------------------------------------------------------
# AppleScript escaping
# ---------------------------------------------------------------------------

class TestAsEscape:
    def test_normal_path_unchanged(self):
        assert rl._as_escape("/Users/alex/Music/track.mp3") == "/Users/alex/Music/track.mp3"

    def test_double_quote_escaped(self):
        assert rl._as_escape('/path/with "quotes".mp3') == '/path/with \\"quotes\\".mp3'

    def test_backslash_escaped(self):
        assert rl._as_escape("/path/with\\backslash.mp3") == "/path/with\\\\backslash.mp3"

    def test_spaces_in_path_unchanged(self):
        path = "/Users/alex/Music/My Mixes/April Mix.mp3"
        assert rl._as_escape(path) == path


# ---------------------------------------------------------------------------
# build_applescript
# ---------------------------------------------------------------------------

class TestBuildApplescript:
    def test_contains_all_paths(self):
        paths = ["/a/track1.mp3", "/b/track2.mp3", "/c/track3.mp3"]
        script = rl.build_applescript(paths)
        for p in paths:
            assert p in script

    def test_contains_music_app_tell_block(self):
        script = rl.build_applescript(["/a/track.mp3"])
        assert 'tell application "Music"' in script

    def test_contains_delete_statement(self):
        assert "delete aTrack" in rl.build_applescript(["/a/track.mp3"])

    def test_contains_trash_statement(self):
        assert "move" in rl.build_applescript(["/a/track.mp3"])
        assert "trash" in rl.build_applescript(["/a/track.mp3"])

    def test_contains_sep_delimiter(self):
        assert rl.SEP in rl.build_applescript(["/a/track.mp3"])

    def test_paths_quoted_in_list(self):
        script = rl.build_applescript(["/a/track.mp3"])
        assert '"/a/track.mp3"' in script

    def test_path_with_spaces_quoted_correctly(self):
        script = rl.build_applescript(["/Users/alex/My Mix.mp3"])
        assert '"/Users/alex/My Mix.mp3"' in script

    def test_path_with_quote_char_escaped(self):
        script = rl.build_applescript(['/path/with "quotes".mp3'])
        assert '\\"quotes\\"' in script

    def test_multiple_paths_form_list(self):
        paths = ["/a/1.mp3", "/b/2.mp3"]
        script = rl.build_applescript(paths)
        # Both paths should appear inside a single AppleScript list {}
        assert '"/a/1.mp3"' in script
        assert '"/b/2.mp3"' in script

    def test_empty_path_list_still_generates_valid_script(self):
        script = rl.build_applescript([])
        assert "tell application" in script
        assert "return resultStr" in script


# ---------------------------------------------------------------------------
# parse_applescript_result
# ---------------------------------------------------------------------------

class TestParseApplescriptResult:
    def test_parses_counts(self):
        output = "REMOVED:30<<<SEP>>>TRASHED:30<<<SEP>>>NOT_FOUND:1"
        result = rl.parse_applescript_result(output)
        assert result["removed"]   == 30
        assert result["trashed"]   == 30
        assert result["not_found"] == 1
        assert result["errors"]    == []

    def test_parses_errors(self):
        output = "REMOVED:2<<<SEP>>>TRASHED:2<<<SEP>>>NOT_FOUND:0<<<SEP>>>ERROR:/a/bad.mp3"
        result = rl.parse_applescript_result(output)
        assert result["removed"] == 2
        assert len(result["errors"]) == 1
        assert "ERROR:/a/bad.mp3" in result["errors"]

    def test_parses_multiple_errors(self):
        parts = ["REMOVED:1", "TRASHED:1", "NOT_FOUND:0",
                 "ERROR:/a/bad1.mp3", "ERROR:/a/bad2.mp3"]
        output = rl.SEP.join(parts)
        result = rl.parse_applescript_result(output)
        assert len(result["errors"]) == 2

    def test_parses_trash_error(self):
        output = "REMOVED:1<<<SEP>>>TRASHED:0<<<SEP>>>NOT_FOUND:0<<<SEP>>>TRASH_ERROR:/a/track.mp3"
        result = rl.parse_applescript_result(output)
        assert any("TRASH_ERROR" in e for e in result["errors"])

    def test_all_zeros_not_found(self):
        output = "REMOVED:0<<<SEP>>>TRASHED:0<<<SEP>>>NOT_FOUND:5"
        result = rl.parse_applescript_result(output)
        assert result["not_found"] == 5
        assert result["removed"]   == 0

    def test_handles_whitespace_in_output(self):
        output = "  REMOVED:10<<<SEP>>>TRASHED:10<<<SEP>>>NOT_FOUND:0  "
        result = rl.parse_applescript_result(output)
        assert result["removed"] == 10


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------

class TestBatching:
    def test_single_batch_for_small_list(self):
        paths = [f"/track{i}.mp3" for i in range(10)]
        batches = [paths[i:i + rl.BATCH_SIZE] for i in range(0, len(paths), rl.BATCH_SIZE)]
        assert len(batches) == 1

    def test_multiple_batches_for_large_list(self):
        paths = [f"/track{i}.mp3" for i in range(rl.BATCH_SIZE + 1)]
        batches = [paths[i:i + rl.BATCH_SIZE] for i in range(0, len(paths), rl.BATCH_SIZE)]
        assert len(batches) == 2

    def test_all_paths_covered_across_batches(self):
        paths = [f"/track{i}.mp3" for i in range(rl.BATCH_SIZE * 3 + 7)]
        batches = [paths[i:i + rl.BATCH_SIZE] for i in range(0, len(paths), rl.BATCH_SIZE)]
        assert sum(len(b) for b in batches) == len(paths)

    def test_last_batch_may_be_smaller(self):
        paths = [f"/track{i}.mp3" for i in range(rl.BATCH_SIZE + 5)]
        batches = [paths[i:i + rl.BATCH_SIZE] for i in range(0, len(paths), rl.BATCH_SIZE)]
        assert len(batches[-1]) == 5
