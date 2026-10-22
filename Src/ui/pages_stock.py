"""
Stock Position & Movement Analytics Report
Includes:
  - Current Stock Position & Excel Download
  - Movement Analysis (Opening, Purchases In, Returns In, Sales Out, Current Stock)
  - Slow-moving SKUs High in Stock
  - Order Bounced / Stock Shortages vs Sales Orders
"""

import io
import streamlit as st
import pandas as pd
from sqlalchemy import text
from ui.db_helper import get_engine
from ui.style_loader import load_css


def to_excel_buffer(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    """Helper to convert DataFrame to Excel bytes buffer with formatted headers."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name[:31]]
        header_fmt = workbook.add_format({
            "bold": True,
            "bg_color": "#1F2937",
            "font_color": "#FFFFFF",
            "border": 1
        })
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            col_len = max(len(str(value)), df[value].astype(str).str.len().max() if not df.empty else 0) + 3
            worksheet.set_column(col_num, col_num, min(col_len, 40))
    return output.getvalue()


def get_divisions(engine):
    """Fetch distinct divisions from items."""
    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                "SELECT DISTINCT division FROM items WHERE source_system = 'shoper' AND division IS NOT NULL ORDER BY division"
            ))
            divs = [row[0] for row in result]
            return divs if divs else ["SPM", "SPW", "Thermal", "KTH"]
    except Exception:
        return ["SPM", "SPW", "Thermal", "KTH"]


def get_jc_periods(engine):
    """Fetch all JC periods ordered by date descending."""
    try:
        with engine.begin() as conn:
            query = """
                SELECT 
                    jc_code || ' (' || financial_year || ')' AS display_label,
                    jc_code,
                    financial_year,
                    start_date,
                    end_date
                FROM jc_periods
                ORDER BY start_date DESC;
            """
            return pd.read_sql(text(query), conn)
    except Exception:
        return pd.DataFrame()


def show_stock_position():
    load_css()
    st.title("📦 Stock Inventory & Movement Intelligence")

    engine = get_engine()
    all_divisions = get_divisions(engine)

    # Global Top Filters
    col_div, col_style = st.columns([2, 2])
    with col_div:
        selected_divisions = st.multiselect("Divisions", all_divisions, default=all_divisions)
    with col_style:
        style_search = st.text_input("Filter SKU / Style Description", value="")

    if not selected_divisions:
        st.warning("Please select at least one division.")
        return

    # Tabs definition
    tab_curr, tab_movement, tab_slow, tab_bounced = st.tabs([
        "📊 Current Stock Position",
        "🔄 Stock Movement Analysis",
        "🐢 Slow Moving High Stock",
        "⚠️ Bounced / Shortage Orders"
    ])

# =========================================================================
    # TAB 1: CURRENT STOCK POSITION
    # =========================================================================
    with tab_curr:
        try:
            curr_query = """
                SELECT 
                    item_code,
                    item_desc,
                    category_1,
                    size,
                    stock_qty,
                    stock_value,
                    mrp,
                    current_cost,
                    division
                FROM items
                WHERE source_system = 'shoper'
                  AND stock_qty IS NOT NULL AND stock_qty <> 0
                  AND division = ANY(:divisions)
                  AND (item_desc ILIKE :style OR item_code ILIKE :style)
                ORDER BY stock_qty DESC, stock_value DESC;
            """
            with engine.begin() as conn:
                curr_df = pd.read_sql(
                    text(curr_query), 
                    conn, 
                    params={"divisions": selected_divisions, "style": f"%{style_search}%"}
                )

            if curr_df.empty:
                st.info("No items found matching the selected criteria.")
            else:
                # Top KPI Cards
                m1, m2, m3, m4, m5 = st.columns(5)
                total_skus = len(curr_df)
                total_qty = curr_df["stock_qty"].sum()
                total_val = curr_df["stock_value"].sum()
                zero_stock = (curr_df["stock_qty"] <= 0).sum()
                avg_cost = (total_val / total_qty) if total_qty > 0 else 0

                m1.metric("Total Active SKUs", f"{total_skus:,}")
                m2.metric("Total Stock Qty", f"{total_qty:,.0f} pcs")
                m3.metric("Total Stock Value", f"₹{total_val:,.0f}")
                m4.metric("Zero Stock SKUs", f"{zero_stock:,}")
                m5.metric("Avg Unit Cost", f"₹{avg_cost:,.2f}")

                st.markdown("---")

                # Friendly column mapping for displays and exports
                col_name_map = {
                    "item_code": "Item Code",
                    "item_desc": "Description",
                    "size": "Size",
                    "stock_qty": "Stock Qty",
                    "division": "Division",
                    "category_1": "Category",
                    "stock_value": "Stock Value (₹)",
                    "mrp": "MRP (₹)",
                    "current_cost": "Cost (₹)"
                }

                # Sales team curtailed list
                sales_cols = ["item_code", "item_desc", "size", "stock_qty", "division"]

                # Header & Export Action Row
                col_head, col_quick_btn, col_custom_exp = st.columns([2, 1.2, 1.2])

                with col_head:
                    st.subheader("SKU Stock Ledger")

                with col_quick_btn:
                    # 1. One-click curated export for Sales Reps
                    sales_df = (
                        curr_df[sales_cols]
                        .rename(columns=col_name_map)
                        .sort_values(by=["Division", "Description", "Size"])
                    )
                    sales_excel = to_excel_buffer(sales_df, sheet_name="Sales_Stock")
                    st.download_button(
                        label="📲 Download for Sales Reps",
                        data=sales_excel,
                        file_name="sales_stock_list.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="Curtailed list: Item Code, Description, Size, Qty, and Division",
                        use_container_width=True
                    )

                with col_custom_exp:
                    # 2. Popover for custom column selection
                    with st.popover("⚙️ Custom Export", use_container_width=True):
                        st.markdown("###### Select Columns to Export")
                        available_keys = list(col_name_map.keys())
                        default_selected = [col_name_map[k] for k in sales_cols]

                        selected_labels = st.multiselect(
                            "Columns",
                            options=[col_name_map[k] for k in available_keys],
                            default=default_selected,
                            key="stock_custom_cols_multiselect"
                        )

                        if selected_labels:
                            # Map friendly labels back to dataframe columns
                            reverse_map = {v: k for k, v in col_name_map.items()}
                            chosen_db_cols = [reverse_map[lbl] for lbl in selected_labels]

                            custom_df = (
                                curr_df[chosen_db_cols]
                                .rename(columns=col_name_map)
                                .sort_values(by=selected_labels[0] if selected_labels else None)
                            )
                            custom_excel = to_excel_buffer(custom_df, sheet_name="Custom_Stock")
                            st.download_button(
                                label="📥 Download Selected Columns",
                                data=custom_excel,
                                file_name="custom_stock_export.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True
                            )
                        else:
                            st.caption("Please select at least one column.")

                # Interactive Grid
                st.dataframe(
                    curr_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code", width="small"),
                        "item_desc": st.column_config.TextColumn("Description", width="large"),
                        "category_1": st.column_config.TextColumn("Category", width="small"),
                        "size": st.column_config.TextColumn("Size", width="small"),
                        "stock_qty": st.column_config.NumberColumn("Stock Qty", format="%d"),
                        "stock_value": st.column_config.NumberColumn("Stock Value (₹)", format="₹%d"),
                        "mrp": st.column_config.NumberColumn("MRP (₹)", format="₹%d"),
                        "current_cost": st.column_config.NumberColumn("Cost (₹)", format="₹%.2f"),
                        "division": st.column_config.TextColumn("Div", width="small")
                    }
                )
        except Exception as e:
            st.error(f"Error loading stock position: {e}")

    # =========================================================================
    # TAB 2: STOCK MOVEMENT ANALYSIS (Purchases In, Sales Out, Returns In)
    # =========================================================================
    with tab_movement:
        st.subheader("Period Movement Analysis (Inflows vs Outflows)")
        
        jc_df = get_jc_periods(engine)
        
        c_period_type, c_sel = st.columns([1, 2])
        with c_period_type:
            period_mode = st.radio("Select Period By", ["Journey Cycle (JC)", "Custom Date Range"], horizontal=True)

        if period_mode == "Journey Cycle (JC)" and not jc_df.empty:
            with c_sel:
                selected_jc_label = st.selectbox("Journey Cycle", jc_df["display_label"].tolist())
                selected_row = jc_df[jc_df["display_label"] == selected_jc_label].iloc[0]
                period_start = selected_row["start_date"]
                period_end = selected_row["end_date"]
        else:
            with c_sel:
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    period_start = st.date_input("From Date", pd.to_datetime("today").replace(day=1))
                with d_col2:
                    period_end = st.date_input("To Date", pd.to_datetime("today"))

        st.caption(f"Analyzing movements between **{period_start}** and **{period_end}**")

        try:
            # Movement SQL:
            # - Purchases in: entries from purchases in period
            # - Sales Returns in: sales with sign_multiplier = -1
            # - Sales out: sales with sign_multiplier = 1 (actual dispatch outflow)
            # - Net Sales = (Sales Out - Returns In)
            # - Subsequent Movements: between period_end and current date to reconstruct Opening & Period-End Stock
            movement_query = """
                WITH period_purchases AS (
                    SELECT 
                        item_code,
                        SUM(qty) AS purchase_qty,
                        SUM(net_value) AS purchase_val
                    FROM purchases
                    WHERE entry_date BETWEEN :p_start AND :p_end
                      AND division = ANY(:divisions)
                    GROUP BY item_code
                ),
                period_sales AS (
                    SELECT 
                        item_code,
                        SUM(CASE WHEN sign_multiplier = 1 THEN qty ELSE 0 END) AS gross_sales_qty,
                        SUM(CASE WHEN sign_multiplier = -1 THEN qty ELSE 0 END) AS sales_return_qty,
                        SUM(qty * sign_multiplier) AS net_sales_qty,
                        SUM(net_value * sign_multiplier) AS net_sales_val
                    FROM sales
                    WHERE sale_date BETWEEN :p_start AND :p_end
                      AND division = ANY(:divisions)
                      AND customer_code <> '1001'
                      AND item_code <> '8901326926543'
                    GROUP BY item_code
                ),
                post_period_purchases AS (
                    SELECT 
                        item_code,
                        SUM(qty) AS post_purch_qty
                    FROM purchases
                    WHERE entry_date > :p_end
                      AND division = ANY(:divisions)
                    GROUP BY item_code
                ),
                post_period_sales AS (
                    SELECT 
                        item_code,
                        SUM(qty * sign_multiplier) AS post_net_sales_qty
                    FROM sales
                    WHERE sale_date > :p_end
                      AND division = ANY(:divisions)
                      AND customer_code <> '1001'
                      AND item_code <> '8901326926543'
                    GROUP BY item_code
                )
                SELECT 
                    i.item_code,
                    i.item_desc,
                    i.category_1,
                    i.division,
                    -- Live current stock
                    COALESCE(i.stock_qty, 0) AS current_stock_qty,
                    -- Period movements
                    COALESCE(p.purchase_qty, 0) AS purchases_in_qty,
                    COALESCE(s.sales_return_qty, 0) AS returns_in_qty,
                    COALESCE(s.gross_sales_qty, 0) AS sales_out_qty,
                    COALESCE(s.net_sales_qty, 0) AS net_sales_qty,
                    -- Stock at Period End = Current Stock - (Purchases after period) + (Net Sales after period)
                    (
                        COALESCE(i.stock_qty, 0) 
                        - COALESCE(post_p.post_purch_qty, 0) 
                        + COALESCE(post_s.post_net_sales_qty, 0)
                    ) AS period_end_stock_qty,
                    -- Opening Stock = Period End Stock - Period Inflows + Period Outflows
                    (
                        (
                            COALESCE(i.stock_qty, 0) 
                            - COALESCE(post_p.post_purch_qty, 0) 
                            + COALESCE(post_s.post_net_sales_qty, 0)
                        )
                        - (COALESCE(p.purchase_qty, 0) + COALESCE(s.sales_return_qty, 0))
                        + COALESCE(s.gross_sales_qty, 0)
                    ) AS opening_stock_qty
                FROM items i
                LEFT JOIN period_purchases p ON i.item_code = p.item_code
                LEFT JOIN period_sales s ON i.item_code = s.item_code
                LEFT JOIN post_period_purchases post_p ON i.item_code = post_p.item_code
                LEFT JOIN post_period_sales post_s ON i.item_code = post_s.item_code
                WHERE i.source_system = 'shoper'
                  AND i.division = ANY(:divisions)
                  AND (i.item_desc ILIKE :style OR i.item_code ILIKE :style)
                  AND (
                      COALESCE(i.stock_qty, 0) <> 0 
                      OR COALESCE(p.purchase_qty, 0) <> 0 
                      OR COALESCE(s.gross_sales_qty, 0) <> 0
                  )
                ORDER BY purchases_in_qty DESC, sales_out_qty DESC;
            """
            with engine.begin() as conn:
                m_df = pd.read_sql(
                    text(movement_query),
                    conn,
                    params={
                        "p_start": period_start,
                        "p_end": period_end,
                        "divisions": selected_divisions,
                        "style": f"%{style_search}%"
                    }
                )

            if m_df.empty:
                st.info("No movement recorded for the selected window and filters.")
            else:
                # Summary KPIs
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Total Purchases In", f"{m_df['purchases_in_qty'].sum():,.0f} pcs")
                k2.metric("Sales Returns In", f"{m_df['returns_in_qty'].sum():,.0f} pcs")
                k3.metric("Gross Sales Out", f"{m_df['sales_out_qty'].sum():,.0f} pcs")
                k4.metric("Net Sales Out", f"{m_df['net_sales_qty'].sum():,.0f} pcs")

                st.markdown("---")
                
                col_t, col_btn = st.columns([3, 1])
                with col_t:
                    st.write("📋 **SKU Movement Register (Open ➔ Inflows ➔ Outflows ➔ Current)**")
                with col_btn:
                    m_excel = to_excel_buffer(m_df, sheet_name="Stock_Movement")
                    st.download_button(
                        label="📥 Download Movement Excel",
                        data=m_excel,
                        file_name=f"stock_movement_{period_start}_to_{period_end}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                st.dataframe(
                    m_df[[
                        "item_code", "item_desc", "category_1", "division",
                        "opening_stock_qty", "purchases_in_qty", "returns_in_qty", 
                        "sales_out_qty", "net_sales_qty", "period_end_stock_qty", "current_stock_qty"
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code", width="small"),
                        "item_desc": st.column_config.TextColumn("Description", width="large"),
                        "category_1": st.column_config.TextColumn("Category", width="small"),
                        "division": st.column_config.TextColumn("Div", width="small"),
                        "opening_stock_qty": st.column_config.NumberColumn("Opening", format="%d"),
                        "purchases_in_qty": st.column_config.NumberColumn("Purch In (+)", format="%d"),
                        "returns_in_qty": st.column_config.NumberColumn("Returns (+)", format="%d"),
                        "sales_out_qty": st.column_config.NumberColumn("Sales Out (-)", format="%d"),
                        "net_sales_qty": st.column_config.NumberColumn("Net Sales", format="%d"),
                        "period_end_stock_qty": st.column_config.NumberColumn("Period End", format="%d"),
                        "current_stock_qty": st.column_config.NumberColumn("Live Current Stock", format="%d")
                    }
                )
        except Exception as e:
            st.error(f"Error loading stock movement: {e}")

    # =========================================================================
    # TAB 3: SLOW MOVING SKUs HIGH IN STOCK
    # =========================================================================
    with tab_slow:
        st.subheader("Slow Moving SKUs with High Stock Exposure")
        st.caption("Identifies SKUs with high inventory holding where sales velocity is critically low or zero in the past 60/90 days.")

        c_days, c_min_stock = st.columns(2)
        with c_days:
            lookback_days = st.selectbox("Sales Velocity Window", [30, 60, 90, 180], index=1)
        with c_min_stock:
            min_stock_thresh = st.number_input("Minimum Stock Qty Threshold", min_value=1, value=20, step=5)

        try:
            slow_query = f"""
                WITH recent_sales AS (
                    SELECT 
                        s.item_code,
                        SUM(s.qty * s.sign_multiplier) AS sold_qty,
                        SUM(s.net_value * s.sign_multiplier) AS sold_val,
                        MAX(s.sale_date) AS last_sold_date
                    FROM sales s
                    WHERE s.sale_date >= CURRENT_DATE - INTERVAL '{lookback_days} days'
                      AND s.division = ANY(:divisions)
                      AND s.customer_code <> '1001'
                      AND s.item_code <> '8901326926543'
                    GROUP BY s.item_code
                ),
                last_receipt AS (
                    SELECT 
                        item_code,
                        MAX(entry_date) AS last_purchase_date
                    FROM purchases
                    WHERE division = ANY(:divisions)
                    GROUP BY item_code
                )
                SELECT 
                    i.item_code,
                    i.item_desc,
                    i.category_1,
                    i.division,
                    i.stock_qty,
                    i.stock_value,
                    i.current_cost,
                    COALESCE(rs.sold_qty, 0) AS sales_qty_in_period,
                    rs.last_sold_date,
                    lr.last_purchase_date,
                    CASE 
                        WHEN COALESCE(rs.sold_qty, 0) <= 0 THEN 'Zero Sales (Dead)'
                        WHEN COALESCE(rs.sold_qty, 0) < (i.stock_qty * 0.10) THEN 'Low Velocity (<10%)'
                        ELSE 'Moderate'
                    END AS inventory_status
                FROM items i
                LEFT JOIN recent_sales rs ON i.item_code = rs.item_code
                LEFT JOIN last_receipt lr ON i.item_code = lr.item_code
                WHERE i.source_system = 'shoper'
                  AND i.division = ANY(:divisions)
                  AND i.stock_qty >= :min_stock
                  AND (COALESCE(rs.sold_qty, 0) <= (i.stock_qty * 0.20))
                  AND (i.item_desc ILIKE :style OR i.item_code ILIKE :style)
                ORDER BY i.stock_value DESC, i.stock_qty DESC;
            """
            with engine.begin() as conn:
                slow_df = pd.read_sql(
                    text(slow_query),
                    conn,
                    params={
                        "divisions": selected_divisions,
                        "min_stock": min_stock_thresh,
                        "style": f"%{style_search}%"
                    }
                )

            if slow_df.empty:
                st.success("No critical slow-moving inventory detected for the selected threshold!")
            else:
                sm1, sm2, sm3 = st.columns(3)
                sm1.metric("Identified Slow SKUs", len(slow_df))
                sm2.metric("Trapped Stock Qty", f"{slow_df['stock_qty'].sum():,.0f} pcs")
                sm3.metric("Trapped Capital", f"₹{slow_df['stock_value'].sum():,.0f}")

                st.markdown("---")

                col_st, col_sbtn = st.columns([3, 1])
                with col_st:
                    st.write("🚨 **High Capital / Low Turnover SKUs**")
                with col_sbtn:
                    slow_excel = to_excel_buffer(slow_df, sheet_name="Slow_Moving_Stock")
                    st.download_button(
                        label="📥 Download Slow Stock Excel",
                        data=slow_excel,
                        file_name=f"slow_moving_stock_{lookback_days}d.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                st.dataframe(
                    slow_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code", width="small"),
                        "item_desc": st.column_config.TextColumn("Description", width="large"),
                        "category_1": st.column_config.TextColumn("Category", width="small"),
                        "division": st.column_config.TextColumn("Div", width="small"),
                        "stock_qty": st.column_config.NumberColumn("Current Stock", format="%d"),
                        "stock_value": st.column_config.NumberColumn("Trapped Value (₹)", format="₹%d"),
                        "sales_qty_in_period": st.column_config.NumberColumn(f"Sold ({lookback_days}d)", format="%d"),
                        "inventory_status": st.column_config.TextColumn("Status", width="medium"),
                        "last_sold_date": st.column_config.DateColumn("Last Sale Date", format="YYYY-MM-DD"),
                        "last_purchase_date": st.column_config.DateColumn("Last Purchase Date", format="YYYY-MM-DD")
                    }
                )
        except Exception as e:
            st.error(f"Error calculating slow-moving inventory: {e}")

    # =========================================================================
    # TAB 4: BOUNCED ORDERS & STOCK SHORTAGES
    # =========================================================================
    with tab_bounced:
        st.subheader("Bounced Orders / Stock Shortage Register")
        st.caption("Orders where items have pending order quantity but available stock is zero or insufficient, with visibility into recent replenishment.")

        try:
            bounced_query = """
                WITH pending_orders AS (
                    SELECT 
                        so.item_code,
                        so.division,
                        COUNT(DISTINCT so.order_id) AS pending_orders_count,
                        COUNT(DISTINCT so.customer_code) AS affected_customers_count,
                        SUM(so.order_qty) AS total_order_qty,
                        SUM(so.billed_qty) AS billed_qty,
                        SUM(COALESCE(so.pending_qty, so.order_qty - so.billed_qty)) AS pending_qty,
                        MIN(so.order_date) AS oldest_pending_date,
                        MAX(so.order_date) AS newest_order_date
                    FROM sales_orders so
                    WHERE so.division = ANY(:divisions)
                      AND (COALESCE(so.pending_qty, so.order_qty - so.billed_qty) > 0)
                    GROUP BY so.item_code, so.division
                ),
                latest_purch AS (
                    SELECT 
                        item_code,
                        MAX(entry_date) AS last_receipt_date,
                        SUM(qty) AS last_30d_received_qty
                    FROM purchases
                    WHERE entry_date >= CURRENT_DATE - INTERVAL '30 days'
                      AND division = ANY(:divisions)
                    GROUP BY item_code
                )
                SELECT 
                    po.item_code,
                    i.item_desc,
                    i.category_1,
                    po.division,
                    po.pending_orders_count,
                    po.affected_customers_count,
                    po.pending_qty,
                    COALESCE(i.stock_qty, 0) AS current_stock_qty,
                    (COALESCE(i.stock_qty, 0) - po.pending_qty) AS stock_gap_qty,
                    lp.last_receipt_date,
                    COALESCE(lp.last_30d_received_qty, 0) AS last_30d_purchase_qty,
                    po.oldest_pending_date
                FROM pending_orders po
                JOIN items i 
                  ON po.item_code = i.item_code 
                 AND po.division = i.division
                LEFT JOIN latest_purch lp 
                  ON po.item_code = lp.item_code
                WHERE (i.stock_qty <= 0 OR i.stock_qty < po.pending_qty)
                  AND (i.item_desc ILIKE :style OR i.item_code ILIKE :style)
                ORDER BY stock_gap_qty ASC, po.pending_qty DESC;
            """
            with engine.begin() as conn:
                bounced_df = pd.read_sql(
                    text(bounced_query),
                    conn,
                    params={
                        "divisions": selected_divisions,
                        "style": f"%{style_search}%"
                    }
                )

            if bounced_df.empty:
                st.success("No pending order shortages found! Current inventory fully covers pending orders.")
            else:
                b1, b2, b3 = st.columns(3)
                total_short_skus = len(bounced_df)
                total_pending_units = bounced_df["pending_qty"].sum()
                total_deficit = abs(bounced_df["stock_gap_qty"].clip(upper=0).sum())

                b1.metric("Shortage SKUs", f"{total_short_skus:,}")
                b2.metric("Pending Customer Orders", f"{total_pending_units:,.0f} pcs")
                b3.metric("Net Supply Deficit", f"{total_deficit:,.0f} pcs", delta_color="inverse")

                st.markdown("---")

                col_bt, col_bbtn = st.columns([3, 1])
                with col_bt:
                    st.write("📋 **Actionable Stock Shortage & Purchase Status**")
                with col_bbtn:
                    bounced_excel = to_excel_buffer(bounced_df, sheet_name="Bounced_Shortage_Orders")
                    st.download_button(
                        label="📥 Download Shortage Excel",
                        data=bounced_excel,
                        file_name="order_shortage_bounced.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                st.dataframe(
                    bounced_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code", width="small"),
                        "item_desc": st.column_config.TextColumn("Description", width="large"),
                        "category_1": st.column_config.TextColumn("Category", width="small"),
                        "division": st.column_config.TextColumn("Div", width="small"),
                        "pending_orders_count": st.column_config.NumberColumn("Orders", format="%d"),
                        "affected_customers_count": st.column_config.NumberColumn("Parties", format="%d"),
                        "pending_qty": st.column_config.NumberColumn("Demand (Pending)", format="%d"),
                        "current_stock_qty": st.column_config.NumberColumn("Stock Qty", format="%d"),
                        "stock_gap_qty": st.column_config.NumberColumn("Shortage Gap", format="%d"),
                        "last_receipt_date": st.column_config.DateColumn("Last Inward Date", format="YYYY-MM-DD"),
                        "last_30d_purchase_qty": st.column_config.NumberColumn("30d Receipts", format="%d"),
                        "oldest_pending_date": st.column_config.DateColumn("Oldest Order", format="YYYY-MM-DD")
                    }
                )
        except Exception as e:
            st.error(f"Error loading shortage and bounced order analytics: {e}")


if __name__ == "__main__":
    show_stock_position()