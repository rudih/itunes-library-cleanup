"""
tests/test_tags.py — Tests for tag parsing, writing, and dirty-tag detection.

Uses real on-disk audio files created with mutagen — no mocking.
"""

import csv
import struct
import sys
import wave
from pathlib import Path

import pytest
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TCON

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import itunes_cleanup.audit as audit
import itunes_cleanup.fix_tags as fix_tags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUDIO_FRAMES = bytes(range(256)) * 8   # recognisable, non-silent sample data


def make_wav(path: Path) -> Path:
    """Create a minimal valid PCM WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(AUDIO_FRAMES)
    return path


def make_aiff(path: Path) -> Path:
    """Create a minimal valid AIFF file (FORM container with COMM + SSND)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = len(AUDIO_FRAMES) // 2
    # 80-bit IEEE extended float for 8000 Hz
    rate = b"\x40\x0b\xfa\x00\x00\x00\x00\x00\x00\x00"
    comm = b"COMM" + struct.pack(">IhIh", 18, 1, frames, 16) + rate
    ssnd = b"SSND" + struct.pack(">III", 8 + len(AUDIO_FRAMES), 0, 0) + AUDIO_FRAMES
    body = b"AIFF" + comm + ssnd
    path.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)
    return path


def aiff_sound_data(path: Path) -> bytes:
    """Return the raw sample bytes from an AIFF file's SSND chunk."""
    data = path.read_bytes()
    assert data[:4] == b"FORM" and data[8:12] == b"AIFF"
    pos = 12
    while pos < len(data):
        cid, size = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        if cid == b"SSND":
            return data[pos + 16:pos + 8 + size]
        pos += 8 + size + (size & 1)
    raise AssertionError("no SSND chunk")

def make_mp3(path: Path, artist="", title="", album="", genre="") -> Path:
    """Create a minimal MP3 file with ID3 tags at path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 128)
    tags = ID3()
    if artist: tags.add(TPE1(encoding=3, text=[artist]))
    if title:  tags.add(TIT2(encoding=3, text=[title]))
    if album:  tags.add(TALB(encoding=3, text=[album]))
    if genre:  tags.add(TCON(encoding=3, text=[genre]))
    tags.save(str(path))
    return path


def read_id3(path: Path) -> dict:
    """Read raw ID3 tags back from a file."""
    tags = ID3(str(path))
    return {
        "artist": str(tags.get("TPE1", "")),
        "title":  str(tags.get("TIT2", "")),
        "album":  str(tags.get("TALB", "")),
        "genre":  str(tags.get("TCON", "")),
    }


def write_tsv(path: Path, rows: list[dict]) -> Path:
    """Write a fixes TSV for use as test input."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write("\t".join([
                row.get("filepath", ""),
                row.get("new_artist", ""),
                row.get("new_title", ""),
                row.get("clear_album", "0"),
            ] + ([row["new_genre"]] if "new_genre" in row else [])) + "\n")
    return path


# ---------------------------------------------------------------------------
# Dirty tag detection (URL patterns in artist / album fields)
# ---------------------------------------------------------------------------

class TestDirtyTagDetection:
    """
    Focused dirty-tag tests from the fix_tags perspective — the patterns we
    actually encounter in phase4_fixes.tsv and the audit report.
    """

    def test_blogspot_in_artist(self):
        assert audit._is_dirty_tag("http___example-music.blogspot.com_", "") is True

    def test_dotcom_site_in_album(self):
        assert audit._is_dirty_tag("Some Artist", "ExampleTracks.com") is True

    def test_uk_site_in_album(self):
        assert audit._is_dirty_tag("Some Artist", "EXAMPLE-DJ.UK") is True

    def test_http_url_in_album(self):
        assert audit._is_dirty_tag("Some Artist", "http://example-mp3s.blogspot.com") is True

    def test_at_prefix_blog_in_album(self):
        assert audit._is_dirty_tag("Another Artist", "@example-dj.blogspot.com") is True

    def test_clean_artist_and_album(self):
        assert audit._is_dirty_tag("Some Artist", "Some Album") is False

    def test_empty_both_fields(self):
        assert audit._is_dirty_tag("", "") is False

    def test_very_long_url_in_album(self):
        long_url = "http_" + "_" * 200 + ".blogspot.com"
        assert audit._is_dirty_tag("", long_url) is True

    def test_non_ascii_clean_tag(self):
        assert audit._is_dirty_tag("Björk", "Homogenic") is False

    def test_non_ascii_with_url(self):
        assert audit._is_dirty_tag("Ëlite", "www.downloadsite.net") is True


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------

class TestParseTsv:
    def test_parses_four_fields(self, tmp_path):
        tsv = write_tsv(tmp_path / "fixes.tsv", [
            {"filepath": "/a/b/track.mp3", "new_artist": "Some Artist",
             "new_title": "Some Track Part II", "clear_album": "1"},
        ])
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert len(rows) == 1
        assert rows[0]["filepath"]    == "/a/b/track.mp3"
        assert rows[0]["new_artist"]  == "Some Artist"
        assert rows[0]["new_title"]   == "Some Track Part II"
        assert rows[0]["clear_album"] == "1"

    def test_new_genre_defaults_to_empty(self, tmp_path):
        tsv = write_tsv(tmp_path / "fixes.tsv", [
            {"filepath": "/a/b/track.mp3", "new_artist": "A", "new_title": "T", "clear_album": "1"},
        ])
        assert fix_tags.parse_fixes_tsv(tsv)[0]["new_genre"] == ""

    def test_parses_optional_genre_field(self, tmp_path):
        tsv = write_tsv(tmp_path / "fixes.tsv", [
            {"filepath": "/a/b/track.mp3", "new_artist": "A", "new_title": "T",
             "clear_album": "1", "new_genre": "House"},
        ])
        assert fix_tags.parse_fixes_tsv(tsv)[0]["new_genre"] == "House"

    def test_skips_plain_header_row(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("filepath\tnew_artist\tnew_title\tclear_album\n/a/b/track.mp3\tA\tT\t1\n")
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert [r["filepath"] for r in rows] == ["/a/b/track.mp3"]

    def test_rejects_preview_file_as_input(self, tmp_path):
        # Regression: a preview TSV used to be parsed positionally, writing
        # the new artist into the title and dropping clear_album.
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "New Artist",
                  "new_title": "New Title", "clear_album": "1"}]
        preview = fix_tags.generate_preview_tsv(fixes, tmp_path)
        with pytest.raises(ValueError, match="preview"):
            fix_tags.parse_fixes_tsv(preview)

    def test_rejects_preview_with_byte_order_mark(self, tmp_path):
        # Regression: a BOM before "filepath" hid the header from the
        # preview check, so the preview was parsed positionally.
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "New Artist",
                  "new_title": "New Title", "clear_album": "1"}]
        preview = fix_tags.generate_preview_tsv(fixes, tmp_path)
        bom = tmp_path / "bom_preview.tsv"
        bom.write_bytes(b"\xef\xbb\xbf" + preview.read_bytes())
        with pytest.raises(ValueError, match="preview"):
            fix_tags.parse_fixes_tsv(bom)

    def test_rejects_preview_rows_without_header(self, tmp_path):
        # Even with the header deleted, preview rows have too many columns
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "X", "new_title": "Y", "clear_album": "1"}]
        preview = fix_tags.generate_preview_tsv(fixes, tmp_path)
        headless = tmp_path / "headless.tsv"
        headless.write_text("".join(preview.read_text().splitlines(keepends=True)[1:]))
        with pytest.raises(ValueError):
            fix_tags.parse_fixes_tsv(headless)

    def test_skips_blank_lines(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("/a/b/track.mp3\tArtist\tTitle\t1\n\n/c/d/other.mp3\tX\tY\t0\n")
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert len(rows) == 2

    def test_skips_comment_lines(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("# This is a comment\n/a/b/track.mp3\tArtist\tTitle\t1\n")
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert len(rows) == 1

    def test_rejects_rows_with_fewer_than_four_fields(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("/a/b/track.mp3\tArtist\tTitle\n")  # only 3 fields
        with pytest.raises(ValueError, match="line 1"):
            fix_tags.parse_fixes_tsv(tsv)

    def test_rejects_rows_with_extra_fields(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("/a/b/track.mp3\tA\tT\t1\tHouse\textra\n")
        with pytest.raises(ValueError, match="columns"):
            fix_tags.parse_fixes_tsv(tsv)

    def test_bad_row_rejects_whole_file(self, tmp_path):
        # Nothing is returned (so nothing is written) if any row is invalid
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("/a/ok.mp3\tA\tT\t1\n/a/bad.mp3\tA\tT\tmaybe\n")
        with pytest.raises(ValueError, match="clear_album"):
            fix_tags.parse_fixes_tsv(tsv)

    def test_rejects_empty_filepath(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("\tA\tT\t1\n")
        with pytest.raises(ValueError, match="filepath"):
            fix_tags.parse_fixes_tsv(tsv)

    def test_rejects_reordered_header(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("filepath\tnew_title\tnew_artist\tclear_album\n/a/t.mp3\tT\tA\t1\n")
        with pytest.raises(ValueError, match="header"):
            fix_tags.parse_fixes_tsv(tsv)

    def test_accepts_header_with_genre(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("filepath\tnew_artist\tnew_title\tclear_album\tnew_genre\n/a/t.mp3\tA\tT\t1\tHouse\n")
        assert fix_tags.parse_fixes_tsv(tsv)[0]["new_genre"] == "House"

    def test_byte_order_mark_is_ignored(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_bytes(b"\xef\xbb\xbf" + "/a/t.mp3\tA\tT\t1\n".encode())
        assert fix_tags.parse_fixes_tsv(tsv)[0]["filepath"] == "/a/t.mp3"

    def test_empty_artist_field_allowed(self, tmp_path):
        tsv = write_tsv(tmp_path / "fixes.tsv", [
            {"filepath": "/a/b.mp3", "new_artist": "", "new_title": "Title", "clear_album": "1"},
        ])
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert rows[0]["new_artist"] == ""

    def test_non_ascii_in_fields(self, tmp_path):
        tsv = tmp_path / "fixes.tsv"
        tsv.write_text("/a/Björk.mp3\tBjörk\tJóga\t0\n", encoding="utf-8")
        rows = fix_tags.parse_fixes_tsv(tsv)
        assert rows[0]["new_artist"] == "Björk"
        assert rows[0]["new_title"]  == "Jóga"

    def test_multiple_rows_parsed_in_order(self, tmp_path):
        rows_in = [
            {"filepath": f"/track{i}.mp3", "new_artist": f"Artist{i}",
             "new_title": f"Title{i}", "clear_album": "0"}
            for i in range(5)
        ]
        tsv = write_tsv(tmp_path / "fixes.tsv", rows_in)
        rows_out = fix_tags.parse_fixes_tsv(tsv)
        assert [r["new_artist"] for r in rows_out] == [f"Artist{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# Tag writing — MP3 (ID3)
# ---------------------------------------------------------------------------

class TestWriteTagsMP3:
    def test_writes_new_artist(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", artist="http___dirty.com", title="Track")
        fix_tags.write_tags_to_file(path, new_artist="Clean Artist", new_title="", clear_album=False)
        assert read_id3(path)["artist"] == "Clean Artist"

    def test_writes_new_title(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", title="Old Title")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="New Title", clear_album=False)
        assert read_id3(path)["title"] == "New Title"

    def test_clear_album_empties_album_and_leaves_genre(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", album="ExampleTracks.com", genre="Classical")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="", clear_album=True)
        after = read_id3(path)
        assert after["album"] == ""
        assert after["genre"] == "Classical"

    def test_new_genre_written_when_given(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", genre="")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="", clear_album=False, new_genre="House")
        assert read_id3(path)["genre"] == "House"

    def test_clear_album_false_leaves_album_unchanged(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", album="Original Album")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="", clear_album=False)
        assert read_id3(path)["album"] == "Original Album"

    def test_empty_new_artist_does_not_overwrite(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", artist="Keep Me")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="", clear_album=False)
        assert read_id3(path)["artist"] == "Keep Me"

    def test_empty_new_title_does_not_overwrite(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3", title="Keep Me Too")
        fix_tags.write_tags_to_file(path, new_artist="", new_title="", clear_album=False)
        assert read_id3(path)["title"] == "Keep Me Too"

    def test_non_ascii_artist_written_correctly(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3")
        fix_tags.write_tags_to_file(path, new_artist="Björk", new_title="Jóga", clear_album=False)
        after = read_id3(path)
        assert after["artist"] == "Björk"
        assert after["title"]  == "Jóga"

    def test_returns_ok_true_on_success(self, tmp_path):
        path = make_mp3(tmp_path / "track.mp3")
        result = fix_tags.write_tags_to_file(path, "Artist", "Title", True)
        assert result["ok"] is True
        assert result["error"] is None

    def test_returns_ok_false_for_missing_file(self, tmp_path):
        result = fix_tags.write_tags_to_file(tmp_path / "ghost.mp3", "A", "T", False)
        assert result["ok"] is False
        assert result["error"] is not None

    def test_unsupported_extension_returns_error(self, tmp_path):
        p = tmp_path / "file.xyz"
        p.write_bytes(b"data")
        result = fix_tags.write_tags_to_file(p, "A", "T", False)
        assert result["ok"] is False


class TestWriteTagsWavAiff:
    """Regression: WAV/AIFF used to be saved with the bare MP3 ID3 writer,
    which replaced the RIFF/FORM header and made the files unreadable."""

    def test_wav_stays_valid_with_audio_unchanged(self, tmp_path):
        path = make_wav(tmp_path / "bounce.wav")
        result = fix_tags.write_tags_to_file(path, "Some Artist", "Some Track", True, "House")
        assert result["ok"] is True
        assert path.read_bytes()[:4] == b"RIFF"
        with wave.open(str(path)) as w:
            assert w.readframes(w.getnframes()) == AUDIO_FRAMES

    def test_wav_tags_written_and_read_back(self, tmp_path):
        path = make_wav(tmp_path / "bounce.wav")
        fix_tags.write_tags_to_file(path, "Some Artist", "Some Track", False, "House")
        tags = fix_tags.current_tags(path)
        assert tags["artist"] == "Some Artist"
        assert tags["title"]  == "Some Track"
        assert tags["genre"]  == "House"

    def test_aiff_stays_valid_with_audio_unchanged(self, tmp_path):
        path = make_aiff(tmp_path / "bounce.aiff")
        result = fix_tags.write_tags_to_file(path, "Some Artist", "Some Track", True)
        assert result["ok"] is True
        assert aiff_sound_data(path) == AUDIO_FRAMES

    def test_aif_extension_tags_read_back(self, tmp_path):
        path = make_aiff(tmp_path / "bounce.aif")
        fix_tags.write_tags_to_file(path, "Some Artist", "", False)
        assert fix_tags.current_tags(path)["artist"] == "Some Artist"


# ---------------------------------------------------------------------------
# Artist-title splitting heuristic
# ---------------------------------------------------------------------------

class TestSplitArtistFromTitle:
    def test_splits_on_dash(self):
        artist, title = fix_tags.split_artist_from_title("Some Artist - Some Track Part II")
        assert artist == "Some Artist"
        assert title  == "Some Track Part II"

    def test_no_dash_returns_empty_artist(self):
        artist, title = fix_tags.split_artist_from_title("Normal Title")
        assert artist == ""
        assert title  == "Normal Title"

    def test_multiple_dashes_splits_on_first(self):
        artist, title = fix_tags.split_artist_from_title("Ad Brown - Good Feeling - Chris Reece Remix")
        assert artist == "Ad Brown"
        assert title  == "Good Feeling - Chris Reece Remix"

    def test_strips_whitespace(self):
        artist, title = fix_tags.split_artist_from_title("  Artist  -  Title  ")
        assert artist == "Artist"
        assert title  == "Title"

    def test_empty_string(self):
        artist, title = fix_tags.split_artist_from_title("")
        assert artist == ""
        assert title  == ""

    def test_non_ascii(self):
        artist, title = fix_tags.split_artist_from_title("Sigur Rós - Ára bátur")
        assert artist == "Sigur Rós"
        assert title  == "Ára bátur"


# ---------------------------------------------------------------------------
# Preview TSV generation
# ---------------------------------------------------------------------------

class TestGeneratePreviewTsv:
    def test_creates_file_in_output_dir(self, tmp_path):
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "X", "new_title": "Y", "clear_album": "1"}]
        out = fix_tags.generate_preview_tsv(fixes, tmp_path)
        previews = list(tmp_path.glob("fix_tags_preview_*.tsv"))
        assert len(previews) == 1

    def test_preview_contains_expected_columns(self, tmp_path):
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "X", "new_title": "Y", "clear_album": "1"}]
        out = fix_tags.generate_preview_tsv(fixes, tmp_path)
        rows = list(csv.DictReader(open(out), delimiter="\t"))
        assert set(fix_tags.PREVIEW_FIELDNAMES).issubset(set(rows[0].keys()))

    def test_preview_shows_proposed_new_artist(self, tmp_path):
        fixes = [{"filepath": "/a/track.mp3", "new_artist": "Clean Artist",
                  "new_title": "", "clear_album": "0"}]
        out = fix_tags.generate_preview_tsv(fixes, tmp_path)
        rows = list(csv.DictReader(open(out), delimiter="\t"))
        assert rows[0]["new_artist"] == "Clean Artist"

    def test_preview_shows_current_tags_for_existing_file(self, tmp_path):
        mp3 = make_mp3(tmp_path / "track.mp3", artist="Dirty.com", album="Blog.net")
        fixes = [{"filepath": str(mp3), "new_artist": "Clean", "new_title": "", "clear_album": "1"}]
        out = fix_tags.generate_preview_tsv(fixes, tmp_path / "logs")
        rows = list(csv.DictReader(open(out), delimiter="\t"))
        assert rows[0]["current_artist"] == "Dirty.com"
        assert rows[0]["current_album"]  == "Blog.net"

    def test_preview_handles_missing_file_gracefully(self, tmp_path):
        fixes = [{"filepath": "/nonexistent/track.mp3", "new_artist": "X",
                  "new_title": "Y", "clear_album": "1"}]
        out = fix_tags.generate_preview_tsv(fixes, tmp_path)
        rows = list(csv.DictReader(open(out), delimiter="\t"))
        assert rows[0]["current_artist"] == ""
