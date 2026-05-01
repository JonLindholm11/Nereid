# Nereid

**Open source CSV/XLSX ↔ PostgreSQL two-way sync engine.**  
A [Lunar Systems](https://github.com/JonLindholm11) open source tool.

Nereid lets non-technical users view and edit database records in a spreadsheet — no SQL, no admin panels, no new accounts. Share a file with your client, they edit it, Nereid diffs the changes and stages them for review before anything touches production.

---

## How it works

Nereid supports two sync modes depending on your setup:

### Local sync (file watcher)

For teams using a locally synced cloud folder (Google Drive desktop app, Dropbox, OneDrive):

```
PostgreSQL ←→ Nereid ←→ Local synced folder ←→ Cloud service ←→ Client
```

Nereid acts as a controlled bridge between the database and user-facing spreadsheets.

### Direct API sync (Google Drive)

For hosted deployments where no local sync client is installed:

```
PostgreSQL ←→ Nereid ←→ Google Drive API ←→ Google Drive ←→ Client
```

Nereid polls the Drive API every 60 seconds (configurable). When the file changes, it downloads it, diffs the rows, and writes changes to the staging schema — no sync client required.

---

## The sync pipeline (both modes)

1. **Export** — pull data from Postgres into an XLSX or CSV
2. **Share** — give your client access to the file
3. **Client edits** — client opens the file, makes changes, saves
4. **Watch** — Nereid detects the change, diffs the rows, writes to staging
5. **Review** — you approve or reject the staged changes
6. **Production** — approved changes are promoted to the production database

---

## Installation

```bash
pip install nereid
```

With Google Drive API support:

```bash
pip install nereid[gdrive]
```

From source:

```bash
git clone https://github.com/JonLindholm11/Nereid
cd Nereid
python install.py
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Core settings

| Variable | Description | Default |
|---|---|---|
| `NEREID_DB_URL` | PostgreSQL connection string | required |
| `NEREID_MODE` | `single` or `multi` | `single` |
| `NEREID_FILE_PATH` | Path to XLSX file (single mode, local watch) | — |
| `NEREID_FOLDER_PATH` | Path to CSV folder (multi mode, local watch) | — |
| `NEREID_PK_COLUMN` | Primary key column name | `id` |
| `NEREID_STAGING_SCHEMA` | Staging schema name in Postgres | `nereid_staging` |
| `NEREID_DEBOUNCE_SECONDS` | Seconds to wait after a file change (local watch) | `2` |

### Google Drive settings

| Variable | Description | Default |
|---|---|---|
| `NEREID_GDRIVE_CREDENTIALS_FILE` | Path to service account JSON key | — |
| `NEREID_GDRIVE_FILE_ID` | Google Drive file ID | — |
| `NEREID_POLL_INTERVAL` | Seconds between Drive polls | `60` |

> These are optional — `nereid connect google-drive` stores them in `.nereid-credentials.json` automatically so you don't need to set them in `.env`.

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

---

### `nereid watch`

Watch a **locally synced** file or folder for changes and sync to the staging schema.

Use this when your server has a sync client installed (Google Drive desktop, Dropbox, etc.) and the file lives on disk.

```bash
# Single mode — watch an XLSX file
nereid watch --mode single --path /path/to/data.xlsx

# Multi mode — watch a folder of CSV files
nereid watch --mode multi --path /path/to/folder/
```

Runs until `Ctrl+C`. Changes go to the staging schema only — **never directly to production**.

---

### `nereid connect`

Configure a cloud provider for direct API sync. Run this once per project.

#### `nereid connect google-drive`

```bash
nereid connect google-drive
```

Prompts you for:
1. Path to your service account JSON key file
2. The Google Drive file ID or URL

Then validates the connection and saves credentials to `.nereid-credentials.json` (automatically added to `.gitignore`).

You can also pass flags directly:

```bash
nereid connect google-drive \
  --credentials /path/to/service-account.json \
  --file-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
```

**One-time Google Cloud setup (required):**
1. Create a Google Cloud project and enable the Drive API
2. Create a service account and download its JSON key
3. Share your XLSX or Google Sheet with the service account's email address

---

### `nereid watch-cloud`

Poll a cloud-hosted file for changes and sync to the staging schema. Use this for hosted deployments with no local sync client.

#### `nereid watch-cloud google-drive`

```bash
# Reads credentials from .nereid-credentials.json (written by nereid connect)
nereid watch-cloud google-drive --db-url postgresql://user:pass@localhost/db

# Override poll interval (default 60s)
nereid watch-cloud google-drive --db-url postgresql://... --poll-interval 30

# Override credentials inline without running nereid connect
nereid watch-cloud google-drive \
  --db-url postgresql://... \
  --credentials /path/to/service-account.json \
  --file-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
```

Runs until `Ctrl+C`. On each poll cycle:
- Checks the file's `modifiedTime` via the Drive API (cheap metadata request)
- If unchanged — waits and checks again
- If changed — downloads the file, diffs the rows, writes to staging

**All options:**

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--db-url` | `NEREID_DB_URL` | required | PostgreSQL connection string |
| `--poll-interval` | `NEREID_POLL_INTERVAL` | `60` | Seconds between Drive polls |
| `--pk` | `NEREID_PK_COLUMN` | `id` | Primary key column name |
| `--staging-schema` | `NEREID_STAGING_SCHEMA` | `nereid_staging` | Staging schema name |
| `--credentials` | `NEREID_GDRIVE_CREDENTIALS_FILE` | from `.nereid-credentials.json` | Service account JSON path |
| `--file-id` | `NEREID_GDRIVE_FILE_ID` | from `.nereid-credentials.json` | Drive file ID |

---

### `nereid review`

Inspect staged changes and decide what to promote to production.

Table names match your actual database table names — the same names that appear as tabs in your XLSX file or as CSV filenames. There are no hardcoded table names — Nereid works with whatever tables you have.

```bash
# View all pending staged changes
nereid review

# Approve everything — promote all staged changes to production
nereid review --approve-all

# Approve a specific table only
nereid review --approve-table orders
nereid review --approve-table invoices

# Reject a specific table — discard its staged changes
nereid review --reject-table customers

# Reject everything — discard all staged changes
nereid review --reject-all

# Interactive mode — go table by table, choose approve / reject / skip
nereid review --interactive
```

Interactive mode is the most useful for real-world review — it shows each table's staged changes one at a time and asks what to do before moving on. Nothing is applied until you explicitly approve it.

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

## Hosted deployment

Nereid is designed to run alongside a hosted PostgreSQL database. A typical server setup:

```bash
# 1. Install
pip install nereid[gdrive]

# 2. Configure credentials (run once)
nereid connect google-drive

# 3. Export initial data to Drive
nereid export --mode single --output data.xlsx --db-url postgresql://...
# Upload data.xlsx to Drive and share it with your client

# 4. Start the sync daemon
nereid watch-cloud google-drive --db-url postgresql://...

# 5. When your client saves changes, review and promote
nereid review --interactive
```

To run as a persistent background process, use your platform's process manager (systemd, Docker, PM2, etc.).

---

## Requirements

- Python 3.10+
- PostgreSQL
- A primary key column (`id` by default) in every synced table
- For `nereid watch-cloud google-drive`: `pip install nereid[gdrive]` + a Google Cloud service account

---

## Staging & Safety

Nereid **never writes directly to your production database** during a watch cycle.  
All changes land in a `nereid_staging` schema first. You review and explicitly approve them.

```
Client edits → nereid_staging → nereid review --approve-all → production
```

A client accidentally clearing a column or pasting bad data won't affect production until you've seen it.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, project structure, and how to submit changes.

---

## Roadmap

- **v0.1** — Core sync engine: export, watch, staging, granular review, Google Drive API sync (current)
- **v0.2** — Column name mapping (DB `cust_acct_ref` → human `Account Reference`)
- **v0.3** — Change history / audit log
- **v0.4** — Additional cloud providers (Dropbox, OneDrive)
- **v0.5** — Web UI for review

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built by [Jon Lindholm](https://github.com/JonLindholm11)*
