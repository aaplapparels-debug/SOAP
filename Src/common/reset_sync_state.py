#!/usr/bin/env python
"""Clear sync_state to force a full backfill on next load."""

from sqlalchemy import create_engine, text
from config_loader import load_config

config = load_config()
pg_cfg = config["postgres"]

print("Connecting to Postgres...")
engine = create_engine(pg_cfg["connection_string"])

with engine.begin() as conn:
    print("Clearing sync_state table...")
    conn.execute(text("DELETE FROM sync_state WHERE source_system = 'shoper'"))
    print("✓ Sync state cleared for Shoper")
    
    print("\nVerifying sync_state is empty for Shoper:")
    result = conn.execute(text("SELECT COUNT(*) FROM sync_state WHERE source_system = 'shoper'"))
    count = result.scalar()
    print(f"  Remaining Shoper entries: {count}")

engine.dispose()
print("\n✓ Done. Next load will do a full backfill from 2023-04-01.")
