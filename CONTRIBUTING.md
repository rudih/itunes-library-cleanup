# Contributing to iTunes Cleanup

Thanks for your interest in contributing! This document outlines the process and guidelines.

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/your-username/itunes_cleanup.git
   cd itunes_cleanup
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Install dependencies** (including dev):
   ```bash
   pip install mutagen pytest
   ```

## Development Workflow

### Writing Code

- Place new phases or utilities in `src/itunes_cleanup/`
- Keep related code in existing modules (e.g., classification logic in `audit.py`, not a new file)
- Use type hints where helpful (e.g., `def classify(path: Path, duration_s: float | None) -> str`)
- Default to no comments (self-explanatory code beats comments). Add comments only when the *why* is non-obvious

### Testing

- Write tests for new classification rules, tag patterns, or verification logic
- Tests use real on-disk files (no mocking). Use `pytest`'s `tmp_path` fixture
- All tests must pass before you open a PR:
  ```bash
  pytest tests/ -v
  ```
- Aim for >90% coverage on new code

### Configuration Changes

- Edit `src/itunes_cleanup/config.py` for new thresholds or patterns
- Add comments explaining user-visible options
- Document any new regex patterns (e.g., bounce production patterns)

## Commit Guidelines

- **Atomic commits:** One logical change per commit
- **Clear messages:** 
  - First line: imperative, under 72 characters (e.g., "Fix hash verification for large files")
  - Blank line, then details if needed
  - Reference issues where applicable (e.g., "Fixes #42")

Example:
```
Fix AppleScript path escaping in remove_library

Inside a tell application "Music" block, `as string` is coerced by
Music.app's type system and doesn't match plain text. Pre-process
paths as `as text` outside the tell block.

Fixes #18
```

## Submitting a PR

1. **Push** your branch to your fork
2. **Open a pull request** against `main`
3. **Fill out the PR template** — describe what you changed and why
4. **Link related issues** (e.g., "Closes #42")
5. **Wait for review** — maintainers will comment within 3-5 business days

### PR Requirements

- ✓ All tests pass (`pytest tests/ -v`)
- ✓ No lint errors (try `pylint` or `flake8` if you want to run it)
- ✓ Updated documentation if you added new features or changed behavior
- ✓ At least one approving review

## Areas for Contribution

### Easy (First-Time Contributors)
- Bug fixes in classification logic
- Test coverage for edge cases
- Documentation improvements
- Config examples for other music libraries

### Medium
- New classification patterns or rules
- Performance optimizations (e.g., parallel copying in phase 2)
- New tag patterns or multi-format support
- Better logging / reporting

### Advanced
- Audio fingerprinting for duplicate detection (using AcoustID or librosa)
- MusicBrainz integration to auto-fix tags
- Windows / Linux support (would require different Music.app integration)
- GUI or web interface

## Code Review Expectations

Reviewers may ask for:
- Clarification on why a change was made
- Additional tests for edge cases
- Documentation updates
- Performance benchmarks for significant changes

**Note:** Reviews focus on correctness, safety, and clarity — not style preferences. The tool handles real music libraries, so safety is paramount.

## Incident-Driven Development

This project was born from a real library incident (see [docs/INCIDENT_2026_03_23.md](docs/INCIDENT_2026_03_23.md)). If you discover a safety issue or bug:

1. **Don't open a public issue** for security-related problems
2. **Email the maintainer** with reproduction steps
3. **Suggest a fix** if you have one
4. **We'll patch ASAP** and credit you in the release notes

Safety > Features.

## Licensing

By contributing, you agree that your code is licensed under the MIT License (see [LICENSE](LICENSE)).

## Questions?

- **Issues:** Open a [GitHub issue](https://github.com/rudih/itunes_cleanup/issues)
- **Discussions:** Start a [GitHub discussion](https://github.com/rudih/itunes_cleanup/discussions)
- **Email:** See MAINTAINERS.md (coming soon)

---

**Thanks for contributing! 🎵**
