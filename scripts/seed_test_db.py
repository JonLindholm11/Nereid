"""
Nereid Test Database Seed Script
Creates a simple test database with realistic dummy data.

Usage:
    python scripts/seed_test_db.py --db-url postgresql://user:password@localhost:5432/nereid_test
"""

import click
from sqlalchemy import create_engine, text


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    product TEXT NOT NULL,
    quantity INTEGER DEFAULT 1,
    total_price NUMERIC(10, 2),
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    sku TEXT UNIQUE NOT NULL,
    price NUMERIC(10, 2),
    stock INTEGER DEFAULT 0
);
"""

CUSTOMERS = """
INSERT INTO customers (name, email, phone, status) VALUES
    ('Alice Johnson',   'alice@example.com',   '555-0101', 'active'),
    ('Bob Martinez',    'bob@example.com',     '555-0102', 'active'),
    ('Carol White',     'carol@example.com',   '555-0103', 'inactive'),
    ('David Kim',       'david@example.com',   '555-0104', 'active'),
    ('Emma Davis',      'emma@example.com',    '555-0105', 'active')
ON CONFLICT DO NOTHING;
"""

PRODUCTS = """
INSERT INTO products (name, sku, price, stock) VALUES
    ('Widget Pro',      'WGT-001', 29.99,  150),
    ('Gadget Plus',     'GDG-002', 49.99,   75),
    ('Doohickey Basic', 'DHK-003',  9.99,  300),
    ('Thingamajig XL',  'TMJ-004', 89.99,   40),
    ('Whatchamacallit',  'WMC-005', 19.99,  200)
ON CONFLICT DO NOTHING;
"""

ORDERS = """
INSERT INTO orders (customer_id, product, quantity, total_price, status) VALUES
    (1, 'Widget Pro',       2,  59.98, 'completed'),
    (1, 'Gadget Plus',      1,  49.99, 'pending'),
    (2, 'Doohickey Basic',  5,  49.95, 'completed'),
    (3, 'Thingamajig XL',  1,  89.99, 'shipped'),
    (4, 'Widget Pro',       1,  29.99, 'pending'),
    (5, 'Whatchamacallit',  3,  59.97, 'completed'),
    (2, 'Gadget Plus',      2,  99.98, 'pending')
ON CONFLICT DO NOTHING;
"""


@click.command()
@click.option(
    "--db-url",
    required=True,
    help="PostgreSQL connection string. e.g. postgresql://user:pass@localhost:5432/nereid_test",
)
@click.option(
    "--drop",
    is_flag=True,
    default=False,
    help="Drop existing tables before seeding (fresh start).",
)
def seed(db_url, drop):
    """Create and populate a test database for Nereid."""
    engine = create_engine(db_url, future=True)

    with engine.connect() as conn:
        if drop:
            click.echo("Dropping existing tables...")
            conn.execute(text("DROP TABLE IF EXISTS orders CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS customers CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS products CASCADE"))
            conn.commit()
            click.echo("  Done.")

        click.echo("Creating tables...")
        conn.execute(text(SCHEMA))
        conn.commit()
        click.echo("  customers, orders, products created.")

        click.echo("Inserting seed data...")
        conn.execute(text(CUSTOMERS))
        conn.execute(text(PRODUCTS))
        conn.execute(text(ORDERS))
        conn.commit()
        click.echo("  5 customers, 5 products, 7 orders inserted.")

    click.echo("\n✓ Test database ready.")
    click.echo(f"  Connection: {db_url}")
    click.echo("\nNext steps:")
    click.echo(f"  nereid export --mode single --output ~/Google\\ Drive/nereid_test.xlsx --db-url {db_url}")
    click.echo(f"  nereid watch  --mode single --path   ~/Google\\ Drive/nereid_test.xlsx --db-url {db_url}")


if __name__ == "__main__":
    seed()