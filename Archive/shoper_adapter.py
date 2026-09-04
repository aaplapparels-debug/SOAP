"""
shoper_adapter.py

Adapter for extracting canonical business data (customers, items, sales,
sales orders, purchases) out of Shoper POS/ERP SQL Server databases.

Shoper stores each division as a *separate* physical database on the same
SQL Server instance (e.g. one database per division: SPM, SPW, Thermal,
KTH). This adapter loops over however many divisions a tenant's config
lists -- it makes no assumption that there are exactly four, so a future
tenant with a different division count needs zero code changes here.

UPDATED: date windows are now anchored to Indian financial years
(April 1 - March 31), not a rolling N-years-from-today window. "3
financial years back" from August 2026 (which sits in FY 2026-27) means
"everything from April 1, 2023 onward" -- covering FY23-24, FY24-25,
FY25-26, and the current partial FY26-27. A rolling DATEADD(YEAR, -3,...)
would have landed on August 2023, which is mid-year and doesn't line up
with how the business actually thinks about "years" of data.

Every transactional extraction method (sales, sales orders, purchases)
now accepts an optional `since_date` parameter. When it's None, the
method uses the financial-year cutoff (the initial full backfill). When
it's given a specific date, that date is used instead -- this is what
the incremental sync in load_to_postgres.py uses to ask for "only
what's changed since the last successful sync" instead of re-pulling
everything every time.

Python concepts used below, since you're reading this while learning:

- `class` bundles related data + functions (called "methods" once they're
  inside a class) together. Think of a class as a blueprint. Writing
  `ShoperAdapter(divisions=[...])` creates one *instance* of that
  blueprint -- one adapter, configured for one tenant's specific list of
  division databases.
- `self` is how a method refers back to its own instance's data. It's
  always the first parameter of a method, and Python passes it in
  automatically -- you never type it yourself when *calling* a method,
  only when *defining* one.
- `@dataclass` is a shortcut for classes that are mostly just a bunch of
  fields with no real logic. It auto-writes the boring "store these
  values on self" code for you.
- A default parameter value, like `since_date: date = None`, means the
  caller can leave that argument out entirely and Python fills in the
  default -- that's what lets the same method serve both "give me
  everything" (no argument) and "give me just what changed" (pass a
  date) without needing two separate methods.
"""

import datetime

import pyodbc
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional


def get_financial_year_cutoff(as_of: datetime.date, years_back: int) -> datetime.date:
    """
    Indian financial year runs April 1 - March 31. Returns April 1 of
    (years_back) complete financial years before the current one -- so
    the result covers `years_back` complete FYs plus whatever's elapsed
    of the current FY.

    Example: as_of = Aug 23, 2026 (inside FY2026-27), years_back = 3
    returns April 1, 2023 -- covering FY23-24, FY24-25, FY25-26, and
    the current FY26-27 so far.
    """
    current_fy_start_year = as_of.year if as_of.month >= 4 else as_of.year - 1
    cutoff_year = current_fy_start_year - years_back
    return datetime.date(cutoff_year, 4, 1)


@dataclass
class DivisionConfig:
    """One division = one physical Shoper database to connect to."""
    division_name: str   # e.g. "SPM", "SPW", "Thermal", "KTH"
    server: str           # e.g. "localhost\\STAGING_SERVER" -- the native instance, no Docker involved
    database: str         # e.g. "Shoper962X" -- the restored database name
    username: str
    password: str


class ShoperAdapter:
    """Extracts canonical DataFrames from one or more Shoper division databases."""

    def __init__(self, divisions: List[DivisionConfig], financial_years_back: int):
        # Stored on `self` so every method below can see the division list
        # without it being passed in again and again to each method.
        self.divisions = divisions
        # The default cutoff used for a full backfill (when a method's
        # since_date argument is left as None). Customers and items
        # aren't filtered by this at all -- they're current master data,
        # not history, so we always want all of it.
        self.default_cutoff = get_financial_year_cutoff(datetime.date.today(), financial_years_back)


    def _connect(self, division: DivisionConfig) -> pyodbc.Connection:
        """Open a connection to one division's database."""
        conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={division.server};"
            f"DATABASE={division.database};"
            f"UID={division.username};PWD={division.password};"
            "TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str)

    def _run_for_all_divisions(self, query: str) -> pd.DataFrame:
        """
        Runs the same query against every division's database, tags each
        result with the division name, and stacks them into one DataFrame.

        This loop is the whole trick: add a 5th division to the config
        list passed into __init__, and this same code handles it with no
        changes -- only the config gets longer.
        """
        frames = []
        for division in self.divisions:
            conn = self._connect(division)
            df = pd.read_sql(query, conn)
            df["division"] = division.division_name
            frames.append(df)
            conn.close()
        # pd.concat glues a list of DataFrames into one, stacked on top of
        # each other. ignore_index=True renumbers rows 0,1,2... instead of
        # keeping each division's own row numbers, which would collide.
        return pd.concat(frames, ignore_index=True)

    def extract_customers(self) -> pd.DataFrame:
        query = """
            SELECT Code AS customer_code, Nm AS customer_name,
                   CreditDays AS credit_days, CreditLimit AS credit_limit,
                   CreditUsed AS credit_used
            FROM Customers
        """
        return self._run_for_all_divisions(query)

    def extract_items(self) -> pd.DataFrame:
        query = """
            SELECT im.StockNo AS item_code, im.ItemDesc AS item_desc,
                   im.Class1Cd AS category_1, im.Class2Cd AS category_2,
                   im.SizeCd AS size, im.Retail_Price AS mrp,
                   im.CurrentCost AS current_cost,
                   sm.CurBalQty AS stock_qty, sm.CurBalVal AS stock_value
            FROM ItemMaster im
            LEFT JOIN StockMaster sm ON im.StockNo = sm.StockNo
        """
        return self._run_for_all_divisions(query)

    def extract_sales(self, since_date: Optional[datetime.date] = None) -> pd.DataFrame:
        # SaleTrnType 2100 = Sales Invoice (counts positive)
        # SaleTrnType 1300 = Sales Return (subtracts)
        # SaleTrnType 1600 = Void/Cancel -- deliberately excluded entirely
        # (not included, not zeroed) since a void means the sale never
        # should have counted in the first place.
        #
        # If since_date isn't given, falls back to the financial-year
        # cutoff -- a full backfill. If it is given (incremental sync),
        # only rows newer than that date are pulled. Sales are treated
        # as immutable once posted (a correction becomes a NEW return
        # row, not an edit to an old one), so "only what's new" is safe
        # to just append without needing to check for changes to old rows.
        cutoff = since_date if since_date else self.default_cutoff
        query = f"""
            SELECT h.DocDt AS sale_date, h.CustCd AS customer_code,
                   d.StockNo AS item_code, h.SaleTrnType AS trn_type,
                   CASE h.SaleTrnType WHEN 2100 THEN 1 WHEN 1300 THEN -1 END AS sign_multiplier,
                   d.DocQty AS qty, d.StkUpdtRate AS rate,
                   d.DocEntNetValue AS net_value,
                   h.DocNoPrefix AS doc_prefix, h.DocNo AS doc_no
            FROM SaleTrnHdr h
            JOIN StkTrnDtls d
                ON h.StkTrnTypeSale = d.TrnType
               AND h.StkTrnCtrlNoSale = d.TrnCtrlNo
            WHERE h.SaleTrnType IN (1300, 2100)
              AND h.DocDt >= '{cutoff.strftime('%Y-%m-%d')}'
        """
        return self._run_for_all_divisions(query)

    def extract_sales_orders(self, since_date: Optional[datetime.date] = None) -> pd.DataFrame:
        # PendingQty already comes pre-computed from Shoper -- no need to
        # derive it ourselves by comparing orders against invoices.
        #
        # Orders are NOT immutable like sales -- an order's pending_qty
        # can keep changing long after it was first placed, as more of
        # it gets billed over time. So this always re-pulls anything
        # still genuinely open (PendingQty > 0), regardless of age, in
        # addition to anything new since the cutoff/since_date. That's
        # why the caller uses an UPSERT for this table, not a plain
        # append -- an "open" order pulled again might be an existing
        # row whose pending_qty just needs updating, not a new row.

        since_date = datetime.date.today() - datetime.timedelta(days=10)
        cutoff = since_date if since_date else self.default_cutoff
        query = f"""
            SELECT OrderNo AS order_id, CustCd AS customer_code,
                   Stockno AS item_code, SalesStaff AS salesperson,
                   OrderDate AS order_date, BilledDate AS billed_date,
                   Orderqty AS order_qty, BilledQty AS billed_qty,
                   PendingQty AS pending_qty, CanceledQty AS cancelled_qty,
                   ReturnQty AS return_qty, MRP AS mrp,
                   InvValue AS invoice_value
            FROM CustSFASalesOrderDtls
            WHERE OrderDate >= '{cutoff.strftime('%Y-%m-%d')}'
               and PendingQty > 0
        """
        return self._run_for_all_divisions(query)

    def extract_purchases(self, since_date: Optional[datetime.date] = None) -> pd.DataFrame:
        # TrnType 1100 = Purchase (confirmed via GenLookUp, same as the
        # sales type codes). Unlike sales, StkTrnHdr IS the purchase
        # header directly -- no separate bridging table, so the join to
        # StkTrnDtls uses (TrnType, TrnCtrlNo) with no indirection.
        #
        # PartyStkDocNo / PartyStkDocDt are the VENDOR's own invoice
        # number and date -- distinct from DocNoPrefix/DocNo, which is
        # Shoper's own internal document numbering, not the vendor's.
        # Treated as immutable once entered, same as sales -- safe to
        # just append new rows on an incremental sync.
        cutoff = since_date if since_date else self.default_cutoff
        query = f"""
            SELECT h.PartyStkDocNo AS vendor_invoice_no,
                   h.PartyStkDocDt AS vendor_invoice_date,
                   h.DocNoPrefix AS doc_prefix, h.DocNo AS doc_no,
                   h.DocDt AS entry_date, h.PartyId AS vendor_code,
                   d.StockNo AS item_code, d.DocQty AS qty,
                   d.StkUpdtRate AS rate, d.DocEntNetValue AS net_value
            FROM StkTrnHdr h
            JOIN StkTrnDtls d
                ON h.TrnType = d.TrnType
               AND h.TrnCtrlNo = d.TrnCtrlNo
            WHERE h.TrnType = 1100
              AND h.DocDt >= '{cutoff.strftime('%Y-%m-%d')}'
        """
        return self._run_for_all_divisions(query)


# ------------------------------------------------------------------
# Example usage -- this is how you'd actually call this from a script.
# The `if __name__ == "__main__":` guard means this block only runs when
# you execute this file directly (python shoper_adapter.py), not when
# some other file imports ShoperAdapter from this one.
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Same config file restore_shoper_backups.py uses -- one source of
    # truth for divisions, host, and credentials. No hardcoded values
    # here anymore, so dev vs. prod is just which config file is active.
    from config_loader import load_config

    config = load_config()
    sql_cfg = config["sql_server"]

    aapl_divisions = [
        DivisionConfig(
            division_name=division["name"],
            server=sql_cfg["host"],
            database=division["staging_db"],  # e.g. ShoperStaging_SPM -- the restored DB, not the original Shoper DB name
            username=sql_cfg["sa_username"],
            password=sql_cfg["sa_password"],
        )
        for division in config["divisions"]
    ]

    adapter = ShoperAdapter(aapl_divisions, financial_years_back=config["sync"]["financial_years_back"])

    print("=== Customers ===")
    customers_df = adapter.extract_customers()
    print(customers_df.head())
    print(f"Total rows: {len(customers_df)}\n")

    print("=== Items ===")
    items_df = adapter.extract_items()
    print(items_df.head())
    print(f"Total rows: {len(items_df)}\n")

    print("=== Sales (full backfill) ===")
    sales_df = adapter.extract_sales()
    print(sales_df.head())
    print(f"Total rows: {len(sales_df)}\n")

    print("=== Sales Orders (full backfill + open orders) ===")
    orders_df = adapter.extract_sales_orders()
    print(orders_df.head())
    print(f"Total rows: {len(orders_df)}\n")

    print("=== Purchases (full backfill) ===")
    purchases_df = adapter.extract_purchases()
    print(purchases_df.head())
    print(f"Total rows: {len(purchases_df)}")
