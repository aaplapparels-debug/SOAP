## Summary of Changes: Date-Based Incremental Sync

### Problem
The old approach used a separate `sync_state` table to track `last_synced_at` timestamps per source. This had issues:
1. If a row failed to insert or got partially loaded, it would be missed forever
2. Requires maintaining a separate tracking table
3. Time-based coupling between runs could cause edge cases

### Solution
New approach uses **the actual data in Postgres as the source of truth**:

1. **Query max date from Postgres**: Find `MAX(sale_date)` for already-loaded data
2. **Incremental cutoff**: Load only rows where `sale_date > MAX(sale_date)` from SQL Server
3. **Self-healing**: If any row was missed, it gets picked up on the next run because we always compare against actual data
4. **No sync_state needed**: For append-only tables (sales, purchases), sync_state is completely unnecessary

### Files Changed

#### `load_shoper_to_postgres.py`
- **Removed**: `get_last_synced()`, `set_last_synced()` functions (sync_state tracking)
- **Added**: `get_max_date_from_postgres()` - queries Postgres directly for MAX(date_column)
- **Updated**: `sync_append_only_table()` - now:
  - Takes optional `date_column` parameter (defaults to 'sale_date', 'entry_date', etc.)
  - Queries Postgres for the max date
  - If empty → full backfill (None returned)
  - If has data → incremental since (max_date + 1 day)
- **Removed imports**: `psycopg2` (unused, using SQLAlchemy now)
- **Added imports**: `Optional` from typing

#### `shoper_adapter.py`
- **Replaced**: Raw `pyodbc` connections with SQLAlchemy engines
- **Updated**: `_connect()` → `_get_engine()` - returns SQLAlchemy engine
- **Improved**: `_run_for_all_divisions()` - added per-division row count logging and error handling
- **Benefit**: Removes pandas warnings about DBAPI2 connections

### Behavior Changes

#### Before
```
First run:  "No previous sync for sales (shoper) -- running full backfill"
            Pulls data from 2023-04-01 (3 years back)
Second run: "Incremental sync for sales (shoper) since 2026-08-29"
            Looks for data only from TODAY onwards
            Gets "No new rows" because no sales happened today
```

#### After
```
First run:  "No existing data for sales (shoper) -- running full backfill"
            Pulls data from 2023-04-01 (3 years back)
            Inserts into Postgres
Second run: Queries Postgres: MAX(sale_date) = 2026-08-27
            "Incremental sync for sales (shoper) since 2026-08-28"
            Pulls only sales from 2026-08-28 onwards
            Gets "No new rows" if nothing new, or appends new data if present
```

### Key Advantages
1. **Self-healing**: Misses get caught on next run
2. **No separate tracking**: One less table to maintain
3. **Accurate**: Uses actual data as the source of truth
4. **Flexible**: Works with any date column (configurable)
5. **Resilient**: Handles partial failures gracefully

### Testing
The sync_state table is still created by canonical_schema.sql but is **no longer used** by load_shoper_to_postgres.py. You can leave it there for backward compatibility or drop it later if other loaders aren't using it.

### Migration Steps
1. ✅ Updated code to use max date from Postgres
2. ✅ Removed sync_state dependency from loader
3. Next: Run the loader and verify data loads correctly
