"""
Src/analytics/ticker_helper.py
Data engine for computing dynamic ticker metrics across Divisions, Items, and Customers.
"""

import pandas as pd
import streamlit as st
from sqlalchemy import text

try:
    from ui.db_helper import get_engine
except ImportError:
    from db_helper import get_engine


@st.cache_data(ttl=60)
def get_ticker_config():
    """Fetches global ticker settings from the database."""
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM portal_ticker_config WHERE id = 1;"), conn)
    return df.iloc[0].to_dict() if not df.empty else None


@st.cache_data(ttl=300)
def get_division_sales_ticker_data(
    scope: str = "JC", 
    metric: str = "QTY"
) -> list[dict]:
    """
    Compares sales by Division (SPW, THM, SPM, KTH) in CY vs LY.
    scope:  'JC' (Current Journey Cycle) or 'YTD' (Financial Year to Date)
    metric: 'QTY' (Pieces) or 'VALUE' (Net Amount in INR)
    """
    engine = get_engine()
    col_expr = "s.qty" if metric == "QTY" else "s.net_value"

    if scope == "YTD":
        query = text(f"""
            WITH fy_dates AS (
                SELECT 
                    CASE 
                        WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 4 
                        THEN MAKE_DATE(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 4, 1)
                        ELSE MAKE_DATE((EXTRACT(YEAR FROM CURRENT_DATE) - 1)::INT, 4, 1)
                    END AS cy_ytd_start,
                    CURRENT_DATE AS cy_ytd_end
            ),
            windows AS (
                SELECT 
                    cy_ytd_start,
                    cy_ytd_end,
                    (cy_ytd_start - INTERVAL '1 year')::DATE AS ly_ytd_start,
                    (cy_ytd_end - INTERVAL '1 year')::DATE AS ly_ytd_end
                FROM fy_dates
            ),
            cy_div AS (
                SELECT 
                    s.division,
                    SUM({col_expr} * s.sign_multiplier) AS cy_val
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.cy_ytd_start AND w.cy_ytd_end
                  AND s.customer_code <> '1001'
                  AND s.item_code <> '8901326926543'
                GROUP BY s.division
            ),
            ly_div AS (
                SELECT 
                    s.division,
                    SUM({col_expr} * s.sign_multiplier) AS ly_val
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.ly_ytd_start AND w.ly_ytd_end
                  AND s.customer_code <> '1001'
                  AND s.item_code <> '8901326926543'
                GROUP BY s.division
            )
            SELECT 
                d.division AS name,
                COALESCE(cy.cy_val, 0) AS cy_val,
                COALESCE(ly.ly_val, 0) AS ly_val
            FROM (SELECT DISTINCT division FROM sales WHERE division IS NOT NULL) d
            LEFT JOIN cy_div cy ON d.division = cy.division
            LEFT JOIN ly_div ly ON d.division = ly.division
            ORDER BY cy_val DESC;
        """)
    else:  # 'JC' mode
        query = text(f"""
            WITH current_jc AS (
                SELECT 
                    jc_code,
                    financial_year AS cy_fy,
                    (financial_year - 10001) AS ly_fy,
                    start_date AS cy_start,
                    CURRENT_DATE AS cy_as_of,
                    (CURRENT_DATE - start_date) AS days_elapsed
                FROM jc_periods
                WHERE CURRENT_DATE BETWEEN start_date AND end_date
                LIMIT 1
            ),
            ly_window AS (
                SELECT 
                    p.start_date AS ly_start,
                    (p.start_date + c.days_elapsed) AS ly_cutoff
                FROM jc_periods p
                JOIN current_jc c ON p.jc_code = c.jc_code AND p.financial_year = c.ly_fy
            ),
            cy_div AS (
                SELECT 
                    s.division,
                    SUM({col_expr} * s.sign_multiplier) AS cy_val
                FROM sales s, current_jc c
                WHERE s.sale_date BETWEEN c.cy_start AND c.cy_as_of
                  AND s.customer_code <> '1001'
                  AND s.item_code <> '8901326926543'
                GROUP BY s.division
            ),
            ly_div AS (
                SELECT 
                    s.division,
                    SUM({col_expr} * s.sign_multiplier) AS ly_val
                FROM sales s, ly_window l
                WHERE s.sale_date BETWEEN l.ly_start AND l.ly_cutoff
                  AND s.customer_code <> '1001'
                  AND s.item_code <> '8901326926543'
                GROUP BY s.division
            )
            SELECT 
                d.division AS name,
                COALESCE(cy.cy_val, 0) AS cy_val,
                COALESCE(ly.ly_val, 0) AS ly_val
            FROM (SELECT DISTINCT division FROM sales WHERE division IS NOT NULL) d
            LEFT JOIN cy_div cy ON d.division = cy.division
            LEFT JOIN ly_div ly ON d.division = ly.division
            ORDER BY cy_val DESC;
        """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    results = []
    for _, r in df.iterrows():
        cy = float(r["cy_val"])
        ly = float(r["ly_val"])
        pct = ((cy - ly) / ly * 100.0) if ly > 0 else (100.0 if cy > 0 else 0.0)
        results.append({
            "name": r["name"],
            "cy": cy,
            "ly": ly,
            "pct": round(pct, 1),
            "trend": "UP" if cy >= ly else "DOWN",
            "metric": metric,
            "scope": scope
        })
    return results


@st.cache_data(ttl=300)
def get_item_sales_ticker_data(scope: str = "JC", limit: int = 15) -> list[dict]:
    """Fetches Stock Items sales comparison."""
    engine = get_engine()
    
    if scope == "YTD":
        query = text("""
            WITH fy_dates AS (
                SELECT 
                    CASE 
                        WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 4 
                        THEN MAKE_DATE(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 4, 1)
                        ELSE MAKE_DATE((EXTRACT(YEAR FROM CURRENT_DATE) - 1)::INT, 4, 1)
                    END AS cy_ytd_start,
                    CURRENT_DATE AS cy_ytd_end
            ),
            windows AS (
                SELECT 
                    cy_ytd_start,
                    cy_ytd_end,
                    (cy_ytd_start - INTERVAL '1 year')::DATE AS ly_ytd_start,
                    (cy_ytd_end - INTERVAL '1 year')::DATE AS ly_ytd_end
                FROM fy_dates
            ),
            cy_sales AS (
                SELECT s.item_code, SUM(s.qty * s.sign_multiplier) AS cy_qty
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.cy_ytd_start AND w.cy_ytd_end
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.item_code
            ),
            ly_sales AS (
                SELECT s.item_code, SUM(s.qty * s.sign_multiplier) AS ly_qty
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.ly_ytd_start AND w.ly_ytd_end
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.item_code
            )
            SELECT 
                i.item_desc AS name,
                COALESCE(cy.cy_qty, 0) AS cy_val,
                COALESCE(ly.ly_qty, 0) AS ly_val
            FROM items i
            LEFT JOIN cy_sales cy ON i.item_code = cy.item_code
            LEFT JOIN ly_sales ly ON i.item_code = ly.item_code
            WHERE COALESCE(cy.cy_qty, 0) <> 0 OR COALESCE(ly.ly_qty, 0) <> 0
            ORDER BY cy_val DESC
            LIMIT :limit;
        """)
    else:
        query = text("""
            WITH current_jc AS (
                SELECT 
                    jc_code,
                    financial_year AS cy_fy,
                    (financial_year - 10001) AS ly_fy,
                    start_date AS cy_start,
                    CURRENT_DATE AS cy_as_of,
                    (CURRENT_DATE - start_date) AS days_elapsed
                FROM jc_periods
                WHERE CURRENT_DATE BETWEEN start_date AND end_date
                LIMIT 1
            ),
            ly_window AS (
                SELECT 
                    p.start_date AS ly_start,
                    (p.start_date + c.days_elapsed) AS ly_cutoff
                FROM jc_periods p
                JOIN current_jc c ON p.jc_code = c.jc_code AND p.financial_year = c.ly_fy
            ),
            cy_sales AS (
                SELECT s.item_code, SUM(s.qty * s.sign_multiplier) AS cy_qty
                FROM sales s, current_jc c
                WHERE s.sale_date BETWEEN c.cy_start AND c.cy_as_of
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.item_code
            ),
            ly_sales AS (
                SELECT s.item_code, SUM(s.qty * s.sign_multiplier) AS ly_qty
                FROM sales s, ly_window l
                WHERE s.sale_date BETWEEN l.ly_start AND l.ly_cutoff
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.item_code
            )
            SELECT 
                i.item_desc AS name,
                COALESCE(cy.cy_qty, 0) AS cy_val,
                COALESCE(ly.ly_qty, 0) AS ly_val
            FROM items i
            LEFT JOIN cy_sales cy ON i.item_code = cy.item_code
            LEFT JOIN ly_sales ly ON i.item_code = ly.item_code
            WHERE COALESCE(cy.cy_qty, 0) <> 0 OR COALESCE(ly.ly_qty, 0) <> 0
            ORDER BY cy_val DESC
            LIMIT :limit;
        """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"limit": limit})

    items = []
    for _, r in df.iterrows():
        cy = float(r["cy_val"])
        ly = float(r["ly_val"])
        pct = ((cy - ly) / ly * 100) if ly > 0 else (100.0 if cy > 0 else 0.0)
        items.append({
            "name": r["name"] or "Unknown Item",
            "cy": int(cy),
            "ly": int(ly),
            "pct": round(pct, 1),
            "trend": "UP" if cy >= ly else "DOWN"
        })
    return items


@st.cache_data(ttl=300)
def get_customer_sales_ticker_data(
    scope: str = "JC", 
    metric: str = "QTY", 
    limit: int = 15
) -> list[dict]:
    """Fetches Customer sales comparison deduplicated to one row per customer."""
    engine = get_engine()
    col_expr = "s.qty" if metric == "QTY" else "s.net_value"

    if scope == "YTD":
        query = text(f"""
            WITH fy_dates AS (
                SELECT 
                    CASE 
                        WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 4 
                        THEN MAKE_DATE(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 4, 1)
                        ELSE MAKE_DATE((EXTRACT(YEAR FROM CURRENT_DATE) - 1)::INT, 4, 1)
                    END AS cy_ytd_start,
                    CURRENT_DATE AS cy_ytd_end
            ),
            windows AS (
                SELECT 
                    cy_ytd_start,
                    cy_ytd_end,
                    (cy_ytd_start - INTERVAL '1 year')::DATE AS ly_ytd_start,
                    (cy_ytd_end - INTERVAL '1 year')::DATE AS ly_ytd_end
                FROM fy_dates
            ),
            cy_cust AS (
                SELECT s.customer_code, SUM({col_expr} * s.sign_multiplier) AS cy_val
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.cy_ytd_start AND w.cy_ytd_end
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.customer_code
            ),
            ly_cust AS (
                SELECT s.customer_code, SUM({col_expr} * s.sign_multiplier) AS ly_val
                FROM sales s, windows w
                WHERE s.sale_date BETWEEN w.ly_ytd_start AND w.ly_ytd_end
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.customer_code
            )
            SELECT 
                c.customer_name AS name,
                COALESCE(cy.cy_val, 0) AS cy_val,
                COALESCE(ly.ly_val, 0) AS ly_val
            FROM (
                SELECT customer_code, MAX(customer_name) AS customer_name
                FROM customers
                GROUP BY customer_code
            ) c
            LEFT JOIN cy_cust cy ON c.customer_code = cy.customer_code
            LEFT JOIN ly_cust ly ON c.customer_code = ly.customer_code
            WHERE COALESCE(cy.cy_val, 0) <> 0 OR COALESCE(ly.ly_val, 0) <> 0
            ORDER BY cy_val DESC
            LIMIT :limit;
        """)
    else:
        query = text(f"""
            WITH current_jc AS (
                SELECT 
                    jc_code,
                    financial_year AS cy_fy,
                    (financial_year - 10001) AS ly_fy,
                    start_date AS cy_start,
                    CURRENT_DATE AS cy_as_of,
                    (CURRENT_DATE - start_date) AS days_elapsed
                FROM jc_periods
                WHERE CURRENT_DATE BETWEEN start_date AND end_date
                LIMIT 1
            ),
            ly_window AS (
                SELECT 
                    p.start_date AS ly_start,
                    (p.start_date + c.days_elapsed) AS ly_cutoff
                FROM jc_periods p
                JOIN current_jc c ON p.jc_code = c.jc_code AND p.financial_year = c.ly_fy
            ),
            cy_cust AS (
                SELECT s.customer_code, SUM({col_expr} * s.sign_multiplier) AS cy_val
                FROM sales s, current_jc c
                WHERE s.sale_date BETWEEN c.cy_start AND c.cy_as_of
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.customer_code
            ),
            ly_cust AS (
                SELECT s.customer_code, SUM({col_expr} * s.sign_multiplier) AS ly_val
                FROM sales s, ly_window l
                WHERE s.sale_date BETWEEN l.ly_start AND l.ly_cutoff
                  AND s.customer_code <> '1001' AND s.item_code <> '8901326926543'
                GROUP BY s.customer_code
            )
            SELECT 
                c.customer_name AS name,
                COALESCE(cy.cy_val, 0) AS cy_val,
                COALESCE(ly.ly_val, 0) AS ly_val
            FROM (
                SELECT customer_code, MAX(customer_name) AS customer_name
                FROM customers
                GROUP BY customer_code
            ) c
            LEFT JOIN cy_cust cy ON c.customer_code = cy.customer_code
            LEFT JOIN ly_cust ly ON c.customer_code = ly.customer_code
            WHERE COALESCE(cy.cy_val, 0) <> 0 OR COALESCE(ly.ly_val, 0) <> 0
            ORDER BY cy_val DESC
            LIMIT :limit;
        """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"limit": limit})

    results = []
    for _, r in df.iterrows():
        cy = float(r["cy_val"])
        ly = float(r["ly_val"])
        pct = ((cy - ly) / ly * 100.0) if ly > 0 else (100.0 if cy > 0 else 0.0)
        results.append({
            "name": r["name"] or "Unknown Customer",
            "cy": cy,
            "ly": ly,
            "pct": round(pct, 1),
            "trend": "UP" if cy >= ly else "DOWN",
            "metric": metric,
            "scope": scope
        })
    return results