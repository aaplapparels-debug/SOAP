# Dashboard Query Fixes - Summary

## Overview
Fixed all dashboard query references to match the canonical Postgres schema. The key issue was that dashboard queries were using incorrect column names and filters that didn't exist in the actual schema.

---

## Files Modified

### 1. **pages_outstanding.py**
**Issue**: Tried to filter outstanding_debtors by `source_system = 'shoper'`
- **Root Cause**: outstanding_debtors is a Tally-only table (live snapshot, full refresh scoped to 'tally')
- **Fix**: Removed `source_system = 'shoper'` filter from query and get_divisions() function
- **Changed SQL**: 
  ```sql
  FROM outstanding_debtors
  WHERE division = ANY(:divisions)  -- NO source_system filter
  ```
- **Changed function**: `get_divisions()` now queries `outstanding_debtors` without source_system filter
- **Status**: ✅ FIXED

### 2. **pages_executive.py**
**Issues**: Multiple query problems
- **Issue A**: Tried to get stock value from outstanding_debtors table (wrong table)
  - **Fix**: Changed to query from `items` table with `source_system = 'shoper'`
- **Issue B**: Tried to filter receipts/PDCs by `source_system = 'shoper'`
  - **Fix**: Receipts table doesn't need source_system filter (Tally-only), but removed filter anyway
- **Issue C**: instrument_date cast was wrong (`::date` is old Postgres syntax that doesn't work for VARCHAR)
  - **Fix**: Changed to `CAST(instrument_date AS DATE)` for proper VARCHAR-to-DATE conversion
- **Issue D**: Poor null handling when extracting values from result rows
  - **Fix**: Added null-safety checks when extracting values from fetchone() results
- **Changed SQL**:
  ```sql
  -- Before (WRONG):
  SELECT SUM(stock_value) FROM outstanding_debtors  -- Wrong table!
  
  -- After (CORRECT):
  SELECT SUM(stock_value) FROM items WHERE source_system = 'shoper'
  ```
- **Status**: ✅ FIXED

### 3. **pages_sales_dashboard.py**
**Status**: ✅ NO CHANGES NEEDED
- Query is correct:
  ```sql
  SELECT DATE_TRUNC('day', sale_date)::date as sale_date
  FROM sales
  WHERE source_system = 'shoper'
  ```
- Uses correct Postgres date functions
- Properly filters by source_system

### 4. **pages_stock.py**
**Status**: ✅ NO CHANGES NEEDED
- Query is correct:
  ```sql
  SELECT item_code, item_desc, ..., stock_value
  FROM items
  WHERE source_system = 'shoper'
  ```
- Uses correct table (items, not outstanding_debtors)
- Properly filters by source_system

---

## New Reference Documents Created

### 1. **SCHEMA_AND_QUERIES.md**
Complete reference guide containing:
- Schema overview for all 10 tables
- Column mappings for each table
- Multi-source architecture explanation
- Correct query patterns for each dashboard
- Common issues & fixes
- Key takeaways for developers

### 2. **test_dashboard_queries.py**
Test script to verify all queries work:
- Tests outstanding_debtors query
- Tests sales query (Shoper)
- Tests items query (Stock)
- Tests receipts/PDCs query
- Tests division/category lookups
- Tests full dashboard queries
- Usage: `python test_dashboard_queries.py` (requires SHOPER_SA_PASSWORD env var)

---

## Critical Schema Insights

### Data Sources by Table
| Table | Source | Scope | Notes |
|-------|--------|-------|-------|
| customers | Shoper | Multi-source safe | Filter by source_system='shoper' |
| items | Shoper | Multi-source safe | Filter by source_system='shoper' |
| sales | Shoper | Append-only | Filter by source_system='shoper' |
| sales_orders | Shoper | Multi-source safe | Filter by source_system='shoper' |
| purchases | Shoper | Append-only | Filter by source_system='shoper' |
| **outstanding_debtors** | **Tally** | **Tally-only** | **NO filter needed** |
| **receipts** | **Tally** | **Tally-only** | **NO filter needed** |
| **credit_notes** | **Tally** | **Tally-only** | **NO filter needed** |
| jc_periods | Manual | Reference | No source_system column |
| dashboard_users | Manual | Access control | No source_system column |

### Tally vs Shoper Architecture
The schema intentionally supports multiple data sources:
- **Shoper tables** have `source_system` column and MUST be filtered by `WHERE source_system = 'shoper'`
- **Tally tables** have `source_system` column but only contain 'tally' data (or left empty)
- Future adapters can feed the same tables without collision (each source isolated by source_system)

### Key Date Handling
- **invoice_date** (outstanding_debtors): DATE type → use date arithmetic directly
- **instrument_date** (receipts): VARCHAR(8) YYYYMMDD string → MUST cast to DATE before comparison
  ```sql
  CAST(instrument_date AS DATE) > CURRENT_DATE  -- Correct
  instrument_date::date > CURRENT_DATE          -- WRONG (doesn't work with VARCHAR)
  ```

---

## Query Patterns by Report

### Outstanding Report (Tally data)
```sql
SELECT customer_name, invoice_date, invoice_reference, pending_amount, division
FROM outstanding_debtors
WHERE division = ANY(:divisions)
  AND pending_amount >= :min_amount
ORDER BY invoice_date DESC
```
**Key**: No source_system filter

### Sales Dashboard (Shoper data)
```sql
SELECT DATE_TRUNC('day', sale_date)::date, division, SUM(net_value)
FROM sales
WHERE source_system = 'shoper'
  AND division = ANY(:divisions)
GROUP BY DATE_TRUNC('day', sale_date), division
ORDER BY sale_date DESC
```
**Key**: MUST filter by source_system, use DATE_TRUNC for Postgres

### Executive Dashboard (Multi-source aggregation)
```sql
-- Outstanding (Tally)
SELECT SUM(pending_amount) FROM outstanding_debtors

-- Stock (Shoper)
SELECT SUM(stock_value) FROM items WHERE source_system = 'shoper'

-- PDCs (Tally)
SELECT COUNT(*), SUM(amount) FROM receipts
WHERE instrument_date IS NOT NULL AND CAST(instrument_date AS DATE) > CURRENT_DATE

-- Sales (Shoper)
SELECT SUM(net_value) FROM sales WHERE source_system = 'shoper'
  AND sale_date >= CURRENT_DATE - INTERVAL '30 days'
```
**Key**: Each data source queried correctly with appropriate filters

### Stock Position (Shoper data)
```sql
SELECT item_code, item_desc, ..., stock_qty, stock_value
FROM items
WHERE source_system = 'shoper'
  AND division = ANY(:divisions)
ORDER BY stock_value DESC
```
**Key**: MUST filter by source_system

---

## Testing Checklist

Before deploying to production:

- [ ] Run `python test_dashboard_queries.py` to verify all queries
- [ ] Test each dashboard page in Streamlit app
- [ ] Verify Outstanding report shows data (requires Tally sync)
- [ ] Verify Sales dashboard shows data (requires Shoper sync)
- [ ] Verify Stock report shows data (requires Shoper sync)
- [ ] Verify Executive dashboard KPIs calculate correctly
- [ ] Check that division/category filters populate correctly
- [ ] Verify no SQL errors in terminal output

---

## Deployment Steps

1. **Verify environment**:
   ```powershell
   $env:SHOPER_SA_PASSWORD = "your-password"
   python test_dashboard_queries.py
   ```

2. **Run data sync**:
   ```powershell
   python load_shoper_to_postgres.py  # Load Shoper data
   # Note: Tally data sync happens on separate machine
   ```

3. **Start Streamlit dashboard**:
   ```powershell
   streamlit run dashboard.py
   ```

4. **Test each report**:
   - Click through each dashboard button
   - Check that data appears
   - Test filters work correctly
   - Verify downloads work (CSV, Excel)

---

## Future Enhancements

1. **Sales 360° Report**: Awaiting user instruction for implementation
2. **Role-based filtering**: Limit data visibility by user role
3. **Caching strategy**: Implement @st.cache_data with appropriate TTL
4. **Error handling**: Add better error messages for missing data
5. **Audit logging**: Track which users access which reports
6. **Performance**: Add indexes on frequently filtered columns (division, sale_date, etc.)

---

## References

- [Canonical Schema](./canonical_schema.sql)
- [Data Sync Logic](./SYNC_CHANGES.md)
- [Dashboard README](./DASHBOARD_README.md)
- [Full Schema Reference](./SCHEMA_AND_QUERIES.md)
