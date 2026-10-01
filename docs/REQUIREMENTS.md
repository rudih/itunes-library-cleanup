# iTunes Library Cleanup — Requirements Document

**Version:** 0.2
**Date:** 2026-03-21
**Status:** Agreed — ready for implementation

> **Note:** This is the original requirements spec. Where it differs from the README or the code, those are authoritative. Notably, the summary report and run log are currently written by phase 3 only, and phase 2 deletes originals permanently once their archive copy is verified.

---

## 1. Background & Problem Statement

An iTunes/Apple Music library accumulates multiple categories of audio file over many years:

- **Voice memos** synced from iPhone (e.g. song ideas, rough takes)
- **Production bounces** — exported stems and work-in-progress exports from a DAW
- **DJ mixes / demos** — long-form personal recordings
- **Dance tracks with dirty tags** — files downloaded from MP3 blogs where the artist or album field contains a URL (e.g. a download site's web address) rather than real metadata

All four categories need different treatment. The existing manual workflow uses two AppleScript files and hand-edited TSV files. The goal of iTunes Library Cleanup is to replace / automate that workflow as a reproducible, tested Python package — suitable for reuse by anyone with a similar iTunes library mess.

---

## 2. Scope

### In scope
- Scanning the iTunes library directory and classifying tracks into categories
- Safely archiving (copy → verify → delete) selected categories of file
- Fixing corrupted tags (URL-as-artist/album) directly via `mutagen`
- Removing archived tracks from Music.app via batched `osascript`
- Generating a human-readable summary report and persistent run log after each operation
- Automated tests covering classification logic, copy verification, and tag parsing

### Out of scope (v1)
- GUI or web interface
- Integration with streaming services or MusicBrainz lookups
- Duplicate detection across audio content (fingerprinting)
- Renaming files/folders to remove URL-derived underscores (nice-to-have for a future version; tracks with underscores are still readable in Rekordbox/CDJ displays)
- Windows / Linux support (macOS only — `osascript` dependency for remove_library)
- `pip install` / `pyproject.toml` packaging (local script collection for now)

---

## 3. Library Structure & Classifications

### Source library root
```
~/Music/Music/iTunes/iTunes Media/Music/
```

### Track classifications — evaluated in priority order

| Priority | Class | Rule | Destination |
|---|---|---|---|
| 1 | `voice_memo` | Path contains `Voice Memos` OR artist tag is listed in `VOICE_MEMO_ARTISTS` | `~/Documents/Voice Notes/` |
| 2 | `long_audio` | Duration ≥ 10 min | `~/Music/Archive/Long Audio Files/` |
| 3 | `bounce` | Path contains `Production Bounces` OR filename matches bounce pattern (e.g. `Track NN`, date-stamped WAV/AIFF) | `~/Music/Archive/Production Bounces/` |
| 4 | `mix_demo` | Filename contains "mix", "demo", "set", "vol", "dj set" (case-insensitive) | `~/Music/Archive/My Mixes and Demos/` |
| 5 | `dirty_tag` | Artist or album field contains a URL pattern (`http`, `www.`, `.com`, `.net`, `.org`, `.blogspot`) | Fix tags in-place via mutagen — do not move file |
| 6 | `clean` | None of the above | No action |

**Rationale for priority order:** Duration ≥ 10 min is the most reliable signal for non-track content — genuine individual tracks almost never exceed this. Voice memos are exempted first because they go to a different destination. `bounce` and `mix_demo` apply only to sub-10-min files. `dirty_tag` is not a movement classification — it flags files for tag repair regardless of other attributes, but a file already classified as `long_audio` or `voice_memo` may also carry a `dirty_tag` flag.

> **Thresholds are configurable** — see `config.py`.

---

## 4. Phases of Operation

### Phase 1 — Audit (`audit.py`)
- Scan the iTunes library directory recursively
- Classify each audio file (`.mp3`, `.m4a`, `.wav`, `.aiff`, `.aif`, `.flac`) using the priority rules above
- Read embedded tags via `mutagen`
- Output an **audit report** (`audit_YYYYMMDD_HHMMSS.tsv`) with columns:
  `filepath | classification | dirty_tag | artist | title | album | duration_s | size_bytes`
  (`dirty_tag` is a boolean flag — a file can be `long_audio` + `dirty_tag` simultaneously)
- No files are moved or modified in this phase — read-only

### Phase 2 — Archive (`archive.py`)
Input: audit report (or filtered subset, e.g. `--classes voice_memo,long_audio`)

1. **Copy** each file to its destination directory
2. **Verify** the copy: compare SHA-256 hash of source and destination
3. **Delete** source file only after successful hash match
4. Any verification failure: source is NOT deleted; error is logged and flagged in summary

**Duplicate filename handling:**
- Same filename **and** same file size in destination → assume duplicate; **skip** (do not copy, do not delete source; log as skipped)
- Same filename **but** different file size → rename destination copy with suffix: `aug test 1 (potential duplicate 1).mp3`, incrementing if further conflicts exist; proceed with copy → verify → delete as normal
- The goal is always to get files out of the library — source is deleted in all non-failure cases

### Phase 3 — Remove from Music.app (`remove_library.py`)
- Takes a list of file paths (e.g. `tracks_to_remove.txt` produced by archive phase, or supplied manually)
- Builds a **single batched AppleScript** containing all paths and passes it to one `osascript` call — avoids the per-track IPC overhead that made the previous script slow
- Locates each track in Music.app by file path and removes it from the library
- Moves the original file to Trash as a safety net
- Produces a removal report with counts: removed / not found / errors

### Phase 4 — Fix Tags (`fix_tags.py`)
- Input: a TSV file with columns `filepath | new_artist | new_title | clear_album`, plus an optional `new_genre` column
  (same format as existing `phase4_fixes.tsv`)
- **Dry-run mode** (default, no flag): writes a preview TSV (`fix_tags_preview_YYYYMMDD_HHMMSS.tsv`) showing current tags alongside proposed changes without modifying any files. The preview is for review only — it has extra columns and must not be passed to `--execute` (fix_tags.py refuses it); edit the original input file instead.
- **Execute mode** (`--execute`): writes corrected tags directly to files via `mutagen`; clears the `album` field when `clear_album == 1`, and sets `genre` only when `new_genre` is given
- Does NOT require Music.app to be running

### Phase 5 — Summary & Log (`summary.py`)
- Called automatically at the end of any phase that modifies files
- Writes a human-readable **summary report** (`summary_YYYYMMDD_HHMMSS.txt`) to `LOG_DIR` including:
  - Phase(s) run and timestamp
  - Counts: processed / archived / verified / failed / skipped / tags fixed
  - List of any errors or verification failures with file paths
  - Total data moved (MB)
- **Appends** a one-line entry to a persistent **run log** (`run_log.tsv`):
  `timestamp | phase | processed | archived | verified | failed | skipped | tags_fixed | data_mb | duration_s`

---

## 5. Configuration (`config.py`)

All tunable values in one place:

```python
LIBRARY_ROOT       = "~/Music/Music/iTunes/iTunes Media/Music"
ARCHIVE_BOUNCES    = "~/Music/Archive/Production Bounces"
ARCHIVE_MIXES      = "~/Music/Archive/My Mixes and Demos"
ARCHIVE_LONG_AUDIO = "~/Music/Archive/Long Audio Files"
ARCHIVE_VOICE      = "~/Documents/Voice Notes"

LONG_AUDIO_THRESHOLD_MINUTES = 10
MIX_KEYWORDS = ["mix", "demo", "set", "vol", "dj set"]
BOUNCE_EXTENSIONS = [".wav", ".aiff", ".aif"]

URL_PATTERNS = ["http", "www.", ".com", ".net", ".org", ".uk", ".blogspot"]

AUDIO_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aiff", ".aif", ".flac"]

LOG_DIR = "~/Music/Archive/logs"
```

---

## 6. Automated Tests

### `tests/test_classify.py`
- `voice_memo`: path containing `Voice Memos` → classified before duration check
- `voice_memo`: artist tag in `VOICE_MEMO_ARTISTS` → classified before duration check
- `long_audio`: duration = 10 min exactly → classifies as `long_audio` (boundary)
- `long_audio`: duration = 9 min 59 sec → does NOT classify as `long_audio`
- `long_audio`: catches a file regardless of name/path (no keyword needed)
- `bounce`: sub-10-min WAV with bounce path pattern → `bounce` (not `long_audio`)
- `mix_demo`: sub-10-min file with "mix" in name → `mix_demo`
- `mix_demo`: keywords are case-insensitive ("MIX", "Mix" → match)
- `clean`: sub-10-min, no keywords, no path signals → `clean`
- `dirty_tag`: artist containing `http` → flag set to `True` regardless of movement classification
- `dirty_tag`: album containing `www.` → flag set to `True`
- `dirty_tag`: clean tags → flag `False`
- Edge case: missing/None duration → treated as 0 (not `long_audio`)
- Edge case: file matching voice_memo + long_audio rules → `voice_memo` wins (priority 1)

### `tests/test_verify.py`
- Copy + verify identical files → returns `True`
- Verify source vs destination with one byte changed → returns `False`
- Missing destination file → returns `False` (no exception bubbles up)
- Zero-byte file → copies and verifies correctly
- Duplicate detection: same filename + identical contents → skip; same filename + different contents (even if same size) → rename
- Duplicate detection: same filename + different size → rename-with-suffix decision returned

### `tests/test_tags.py`
- Detect URL in artist field → `dirty_tag = True`
- Detect URL in album field → `dirty_tag = True`
- Clean fields → `dirty_tag = False`
- Parse TSV row: correct extraction of filepath, new_artist, new_title, clear_album
- `clear_album == "1"` → album cleared, genre unchanged
- `new_genre` given → genre set; omitted → genre unchanged
- `clear_album == "0"` → album unchanged
- Edge cases: empty artist field, non-ASCII characters, very long URLs, tab characters in values

---

## 7. CLI Interface

Each module is runnable directly:

```bash
python audit.py [--library PATH] [--output DIR]
python archive.py --input audit.tsv [--classes voice_memo,long_audio] [--execute]
python fix_tags.py --input phase4_fixes.tsv [--execute]
python remove_library.py --input tracks_to_remove.txt [--execute]
```

**Default behaviour is always safe / non-destructive:**
- `archive.py` and `remove_library.py` require `--execute` to actually delete anything
- `fix_tags.py` defaults to a dry run (writes preview TSV); requires `--execute` to write tags

---

## 8. Dependencies

| Package | Purpose |
|---|---|
| `mutagen` | Read/write audio tags (MP3, M4A, FLAC, WAV, AIFF) |
| `pytest` | Test runner |
| Standard library only otherwise | `hashlib`, `shutil`, `pathlib`, `csv`, `subprocess`, `datetime`, `argparse` |

No third-party HTTP clients, no MusicBrainz, no external API calls.

---

## 9. Non-Functional Requirements

- **Safety first:** no source file is ever deleted without a verified SHA-256 hash match
- **Re-runs:** running archive twice on the same input skips files already archived (identical contents, checked by SHA-256)
- **Explicit execution:** destructive phases require `--execute`; default is always a dry-run or preview
- **macOS only** for `remove_library` phase; all other phases are platform-agnostic
- **No Music.app dependency** for audit, archive, or fix_tags phases
- **Performance:** `remove_library` sends one batched `osascript` call for all tracks, not one per track
- Log and summary files are always written, even if the run fails partway through
- Local script collection (no packaging); runnable with `python <script>.py`
