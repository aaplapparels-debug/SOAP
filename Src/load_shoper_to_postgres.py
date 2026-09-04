"""
load_shoper_to_postgres.py

Runs ShoperAdapter's extractions and loads them into the canonical
Postgres (Neon) tables defined in canonical_schema.sql.

Tally and other sources are now loaded from separate machines --
this script is Shoper-only.

MULTI-SOURCE SAFE: every load is scoped to (table, source_system) --
never a blind, whole-table TRUNCATE. This is what lets a second source
(a future Botree adapter, an Excel-based adapter for a division without
a proper ERP, etc.) feed the SAME canonical table as Shoper
without one source's load destroying another's data on its next run.

INCREMENTAL SYNC: For append-only tables (sales, purchases), the cutoff
date is determined by querying MAX(date_column) directly from Postgres,
not a separate sync_state table. This is more resilient -- if a row got
missed or a prior run partially failed, the date-based filter catches it
on the next run.

- customers, items: full refresh, scoped to this source's rows only
  (DELETE WHERE source_system = X, then reload). Small master data,
  changes slowly.
- sales, purchases: incremental via max date in Postgres. Find the
  maximum sale_date/entry_date already in Postgres for this source,
  then query SQL Server for only rows newer than that. Treated as
  immutable once posted, so new rows are safe to just append.
- sales_orders: full refresh, scoped to source -- a live snapshot of
  "genuinely actionable pending orders" (see extract_sales_orders in
  shoper_adapter.py), not history. An upsert-based approach was tried
  and rejected: it can only add/update, never remove a row that's no
  longer true (an order that got billed, or aged out of the lookback
  window), which would leave stale pending_qty values sitting around
  forever. Full refresh avoids that.

KNOWN DEFERRED PROBLEM: if two sources ever describe "the same"
customer under different ID schemes, this does NOT unify them -- they
sit as separate rows tagged by source_system. Real cross-system
identity matching needs a real second source to design against, not a
guess made now.
"""

import datetime

import pandas as pd
from sqlalchemy import create_engine, text
from typing import Optional

from config_loader import load_config
from shoper_adapter import ShoperAdapter, DivisionConfig


def get_engine(connection_string: str):
    return create_engine(connection_string)


def apply_schema(engine, schema_file: str = "canonical_schema.sql"):
    """Runs canonical_schema.sql against the database -- safe to run
    every time, since every CREATE TABLE uses IF NOT EXISTS."""
    with open(schema_file, "r") as f:
        schema_sql = f.read()
    with engine.begin() as conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            # Filter out empty statements and blocks containing only SQL comments
            clean_lines = [
                line for line in statement.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ]
            if clean_lines:
                conn.execute(text(statement))

def get_max_date_from_postgres(engine, table_name: str, source_system: str, date_column: str) -> Optional[datetime.date]:
    """
    Query Postgres directly for the maximum date in the specified date column
    for rows tagged with this source_system. If the table is empty for this
    source, returns None (signals full backfill).
    
    This replaces sync_state: the "source of truth" for the cutoff is the
    actual data in Postgres, not a separate tracking table. More resilient
    to failures -- if a row got missed, the date-based filter will catch it
    on the next run.
    """
    with engine.begin() as conn:
        query = f"SELECT MAX({date_column}) FROM {table_name} WHERE source_system = :s"
        result = conn.execute(text(query), {"s": source_system}).fetchone()
        max_date = result[0] if result and result[0] else None
    return max_date


def full_reload_table(engine, df: pd.DataFrame, table_name: str, source_system: str):
    """
    Reloads ONLY this source's rows -- DELETE scoped to source_system,
    never a table-wide TRUNCATE. This is the core fix: a second source
    feeding this same table can run its own load without this one
    destroying its data, and vice versa.
    """
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table_name} WHERE source_system = :s"), {"s": source_system})
        df.to_sql(table_name, conn, if_exists="append", index=False)
    print(f"Full reload ({source_system}): {len(df)} rows into {table_name}")


def append_new_rows(engine, df: pd.DataFrame, table_name: str):
    """Adds rows without touching what's already there. Already safe
    for multi-source by construction -- a pure append never removes or
    overwrites another source's rows, regardless of tagging."""
    if df.empty:
        print(f"No new rows for {table_name}")
        return
    with engine.begin() as conn:
        df.to_sql(table_name, conn, if_exists="append", index=False)
    print(f"Appended {len(df)} new rows into {table_name}")


def sync_append_only_table(
    engine, 
    adapter_method, 
    table_name: str, 
    source_system: str,
    date_column: str = None
):
    """
    Shared logic for sales/purchases -- immutable-once-posted sources use
    "find max date, then append new." Uses the actual maximum date from the
    Postgres table, not a separate sync_state tracker.
    
    Args:
        engine: Postgres connection
        adapter_method: The extraction method (e.g., shoper.extract_sales)
        table_name: Canonical table name (e.g., 'sales')
        source_system: Source identifier (e.g., 'shoper')
        date_column: The date column to use as the cutoff (e.g., 'sale_date' for sales table)
    """
    if date_column is None:
        # Default column names based on table
        date_column = {
            'sales': 'sale_date',
            'purchases': 'entry_date',
            'receipts': 'receipt_date',
            'credit_notes': 'cn_date',
        }.get(table_name, 'created_at')
    
    max_date_in_postgres = get_max_date_from_postgres(engine, table_name, source_system, date_column)
    
    if max_date_in_postgres is None:
        # Table is empty for this source -- do a full backfill
        print(f"No existing data for {table_name} ({source_system}) -- running full backfill.")
        df = adapter_method()
        full_reload_table(engine, df, table_name, source_system)
    else:
        # Incremental: get only rows newer than the max we already have
        # Add 1 day to avoid re-processing the boundary date
        since_date = max_date_in_postgres + datetime.timedelta(days=1)
        print(f"Incremental sync for {table_name} ({source_system}) since {since_date}...")
        df = adapter_method(since_date=since_date)
        append_new_rows(engine, df, table_name)


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
            password=config["sql_server"]["sa_password"],
        )
        for division in config["divisions"]
    ]
    shoper = ShoperAdapter(
        divisions,
        financial_years_back=config["sync"]["financial_years_back"],
        sales_orders_lookback_days=config["sync"]["sales_orders_lookback_days"],
    )
    engine = get_engine(pg_connection_string)

    print("Applying schema (safe to run every time)...")
    apply_schema(engine)

    print("\n=== Shoper ===")

    print("\n--- Customers (full refresh, scoped to shoper) ---")
    full_reload_table(engine, shoper.extract_customers(), "customers", shoper.SOURCE_SYSTEM)

    print("\n--- Items (full refresh, scoped to shoper) ---")
    full_reload_table(engine, shoper.extract_items(), "items", shoper.SOURCE_SYSTEM)

    print("\n--- Sales (incremental) ---")
    sync_append_only_table(engine, shoper.extract_sales, "sales", shoper.SOURCE_SYSTEM)

    print("\n--- Purchases (incremental) ---")
    sync_append_only_table(engine, shoper.extract_purchases, "purchases", shoper.SOURCE_SYSTEM)

    print("\n--- Sales Orders (full refresh, currently-actionable snapshot) ---")
    full_reload_table(engine, shoper.extract_sales_orders(), "sales_orders", shoper.SOURCE_SYSTEM)

    print("\nDone.")


if __name__ == "__main__":
    run_load()
