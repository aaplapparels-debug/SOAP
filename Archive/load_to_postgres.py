"""
load_to_postgres.py

Runs ShoperAdapter's extractions and loads them into the canonical
Postgres (Neon) tables defined in canonical_schema.sql.

UPDATED: this now does real incremental sync instead of a full wipe-
and-reload every time.

- customers, items: always a full refresh (TRUNCATE + reload). Small
  master data, changes slowly, no real cost to just redoing it fully
  every run.
- sales, purchases: incremental via a watermark. sync_state remembers
  the last successful sync time per table; each run only pulls rows
  newer than that, then APPENDS them (never re-touches old rows). Safe
  because both are treated as immutable once posted -- a correction in
  Shoper shows up as a new row (e.g. a sales return), not an edit to
  an old one.
- sales_orders: always re-pulls anything still open (pending_qty > 0),
  regardless of how old it is, plus anything new since the watermark --
  see extract_sales_orders in shoper_adapter.py. Because an "open"
  order pulled again is very likely an EXISTING row whose pending_qty
  just changed, this uses an UPSERT (insert new, update existing) 
  instead of a plain append.

New Python/SQL concepts in this file:
- `INSERT ... ON CONFLICT (...) DO UPDATE SET ...` is Postgres's upsert
  syntax: try to insert a row; if a row with the same primary key
  already exists (a "conflict"), update it instead of erroring out.
- A staging table (sales_orders_staging) is a common pattern for
  bringing a whole DataFrame in via pandas' fast to_sql, then using one
  SQL statement to merge it into the real table -- much faster than
  looping through rows one at a time in Python.
"""

import datetime

import psycopg2
import pandas as pd
from sqlalchemy import create_engine, text

from config_loader import load_config
from shoper_adapter import ShoperAdapter, DivisionConfig


def get_engine(connection_string: str):
    return create_engine(connection_string)


def apply_schema(engine, schema_file: str = "canonical_schema.sql"):
    """Runs canonical_schema.sql against the database -- safe to run
    every time, since every CREATE TABLE in that file uses
    IF NOT EXISTS, so it does nothing if the tables already exist."""
    with open(schema_file, "r") as f:
        schema_sql = f.read()
    with engine.begin() as conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))


def get_last_synced(engine, source_table: str):
    """Returns the last_synced_at timestamp for this table, or None if
    it's never been synced before -- None is the signal to do a full
    backfill instead of an incremental pull."""
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT last_synced_at FROM sync_state WHERE source_table = :t"),
            {"t": source_table},
        ).fetchone()
    return result[0] if result else None


def set_last_synced(engine, source_table: str, when: datetime.datetime):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO sync_state (source_table, last_synced_at)
                VALUES (:t, :w)
                ON CONFLICT (source_table) DO UPDATE SET last_synced_at = :w
            """),
            {"t": source_table, "w": when},
        )


def full_reload_table(engine, df: pd.DataFrame, table_name: str):
    """TRUNCATE + reload -- used for customers/items, and for the very
    first sync of any table, all inside one transaction."""
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {table_name}"))
        df.to_sql(table_name, conn, if_exists="append", index=False)
    print(f"Full reload: {len(df)} rows into {table_name}")


def append_new_rows(engine, df: pd.DataFrame, table_name: str):
    """Adds rows without touching what's already there -- correct for
    sales/purchases, which are immutable once posted."""
    if df.empty:
        print(f"No new rows for {table_name}")
        return
    with engine.begin() as conn:
        df.to_sql(table_name, conn, if_exists="append", index=False)
    print(f"Appended {len(df)} new rows into {table_name}")


def upsert_sales_orders(engine, df: pd.DataFrame):
    """Inserts new order lines, updates existing ones (matched on
    order_id + item_code + division) -- necessary because an order's
    pending_qty can change after it was first loaded.

    The staging table is created with `LIKE sales_orders` rather than
    letting pandas' to_sql guess its column types -- pandas' guesses
    (e.g. dates as full timestamps, numbers as floating point) don't
    always match what canonical_schema.sql explicitly defines, and
    Postgres won't silently cast around a mismatch during INSERT...
    SELECT. Copying the real table's exact column types up front avoids
    the type-guessing entirely instead of debugging it column by column.
    """
    if df.empty:
        print("No sales_orders rows to upsert")
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sales_orders_staging"))
        conn.execute(text("CREATE TABLE sales_orders_staging (LIKE sales_orders)"))
        df.to_sql("sales_orders_staging", conn, if_exists="append", index=False)
        conn.execute(text("""
            INSERT INTO sales_orders (
                order_id, customer_code, item_code, salesperson,
                order_date, billed_date, order_qty, billed_qty,
                pending_qty, cancelled_qty, return_qty, mrp,
                invoice_value, division
            )
            SELECT
                order_id, customer_code, item_code, salesperson,
                order_date, billed_date, order_qty, billed_qty,
                pending_qty, cancelled_qty, return_qty, mrp,
                invoice_value, division
            FROM sales_orders_staging
            ON CONFLICT (order_id, item_code, division) DO UPDATE SET
                customer_code = EXCLUDED.customer_code,
                salesperson   = EXCLUDED.salesperson,
                order_date    = EXCLUDED.order_date,
                billed_date   = EXCLUDED.billed_date,
                order_qty     = EXCLUDED.order_qty,
                billed_qty    = EXCLUDED.billed_qty,
                pending_qty   = EXCLUDED.pending_qty,
                cancelled_qty = EXCLUDED.cancelled_qty,
                return_qty    = EXCLUDED.return_qty,
                mrp           = EXCLUDED.mrp,
                invoice_value = EXCLUDED.invoice_value
        """))
        conn.execute(text("DROP TABLE sales_orders_staging"))
    print(f"Upserted {len(df)} rows into sales_orders")


def sync_append_only_table(engine, adapter_method, table_name: str):
    """
    Shared logic for sales and purchases -- both immutable-once-posted,
    both use the same "watermark, then append" pattern. Passing the
    adapter's extraction method itself (adapter.extract_sales, e.g.)
    as an argument means this one function works for both instead of
    writing the same branching logic twice.
    """
    last_synced = get_last_synced(engine, table_name)
    if last_synced is None:
        print(f"No previous sync for {table_name} -- running full backfill.")
        df = adapter_method()
        full_reload_table(engine, df, table_name)
    else:
        since = last_synced.date()
        print(f"Incremental sync for {table_name} since {since}...")
        df = adapter_method(since_date=since)
        append_new_rows(engine, df, table_name)
    set_last_synced(engine, table_name, datetime.datetime.now())


def sync_sales_orders(engine, adapter: ShoperAdapter):
    last_synced = get_last_synced(engine, "sales_orders")
    since = last_synced.date() if last_synced else None
    if since is None:
        print("No previous sync for sales_orders -- running full backfill (+ open orders).")
    else:
        print(f"Incremental sync for sales_orders since {since} (+ still-open orders)...")
    df = adapter.extract_sales_orders(since_date=since)
    upsert_sales_orders(engine, df)
    set_last_synced(engine, "sales_orders", datetime.datetime.now())


def run_load():
    config = load_config()
    sql_cfg = config["sql_server"]
    pg_connection_string = config["postgres"]["connection_string"]

    divisions = [
        DivisionConfig(
            division_name=division["name"],
            server=sql_cfg["host"],
            database=division["staging_db"],
            username=sql_cfg["sa_username"],
            password=sql_cfg["sa_password"],
        )
        for division in config["divisions"]
    ]
    adapter = ShoperAdapter(divisions, financial_years_back=config["sync"]["financial_years_back"])
    engine = get_engine(pg_connection_string)

    print("Applying schema (safe to run every time)...")
    apply_schema(engine)

    print("\n--- Customers (always full refresh) ---")
    full_reload_table(engine, adapter.extract_customers(), "customers")

    print("\n--- Items (always full refresh) ---")
    full_reload_table(engine, adapter.extract_items(), "items")

    print("\n--- Sales (incremental) ---")
    sync_append_only_table(engine, adapter.extract_sales, "sales")

    print("\n--- Purchases (incremental) ---")
    sync_append_only_table(engine, adapter.extract_purchases, "purchases")

    print("\n--- Sales Orders (incremental + open-order recheck) ---")
    sync_sales_orders(engine, adapter)

    print("\nDone.")


if __name__ == "__main__":
    run_load()