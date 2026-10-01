---
name: Bug Report
about: Report a bug in iTunes Cleanup
title: "[BUG] "
labels: bug
assignees: ''

---

## Description
A clear and concise description of what the bug is.

## Steps to Reproduce
1. Run `python audit.py`
2. Modify config to ...
3. Run `python archive.py --input audit.tsv --execute`
4. Observe error

## Expected Behavior
What you expected to happen.

## Actual Behavior
What actually happened instead.

## Error Message
If applicable, paste the full error message and traceback:
```
Traceback (most recent call last):
  ...
```

## Environment
- macOS version: (e.g. 13.5)
- Python version: (run `python --version`)
- mutagen version: (run `pip show mutagen`)
- iTunes Cleanup version: (commit hash or branch)

## Library Info
- Approximate library size: X tracks
- Phase that failed: (1: Audit / 2: Archive / 3: Remove from App / 4: Fix Tags)

## Did You Back Up?
- [ ] Yes, I backed up before running any phases

## Additional Context
Any other information that might help (configs changed, unusual file structures, etc.)
