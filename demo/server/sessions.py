import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from nereid.utils.db import get_engine, get_table_names
from nereid.core.staging import write_to_staging, promote_to_production, clear_staging
from demo.server.seed import seed_session

def generate_session_id():
    session_id = str(uuid.uuid4().hex[:12])
    return session_id

def get_schema_name(session_id):
    schema_name = f"demo_{session_id}"
    return schema_name

def create_session(engine):
    session_id = generate_session_id()
    schema = get_schema_name(session_id)
    
    # seed the schema and tables
    seed_session(engine, schema)
    
    # record the session
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS demo_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(
            text("INSERT INTO demo_sessions (session_id) VALUES (:sid)"),
            {"sid": session_id}
        )
        conn.commit()
    
    return session_id


def drop_session(engine, session_id):
    schema = get_schema_name(session_id)
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(
            text("DELETE FROM demo_sessions WHERE session_id = :sid"),
            {"sid": session_id}
        )
        conn.commit()


def session_exists(engine, session_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM demo_sessions WHERE session_id = :sid"),
            {"sid": session_id}
        )
        return result.fetchone() is not None


def cleanup_expired_sessions(engine):
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT session_id FROM demo_sessions
            WHERE created_at < NOW() - INTERVAL '1 hour'
        """))
        expired = [row[0] for row in result.fetchall()]
    
    for session_id in expired:
        drop_session(engine, session_id)


def ensure_sessions_table(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS demo_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.commit()