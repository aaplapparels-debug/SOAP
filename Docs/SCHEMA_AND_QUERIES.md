# Canonical Schema & Dashboard Queries Reference

## Schema Overview

The canonical Postgres schema supports **multi-source data ingestion** with each table tagged by `source_system`.

### Core Tables

#### 1. **customers** (Multi-source)
```
customer_code, customer_name, credit_days, credit_limit, credit_used, 
division, source_system
PRIMARY KEY: (customer_code, division, source_system)
```
- Source: Shoper (and future sources)
- Usage: Customer master data

#### 2. **items** (Multi-source)
```
item_code, item_desc, category_1, category_2, size, mrp, current_cost, 
stock_qty, stock_value, division, source_system
PRIMARY KEY: (item_code, division, source_system)
```
- Source: Shoper (and future sources)
- Usage: Inventory tracking, stock valuation
- **Note**: Contains ONLY Shoper data currently

#### 3. **sales** (Multi-source, Append-only)
```
sale_date, customer_code, item_code, trn_type, sign_multiplier, qty, rate, 
net_value, doc_prefix, doc_no, division, source_system
```
- Source: Shoper (and future sources)
- Usage: Daily sales transactions
- **Note**: Filter by `source_system = 'shoper'` for Shoper data

#### 4. **sales_orders** (Multi-source)
```
order_id, customer_code, item_code, salesperson, order_date, billed_date, 
order_qty, billed_qty, pending_qty, cancelled_qty, return_qty, mrp, 
invoice_value, division, source_system
```
- Source: Shoper
- Usage: Sales pipeline tracking

#### 5. **purchases** (Multi-source, Append-only)
```
vendor_invoice_no, vendor_invoice_date, doc_prefix, doc_no, entry_date, 
vendor_code, item_code, qty, rate, net_value, division, source_system
```
- Source: Shoper
- Usage: Vendor purchases tracking

### Tally-Only Tables (Live Snapshots - Full Refresh)

#### 6. **outstanding_debtors** (Tally-only)
```
customer_name, invoice_date, invoice_reference, pending_amount, 
division, source_system
```
- Source: Tally ONLY (source_system='tally')
- Refresh: Full refresh scoped to `source_system = 'tally'`
- **Note**: NO `source_system` filter needed in queries - only Tally data exists

#### 7. **receipts** (Tally-only, Append-only)
```
receipt_date, voucher_number, customer_name, bill_reference, bill_type, amount,
mode_of_payment, instrument, instrument_date (YYYYMMDD string), bank,
division, source_system
```
- Source: Tally ONLY
- Usage: Cash receipts, PDCs (Post-Dated Cheques)
- **Note**: PDCs have `instrument_date` IS NOT NULL and date > CURRENT_DATE

#### 8. **credit_notes** (Tally-only, Append-only)
```
cn_date, voucher_number, customer_name, bill_reference, bill_type, amount,
division, source_system
```
- Source: Tally ONLY
- Usage: Credit note tracking

### Reference Tables

#### 9. **jc_periods** (Manual entry)
```
jc_code, financial_year, start_date, end_date
PRIMARY KEY: (jc_code, financial_year)
```
- Format: `financial_year = 20262027` means FY2026-27 (Apr 2026 - Mar 2027)
- Usage: Journey Cycle period boundaries for year-over-year comparison

#### 10. **dashboard_users** (Access control)
```
email, role, is_active, created_at
```
- Roles: Admin, Manager, Sales, etc.

---

## Dashboard Query Patterns

### Outstanding Debtors Report
**Source**: `outstanding_debtors` (Tally)
**Pattern**: NO source_system filter needed
```sql
SELECT customer_name, invoice_date, invoice_reference, pending_amount, division
FROM outstanding_debtors
WHERE division = ANY(:divisions)
  AND pending_amount >= :min_amount
ORDER BY invoice_date DESC
```

### Sales Dashboard
**Source**: `sales` (Shoper) + `customers` for name lookup
**Pattern**: MUST filter by `source_system = 'shoper'`
```sql
SELECT 
    DATE_TRUNC('day', sale_date)::date as sale_date,
    division,
    SUM(net_value) as daily_sales
FROM sales
WHERE source_system = 'shoper'
  AND division = ANY(:divisions)
  AND sale_date >= :start_date
GROUP BY DATE_TRUNC('day', sale_date), division
ORDER BY sale_date DESC
```

### Executive Dashboard - KPIs
**Sources**: Multiple
```sql
-- Outstanding (Tally)
SELECT SUM(pending_amount), COUNT(DISTINCT customer_name)
FROM outstanding_debtors

-- Stock Value (Shoper)
SELECT SUM(stock_value), SUM(stock_qty)
FROM items
WHERE source_system = 'shoper'

-- PDCs (Tally)
SELECT COUNT(*), SUM(amount)
FROM receipts
WHERE instrument_date IS NOT NULL
  AND CAST(instrument_date AS DATE) > CURRENT_DATE

-- Recent Sales (Shoper)
SELECT SUM(net_value), COUNT(DISTINCT customer_code)
FROM sales
WHERE source_system = 'shoper'
  AND sale_date >= CURRENT_DATE - INTERVAL '30 days'
```

### Stock Position Report
**Source**: `items` (Shoper)
**Pattern**: MUST filter by `source_system = 'shoper'`
```sql
SELECT 
    item_code, item_desc, category_1, category_2, size,
    stock_qty, stock_value, mrp, current_cost, division
FROM items
WHERE source_system = 'shoper'
  AND division = ANY(:divisions)
ORDER BY stock_value DESC
```

---

## Common Issues & Fixes

### ❌ Problem: "source_system filter on outstanding_debtors"
**Root Cause**: outstanding_debtors is Tally-only; filtering by 'shoper' returns no rows
**Fix**: Remove source_system filter or use `source_system = 'tally'` if needed

### ❌ Problem: "instrument_date::date cast fails"
**Root Cause**: `instrument_date` is VARCHAR(8) YYYYMMDD string, not a DATE
**Fix**: Use `CAST(instrument_date AS DATE)` or string comparison

### ❌ Problem: "DATEDIFF not found"
**Root Cause**: DATEDIFF is SQL Server syntax; Postgres uses EXTRACT or subtraction
**Fix**: Use `EXTRACT(DAY FROM CURRENT_DATE - invoice_date)` or `CURRENT_DATE - invoice_date`

### ❌ Problem: "ANY() with empty parameter"
**Root Cause**: Passing empty list to `= ANY(:divisions)` 
**Fix**: Check that filter lists are never empty; provide defaults

---

## Sync State & Incremental Loads

**Table**: `sync_state` (tracks last successful load per source/table)
```
source_table (e.g., 'sales'), source_system (e.g., 'shoper'), last_synced_at
PRIMARY KEY: (source_table, source_system)
```

**Current Strategy**: Date-based incremental (not sync_state-based)
- Query `MAX(date_column)` from Postgres for each table
- Load only rows where date > MAX(date)
- More resilient; misses get caught on next run

---

## Key Takeaways

1. **outstanding_debtors** = Tally-only, no filtering needed
2. **sales, items** = Shoper-primary, filter by `source_system = 'shoper'`
3. **receipts, credit_notes** = Tally-only
4. **instrument_date** in receipts is VARCHAR(8), needs CAST to DATE
5. Use Postgres date functions: EXTRACT, DATE_TRUNC, date arithmetic
6. All dashboard queries scoped to specific divisions for security/performance
