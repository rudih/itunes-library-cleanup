# iTunes & Apple Music Library Cleanup

**A safe, tested Python tool to clean up your iTunes/Apple Music library by removing production bounces, voice memos, long-form audio, and fixing URL-contaminated tags.**

![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue) ![macOS](https://img.shields.io/badge/macOS-10.14%2B-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

---

## What This Does

Old iTunes and Apple Music libraries accumulated junk back when iTunes was the default app for opening audio files: voice memos from your iPhone, production bounces from your DAW, DJ mixes, audio demos, files tagged with URLs instead of proper metadata. This tool **safely identifies and archives** these files, **fixes corrupted tags**, and **removes entries from Music.app** — all with comprehensive verification and rollback protection.

### What It Handles

This tool was built and tested against a real, long-lived personal library. Out of the box it can:
- ✅ **Archive voice memos** synced from an iPhone
- ✅ **Archive production bounces** and work-in-progress exports from your DAW
- ✅ **Archive long-form audio** (10+ minute tracks: mixes, DJ sets, podcasts)
- ✅ **Fix URL-contaminated metadata** (e.g. an artist or album tag set to a download site's web address)
- ✅ **Leave genuine music untouched** in the library
- ✅ **Avoid accidental file loss** through hash verification and dry-run defaults

These categories reflect one library. Yours will have its own kinds of clutter; see [Customising for Your Library](#customising-for-your-library) to change what gets archived.

**Note:** One incident in March 2026 accidentally removed valid entries from the Music.app index (not files on disk). The library was restored from Time Machine. See [INCIDENT_2026_03_23.md](docs/INCIDENT_2026_03_23.md) for the root cause analysis and safety improvements implemented since.

---

## ⚠️ Critical: Before You Begin

**Back up your iTunes library before running this tool.** While the tool is designed to be safe (hash verification, trash-not-delete), accidental deletion is always possible.

### Recommended Backup Steps

1. **Time Machine / Full System Backup**
   ```bash
   # Check Time Machine status
   tmutil latestbackup
   
   # Ensure a recent backup exists before proceeding
   ```

2. **Manual iTunes Library Copy**
   ```bash
   # Copy your entire Music library to an external drive
   cp -r ~/Music/Music ~/Music/Music-Backup-$(date +%Y%m%d)
   ```

3. **Local Snapshot (Optional)**
   ```bash
   # Create a timestamped copy in your home directory
   cp -r ~/Music/Music ~/Music-Library-$(date +%Y%m%d-%H%M%S).bak
   ```

**Do not proceed without at least one backup.** If something goes wrong:
- Files on disk are never permanently deleted (moved to Trash)
- Music.app library entries can be restored from Time Machine
- The tool provides detailed error logs for each phase

---

## Installation

### Requirements
- **Python 3.9+** (macOS ships with 3.x; use `brew install python3` if needed)
- **macOS 10.14+** (for Music.app integration)
- **mutagen** (installs automatically)
- **pytest** (for running tests; optional)

### Quick Start

1. Clone this repository:
   ```bash
   git clone https://github.com/rudih/itunes-library-cleanup.git
   cd itunes-library-cleanup
   ```

2. Install dependencies:
   ```bash
   pip install mutagen pytest
   ```

3. Customise paths and rules to match your library (see [Customising for Your Library](#customising-for-your-library)):
   ```python
   LIBRARY_ROOT = Path("~/Music/Music/iTunes/iTunes Media/Music").expanduser()
   ARCHIVE_VOICE = Path("~/Documents/Voice Notes").expanduser()
   # ... etc
   ```

4. Run a dry-run audit:
   ```bash
   python audit.py
   ```

---

## Usage: 5-Phase Workflow

### Phase 1: Audit (Read-Only Scan)

Scan your iTunes library and classify every file. No files are moved or modified.

```bash
python audit.py [--library PATH] [--output DIR]
```

**Output:** `audit_YYYYMMDD_HHMMSS.tsv` — a spreadsheet with columns:
- `filepath` — full path to the file
- `classification` — `voice_memo`, `long_audio`, `bounce`, `mix_demo`, or `clean`
- `dirty_tag` — `True` if artist/album contains a URL pattern
- `artist`, `title`, `album` — metadata from the file
- `duration_s`, `size_bytes` — file properties

**Example Audit Report (abbreviated):**
```
filepath                                  | classification | dirty_tag | artist            | title         | duration_s | size_bytes
~/Music/Music/.../Voice Memos/idea.m4a    | voice_memo     | False     | My iPhone         | Idea v1       | 45         | 485000
~/Music/Music/.../Unknown/Unknown/v1.wav  | bounce         | False     | Unknown Artist    | v1            | 120        | 2400000
~/Music/Music/.../Track 01.mp3            | long_audio     | True      | http___blog_.com_ | Mix           | 620        | 18000000
~/Music/Music/.../Song.mp3                | clean          | False     | Artist            | Song Title    | 180        | 5000000
```

You can **inspect, filter, and edit this spreadsheet** before proceeding to phase 2. Remove rows you don't want to archive, or add manual overrides in `config.py`.

### Phase 2: Archive (Copy → Verify → Delete)

Copy files to destination folders, verify integrity via SHA-256, and delete sources.

```bash
# Dry-run: show what would happen (no files moved)
python archive.py --input audit.tsv

# Archive only voice memos (dry-run)
python archive.py --input audit.tsv --classes voice_memo

# Actually archive (requires --execute)
python archive.py --input audit.tsv --classes voice_memo,long_audio --execute
```

**What happens:**
1. Copy source file to destination (e.g., `~/Music/Archive/Voice Notes/`)
2. Calculate SHA-256 hash of source and destination
3. If hashes match: delete source file (move to Trash)
4. If hashes don't match: leave source untouched, log error

**Duplicate handling:**
- Same filename + same size → skip (already archived)
- Same filename + different size → rename destination with suffix, archive both

**Output:** `summary_YYYYMMDD_HHMMSS.txt` + appended `run_log.tsv`

### Phase 3: Remove from Music.app

Remove archived tracks from Music.app's library index. Moves the original file to Trash as a safety net.

```bash
# List tracks to remove (from phase 2 output)
python archive.py --input audit.tsv --classes voice_memo --execute 2>&1 | grep "tracks_to_remove"

# Dry-run: show what would be removed
python remove_library.py --input tracks_to_remove_YYYYMMDD_HHMMSS.txt

# Actually remove from Music.app
python remove_library.py --input tracks_to_remove_YYYYMMDD_HHMMSS.txt --execute
```

**Why this matters:** After phase 2 (file deletion), the tracks still appear in Music.app. Phase 3 removes them from the Music.app library. Files are moved to Trash (not permanently deleted) for safety.

**Note:** Music.app must be running for this phase (uses AppleScript via `osascript`).

### Phase 4: Fix Tags (Optional)

Fix URL-contaminated tags directly in file metadata. Useful for files you're keeping but want to fix.

```bash
# Generate a preview of what would be fixed
python fix_tags.py --input docs/examples/phase4_fixes.tsv --dry-run

# Review the preview, then execute
python fix_tags.py --input phase4_fixes_preview_YYYYMMDD_HHMMSS.tsv --execute
```

**Input format (TSV):**
```
filepath                           | new_artist      | new_title | clear_album
~/Music/Music/.../Song.mp3        | Artist Name     | Song      | 1
```

- `new_artist`, `new_title` — replacement values
- `clear_album` — set to `1` to clear album + set genre to "Dance", or `0` to leave unchanged

### Phase 5: Summary & Logging

Automatically generated after phases 2, 3, or 4. Shows:
- Files processed, archived, verified, failed, skipped
- Total data moved (MB)
- Full error list with file paths
- Phase duration

**Persistent run log:** `run_log.tsv` tracks all operations across sessions.

---

## Configuration

Edit `src/itunes_cleanup/config.py` to customise behaviour:

```python
# Library location (macOS default shown)
LIBRARY_ROOT = Path("~/Music/Music/iTunes/iTunes Media/Music").expanduser()

# Archive destinations
ARCHIVE_VOICE = Path("~/Documents/Voice Notes").expanduser()
ARCHIVE_LONG_AUDIO = Path("~/Music/Archive/Long Audio Files").expanduser()
ARCHIVE_BOUNCES = Path("~/Music/Archive/Production Bounces").expanduser()
ARCHIVE_MIXES = Path("~/Music/Archive/My Mixes and Demos").expanduser()

# Classification thresholds
LONG_AUDIO_THRESHOLD_MINUTES = 10  # 10+ min = long_audio
MIX_KEYWORDS = [r"\bmix\b", r"\bdemo\b", r"\bset\b", r"\bvol\d*\b", r"\bdj\s+set\b"]

# Your artist folders (files here are bounces unless they contain "released")
BOUNCE_ARTIST_FOLDERS = {"your artist name"}

# Artist tags that mark synced voice memos (your phone's name)
VOICE_MEMO_ARTISTS = {"alex's iphone"}

# URL patterns indicating contaminated tags
URL_PATTERNS = ["http", "www.", ".com", ".net", ".org", ".blogspot"]

# Manual overrides (applied before automatic rules)
MANUAL_OVERRIDES = {
    "Some Artist - Long Album Track": "clean",   # genuine long release, keep it
    "My Track v3":                    "bounce",  # production file
}
```

---

## Customising for Your Library

Every library collects different clutter. The categories above (voice memos, bounces, long audio, mixes/demos) are only defaults. Before you run anything, make the rules describe *your* library.

`src/itunes_cleanup/config.py` holds the defaults. Put your own values in `src/itunes_cleanup/local_config.py`; any setting you define there replaces the default. That file is git-ignored, so your library details stay out of the repository and survive `git pull`:

```python
# src/itunes_cleanup/local_config.py
BOUNCE_ARTIST_FOLDERS = {"your artist name"}
VOICE_MEMO_ARTISTS = {"alex's iphone"}
MANUAL_OVERRIDES = {"Some Artist - Long Album Track": "clean"}
```

### Tune the built-in categories

| You want to… | Change this in `config.py` |
|---|---|
| Keep tracks longer than 10 minutes (e.g. extended mixes, classical) | Raise `LONG_AUDIO_THRESHOLD_MINUTES` |
| Catch or stop catching mixes/demos by filename | Add or remove regexes in `MIX_KEYWORDS` (e.g. `r"\bpodcast\b"`, `r"\bep\s*\d+\b"`) |
| Mark your own productions as bounces | Put your artist folder names in `BOUNCE_ARTIST_FOLDERS` |
| Keep finished releases from those folders | Set `BOUNCE_RELEASED_MARKER` to a word you use in released filenames |
| Match your DAW or mastering service's export names | Edit `BOUNCE_PRODUCTION_PATTERNS` (e.g. `r"^bounce_"`, `r"\bmaster\b"`) |
| Treat lossless files as music, not bounces | Remove extensions from `BOUNCE_EXTENSIONS` |
| Flag other junk in tags | Add strings to `URL_PATTERNS` (e.g. a site name, `"promo only"`) |
| Send files somewhere else | Change the `ARCHIVE_*` paths |
| Catch voice memos tagged with your phone's name | Add the name to `VOICE_MEMO_ARTISTS` (e.g. `"alex's iphone"`) |
| Override a single track | Add its filename (without extension) to `MANUAL_OVERRIDES` |

Voice memos are matched by a `Voice Memos` folder anywhere in the path, or by an artist tag listed in `VOICE_MEMO_ARTISTS`.

### Add a new audio type

Say your library is full of audiobook chapters, lecture recordings, or ringtones. To archive them as their own category:

1. **Add a destination** in `config.py`:
   ```python
   ARCHIVE_AUDIOBOOKS = Path("~/Music/Archive/Audiobooks").expanduser()
   AUDIOBOOK_KEYWORDS = [r"\bchapter\s*\d+\b", r"\bunabridged\b"]
   ```
2. **Add a detector and a rule** in `src/itunes_cleanup/audit.py`. `classify()` checks rules in priority order and the first match wins, so place yours where it belongs relative to the others:
   ```python
   def _is_audiobook(path: Path, album: str) -> bool:
       text = f"{path.stem} {album}"
       return any(re.search(kw, text, re.I) for kw in config.AUDIOBOOK_KEYWORDS)

   # inside classify(), before the long_audio check:
   if _is_audiobook(path, album):
       return "audiobook"
   ```
3. **Map the class to its folder** by adding `"audiobook": config.ARCHIVE_AUDIOBOOKS` to `DEST_MAP` in `src/itunes_cleanup/archive.py`.
4. **Add a test** in `tests/test_classify.py` using a synthetic path, following the existing test classes.
5. **Dry-run it.** Run `python audit.py`, open the TSV, and check that the new class matches what you expect (and nothing else) before archiving with `--classes audiobook --execute`.

### Keep a type you don't want archived

You don't need to remove a category from the code. Pass `--classes` to `archive.py` with only the categories you want (it defaults to all of them), and everything else stays in the library. To stop a category from appearing in the audit at all, delete its check from `classify()`.

> **Tip:** Change one rule at a time and re-run the audit after each change. The audit is read-only, so you can iterate on it as often as you like.

---

## Safety Features

| Feature | How It Works |
|---------|---|
| **Hash Verification** | SHA-256 comparison before deletion. Source untouched if hashes don't match. |
| **Trash-Not-Delete** | Files moved to Trash, not permanently removed. Recoverable for 24+ hours. |
| **Dry-Run by Default** | All destructive phases require explicit `--execute` flag. Safe preview first. |
| **Duplicate Detection** | Prevents re-archiving the same file twice. |
| **Phase Independence** | Run phases individually or in sequence. Idempotent (safe to re-run). |
| **Audit Trail** | Every operation logged to `run_log.tsv` with timestamp, counts, and errors. |
| **Human Inspection** | Audit reports as TSV files — inspect, filter, edit in Excel/Numbers before executing. |

---

## Testing

Run the test suite to verify classification logic, copy verification, and tag fixing:

```bash
# Install test dependencies
pip install pytest mutagen

# Run all tests
pytest tests/ -v

# Run a specific test
pytest tests/test_classify.py::TestVoiceMemo -v
```

**Test coverage:**
- `test_classify.py` — 14+ tests for classification priority, edge cases, manual overrides
- `test_verify.py` — 8+ tests for hash verification, duplicate detection, zero-byte files
- `test_tags.py` — 10+ tests for URL detection, tag parsing, tag writing
- `test_remove_library.py` — removal integration tests

All tests use real on-disk files (no mocking) to verify actual behaviour.

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deep dive into the 5-phase workflow, classification rules, and safety patterns.

### Classification Priority

```
Priority 1: voice_memo       → Voice Memos folder OR artist tag matching your phone's name
Priority 2: long_audio       → Duration ≥ 10 minutes (catches mixes, jams, podcasts)
Priority 3: bounce           → Production bounce patterns (folder, LANDR-, version #s)
Priority 4: mix_demo         → Filename keywords: mix, demo, set, vol, dj set
Priority 5: dirty_tag (flag) → Artist/album contains URL pattern (HTTP, .com, .blogspot, etc.)
Priority 6: clean            → None of the above — leave in library
```

---

## Known Issues & Limitations

- **macOS only** — Uses `osascript` for Music.app integration. Linux/Windows not supported.
- **Music.app dependency** — Phase 3 (remove from library) requires Music.app running.
- **No Music.app needed** — Phases 1, 2, and 4 work without Music.app open.
- **iTunes XML export** — Optional; library scanning uses file system directly.
- **Duplicate detection by filename** — Uses filename + size, not audio fingerprinting. Different edits of the same song may be treated as duplicates.

---

## Incident: Library Wipe (March 2026)

An AppleScript bug in an earlier version accidentally deleted valid Music.app library entries (files on disk were never touched). The library was restored from Time Machine.

**Root cause:** `exists POSIX file p` inside a `tell application "Music"` block was dispatched to Music.app instead of the OS, always returning `false`.

**Lessons learned & implemented:**
- ✅ All file-system checks now happen in Python (before calling AppleScript)
- ✅ Path processing (`as text` coercion) happens outside the tell block
- ✅ Comprehensive test coverage for remove_library logic

See [docs/INCIDENT_2026_03_23.md](docs/INCIDENT_2026_03_23.md) for full details.

---

## Licence

MIT — Use freely. See [LICENSE](LICENSE) for details.

---

## Contributing

Contributions welcome! Areas for improvement:
- Windows / Linux support (would require different Music.app integration)
- GUI interface for non-technical users
- Music fingerprinting for duplicate detection
- MusicBrainz metadata lookup to fix contaminated tags

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## FAQ

**Q: How do I remove voice memos from my iTunes or Apple Music library?**  
A: Run `python audit.py` to find them, then `python archive.py --input audit.tsv --classes voice_memo --execute` to move them to an archive folder, then `python remove_library.py --input tracks_to_remove_YYYYMMDD_HHMMSS.txt --execute` to remove the entries from Music.app. Each step does a dry run first unless you pass `--execute`.

**Q: How do I remove DAW bounces and production exports from Apple Music?**  
A: The audit classifies these as `bounce`: files in a `Production Bounces` folder, LANDR exports, Unknown Artist files with version numbers (`v3`) or words like `rough` or `wip`, and WAV/AIFF files named `Track 01` or starting with a date. Archive them with `--classes bounce`. Add your artist name to `BOUNCE_ARTIST_FOLDERS` to catch bounces filed under your own name, and edit `BOUNCE_PRODUCTION_PATTERNS` to match your DAW's export names.

**Q: How do I find long DJ mixes and podcasts in my iTunes library?**  
A: Any track of 10 minutes or more is classified as `long_audio`. Change `LONG_AUDIO_THRESHOLD_MINUTES` to adjust the cut-off, and add genuine long tracks to `MANUAL_OVERRIDES` to keep them.

**Q: How do I fix artist or album tags that show a website URL?**  
A: The audit flags these in the `dirty_tag` column. List the corrections in a TSV (see `docs/examples/phase4_fixes.tsv`) and run `python fix_tags.py`. It previews the changes first and only writes tags with `--execute`.

**Q: Does it work with the Music app, or only old iTunes?**  
A: It works with the Music app on current macOS. The library files are scanned directly, so phases 1, 2 and 4 don't depend on which app you use.

**Q: Is this safe?**  
A: Yes. All destructive operations default to dry-run and require explicit `--execute`. Files are moved to Trash (recoverable) and verified via SHA-256 before deletion. Backup before you start, just in case.

**Q: Do I need Music.app running?**  
A: Only for phase 3 (remove from Music.app). Phases 1, 2, and 4 work without it.

**Q: Can I run just one phase?**  
A: Yes. Each phase is independent. You can audit, then skip archiving, then fix tags later. No required order.

**Q: What if something goes wrong?**  
A: Check `~/Music/Archive/logs/` for detailed error reports. Restore from your backup. Files moved to Trash are recoverable for 24+ hours.

**Q: How long does it take?**  
A: Depends on library size. Phase 1 (audit) takes ~1-2 minutes for 4,000 tracks. Phase 2 (archive) takes ~5-10 minutes per 500 files (depends on disk speed). Phase 3 (remove from Music.app) is slower per-track due to AppleScript IPC.

---

## Support

- **Issues:** Found a bug or have a question? [Open an issue](https://github.com/rudih/itunes-library-cleanup/issues)
- **Incident Reports:** See [docs/](docs/) for detailed logs and incident analysis

---

**Made with ❤️ for people with messy music libraries.**
