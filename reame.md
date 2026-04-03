# Nereid

**Open source CSV/XLSX ↔ PostgreSQL two-way sync engine.**  
A [Lunar Systems](https://github.com/JonLindholm11) open source tool.

Nereid lets non-technical users view and edit database records in a spreadsheet — no SQL, no admin panels, no new accounts. Companies share a cloud-synced file (Google Drive, Dropbox, OneDrive) with their customers. Nereid watches for saves, diffs the changes, and stages them for review before anything touches production.

---

## How it works

```
PostgreSQL ←→ Nereid ←→ Local synced folder ←→ Cloud service ←→ Customer
```

1. **Export** — pull data from Postgres into an XLSX or CSV folder
2. **Share** — company shares the synced folder with their customer via Google Drive / Dropbox / OneDrive
3. **Customer edits** — customer opens the file, makes changes, saves
4. **Watch** — Nereid detects the save, diffs the changes, writes to a staging schema
5. **Review** — company reviews staged changes and approves or rejects
6. **Production** — approved changes are promoted to the production database

---

## Installation

```bash
pip install nereid
```

Or from source:

```bash
git clone https://github.com/JonLindholm11/Nereid
cd Nereid
pip install -e ".[dev]"
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key settings:

| Variable | Description | Default |
|---|---|---|
| `NEREID_DB_URL` | PostgreSQL connection string | required |
| `NEREID_MODE` | `single` or `multi` | `single` |
| `NEREID_FILE_PATH` | Path to XLSX file (single mode) | required |
| `NEREID_FOLDER_PATH` | Path to CSV folder (multi mode) | — |
| `NEREID_PK_COLUMN` | Primary key column name | `id` |
| `NEREID_STAGING_SCHEMA` | Staging schema name in Postgres | `nereid_staging` |
| `NEREID_DEBOUNCE_SECONDS` | Seconds to wait after file change | `2` |

---

## CLI

### `nereid export`

Pull data from PostgreSQL into a spreadsheet or CSV folder.

```bash
# Single mode — all tables → one XLSX file, tabs = table names
nereid export --mode single --output /path/to/data.xlsx

# Multi mode — each table → its own CSV file
nereid export --mode multi --output /path/to/folder/

# Export specific tables only
nereid export --mode single --output data.xlsx --tables customers --tables orders
```

### `nereid watch`

Watch the file or folder for changes and sync to the staging schema.

```bash
# Single mode
nereid watch --mode single --path /path/to/data.xlsx

# Multi mode
nereid watch --mode multi --path /path/to/folder/
```

Nereid will run until `Ctrl+C`. Changes are written to the staging schema (`nereid_staging` by default) — **never directly to production**.

### `nereid review`

Inspect staged changes and decide what to do with them.

```bash
# View pending changes
nereid review

# Approve — promote all staged changes to production
nereid review --approve

# Reject — discard all staged changes
nereid review --reject
```

---

## Modes

### Single mode

One XLSX file. Each tab corresponds to a table in PostgreSQL.

```
data.xlsx
├── customers    →  public.customers
├── orders       →  public.orders
└── products     →  public.products
```

### Multi mode

A folder of CSV files. Each filename corresponds to a table.

```
data/
├── customers.csv  →  public.customers
├── orders.csv     →  public.orders
└── products.csv   →  public.products
```

---

## Requirements

- Python 3.10+
- PostgreSQL
- A primary key column (`id` by default) in every synced table

---

## Staging & Safety

Nereid **never writes directly to your production database** during a watch cycle.  
All changes land in a `nereid_staging` schema first. You review and explicitly approve them.

```
Customer edits → nereid_staging → nereid review --approve → production
```

This means a customer accidentally clearing a column or pasting bad data won't touch production until you've seen it.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
```

---

## Roadmap

- **v0.1** — Export, watch, staging, review (current)
- **v0.2** — Column name mapping (DB `cust_acct_ref` → human `Account Reference`)
- **v0.3** — Change history / audit log
- **v0.4** — Web UI for review

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built by [Lunar Systems](https://github.com/JonLindholm11)*