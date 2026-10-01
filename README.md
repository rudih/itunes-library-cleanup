# iTunes & Apple Music Library Cleanup

**Audit and clean up a local iTunes or Apple Music library on macOS. Find voice memos, DAW exports and long recordings, then selectively archive them or fix unwanted metadata. Dry-run by default; back up your library and review every preview before running anything for real.**

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue) ![macOS](https://img.shields.io/badge/macOS-10.15%2B-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

---

## What This Does

Old iTunes and Apple Music libraries accumulated junk back when iTunes was the default app for opening audio files: voice memos from your iPhone, production bounces from your DAW, DJ mixes, audio demos, files tagged with URLs instead of proper metadata. This tool **safely identifies and archives** these files, **fixes corrupted tags**, and **removes entries from Music.app** — with SHA-256-verified archive copies and a dry-run preview before anything changes.

### What It Handles

This tool was built and tested against a real, long-lived personal library. Out of the box it can:
- ✅ **Archive voice memos** synced from an iPhone
- ✅ **Archive production bounces** and work-in-progress exports from your DAW
- ✅ **Archive long-form audio** (10+ minute tracks: mixes, DJ sets, podcasts)
- ✅ **Fix URL-contaminated metadata** (e.g. an artist or album tag set to a download site's web address)
- ✅ **Leave genuine music untouched** in the library
- ✅ **Preview before acting**: every phase that changes files is a dry run unless you pass `--execute`

These categories reflect one library. Yours will have its own kinds of clutter; see [Customising for Your Library](#customising-for-your-library) to change what gets archived.

**Note:** One incident in March 2026 accidentally removed valid entries from the Music.app index (not files on disk). The library was restored from Time Machine. See [INCIDENT_2026_03_23.md](docs/INCIDENT_2026_03_23.md) for the root cause analysis and safety improvements implemented since.

---

## ⚠️ Critical: Before You Begin

**Back up your library before running this tool.** The author has used it successfully on their own library, but your setup may differ (library location, file formats, iCloud Music Library / Sync Library, external drives), so be sure to have a backup before use.

Know what the destructive steps do:
- **Phase 2 (archive)** copies each file to an archive folder, checks the copy with SHA-256, then **permanently deletes the original**. It is not moved to the Trash; the archive copy is your copy.
- **Phase 3 (remove from library)** deletes entries from your Music library and moves any remaining files to the Trash. With Sync Library turned on, deleting from your library can also remove items from your other devices.
- **Phase 4 (fix tags)** rewrites metadata inside your audio files.

### Recommended Backup Steps

1. **Time Machine / Full System Backup**
   ```bash
   # Check Time Machine status
   tmutil latestbackup
   
   # Ensure a recent backup exists before proceeding
   ```

2. **Manual iTunes Library Copy**
   ```bash
   # Copy your entire Music folder (library file + media)
   cp -r ~/Music/Music ~/Music/Music-Backup-$(date +%Y%m%d)
   ```

3. **Local Snapshot (Optional)**
   ```bash
   # Create a timestamped copy in your home directory
   cp -r ~/Music/Music ~/Music-Library-$(date +%Y%m%d-%H%M%S).bak
   ```

**Do not proceed without at least one backup.** If something goes wrong:
- Archived files are in your archive folders (each copy was hash-checked before its original was deleted)
- Files removed in phase 3 are in the Trash until you empty it
- Your Music library (playlists, play counts, entries) can be restored from your backup
- Check the terminal output and `~/Music/Archive/logs/` for errors

---

## Installation

### Requirements
- **Python 3.10+** (check with `python3 --version`; use `brew install python3` if needed)
- **macOS 10.15 (Catalina) or later** for phase 3, which scripts the Music app. Phases 1, 2 and 4 work on the files directly.
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
3. If hashes match: delete the original file permanently (it is **not** moved to the Trash)
4. If hashes don't match: leave source untouched, log error

**Duplicate handling:**
- Same filename + identical contents (SHA-256) → skip (already archived)
- Same filename + different contents → archive under a `(potential duplicate N)` name, so both are kept

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
# Dry run (default): writes fix_tags_preview_YYYYMMDD_HHMMSS.tsv showing current vs new tags
python fix_tags.py --input my_fixes.tsv

# Review the preview, then run again on the SAME input file
python fix_tags.py --input my_fixes.tsv --execute
```

**Input format (TSV):**
```
filepath                           | new_artist      | new_title | clear_album | new_genre
~/Music/Music/.../Song.mp3        | Artist Name     | Song      | 1           | House
```

- `new_artist`, `new_title` — replacement values (leave empty to keep the current value)
- `clear_album` — set to `1` to clear the album, or `0` to leave it unchanged
- `new_genre` — optional; leave empty or omit the column to keep the current genre

See `docs/examples/phase4_fixes.tsv` for a template.

> **Run `--execute` on your fixes file, not the preview.** The preview has extra columns for review only; `fix_tags.py` refuses to use it as input.

Supported formats: MP3, M4A, FLAC, WAV and AIFF.

### Phase 5: Summary & Logging

Phase 3 writes a summary file (`summary_YYYYMMDD_HHMMSS.txt`) and appends a row to `run_log.tsv` in the log folder, showing:
- Tracks processed, removed, trashed, not found and failed
- Full error list with file paths
- Phase duration

Phases 2 and 4 print their results to the terminal; phase 2 also writes the `tracks_to_remove_*.txt` list used by phase 3. Keep the terminal output if you want a record of those runs.

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
| **Hash Verification** | Each archive copy is checked with SHA-256 before the original is deleted. If the hashes don't match, the original is left untouched. |
| **Archive Before Delete** | Phase 2 deletes an original only after a verified copy exists in the archive. Phase 3 moves files to the Trash rather than deleting them. |
| **Dry-Run by Default** | Every phase that changes files or your library needs an explicit `--execute` flag. |
| **Skip Already-Archived Files** | A file is skipped only if the archive already holds a copy with identical contents (SHA-256). Same name, different contents → both are kept. |
| **Phase Independence** | Run phases individually or in sequence. |
| **Human Inspection** | Audit reports are TSV files — inspect, filter and edit them in Excel/Numbers before executing. |

These features reduce risk; they don't remove it. They have worked on the author's library, but they aren't a substitute for a backup.

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
- **Not a duplicate-song finder** — Archive collisions are checked by exact file contents, so different encodes or edits of the same song are treated as different files. There's no audio fingerprinting.
- **iCloud Music Library / Sync Library** — Not tested. Deleting from your library may also remove items from other devices.
- **Heuristic classification** — Long duration, filename keywords and folder names are signals, not proof. Genuine music can be flagged, so review the audit before archiving, and pass `--classes` to archive only the categories you've checked.

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
A: Phase 3 scripts the Music app, so it needs macOS 10.15 (Catalina) or later. Phases 1, 2 and 4 work on the library files directly, so they don't depend on which app you use.

**Q: Is this safe?**  
A: The author has used it successfully on their own library, but your setup may differ, so back up your library before use. Every phase that changes anything is a dry run unless you pass `--execute`, and archive copies are hash-checked before originals are deleted. Phase 2 deletes originals permanently (not to the Trash), so review the audit and dry-run output before executing.

**Q: Do I need Music.app running?**  
A: Only for phase 3 (remove from Music.app). Phases 1, 2, and 4 work without it.

**Q: Can I run just one phase?**  
A: Yes. Each phase is independent. You can audit, then skip archiving, then fix tags later. No required order.

**Q: What if something goes wrong?**  
A: Check the terminal output and `~/Music/Archive/logs/` for errors. Archived files are in your archive folders, files removed in phase 3 are in the Trash until you empty it, and anything else (including your Music library itself) comes back from your backup.

**Q: How long does it take?**  
A: Depends on library size. Phase 1 (audit) takes ~1-2 minutes for 4,000 tracks. Phase 2 (archive) takes ~5-10 minutes per 500 files (depends on disk speed). Phase 3 (remove from Music.app) is slower per-track due to AppleScript IPC.

---

## Support

- **Issues:** Found a bug or have a question? [Open an issue](https://github.com/rudih/itunes-library-cleanup/issues)
- **Incident Reports:** See [docs/](docs/) for detailed logs and incident analysis

---

**Made with ❤️ for people with messy music libraries.**
