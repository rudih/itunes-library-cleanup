# Architecture: 5-Phase iTunes Library Cleanup

This document explains the design philosophy, phase workflow, classification rules, and safety patterns used in iTunes Library Cleanup (Python package `itunes_cleanup`).

---

## Design Principles

1. **Phase Separation** — Each phase is independent. Can run phase 1 → phase 2 → phase 4, skipping phase 3. No forced order.
2. **Human Inspection** — Data flows through TSV files. Users can inspect, filter, edit, and re-run with confidence.
3. **Safety First** — All destructive operations default to dry-run. Explicit `--execute` required. Hash verification before deletion. Phase 3 moves files to the Trash; phase 2 deletes originals permanently once their archive copy is verified.
4. **Filesystem Truth** — Direct file traversal + mutagen for ground truth, not iTunes XML (which can become stale).
5. **Comprehensive Logging** — Every run is logged. Audit trail persists in `run_log.tsv`.

---

## Phase Overview

```
┌──────────────────────────────────────────────────────────┐
│ Phase 1: AUDIT                                          │
│ Input:  ~/Music/Music/iTunes/iTunes Media/Music/        │
│ Output: audit_YYYYMMDD_HHMMSS.tsv                       │
│ Role:   Read-only scan + classify every file            │
│ Time:   ~1-2 min for 4,000 tracks                       │
│ Safety: ✓ No files touched                              │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ Phase 2: ARCHIVE                                        │
│ Input:  audit.tsv (filter by --classes)                │
│ Output: tracks_to_remove_*.txt                          │
│ Role:   Copy → SHA-256 verify → delete                  │
│ Time:   ~5-10 min per 500 files (disk-dependent)       │
│ Safety: ✓ Hash verification before deletion             │
│         ✓ Duplicate detection + rename                  │
│         ✗ Originals deleted permanently (not to Trash)  │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ Phase 3: REMOVE FROM MUSIC.APP                         │
│ Input:  tracks_to_remove_*.txt (from phase 2)          │
│ Output: summary_*.txt + removal report                  │
│ Role:   Remove library entries via AppleScript          │
│ Time:   ~1-5 min (depends on count)                    │
│ Safety: ✓ Batched osascript (no per-track IPC)        │
│         ✓ Path pre-processing avoids type coercion      │
│         ✓ Moves to Trash as final safety net           │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ Phase 4: FIX TAGS (Optional)                            │
│ Input:  phase4_fixes.tsv (user-created TSV)            │
│ Output: summary_*.txt + modified files                  │
│ Role:   Direct mutagen write to fix URL-contaminated    │
│         metadata                                         │
│ Time:   <1 min for 50-100 files                        │
│ Safety: ✓ Dry-run preview by default                   │
│         ✓ Inspect preview before --execute              │
│         ✓ No Music.app dependency                       │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ Phase 5: SUMMARY & LOG (Auto)                           │
│ Output: summary_*.txt (human-readable)                  │
│         run_log.tsv (persistent append)                 │
│ Role:   Generate summary report + update run log        │
│ Safety: ✓ Appended to persistent log even on failure   │
└──────────────────────────────────────────────────────────┘
```

---

## Phase 1: Audit (Read-Only Scan)

### Purpose
Traverse the entire iTunes library directory, classify every audio file, read metadata via `mutagen`, and output a human-readable TSV report.

### Workflow

```python
for audio_file in library:
    1. Determine relative path from library root
    2. Apply classification rules (priority order):
       a. Check manual overrides first
       b. Apply voice_memo rule
       c. Apply long_audio rule (duration ≥ 10 min)
       d. Apply bounce rule (folder patterns, LANDR-, artist folder, version #s)
       e. Apply mix_demo rule (filename keywords)
       f. Flag dirty_tag if applicable (URL patterns in artist/album)
       g. Default to "clean"
    3. Read metadata: artist, title, album, duration via mutagen
    4. Append to TSV: filepath | classification | dirty_tag | artist | title | album | duration_s | size_bytes
```

### Classification Rules (Priority Order)

#### Rule 1: Manual Overrides (Highest Priority)
```python
MANUAL_OVERRIDES = {
    "Some Artist - Long Album Track": "clean",   # genuine long release
    "My Track v3": "bounce",                     # production file
}
```
Applied to filename stem (without extension), case-insensitive. Overrides all other rules.

#### Rule 2: voice_memo
```python
def _is_voice_memo(path: Path, artist: str) -> bool:
    return (
        "voice memos" in [p.lower() for p in path.parts]
        or artist.lower() in {name.lower() for name in config.VOICE_MEMO_ARTISTS}
    )
```
Catches voice memos synced from iPhone. Checked before duration to ensure priority.

#### Rule 3: long_audio (Duration ≥ 10 minutes)
```python
def _is_long_audio(duration_s: float | None) -> bool:
    return duration_s >= config.LONG_AUDIO_THRESHOLD_MINUTES * 60
```
Threshold configurable; default 10 minutes. Catches mixes, jams, podcasts, DJ sets. Sub-10-min bounces and mixes are handled by later rules.

#### Rule 4: bounce (Production Bounces)
Three signals checked in priority order:

**4a. Bounce Folder Path:**
```python
if "Production Bounces" in path.parts:
    return "bounce"
```

**4b. User's Artist Folders (with "released" exception):**
```python
if artist_folder in BOUNCE_ARTIST_FOLDERS:
    if "released" not in filename_stem.lower():
        return "bounce"  # Files here are bounces unless "released"
```

**4c. LANDR Export + Version Patterns (Unknown Artist):**
```python
if "unknown artist" in path.parts.lower():
    if matches_bounce_patterns(filename):  # v1, v3.2, LANDR-, ozone, wip, etc.
        return "bounce"
```

Regex patterns (configurable):
```python
BOUNCE_PRODUCTION_PATTERNS = [
    r"^landr-",                      # LANDR mastered export
    r"\bv\d+[\d\.]*[a-z]?\b",       # version: v1, v3.2, v5b
    r"\b(ozone|rough|wip|bounce|instrumental)\b",
]
```

#### Rule 5: mix_demo (Filename Keywords)
```python
MIX_KEYWORDS = [r"\bmix\b", r"\bdemo\b", r"\bset\b", r"\bvol\d*\b", r"\bdj\s+set\b"]

def _is_mix_demo(path: Path) -> bool:
    filename_lower = path.stem.lower()  # without extension
    return any(re.search(pattern, filename_lower, re.IGNORECASE) for pattern in MIX_KEYWORDS)
```

Applied only to sub-10-min files (to avoid catching genuine 11-min releases named "mix").

#### Rule 6: dirty_tag (Flag Only, Not a Movement)
```python
def _is_dirty_tag(artist: str, album: str) -> bool:
    return any(pat.lower() in artist.lower() or pat.lower() in album.lower()
               for pat in URL_PATTERNS)

URL_PATTERNS = ["http", "www.", ".com", ".net", ".org", ".uk", ".blogspot"]
```

Files flagged `dirty_tag = True` are NOT moved in phase 2. They're left in place but flagged for phase 4 (tag fixing). A file can be both `long_audio` and `dirty_tag`.

#### Rule 7: clean (Default)
```python
if not matched_any_above:
    return "clean"
```

### Output Format

**audit_YYYYMMDD_HHMMSS.tsv**
```
filepath | classification | dirty_tag | artist | title | album | duration_s | size_bytes
~/Music/Music/Artist/Album/Song.mp3 | clean | False | Artist | Song | Album | 180 | 5000000
~/Music/Music/.../Voice Memos/idea.m4a | voice_memo | False | My iPhone | Idea | | 45 | 485000
```

**Human inspection:** Open in Excel/Numbers, filter by classification, remove rows you don't want to archive, save, and pass to phase 2.

---

## Phase 2: Archive (Copy → Verify → Delete)

### Purpose
Safe file archival with three-step verification: copy → hash check → delete.

### Workflow

```python
for each row in audit.tsv:
    if classification in --classes (or all if not filtered):
        1. Check if destination file exists (duplicate handling)
        2. Copy source → destination
        3. Hash source and destination (SHA-256)
        4. If hashes match:
               - Delete source permanently (not to Trash)
               - Log as "archived + verified"
           Else:
               - Leave source untouched
               - Log as "failed verification"
        5. Track: processed, archived, verified, failed, skipped
```

### Duplicate Handling

| Scenario | Decision |
|----------|----------|
| Same filename + identical contents (SHA-256) | Skip (already archived) |
| Same filename + different contents | Rename destination with suffix `(potential duplicate N)` |
| Matches an existing `(potential duplicate N)` copy | Skip (already archived on a previous run) |
| Different filename | Proceed normally |

**Rationale:** Size is checked first as a cheap filter; files are only hashed when name and size both match. A skip therefore always means an identical copy exists in the archive, which makes it safe to list the source for library removal. Audio fingerprinting (different encodes of the same song) could be added in a future version.

### Verification: SHA-256 Hash

```python
def verify_copy(source: Path, destination: Path) -> bool:
    source_hash = hash_file(source)
    dest_hash = hash_file(destination)
    return source_hash == dest_hash

def hash_file(path: Path, chunk_size=1024*1024) -> str:
    # Read in 1MB chunks (handles large files efficiently)
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()
```

**Safety:** Source file is **never deleted** until hash matches. Bit-rot, disk errors, or incomplete copies are caught.

### Output

**summary_YYYYMMDD_HHMMSS.txt** (human-readable)
```
Phase: archive
Timestamp: 2026-03-22 15:30:45
Files processed: 120
Files archived: 120
Files verified: 120
Files failed: 0
Files skipped: 0
Total data moved: 1,500 MB
Duration: 7 min 34 sec

Errors: None
```

**tracks_to_remove_YYYYMMDD_HHMMSS.txt** (file paths, one per line)
```
/Users/yourname/Music/Music/iTunes/iTunes Media/Music/Artist/Song.mp3
/Users/yourname/Music/Music/iTunes/iTunes Media/Music/Voice Memos/idea.m4a
...
```

**run_log.tsv** (persistent append)
```
timestamp | phase | processed | archived | verified | failed | skipped | data_mb | duration_s
2026-03-22T15:30:45 | archive | 120 | 120 | 120 | 0 | 0 | 1500 | 454
```

---

## Phase 3: Remove from Music.app

### Purpose
Remove archived tracks from Music.app's library index. Files are moved to Trash as a final safety net.

### Why This Phase Exists

After phase 2, files are deleted from disk but still appear in Music.app. Phase 3 removes them from the library. Without this, Music.app shows "missing file" warnings.

### Workflow

```python
1. Read tracks_to_remove.txt (file paths)
2. Build a single batched AppleScript containing all paths
3. Execute: osascript <<EOF
   tell application "Music"
       repeat with targetPath in targetPaths
           try
               set aTrack to (every track whose file is targetPath)
               delete aTrack
           end try
       end repeat
   end tell
EOF
4. For each path: move to Trash as backup
5. Output removal report (removed / not found / errors)
```

### AppleScript Safety Lessons

**Bug Lesson 1:** `exists POSIX file p` inside a `tell application "Music"` block is dispatched to Music.app (which doesn't implement it), always returning `false`. **Fix:** Pre-check file existence in Python; don't ask AppleScript.

**Bug Lesson 2:** `aPath as string` inside a `tell application` block is coerced by Music.app's type system, not AppleScript's. The result doesn't match plain text comparisons. **Fix:** Pre-process paths as `as text` outside the tell block.

**Batching Optimization:** Sending one osascript call with hundreds of paths is ~10x faster than one call per path.

---

## Phase 4: Fix Tags (Optional)

### Purpose
Directly modify audio file metadata to fix URL-contaminated tags. Useful for files you're keeping but need to repair.

### Workflow (Two-Stage)

**Stage 1: Dry-Run (Preview)**
```python
python fix_tags.py --input phase4_fixes.tsv
# Output: fix_tags_preview_YYYYMMDD_HHMMSS.tsv
# User inspects preview and may edit it
```

**Stage 2: Execute**
```python
python fix_tags.py --input fix_tags_preview_YYYYMMDD_HHMMSS.tsv --execute
# Files are modified directly via mutagen
# Output: summary_*.txt with counts
```

### Input Format (TSV)

```
filepath | new_artist | new_title | clear_album | new_genre
~/Music/.../Song.mp3 | Artist Name | Song Title | 0 |
~/Music/.../Mix.mp3  | Unknown Artist | Mix | 1 | House
```

- `filepath` — full path to audio file
- `new_artist` — replacement artist (empty = leave unchanged)
- `new_title` — replacement title (empty = leave unchanged)
- `clear_album` — `0` = keep album, `1` = clear album
- `new_genre` — optional; replacement genre (empty or omitted = leave unchanged)

### Multi-Format Support

```python
from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.aiff import AIFF
```

Supported formats: MP3 (ID3), MP4/M4A (iTunes atoms), FLAC (Vorbis), WAV and AIFF (ID3 chunk inside the RIFF/FORM container, written via mutagen's `WAVE`/`AIFF` classes so the container and audio data are preserved).

### Tag Writing

**Example: MP3 (ID3v2.4)**
```python
audio = MP3(str(filepath))
audio.tags["TIT2"] = TIT2(encoding=3, text=[new_title])
audio.tags["TPE1"] = TPE1(encoding=3, text=[new_artist])
if clear_album:
    audio.tags["TALB"] = TALB(encoding=3, text=[])
if new_genre:
    audio.tags["TCON"] = TCON(encoding=3, text=[new_genre])
audio.save()
```

---

## Phase 5: Summary & Logging

### Summary Report (Human-Readable)

**summary_YYYYMMDD_HHMMSS.txt**
```
==================================================
Phase: archive
Timestamp: 2026-03-22T15:30:45
==================================================

Overview:
  Files processed: 120
  Files archived: 120
  Files verified: 120
  Files failed: 0
  Files skipped: 0

Data Movement:
  Total bytes moved: 1,572,864,000
  Total MB moved: 1,500.00
  Duration: 7 min 34 sec

Errors: None reported.

==================================================
```

### Persistent Run Log (Machine-Readable)

**run_log.tsv** (append-only)
```
timestamp | phase | processed | archived | verified | failed | skipped | tags_fixed | data_mb | duration_s
2026-03-20T10:15:22 | audit | 2000 | | | | | | | 60
2026-03-20T10:20:31 | archive | 200 | 200 | 200 | 0 | 0 | | 1000 | 300
2026-03-20T10:25:45 | remove_library | 200 | | | | | | | 90
2026-03-21T14:33:12 | fix_tags | | | | | | 25 | | 15
```

Used for tracking long-term cleanup progress across multiple runs.

---

## Configuration (`config.py`)

All thresholds and paths in one place:

```python
# Paths (expand ~ to home directory)
LIBRARY_ROOT = Path("~/Music/Music/iTunes/iTunes Media/Music").expanduser()
ARCHIVE_VOICE = Path("~/Documents/Voice Notes").expanduser()
ARCHIVE_LONG_AUDIO = Path("~/Music/Archive/Long Audio Files").expanduser()
ARCHIVE_BOUNCES = Path("~/Music/Archive/Production Bounces").expanduser()
ARCHIVE_MIXES = Path("~/Music/Archive/My Mixes and Demos").expanduser()
LOG_DIR = Path("~/Music/Archive/logs").expanduser()

# Thresholds
LONG_AUDIO_THRESHOLD_MINUTES = 10

# Patterns (regex)
MIX_KEYWORDS = [r"\bmix\b", r"\bdemo\b", r"\bset\b", r"\bvol\d*\b", r"\bdj\s+set\b"]
BOUNCE_PRODUCTION_PATTERNS = [r"^landr-", r"\bv\d+[\d\.]*[a-z]?\b", ...]
URL_PATTERNS = ["http", "www.", ".com", ".net", ".org", ".uk", ".blogspot"]

# User-specific
BOUNCE_ARTIST_FOLDERS = {"your artist name"}  # your artist folders
VOICE_MEMO_ARTISTS = {"your phone's name"}     # artist tag on synced voice memos
BOUNCE_RELEASED_MARKER = "released"

# Overrides
MANUAL_OVERRIDES = {"Some Artist - Long Album Track": "clean", ...}

# File types
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aiff", ".aif", ".flac"}
```

---

## Safety Patterns

### 1. Hash Verification (Before Deletion)

```python
# Phase 2: Archive
source_hash = hash_file(source)
destination_hash = hash_file(destination)
if source_hash == destination_hash:
    delete_source()
else:
    log_error_and_skip()
```

**Guarantees:** Source file is **never deleted** unless the copy is identical.

### 2. Trash in Phase 3 (Partial Safety Net)

Phase 3 asks Finder to move each listed file to the Trash rather than deleting it, so those files stay recoverable until the Trash is emptied.

Phase 2 does **not** use the Trash: once the archive copy's SHA-256 matches, the original is deleted with `unlink()`. The verified archive copy is the recovery path for those files.

### 3. Dry-Run by Default (Explicit Execution)

```bash
# Dry-run (safe, shows what would happen)
python archive.py --input audit.tsv

# Actual execution (requires flag)
python archive.py --input audit.tsv --execute
```

**Guarantees:** No destructive operations without explicit `--execute`.

### 4. Phase Independence (Flexible Workflow)

- Run phase 1 (audit) → inspect → pause
- Run phase 2 (archive) selectively (--classes)
- Skip phase 3 (remove from app) — files are already deleted
- Run phase 4 (fix tags) later on remaining files

**Guarantees:** No forced sequence. Can iterate safely.

### 5. Audit Trail (Persistent Logging)

```
run_log.tsv (append-only) — tracks all operations across sessions
```

**Guarantees:** Complete history; useful for debugging and understanding what happened.

---

## Testing Strategy

### Unit Tests (No Real Files)

**test_classify.py** — 14+ classification tests
- voice_memo priority, long_audio boundaries, bounce patterns, mix keywords, dirty_tag detection
- Edge cases: missing duration, file matching multiple rules, manual overrides

**test_tags.py** — 10+ tag detection/writing tests
- URL detection in artist/album, multi-format support (MP3/MP4/FLAC), dry-run vs. execute

### Integration Tests (Real On-Disk Files)

**test_verify.py** — 8+ hash verification tests
- Copy + hash match, hash mismatch detection, duplicate handling, zero-byte files

**test_remove_library.py** — removal integration
- Path escaping, AppleScript generation, batch handling

### Confidence

All tests use actual files on disk (no mocking). If tests pass, real operations will work.

---

## Future Enhancements

1. **Audio Fingerprinting** — Detect duplicates by content hash (AcoustID), not just filename + size
2. **MusicBrainz Lookup** — Auto-fix tags using MB metadata
3. **GUI / Web Interface** — For non-technical users
4. **Windows / Linux Support** — Would require different Music.app integration (Spotify API, VLC library, etc.)
5. **Batch Filtering UI** — Inspect audit.tsv interactively, not in a spreadsheet
6. **Cloud Integration** — Sync archive to S3, Dropbox, etc.

---

## References

- [INCIDENT_2026_03_23.md](INCIDENT_2026_03_23.md) — Library wipe incident + AppleScript safety lessons
- [REQUIREMENTS.md](REQUIREMENTS.md) — Original specification document
- [../tests/](../tests/) — Test coverage
