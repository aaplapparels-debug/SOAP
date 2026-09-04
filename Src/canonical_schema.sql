-- canonical_schema.sql
--
-- The canonical schema. Every table now carries a `source_system`
-- column (e.g. 'shoper', 'tally', 'botree', 'excel') -- this is what
-- makes multi-source-per-tenant safe. A load for one source only ever
-- touches rows tagged with that source (DELETE ... WHERE source_system
-- = X, then insert), never the whole table. Two different source
-- adapters can feed the same table without one destroying the other's
-- data on its next run.
--
-- KNOWN DEFERRED PROBLEM, not solved here: if two sources both claim
-- to describe "the same" customer/item under different ID schemes
-- (e.g. Shoper's customer_code vs a future Botree's own numbering),
-- this schema does NOT unify them into one identity -- they'd sit as
-- separate rows, tagged by source. Real identity-matching across
-- systems is a genuinely harder problem that needs a real second
-- source to design against, not a guess made now. Same reasoning as
-- deferring the column-mapping tool.
--
-- No tenant_id column anywhere -- isolation happens at the database
-- level (each tenant gets their own Neon project).

CREATE TABLE IF NOT EXISTS customers (
    customer_code   VARCHAR(50),
    customer_name   VARCHAR(255),
    credit_days     INTEGER,
    credit_limit    NUMERIC(14, 2),
    credit_used     NUMERIC(14, 2),
    division        VARCHAR(20),
    source_system   VARCHAR(20),
    PRIMARY KEY (customer_code, division, source_system)
);

CREATE TABLE IF NOT EXISTS items (
    item_code       VARCHAR(50),
    item_desc       VARCHAR(255),
    category_1      VARCHAR(50),
    category_2      VARCHAR(50),
    size            VARCHAR(20),
    mrp             NUMERIC(12, 2),
    current_cost    NUMERIC(12, 2),
    stock_qty       NUMERIC(12, 2),
    stock_value     NUMERIC(14, 2),
    division        VARCHAR(20),
    source_system   VARCHAR(20),
    PRIMARY KEY (item_code, division, source_system)
);

CREATE TABLE IF NOT EXISTS sales (
    sale_date       DATE,
    customer_code   VARCHAR(50),
    item_code       VARCHAR(50),
    trn_type        INTEGER,
    sign_multiplier INTEGER,
    qty             NUMERIC(12, 2),
    rate            NUMERIC(12, 4),
    net_value       NUMERIC(14, 2),
    doc_prefix      VARCHAR(20),
    doc_no          INTEGER,
    division        VARCHAR(20),
    source_system   VARCHAR(20)
    -- No primary key -- a single invoice can have several identical-
    -- looking line items that are genuinely separate rows.
);

CREATE TABLE IF NOT EXISTS sales_orders (
    order_id        VARCHAR(50),
    customer_code   VARCHAR(50),
    item_code       VARCHAR(50),
    salesperson     VARCHAR(100),
    order_date      DATE,
    billed_date     DATE,
    order_qty       NUMERIC(12, 2),
    billed_qty      NUMERIC(12, 2),
    pending_qty     NUMERIC(12, 2),
    cancelled_qty   NUMERIC(12, 2),
    return_qty      NUMERIC(12, 2),
    mrp             NUMERIC(12, 2),
    invoice_value   NUMERIC(14, 2),
    division        VARCHAR(20),
    source_system   VARCHAR(20),
    PRIMARY KEY (order_id, item_code, division, source_system)
);

CREATE TABLE IF NOT EXISTS purchases (
    vendor_invoice_no      VARCHAR(50),
    vendor_invoice_date    DATE,
    doc_prefix             VARCHAR(20),
    doc_no                 INTEGER,
    entry_date             DATE,
    vendor_code            VARCHAR(50),
    item_code              VARCHAR(50),
    qty                    NUMERIC(12, 2),
    rate                   NUMERIC(12, 4),
    net_value              NUMERIC(14, 2),
    division               VARCHAR(20),
    source_system          VARCHAR(20)
);

-- Tally-sourced tables. Outstanding is a live snapshot (full refresh,
-- scoped to source_system='tally') receipts and credit notes are
-- append-only, same reasoning as sales/purchases.

CREATE TABLE IF NOT EXISTS outstanding_debtors (
    customer_name       VARCHAR(255),
    invoice_date        DATE,
    invoice_reference    VARCHAR(100),
    pending_amount      NUMERIC(14, 2),
    division            VARCHAR(20),
    source_system       VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_date         DATE,
    voucher_number        VARCHAR(50),
    customer_name         VARCHAR(255),
    bill_reference        VARCHAR(100),
    bill_type             VARCHAR(50),
    amount                NUMERIC(14, 2),
    -- Cash payments: all four of these stay NULL. Anything else:
    -- populated with the relevant bank/instrument detail.
    mode_of_payment       VARCHAR(50),
    instrument            VARCHAR(50),
    instrument_date       VARCHAR(8),   -- YYYYMMDD string, matching format_tally_date's output
    bank                  VARCHAR(100),
    division              VARCHAR(20),
    source_system         VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS credit_notes (
    cn_date              DATE,
    voucher_number       VARCHAR(50),
    customer_name        VARCHAR(255),
    bill_reference       VARCHAR(100),
    bill_type            VARCHAR(50),
    amount               NUMERIC(14, 2),
    division             VARCHAR(20),
    source_system        VARCHAR(20)
);

-- Tracks the last successful incremental sync PER (table, source) --
-- not just per table. This matters once two sources feed the same
-- table: each needs its own independent watermark, or one source's
-- sync would overwrite the other's progress tracking.
CREATE TABLE IF NOT EXISTS sync_state (
    source_table    TEXT,
    source_system   TEXT,
    last_synced_at  TIMESTAMP,
    PRIMARY KEY (source_table, source_system)
);

-- Dashboard access control -- replaces the old Google Sheets USERS
-- worksheet, now that everything else has moved off Sheets too.
CREATE TABLE IF NOT EXISTS dashboard_users (
    email        VARCHAR(255) PRIMARY KEY,
    role         VARCHAR(50) NOT NULL,   -- 'Admin', 'Manager', 'Sales', etc.
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- JC (Journey Cycle) period boundaries -- just the date ranges, not
-- targets. Targets are manually-entered numbers with no relationship
-- to sales data period boundaries are reference data used purely to
-- segment sales by period for year-over-year comparison.
--
-- Keyed on (jc_code, financial_year), NOT jc_code alone -- JC dates
-- vary by financial year (M1 in FY25-26 covers different actual dates
-- than M1 in FY26-27), so jc_code alone would collide across years
-- and silently lose one year's boundaries.
CREATE TABLE IF NOT EXISTS jc_periods (
    jc_code          VARCHAR(20),
    financial_year   INTEGER,   -- e.g. 20262027 means FY2026-27 (Apr 2026 - Mar 2027) -- full year pair, no dash, unambiguous at a glance
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL,
    PRIMARY KEY (jc_code, financial_year)
);

-- The ONE genuinely manual input -- target pieces per division per JC
-- period. Everything else (achieved pcs/value, %, balance) is fully
-- derivable from this plus the sales table, so none of it is stored
-- here -- see the jc_achievement view below. Dates live in jc_periods,
-- not repeated here, since they're identical across all divisions for
-- a given period -- repeating them risked one division's row getting
-- edited out of sync with the others.
CREATE TABLE IF NOT EXISTS jc_targets (
    jc_code          VARCHAR(20),
    financial_year   INTEGER,
    division         VARCHAR(20),
    target_pcs       INTEGER NOT NULL,
    PRIMARY KEY (jc_code, financial_year, division),
    FOREIGN KEY (jc_code, financial_year) REFERENCES jc_periods (jc_code, financial_year)
);

-- Computed at query time, not stored -- same reasoning as the ledger:
-- storing a derived number risks it silently disagreeing with the
-- real sales data underneath it if sales ever get corrected or
-- reloaded. This view is always correct by construction, because it's
-- always freshly derived.
--
-- qty/net_value are multiplied by sign_multiplier so returns correctly
-- REDUCE achievement, not just additively pile on top of invoices --
-- same net-of-returns logic used everywhere else sales are summed in
-- this project.
--
-- achv_pct is 0 (not NULL, not an error) when target_pcs is 0, and
-- balance_pcs never goes negative -- both match the exact convention
-- already used in the source spreadsheet's real data.
CREATE OR REPLACE VIEW jc_achievement AS
SELECT
    t.jc_code,
    t.financial_year,
    t.division,
    p.start_date,
    p.end_date,
    t.target_pcs,
    COALESCE(SUM(s.qty * s.sign_multiplier), 0) AS achv_pcs,
    COALESCE(SUM(s.net_value * s.sign_multiplier), 0) AS achv_value,
    CASE
        WHEN t.target_pcs > 0
        THEN ROUND(COALESCE(SUM(s.qty * s.sign_multiplier), 0) / t.target_pcs * 100, 2)
        ELSE 0
    END AS achv_pct,
    GREATEST(t.target_pcs - COALESCE(SUM(s.qty * s.sign_multiplier), 0), 0) AS balance_pcs
FROM jc_targets t
JOIN jc_periods p
    ON t.jc_code = p.jc_code AND t.financial_year = p.financial_year
LEFT JOIN sales s
    ON s.division = t.division
   AND s.sale_date >= p.start_date
   AND s.sale_date <= p.end_date
   AND s.customer_code <> '1001'
   AND s.item_code <> '8901326926543'
GROUP BY t.jc_code, t.financial_year, t.division, p.start_date, p.end_date, t.target_pcs;
