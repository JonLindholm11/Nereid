# Contributing to Nereid

Thanks for your interest in contributing to Nereid — a Lunar Systems open source project.

This document covers how to get set up locally, how we work, and what we're looking for from contributors.

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL (local install or Docker)
- Git

### Local Setup

```bash
# Clone the repo
git clone https://github.com/JonLindholm11/Nereid
cd Nereid

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Set up your environment
cp .env.example .env
# Edit .env with your local PostgreSQL connection string
```

### Seed a Test Database

```bash
# Create a test database
createdb nereid_test

# Populate it with dummy data
python scripts/seed_test_db.py --db-url "postgresql://user:password@localhost:5432/nereid_test"
```

### Run the Tests

```bash
pytest
```

### Run the Linter

```bash
ruff check .
```

---

## Project Structure

```
nereid/
├── nereid/
│   ├── cli/
│   │   └── main.py          # CLI entry point — export, watch, review commands
│   ├── core/
│   │   ├── exporter.py      # Reads from Postgres, writes to XLSX or CSV
│   │   ├── differ.py        # Row-level diff engine (old state vs new state)
│   │   ├── watcher.py       # File system watcher with debounce + stability check
│   │   ├── staging.py       # Writes changesets to staging schema
│   │   └── reviewer.py      # Displays staged changes, handles approve/reject
│   └── utils/
│       ├── db.py            # SQLAlchemy connection and schema helpers
│       ├── config.py        # .env config loader
│       └── logger.py        # Rich-based logging
├── scripts/
│   └── seed_test_db.py      # Creates and populates a test database
├── tests/
│   ├── unit/                # Unit tests (no DB required)
│   └── integration/         # Integration tests (requires PostgreSQL)
├── .env.example             # Environment variable reference
├── install.py               # One-command installer for new users
└── pyproject.toml           # Project metadata and dependencies
```

---

## How Nereid Works

Understanding the data flow helps when contributing:

```
PostgreSQL (production)
    ↓ nereid export
XLSX / CSV file
    ↓ cloud sync (Google Drive, Dropbox, OneDrive)
Customer edits file
    ↓ cloud sync back to local folder
nereid watch detects file change
    ↓ differ computes row-level changeset
nereid_staging schema (PostgreSQL)
    ↓ nereid review --approve-all
PostgreSQL (production) updated
```

Key design decisions:
- **Nereid never writes directly to production during a watch cycle** — all changes land in staging first
- **Diffs are row-level by primary key** — Nereid requires a PK column (default `id`) in every synced table
- **File stability check** — Nereid waits for the file size to stop changing before reading it, which handles cloud sync clients that write files in multiple passes

---

## Making Changes

### Branching

Create a branch from `main` for your work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-description
```

### Commit Style

Keep commits focused and use clear messages:

```
fix: handle missing PK column gracefully in differ
feat: add --dry-run flag to nereid review
docs: update contributing guide with integration test instructions
```

### Pull Requests

- Open a PR against `main`
- Include a description of what changed and why
- If it fixes a bug, describe how to reproduce the original issue
- If it adds a feature, explain the use case
- Make sure `pytest` and `ruff check .` both pass before submitting

---

## What We're Looking For

Areas where contributions are especially welcome:

**Bug fixes**
- Edge cases in the diff engine (type mismatches, null values, empty sheets)
- File handling edge cases (locked files, partially written files, encoding issues)
- Windows / macOS / Linux compatibility

**Improvements**
- Better error messages for common mistakes (wrong PK column, missing table, bad connection string)
- More test coverage — especially integration tests against a real PostgreSQL instance
- Performance improvements for large tables

**Upcoming features (v0.2+)**
- Column name mapping — translate DB column names to human-readable labels in the spreadsheet
- Change history / audit log — track who changed what and when
- `--dry-run` mode for `nereid review` — show what would be promoted without doing it
- Row-level approve/reject in the review command

If you want to work on something larger, open an issue first so we can discuss the approach before you invest a lot of time.

---

## Code Style

- Python 3.10+ features are fine (use `str | None` not `Optional[str]`, etc.)
- Line length: 100 characters (enforced by ruff)
- No external dependencies without discussion — keep the install footprint small
- Prefer explicit over clever — this codebase should be easy to read for contributors who are new to it

---

## Reporting Issues

Open an issue on GitHub with:
- What you were trying to do
- What command you ran
- The full error output
- Your OS, Python version, and PostgreSQL version

---

## License

By contributing to Nereid you agree that your contributions will be licensed under the MIT License.

---

*Nereid is built by [Lunar Systems](https://github.com/JonLindholm11)*