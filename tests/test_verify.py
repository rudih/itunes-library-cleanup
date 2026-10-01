"""
tests/test_verify.py — Tests for copy verification and destination resolution.

All tests use pytest's tmp_path fixture for real on-disk files.
No mocking — we test the actual SHA-256 mechanism that guards source deletion.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from itunes_cleanup.archive import hash_file, verify_copy, resolve_destination, copy_and_verify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write(path: Path, content: bytes = b"audio data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------

class TestHashFile:
    def test_same_content_same_hash(self, tmp_path):
        a = write(tmp_path / "a.mp3", b"hello")
        b = write(tmp_path / "b.mp3", b"hello")
        assert hash_file(a) == hash_file(b)

    def test_different_content_different_hash(self, tmp_path):
        a = write(tmp_path / "a.mp3", b"hello")
        b = write(tmp_path / "b.mp3", b"world")
        assert hash_file(a) != hash_file(b)

    def test_zero_byte_file(self, tmp_path):
        f = write(tmp_path / "empty.mp3", b"")
        digest = hash_file(f)
        assert isinstance(digest, str) and len(digest) == 64

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            hash_file(tmp_path / "nonexistent.mp3")


# ---------------------------------------------------------------------------
# verify_copy
# ---------------------------------------------------------------------------

class TestVerifyCopy:
    def test_identical_files_returns_true(self, tmp_path):
        src  = write(tmp_path / "src" / "track.mp3", b"audio bytes")
        dest = write(tmp_path / "dst" / "track.mp3", b"audio bytes")
        assert verify_copy(src, dest) is True

    def test_corrupted_dest_returns_false(self, tmp_path):
        src  = write(tmp_path / "src" / "track.mp3", b"audio bytes")
        dest = write(tmp_path / "dst" / "track.mp3", b"audio XXXXX")
        assert verify_copy(src, dest) is False

    def test_missing_dest_returns_false(self, tmp_path):
        src = write(tmp_path / "src" / "track.mp3", b"audio bytes")
        assert verify_copy(src, tmp_path / "dst" / "track.mp3") is False

    def test_missing_source_returns_false(self, tmp_path):
        dest = write(tmp_path / "dst" / "track.mp3", b"audio bytes")
        assert verify_copy(tmp_path / "src" / "track.mp3", dest) is False

    def test_zero_byte_files_match(self, tmp_path):
        src  = write(tmp_path / "src" / "empty.mp3", b"")
        dest = write(tmp_path / "dst" / "empty.mp3", b"")
        assert verify_copy(src, dest) is True

    def test_one_byte_difference_returns_false(self, tmp_path):
        content = b"x" * 1024
        src  = write(tmp_path / "src" / "track.mp3", content)
        corrupted = bytearray(content)
        corrupted[512] ^= 0xFF
        dest = write(tmp_path / "dst" / "track.mp3", bytes(corrupted))
        assert verify_copy(src, dest) is False


# ---------------------------------------------------------------------------
# resolve_destination
# ---------------------------------------------------------------------------

class TestResolveDestination:
    def test_no_conflict_returns_copy(self, tmp_path):
        src      = write(tmp_path / "source" / "track.mp3", b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        path, action = resolve_destination(src, dest_dir)
        assert action == "copy"
        assert path == dest_dir / "track.mp3"

    def test_same_name_same_size_returns_skip(self, tmp_path):
        content  = b"identical audio"
        src      = write(tmp_path / "source" / "track.mp3", content)
        existing = write(tmp_path / "dest"   / "track.mp3", content)
        path, action = resolve_destination(src, tmp_path / "dest")
        assert action == "skip"
        assert path == existing

    def test_same_name_same_size_different_content_returns_rename(self, tmp_path):
        # Regression: same name + size used to be skipped without comparing
        # contents, so the second file was never archived but still queued
        # for removal from the library.
        src = write(tmp_path / "source" / "track.mp3", b"BBBB")
        write(tmp_path / "dest" / "track.mp3", b"AAAA")
        path, action = resolve_destination(src, tmp_path / "dest")
        assert action == "rename"
        assert path.name == "track (potential duplicate 1).mp3"

    def test_identical_to_existing_renamed_copy_returns_skip(self, tmp_path):
        # Re-running after a rename must not archive a third copy
        src = write(tmp_path / "source" / "track.mp3", b"BBBB")
        write(tmp_path / "dest" / "track.mp3", b"AAAA")
        existing = write(tmp_path / "dest" / "track (potential duplicate 1).mp3", b"BBBB")
        path, action = resolve_destination(src, tmp_path / "dest")
        assert action == "skip"
        assert path == existing

    def test_same_name_different_size_returns_rename(self, tmp_path):
        src      = write(tmp_path / "source" / "track.mp3", b"version 2 longer")
        _        = write(tmp_path / "dest"   / "track.mp3", b"v1")
        path, action = resolve_destination(src, tmp_path / "dest")
        assert action == "rename"
        assert path.name == "track (potential duplicate 1).mp3"

    def test_rename_increments_if_slot_taken(self, tmp_path):
        src = write(tmp_path / "source" / "track.mp3", b"version 3 data xx")
        write(tmp_path / "dest" / "track.mp3",                      b"v1")
        write(tmp_path / "dest" / "track (potential duplicate 1).mp3", b"v2")
        path, action = resolve_destination(src, tmp_path / "dest")
        assert action == "rename"
        assert path.name == "track (potential duplicate 2).mp3"

    def test_extension_preserved_on_rename(self, tmp_path):
        src = write(tmp_path / "source" / "mix.wav", b"wav data longer")
        write(tmp_path / "dest" / "mix.wav", b"old")
        path, _ = resolve_destination(src, tmp_path / "dest")
        assert path.suffix == ".wav"


# ---------------------------------------------------------------------------
# copy_and_verify (integration)
# ---------------------------------------------------------------------------

class TestCopyAndVerify:
    def test_successful_copy_deletes_source(self, tmp_path):
        src      = write(tmp_path / "source" / "track.mp3", b"real audio data")
        dest_dir = tmp_path / "dest"
        result   = copy_and_verify(src, dest_dir)
        assert result["action"]   == "copied"
        assert result["verified"] is True
        assert result["deleted"]  is True
        assert not src.exists()
        assert (dest_dir / "track.mp3").read_bytes() == b"real audio data"

    def test_dest_dir_created_if_missing(self, tmp_path):
        src      = write(tmp_path / "source" / "track.mp3", b"data")
        dest_dir = tmp_path / "new" / "nested" / "dir"
        result   = copy_and_verify(src, dest_dir)
        assert result["action"] == "copied"
        assert dest_dir.exists()

    def test_skip_does_not_delete_source(self, tmp_path):
        content  = b"same bytes"
        src      = write(tmp_path / "source" / "track.mp3", content)
        write(tmp_path / "dest" / "track.mp3", content)
        result = copy_and_verify(src, tmp_path / "dest")
        assert result["action"]  == "skipped"
        assert result["deleted"] is False
        assert src.exists()   # source preserved — library removal handles this

    def test_same_size_different_content_is_archived_not_skipped(self, tmp_path):
        src = write(tmp_path / "source" / "track.mp3", b"BBBB")
        write(tmp_path / "dest" / "track.mp3", b"AAAA")
        result = copy_and_verify(src, tmp_path / "dest")
        assert result["action"] == "renamed"
        assert result["verified"] is True
        assert result["dest"].read_bytes() == b"BBBB"
        assert (tmp_path / "dest" / "track.mp3").read_bytes() == b"AAAA"  # untouched

    def test_rename_copies_with_new_name(self, tmp_path):
        src = write(tmp_path / "source" / "aug test 1.mp3", b"longer version")
        write(tmp_path / "dest" / "aug test 1.mp3", b"old")
        result = copy_and_verify(src, tmp_path / "dest")
        assert result["action"] == "renamed"
        assert result["dest"].name == "aug test 1 (potential duplicate 1).mp3"
        assert result["verified"] is True
        assert result["deleted"]  is True
        assert not src.exists()

    def test_hash_mismatch_preserves_source(self, tmp_path, monkeypatch):
        # Simulate a hash mismatch (e.g. flipped bit after copy)
        src = write(tmp_path / "source" / "track.mp3", b"data")
        import itunes_cleanup.archive as archive
        monkeypatch.setattr(archive, "verify_copy", lambda s, d: False)
        result = copy_and_verify(src, tmp_path / "dest")
        assert result["action"]   == "failed"
        assert result["verified"] is False
        assert result["deleted"]  is False
        assert src.exists()   # source must NOT be deleted on mismatch

    def test_missing_source_returns_failed(self, tmp_path):
        result = copy_and_verify(tmp_path / "ghost.mp3", tmp_path / "dest")
        assert result["action"] == "failed"
        assert result["error"] is not None

    def test_zero_byte_file_copies_and_verifies(self, tmp_path):
        src    = write(tmp_path / "source" / "empty.mp3", b"")
        result = copy_and_verify(src, tmp_path / "dest")
        assert result["action"]   == "copied"
        assert result["verified"] is True
