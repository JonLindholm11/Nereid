"""
Nereid Demo Seed — creates and populates session schema tables.

Called by create_session() in sessions.py to initialize a fresh demo environment.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def get_schema_ddl(schema: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS "{schema}".customers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS "{schema}".products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL,
            price NUMERIC(10, 2),
            stock INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS "{schema}".orders (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER,
            product TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            total_price NUMERIC(10, 2),
            status TEXT DEFAULT 'pending'
        );
    """


def get_seed_statements(schema: str) -> list[str]:
    return [
        f"""
        INSERT INTO "{schema}".customers (name, email, phone, status) VALUES
            ('Alice Johnson',  'alice@example.com',  '555-0101', 'active'),
            ('Bob Martinez',   'bob@example.com',    '555-0102', 'active'),
            ('Carol White',    'carol@example.com',  '555-0103', 'inactive'),
            ('David Kim',      'david@example.com',  '555-0104', 'active'),
            ('Emma Davis',     'emma@example.com',   '555-0105', 'active')
        ON CONFLICT DO NOTHING;
        """,
        f"""
        INSERT INTO "{schema}".products (name, sku, price, stock) VALUES
            ('Widget Pro',      'WGT-001', 29.99, 150),
            ('Gadget Plus',     'GDG-002', 49.99,  75),
            ('Doohickey Basic', 'DHK-003',  9.99, 300),
            ('Thingamajig XL',  'TMJ-004', 89.99,  40),
            ('Whatchamacallit', 'WMC-005', 19.99, 200)
        ON CONFLICT DO NOTHING;
        """,
        f"""
        INSERT INTO "{schema}".orders (customer_id, product, quantity, total_price, status) VALUES
            (1, 'Widget Pro',       2,  59.98, 'completed'),
            (1, 'Gadget Plus',      1,  49.99, 'pending'),
            (2, 'Doohickey Basic',  5,  49.95, 'completed'),
            (3, 'Thingamajig XL',  1,  89.99, 'shipped'),
            (4, 'Widget Pro',       1,  29.99, 'pending'),
            (5, 'Whatchamacallit',  3,  59.97, 'completed'),
            (2, 'Gadget Plus',      2,  99.98, 'pending')
        ON CONFLICT DO NOTHING;
        """,
    ]


def seed_session(engine: Engine, schema: str) -> None:
    """
    Create and populate all three demo tables inside the given schema.
    Called by create_session() after the schema is created.
    """
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(text(get_schema_ddl(schema)))
        for stmt in get_seed_statements(schema):
            conn.execute(text(stmt))
        conn.commit()