# CLAUDE.md

## What This Project Does

Safe, tested Python tool that cleans an iTunes/Apple Music library: archives voice memos,
production bounces, and long-form audio (10+ min mixes/podcasts), fixes URL-contaminated tags,
and removes stale entries from Music.app — with hash verification, dry-run defaults, and
archive-not-delete throughout. Developed against a real, long-lived personal library.

## Layout

- `src/itunes_cleanup/` — the package (classification, verification, Music.app scripting)
- Root wrapper scripts: `audit.py`, `archive.py`, `fix_tags.py`, `remove_library.py`
- `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `tests/` (pytest)

## Commands

```bash
python3 audit.py                      # scan library, produce classification report
python3 archive.py                    # dry-run by default; --execute to act
python3 fix_tags.py                   # clean URL-contaminated artist/album tags
python3 remove_library.py --execute   # remove archived entries from Music.app index
pytest
```

## SAFETY — read before touching anything destructive

**This project caused a real incident: 2026-03-23, every valid track deleted from the
Music.app index (restored from Time Machine). Read `docs/INCIDENT_2026_03_23.md` first.**

Root cause and standing rules:
- **Never put OS/filesystem commands inside an AppleScript `tell application "Music"` block** —
  `exists POSIX file p` etc. dispatch to Music.app, not the OS, and return wrong answers.
- Dry-run first, always; show the manifest; require explicit user go-ahead for `--execute`.
- Verify a Time Machine backup exists (`tmutil latestbackup`) before any execute pass.
- Archive/trash rather than delete; verify file hashes before and after moves.
- Music.app and Ableton have built-in locate/reconnect UI for missing files — suggest that
  before writing reconnection scripts.
- Batch OS-level deletions so the user isn't prompted for a password per file.
