"""
tests/test_classify.py — Unit tests for track classification logic in audit.py.

Tests are organised by classification tier, following the priority order:
  manual_override > voice_memo > long_audio > bounce > mix_demo > clean

Each test works with synthetic paths and does not touch the real library.
"""

import sys
from pathlib import Path

import pytest

# Allow imports from the parent package directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import itunes_cleanup.config as config
import itunes_cleanup.audit as audit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LIBRARY = Path("/fake/iTunes/Media/Music")


def path(relative: str) -> Path:
    """Build a fake library path for use in tests."""
    return LIBRARY / relative


@pytest.fixture(autouse=True)
def test_config(monkeypatch):
    """Pin library-specific settings so tests don't depend on the user's config."""
    monkeypatch.setattr(config, "MANUAL_OVERRIDES", {
        "Long Album Track": "clean",
        "My Track v3 1":    "bounce",
    })
    monkeypatch.setattr(config, "BOUNCE_ARTIST_FOLDERS", {"test artist", "test artist feat. guest"})
    monkeypatch.setattr(config, "VOICE_MEMO_ARTISTS", {"test user's iphone"})


def classify(relative: str, artist: str = "", album: str = "", duration_s: float = 180.0) -> str:
    return audit.classify(path(relative), artist, album, duration_s, library_root=LIBRARY)


# ---------------------------------------------------------------------------
# Manual overrides — checked before everything else
# ---------------------------------------------------------------------------

class TestManualOverrides:
    def test_override_forces_clean_regardless_of_duration(self):
        # Long Album Track is >10 min but must stay clean
        assert classify(
            "Unknown Artist/Unknown Album/Long Album Track.mp3",
            duration_s=654.0,
        ) == "clean"

    def test_override_forces_bounce_regardless_of_path(self):
        # My Track v3 1 is in Unknown Artist but override sends it to bounce
        assert classify(
            "Unknown Artist/Unknown Album/My Track v3 1.mp3",
            duration_s=732.0,
        ) == "bounce"

    def test_override_wins_over_voice_memo_path(self, monkeypatch):
        # If someone added a voice-memo path file to overrides as clean, it wins
        monkeypatch.setitem(config.MANUAL_OVERRIDES, "Voice Override Test", "clean")
        assert classify(
            "Test User's iPhone/Voice Memos/Voice Override Test.m4a",
            artist="Test User's iPhone",
            duration_s=30.0,
        ) == "clean"


# ---------------------------------------------------------------------------
# Voice memo classification (priority 1)
# ---------------------------------------------------------------------------

class TestVoiceMemo:
    def test_voice_memos_path(self):
        assert classify("Test User's iPhone/Voice Memos/Song Idea 4.m4a") == "voice_memo"

    def test_voice_memos_path_case_insensitive(self):
        assert classify("Test User's iPhone/voice memos/Some Idea.m4a") == "voice_memo"

    def test_artist_tag_iphone(self):
        assert classify(
            "Unknown Artist/Unknown Album/Some Recording.m4a",
            artist="Test User's iPhone",
        ) == "voice_memo"

    def test_voice_memo_wins_over_long_audio(self):
        # A long voice memo should still be voice_memo, not long_audio
        assert classify(
            "Test User's iPhone/Voice Memos/Long Ramble.m4a",
            duration_s=900.0,
        ) == "voice_memo"

    def test_voice_memo_wins_over_mix_keywords(self):
        # A voice memo with "demo" in the filename stays voice_memo
        assert classify(
            "Test User's iPhone/Voice Memos/Song demo idea.m4a",
        ) == "voice_memo"

    def test_normal_track_not_voice_memo(self):
        assert classify(
            "Some Artist/Some Album/Some Track.mp3",
            artist="Some Artist",
        ) != "voice_memo"


# ---------------------------------------------------------------------------
# Long audio classification (priority 2)
# ---------------------------------------------------------------------------

class TestLongAudio:
    def test_exactly_at_threshold(self):
        threshold_s = config.LONG_AUDIO_THRESHOLD_MINUTES * 60
        assert classify("Unknown Artist/Unknown Album/Meditation.mp3", duration_s=threshold_s) == "long_audio"

    def test_one_second_below_threshold(self):
        threshold_s = config.LONG_AUDIO_THRESHOLD_MINUTES * 60 - 1
        result = classify("Unknown Artist/Unknown Album/Normal Track.mp3", duration_s=threshold_s)
        assert result != "long_audio"

    def test_clearly_long(self):
        assert classify("Unknown Artist/Unknown Album/Party Mix.mp3", duration_s=7200.0) == "long_audio"

    def test_none_duration_not_long_audio(self):
        assert classify("Unknown Artist/Unknown Album/Unknown.mp3", duration_s=None) != "long_audio"

    def test_long_audio_catches_any_name(self):
        # No keywords needed — duration alone is sufficient
        assert classify("Some Artist/Some Album/asdfqwerty.mp3", duration_s=700.0) == "long_audio"

    def test_long_audio_does_not_catch_voice_memo(self):
        # voice_memo has higher priority
        assert classify(
            "Test User's iPhone/Voice Memos/Long Recording.m4a",
            duration_s=900.0,
        ) == "voice_memo"


# ---------------------------------------------------------------------------
# Bounce classification (priority 3)
# ---------------------------------------------------------------------------

class TestBounce:
    def test_production_bounces_folder(self):
        assert classify("Production Bounces/Track 10.m4a", duration_s=120.0) == "bounce"

    def test_landr_prefix(self):
        assert classify(
            "Unknown Artist/Unknown Album/LANDR-My Song v4.mp3",
            duration_s=300.0,
        ) == "bounce"

    def test_landr_prefix_case_insensitive(self):
        assert classify(
            "Unknown Artist/Unknown Album/landr-some track.mp3",
            duration_s=300.0,
        ) == "bounce"

    def test_own_artist_folder_no_released(self):
        assert classify(
            "Test Artist/Unknown Album/My Track v3.mp3",
            duration_s=300.0,
        ) == "bounce"

    def test_own_artist_folder_released_stays_clean(self):
        assert classify(
            "Test Artist/Unknown Album/Finished Song (Main Mix) RELEASED.mp3",
            duration_s=260.0,
        ) == "clean"

    def test_own_artist_folder_released_case_insensitive(self):
        assert classify(
            "Test Artist feat. Guest/Unknown Album/Another Song (Original Mix) released.mp3",
            duration_s=260.0,
        ) == "clean"

    def test_unknown_artist_version_number(self):
        assert classify(
            "Unknown Artist/Unknown Album/My Song v4.2.mp3",
            duration_s=430.0,
        ) == "bounce"

    def test_unknown_artist_version_number_with_letter(self):
        assert classify(
            "Unknown Artist/Unknown Album/My Song V3.1b.mp3",
            duration_s=200.0,
        ) == "bounce"

    def test_unknown_artist_ozone_keyword(self):
        assert classify(
            "Unknown Artist/Unknown Album/My Song V5.4 OZONE.mp3",
            duration_s=200.0,
        ) == "bounce"

    def test_unknown_artist_rough_keyword(self):
        assert classify(
            "Unknown Artist/Unknown Album/New Song rough bounce2.mp3",
            duration_s=270.0,
        ) == "bounce"

    def test_unknown_artist_groovestation_keyword(self):
        assert classify(
            "Unknown Artist/Unknown Album/My Song groovestation v4.mp3",
            duration_s=320.0,
        ) == "bounce"

    def test_bounce_sub_10_min_not_caught_by_long_audio(self):
        # A 3-min bounce should be bounce, not long_audio
        result = classify(
            "Unknown Artist/Unknown Album/My Song V5.mp3",
            duration_s=204.0,
        )
        assert result == "bounce"

    def test_normal_dance_track_in_unknown_artist_not_bounce(self):
        # No version/production signals → stays clean
        assert classify(
            "Unknown Artist/Unknown Album/Some Track (Other Artist Dub).mp3",
            duration_s=400.0,
        ) == "clean"

    def test_track_numbered_wav(self):
        assert classify(
            "Unknown Artist/Unknown Album/Track 10.wav",
            duration_s=120.0,
        ) == "bounce"

    def test_digit_prefixed_wav(self):
        assert classify(
            "Unknown Artist/Unknown Album/03jun.wav",
            duration_s=180.0,
        ) == "bounce"


# ---------------------------------------------------------------------------
# Mix/demo classification (priority 4)
# ---------------------------------------------------------------------------

class TestMixDemo:
    def test_mix_in_stem(self):
        assert classify("Unknown Artist/Unknown Album/april mix v6.mp3", duration_s=216.0) == "mix_demo"

    def test_mix_case_insensitive(self):
        assert classify("Unknown Artist/Unknown Album/APRIL MIX V6.mp3", duration_s=216.0) == "mix_demo"

    def test_demo_keyword(self):
        assert classify("Unknown Artist/Unknown Album/Spring Demo.mp3", duration_s=180.0) == "mix_demo"

    def test_dj_set_phrase(self):
        assert classify("Unknown Artist/Unknown Album/Summer dj Set.mp3", duration_s=540.0) == "mix_demo"

    def test_vol_keyword(self):
        assert classify("Unknown Artist/Unknown Album/Chill Selection vol1.mp3", duration_s=200.0) == "mix_demo"

    def test_remix_in_parens_not_mix_demo(self):
        # "(Original Mix)" is a version label, not a personal mix
        assert classify(
            "Unknown Artist/Unknown Album/Run Away (Original Mix).mp3",
            duration_s=340.0,
        ) == "clean"

    def test_remix_suffix_not_mix_demo(self):
        # "Remix" at end of name should not trigger "mix" keyword
        assert classify(
            "Unknown Artist/Unknown Album/Some Artist - Some Track Remix.mp3",
            duration_s=340.0,
        ) == "clean"

    def test_bracket_remix_not_mix_demo(self):
        assert classify(
            "Unknown Artist/Unknown Album/Some Track [Other Artist Remix].m4a",
            duration_s=380.0,
        ) == "clean"

    def test_mix_in_brackets_not_mix_demo(self):
        assert classify(
            "Unknown Artist/Unknown Album/Track Name [Extended Mix].mp3",
            duration_s=300.0,
        ) == "clean"

    def test_my_mixes_folder_path(self):
        assert classify(
            "My Mixes/April mix.mp3",
            duration_s=3600.0,
        ) == "long_audio"  # long_audio wins on duration

    def test_underscore_mix_stem(self):
        # Underscores replaced with spaces before keyword check
        assert classify(
            "Unknown Artist/Unknown Album/aug_mix_alternative.mp3",
            duration_s=180.0,
        ) == "mix_demo"


# ---------------------------------------------------------------------------
# Clean classification (default / no signals)
# ---------------------------------------------------------------------------

class TestClean:
    def test_normal_track(self):
        assert classify(
            "Some Artist/Some Album/Some Track.mp3",
            artist="Some Artist",
            album="Some Album",
            duration_s=480.0,
        ) == "clean"

    def test_short_no_signals(self):
        assert classify(
            "Unknown Artist/Unknown Album/Normal Dance Track.mp3",
            duration_s=390.0,
        ) == "clean"

    def test_url_in_tags_does_not_change_movement_class(self):
        # dirty_tag is a flag; a clean-length track with URL tags is still clean
        assert classify(
            "Unknown Artist/Unknown Album/Some Track.mp3",
            album="http___example-music.blogspot.com_",
            duration_s=300.0,
        ) == "clean"


# ---------------------------------------------------------------------------
# Dirty tag detection (independent flag)
# ---------------------------------------------------------------------------

class TestDirtyTag:
    def test_url_in_artist(self):
        assert audit._is_dirty_tag("http___example-music.blogspot.com_", "") is True

    def test_url_in_album(self):
        assert audit._is_dirty_tag("Clean Artist", "www.example-promo.com") is True

    def test_http_in_album(self):
        assert audit._is_dirty_tag("", "http://example-mp3s.blogspot.com") is True

    def test_dotcom_in_album(self):
        assert audit._is_dirty_tag("Some Artist", "ExampleTracks.com") is True

    def test_dotnet_in_album(self):
        assert audit._is_dirty_tag("Another Artist", "ExampleTracks.net") is True

    def test_clean_tags_not_dirty(self):
        assert audit._is_dirty_tag("Some Artist", "Some Album") is False

    def test_empty_tags_not_dirty(self):
        assert audit._is_dirty_tag("", "") is False

    def test_dirty_tag_on_long_audio_file(self):
        # A long file can be long_audio AND dirty — classification is long_audio,
        # but the flag is set separately
        cls = classify(
            "Unknown Artist/Unknown Album/Long Blog Track.mp3",
            album="www.blogsite.com",
            duration_s=900.0,
        )
        assert cls == "long_audio"
        assert audit._is_dirty_tag("", "www.blogsite.com") is True


# ---------------------------------------------------------------------------
# Library scan
# ---------------------------------------------------------------------------

class TestScanLibrary:
    def test_folder_rules_use_scanned_root(self, tmp_path):
        # Regression: scan_library() didn't pass its root to classify(), so
        # folder-relative rules (own artist folders, Unknown Artist patterns)
        # were checked against config.LIBRARY_ROOT instead of --library.
        root = tmp_path / "Other Library"
        track = root / "Test Artist" / "Unknown Album" / "Work In Progress.mp3"
        track.parent.mkdir(parents=True)
        track.write_bytes(b"\x00" * 128)
        rows = audit.scan_library(root)
        assert [r["classification"] for r in rows] == ["bounce"]
