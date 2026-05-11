"""
Nereid Hosted API — endpoints for self-hosted Google Drive folder watching.
"""

import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from nereid.utils.config import load_hosted_config, ConnectionConfig
from nereid.utils.db import get_engine
from nereid.core.staging import promote_to_production, clear_staging
from nereid.core.reviewer import _get_staged_tables, _promote_table, _reject_table
from nereid.core.exporter import sync_drive_to_db_state
from nereid.core.cloud_watcher import run_cloud_watch_folder
from nereid.providers.google_drive import GoogleDriveProvider

router = APIRouter(prefix="/api")

# ── In-memory state ───────────────────────────────────────────────────────────
# Keyed by connection name
_watchers: dict[str, threading.Thread] = {}
_file_registries: dict[str, dict[str, str]] = {}
_config = None


def init_api(app):
    """Call this from main.py startup to load config and start watchers."""
    global _config
    try:
        _config = load_hosted_config()
    except FileNotFoundError:
        return  # no hosted config present, demo-only mode

    for conn in _config.connections:
        _start_watcher(conn)

    app.include_router(router)


def _start_watcher(conn: ConnectionConfig):
    """Start a folder watcher thread for a connection."""
    def watch():
        run_cloud_watch_folder(
            folder_id=conn.folder_id,
            mode=conn.mode,
            db_url=conn.db_url,
            pk_column=conn.pk_column,
            staging_schema=conn.staging_schema,
            poll_interval=_config.poll_interval,
            schema=conn.schema,
        )

    t = threading.Thread(target=watch, daemon=True, name=f"watcher-{conn.name}")
    t.start()
    _watchers[conn.name] = t


# ── Models ────────────────────────────────────────────────────────────────────

class ApiReviewAction(BaseModel):
    action: str
    table: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """Returns watcher status and staged changes summary per connection."""
    if not _config:
        raise HTTPException(status_code=503, detail="No hosted config loaded.")

    result = []
    for conn in _config.connections:
        engine = get_engine(conn.db_url)
        try:
            tables = _get_staged_tables(engine, conn.staging_schema)
            result.append({
                "name": conn.name,
                "mode": conn.mode,
                "folder_id": conn.folder_id,
                "staging_schema": conn.staging_schema,
                "watcher_alive": _watchers.get(conn.name, {}) and _watchers[conn.name].is_alive(),
                "staged_tables": tables,
                "has_changes": len(tables) > 0,
            })
        except Exception as e:
            result.append({
                "name": conn.name,
                "error": str(e),
            })

    return {"connections": result}


@router.get("/review/{connection_name}")
async def get_review(connection_name: str):
    """Returns staged changes for a specific connection."""
    if not _config:
        raise HTTPException(status_code=503, detail="No hosted config loaded.")

    conn = _get_connection(connection_name)
    engine = get_engine(conn.db_url)

    try:
        tables = _get_staged_tables(engine, conn.staging_schema)
        review_data = {}

        for table_name in tables:
            with engine.connect() as c:
                result = c.execute(
                    text(f'SELECT * FROM "{conn.staging_schema}"."{table_name}"')
                )
                review_data[table_name] = [dict(row._mapping) for row in result.fetchall()]

        return {
            "connection": connection_name,
            "staged": review_data,
            "has_changes": len(tables) > 0,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/review/{connection_name}/action")
async def review_action(connection_name: str, body: ApiReviewAction):
    """Approve or reject staged changes for a connection."""
    if not _config:
        raise HTTPException(status_code=503, detail="No hosted config loaded.")

    conn = _get_connection(connection_name)
    engine = get_engine(conn.db_url)
    provider = GoogleDriveProvider(file_id="folder_mode")
    registry = _file_registries.get(connection_name, {})

    try:
        if body.action == "approve_all":
            promote_to_production(engine, conn.staging_schema, conn.schema)
            _sync_after_review(engine, conn, provider, registry)
            return {"result": "approved_all"}

        elif body.action == "reject_all":
            clear_staging(engine, conn.staging_schema)
            _sync_after_review(engine, conn, provider, registry)
            return {"result": "rejected_all"}

        elif body.action == "approve_table":
            if not body.table:
                raise HTTPException(status_code=400, detail="table required")
            _promote_table(engine, conn.staging_schema, body.table, conn.schema)
            _sync_if_staging_empty(engine, conn, provider, registry)
            return {"result": "approved_table", "table": body.table}

        elif body.action == "reject_table":
            if not body.table:
                raise HTTPException(status_code=400, detail="table required")
            _reject_table(engine, conn.staging_schema, body.table)
            _sync_if_staging_empty(engine, conn, provider, registry)
            return {"result": "rejected_table", "table": body.table}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_connection(name: str) -> ConnectionConfig:
    if not _config:
        raise HTTPException(status_code=503, detail="No hosted config loaded.")
    for conn in _config.connections:
        if conn.name == name:
            return conn
    raise HTTPException(status_code=404, detail=f"Connection '{name}' not found.")


def _sync_after_review(engine, conn, provider, registry):
    """Sync Drive back to DB state after approve/reject all."""
    if not registry:
        return
    try:
        sync_drive_to_db_state(
            engine=engine,
            folder_id=conn.folder_id,
            provider=provider,
            mode=conn.mode,
            file_registry=registry,
            schema=conn.schema,
        )
    except Exception as e:
        pass  # log but don't fail the review action


def _sync_if_staging_empty(engine, conn, provider, registry):
    """Sync Drive only if staging is now empty — review session complete."""
    try:
        remaining = _get_staged_tables(engine, conn.staging_schema)
        if not remaining:
            _sync_after_review(engine, conn, provider, registry)
    except Exception:
        pass