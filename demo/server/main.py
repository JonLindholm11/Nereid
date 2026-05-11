

"""
Nereid Demo Server — FastAPI app for the live demo environment.
"""

import os
import pandas as pd

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from nereid.utils.db import get_engine
from nereid.core.differ import compute_diff
from nereid.core.staging import write_to_staging, promote_to_production, clear_staging
from nereid.core.reviewer import _get_staged_tables, _promote_table, _reject_table
from demo.server.seed import seed_session
from demo.server.sessions import (
    create_session,
    drop_session,
    session_exists,
    cleanup_expired_sessions,
    ensure_sessions_table,
    get_schema_name,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = get_engine(DATABASE_URL)

class SaveRequest(BaseModel):
    customers: list[dict]
    products: list[dict]
    orders: list[dict]

class ReviewAction(BaseModel):
    action: str
    table: str | None = None

app = FastAPI(title="Nereid Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    ensure_sessions_table(engine)
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: cleanup_expired_sessions(engine), "interval", minutes=15)
    scheduler.start()

# ── Endpoints go here ──────────────────────────────────────────────────────

@app.post("/demo/session")
async def start_session():
    try:
        session_id = create_session(engine)
        return {"session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/demo/session/{session_id}")
async def get_session(session_id: str):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    schema = get_schema_name(session_id)
    
    try:
        with engine.connect() as conn:
            customers = [dict(row._mapping) for row in conn.execute(
                text(f'SELECT * FROM "{schema}".customers')
            ).fetchall()]
            
            products = [dict(row._mapping) for row in conn.execute(
                text(f'SELECT * FROM "{schema}".products')
            ).fetchall()]
            
            orders = [dict(row._mapping) for row in conn.execute(
                text(f'SELECT * FROM "{schema}".orders')
            ).fetchall()]
        
        return {
            "session_id": session_id,
            "customers": customers,
            "products": products,
            "orders": orders
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/demo/save/{session_id}")
async def save_session(session_id: str, body: SaveRequest):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found, cannot save")

    schema = get_schema_name(session_id)

    try:
        tables = {
            "customers": body.customers,
            "products": body.products,
            "orders": body.orders,
        }

        pk_map = {
            "customers": "id",
            "products": "id",
            "orders": "id",
        }

        summaries = {}

        for table_name, rows in tables.items():
            new_df = pd.DataFrame(rows)

            with engine.connect() as conn:
                result = conn.execute(text(f'SELECT * FROM "{schema}"."{table_name}"'))
                old_df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

            changeset = compute_diff(old_df, new_df, pk_map[table_name], table_name)
            
            if not changeset.is_empty:
                write_to_staging(engine, changeset, f"{schema}_staging")
            
            summaries[table_name] = changeset.summary()

        return {
            "session_id": session_id,
            "summary": summaries
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/demo/promote/{session_id}")
async def promote_session(session_id: str):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found, cannot promote")
    
    schema = get_schema_name(session_id)
    staging_schema = f"{schema}_staging"
    
    try:
        promote_to_production(engine, staging_schema, schema)
        return {"promoted": True, "session_id": session_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/demo/reset/{session_id}")
async def reset_session(session_id: str):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found, cannot reset")
    
    schema = get_schema_name(session_id)
    
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}_staging" CASCADE'))
            conn.commit()
        
        seed_session(engine, schema)
        
        return {"reset": True, "session_id": session_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/demo/session/{session_id}")
async def delete_session(session_id: str):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found, cannot delete")
    
    try:
        drop_session(engine, session_id)
        return {"deleted": True, "session_id": session_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/demo/review/{session_id}")
async def get_review(session_id: str):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    schema = get_schema_name(session_id)
    staging_schema = f"{schema}_staging"

    try:
        tables = _get_staged_tables(engine, staging_schema)
        review_data = {}

        for table_name in tables:
            with engine.connect() as conn:
                result = conn.execute(text(f'SELECT * FROM "{staging_schema}"."{table_name}"'))
                rows = [dict(row._mapping) for row in result.fetchall()]
            review_data[table_name] = rows

        return {
            "session_id": session_id,
            "staged": review_data,
            "has_changes": len(tables) > 0
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/demo/review/{session_id}/action")
async def review_action(session_id: str, body: ReviewAction):
    if not session_exists(engine, session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    schema = get_schema_name(session_id)
    staging_schema = f"{schema}_staging"

    try:
        if body.action == "approve_all":
            promote_to_production(engine, staging_schema, schema)
            return {"result": "approved_all"}

        elif body.action == "reject_all":
            clear_staging(engine, staging_schema)
            return {"result": "rejected_all"}

        elif body.action == "approve_table":
            if not body.table:
                raise HTTPException(status_code=400, detail="table required for approve_table")
            _promote_table(engine, staging_schema, body.table, schema)
            return {"result": "approved_table", "table": body.table}

        elif body.action == "reject_table":
            if not body.table:
                raise HTTPException(status_code=400, detail="table required for reject_table")
            _reject_table(engine, staging_schema, body.table)
            return {"result": "rejected_table", "table": body.table}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))