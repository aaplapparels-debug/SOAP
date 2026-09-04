# Dashboard Query Validation Checklist

## Outstanding Debtors Report (pages_outstanding.py)

### Query Pattern Analysis
- ✅ Table: `outstanding_debtors` (Tally-only)
- ✅ NO source_system filter (correct - Tally data only)
- ✅ Date calculation: `EXTRACT(DAY FROM CURRENT_DATE - invoice_date)` (correct Postgres syntax)
- ✅ Columns used: customer_name, invoice_date, invoice_reference, pending_amount, division (all exist in schema)
- ✅ Sorting: By pending_amount, customer_name, or invoice_date (valid columns)

### get_divisions() Helper
- ✅ Query: `SELECT DISTINCT division FROM outstanding_debtors` (no source_system filter)
- ✅ Fallback: Returns ['SPM', 'SPW', 'Thermal', 'KTH'] if query fails

**STATUS**: ✅ CORRECT

---

## Sales Dashboard (pages_sales_dashboard.py)

### Query Pattern Analysis
- ✅ Table: `sales` (Shoper multi-source)
- ✅ REQUIRED filter: `source_system = 'shoper'` (correctly applied)
- ✅ Date function: `DATE_TRUNC('day', sale_date)::date` (correct Postgres aggregation)
- ✅ Columns used: sale_date, division, net_value, customer_code (all exist in schema)
- ✅ Grouping: By DATE_TRUNC and division (correct)
- ✅ Period selector: Custom period logic implemented correctly

### get_divisions() Helper
- ✅ Query: `SELECT DISTINCT division FROM sales WHERE source_system = 'shoper'` (correct filter)

**STATUS**: ✅ CORRECT

---

## Executive Dashboard (pages_executive.py)

### Query 1: Outstanding (Tally)
- ✅ Table: `outstanding_debtors`
- ✅ NO source_system filter (correct)
- ✅ Aggregation: SUM(pending_amount), COUNT(DISTINCT customer_name)
- ✅ Null safety: Checks empty result before extracting values

### Query 2: Stock Value (Shoper)
- ✅ Table: `items` (WAS: outstanding_debtors - NOW FIXED)
- ✅ REQUIRED filter: `source_system = 'shoper'` (correctly applied)
- ✅ Aggregation: SUM(stock_value), SUM(stock_qty)
- ✅ Null safety: Checks empty result before extracting values

### Query 3: PDCs (Tally)
- ✅ Table: `receipts`
- ✅ PDC filter: `instrument_date IS NOT NULL AND CAST(instrument_date AS DATE) > CURRENT_DATE` (WAS: ::date NOW: CAST())
- ✅ Aggregation: COUNT(*), SUM(amount)
- ✅ Null safety: Checks empty result

### Query 4: Recent Sales (Shoper)
- ✅ Table: `sales`
- ✅ REQUIRED filter: `source_system = 'shoper'`
- ✅ Date range: `sale_date >= CURRENT_DATE - INTERVAL '30 days'` (correct)
- ✅ Aggregation: SUM(net_value), COUNT(DISTINCT customer_code)

### Query 5: Division Breakdown
- ✅ Joins multiple sources appropriately
- ✅ Subqueries filter by source correctly:
  - outstanding_debtors (no filter)
  - items (source_system = 'shoper')
  - sales (source_system = 'shoper')

**STATUS**: ✅ CORRECT (Fixed from pages_executive.py version 1)

---

## Stock Position Report (pages_stock.py)

### Query Pattern Analysis
- ✅ Table: `items` (Shoper multi-source)
- ✅ REQUIRED filter: `source_system = 'shoper'` (correctly applied)
- ✅ Columns used: item_code, item_desc, category_1, category_2, size, stock_qty, stock_value, mrp, current_cost, division (all exist)
- ✅ Optional filters: category_1, stock_qty ranges (valid columns)
- ✅ Sorting: By stock_value DESC (correct for value-based inventory analysis)

### get_categories() Helper
- ✅ Query: `SELECT DISTINCT category_1 FROM items WHERE source_system = 'shoper' AND category_1 IS NOT NULL` (correct filter)

**STATUS**: ✅ CORRECT

---

## Sales 360° Report (pages_sales360.py)

### Status
- ⏳ DEFERRED - Awaiting user instruction per user message
- 📝 Implementation skeleton exists
- 🚫 Query implementation not yet started

**STATUS**: ⏳ PENDING USER INSTRUCTION

---

## Summary Statistics

| Report | Table(s) | Source Filter | Status |
|--------|----------|---------------|--------|
| Outstanding | outstanding_debtors | None (Tally-only) | ✅ FIXED |
| Sales Dashboard | sales | WHERE source_system='shoper' | ✅ OK |
| Executive | outstanding_debtors, items, receipts, sales | Mixed (see above) | ✅ FIXED |
| Stock | items | WHERE source_system='shoper' | ✅ OK |
| Sales 360° | (TBD) | (TBD) | ⏳ PENDING |

---

## Date Function Audit

| Function | Usage | Status |
|----------|-------|--------|
| DATE_TRUNC('day', date_col)::date | GROUP BY periods (Sales) | ✅ Correct |
| EXTRACT(DAY FROM CURRENT_DATE - date_col) | Age calculation (Outstanding) | ✅ Correct |
| CAST(varchar_col AS DATE) > CURRENT_DATE | PDC future-date check | ✅ Correct |
| CURRENT_DATE - INTERVAL '30 days' | Recent sales filter | ✅ Correct |

---

## Multi-Source Safety Audit

### Shoper Tables (MUST filter by source_system='shoper')
- ✅ sales: Filtered in all queries
- ✅ items: Filtered in all queries
- ✅ customers: Would need filter (not currently used in dashboards)
- ✅ sales_orders: Would need filter (not currently used in dashboards)
- ✅ purchases: Would need filter (not currently used in dashboards)

### Tally Tables (NO filter needed - Tally data only)
- ✅ outstanding_debtors: Correctly has NO filter
- ✅ receipts: Correctly has NO filter
- ✅ credit_notes: Not currently used in dashboards

**STATUS**: ✅ ALL SAFE

---

## Column Existence Verification

### outstanding_debtors
- ✅ customer_name (VARCHAR 255)
- ✅ invoice_date (DATE)
- ✅ invoice_reference (VARCHAR 100)
- ✅ pending_amount (NUMERIC 14,2)
- ✅ division (VARCHAR 20)
- ✅ source_system (VARCHAR 20)

### sales
- ✅ sale_date (DATE)
- ✅ customer_code (VARCHAR 50)
- ✅ item_code (VARCHAR 50)
- ✅ net_value (NUMERIC 14,2)
- ✅ division (VARCHAR 20)
- ✅ source_system (VARCHAR 20)

### items
- ✅ item_code (VARCHAR 50)
- ✅ item_desc (VARCHAR 255)
- ✅ category_1 (VARCHAR 50)
- ✅ category_2 (VARCHAR 50)
- ✅ size (VARCHAR 20)
- ✅ stock_qty (NUMERIC 12,2)
- ✅ stock_value (NUMERIC 14,2)
- ✅ mrp (NUMERIC 12,2)
- ✅ current_cost (NUMERIC 12,2)
- ✅ division (VARCHAR 20)
- ✅ source_system (VARCHAR 20)

### receipts
- ✅ receipt_date (DATE)
- ✅ voucher_number (VARCHAR 50)
- ✅ customer_name (VARCHAR 255)
- ✅ amount (NUMERIC 14,2)
- ✅ instrument_date (VARCHAR 8) - YYYYMMDD format
- ✅ division (VARCHAR 20)
- ✅ source_system (VARCHAR 20)

**STATUS**: ✅ ALL COLUMNS EXIST

---

## Final Validation

✅ All outstanding_debtors queries have NO source_system filter (Tally-only)
✅ All sales queries filter by source_system='shoper'
✅ All items queries filter by source_system='shoper'
✅ All date functions use Postgres-compatible syntax
✅ All columns referenced in queries exist in canonical_schema.sql
✅ No references to non-existent tables
✅ Null safety implemented where needed
✅ Division/category filters populate dynamically
✅ All files compile without syntax errors

**OVERALL STATUS**: ✅ ALL QUERIES VALIDATED AND CORRECT
