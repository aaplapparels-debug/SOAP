"""Sales 360° Analysis Dashboard"""

import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from config_loader import load_config
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine():
    config = load_config()
    return create_engine(config["postgres"]["connection_string"])


def format_inr(val, decimals=0):
    if pd.isna(val) or val is None:
        return "₹0"
    if decimals > 0:
        return f"₹{val:,.{decimals}f}"
    return f"₹{val:,.0f}"


def get_jc_periods(engine):
    query = """
    SELECT jc_code, financial_year, start_date, end_date
    FROM jc_periods
    ORDER BY financial_year DESC, start_date ASC
    """
    try:
        with engine.begin() as conn:
            df = pd.read_sql(text(query), conn)
            df["start_date"] = pd.to_datetime(df["start_date"]).dt.date
            df["end_date"] = pd.to_datetime(df["end_date"]).dt.date
            return df
    except Exception:
        return pd.DataFrame()


def get_customers(engine):
    query = """
    SELECT DISTINCT customer_code, customer_name
    FROM customers
    WHERE source_system = 'shoper'
    ORDER BY customer_name
    """
    try:
        with engine.begin() as conn:
            return pd.read_sql(text(query), conn)
    except Exception:
        return pd.DataFrame()


def show_sales_360():
    st.title("🔄 Sales 360° Customer & Item Intelligence")

    engine = get_engine()
    periods_df = get_jc_periods(engine)
    cust_df = get_customers(engine)

    if periods_df.empty:
        st.warning("No JC periods configured in the database.")
        return

    # --- Top Filter Bar ---
    st.markdown("---")
    f_col1, f_col2, f_col3 ,f_col4= st.columns([1, 1, 1,1.2])

    # 1. Customer Selector
    customer_options = ["All Parties"]
    cust_map = {}
    if not cust_df.empty:
        for _, row in cust_df.iterrows():
            label = f"{row['customer_name']} ({row['customer_code']})"
            customer_options.append(label)
            cust_map[label] = {
                "code": row["customer_code"],
                "name": row["customer_name"],
            }

    with f_col1:
        selected_cust_label = st.selectbox(
            "Select Customer", options=customer_options, index=0
        )

    # 2. Financial Year & JC Month Selector
    available_fys = sorted(periods_df["financial_year"].unique(), reverse=True)
    with f_col2:
        selected_fy = st.selectbox("Financial Year", options=available_fys, index=0)

    fy_periods = periods_df[periods_df["financial_year"] == selected_fy]
    today = datetime.date.today()
    active_match = fy_periods[
        (fy_periods["start_date"] <= today) & (today <= fy_periods["end_date"])
    ]
    default_jc_idx = (
        int(active_match.index[0] - fy_periods.index[0])
        if not active_match.empty
        else (len(fy_periods) - 1)
    )

    with f_col3:
        selected_jc = st.selectbox(
            "JC Month",
            options=fy_periods["jc_code"].tolist(),
            index=default_jc_idx,
        )

    with f_col4:
        st.markdown(
            "<p style='font-size:14px; font-weight:500; margin-bottom:4px;align: center;'>Account Health</p>",
            unsafe_allow_html=True,
        )
        health_placeholder = st.empty()

    # Determine Date Boundaries for Current JC and Last Year (LY) Same JC
    curr_period = fy_periods[fy_periods["jc_code"] == selected_jc].iloc[0]
    curr_start, curr_end = curr_period["start_date"], curr_period["end_date"]

    ly_fy = selected_fy - 10001  # e.g., 20262027 -> 20252026
    ly_match = periods_df[
        (periods_df["financial_year"] == ly_fy)
        & (periods_df["jc_code"] == selected_jc)
    ]
    if not ly_match.empty:
        ly_start, ly_end = (
            ly_match.iloc[0]["start_date"],
            ly_match.iloc[0]["end_date"],
        )
    else:
        # Approximate 1-year shift fallback
        ly_start = curr_start - datetime.timedelta(days=364)
        ly_end = curr_end - datetime.timedelta(days=364)

    st.caption(
        f"📅 **Current JC ({selected_jc}):** `{curr_start}` to `{curr_end}` | "
        f"📅 **LY Same JC ({selected_jc}):** `{ly_start}` to `{ly_end}`"
    )
    st.markdown("---")

    cust_code = (
        cust_map[selected_cust_label]["code"]
        if selected_cust_label != "All Parties"
        else None
    )
    cust_name = (
        cust_map[selected_cust_label]["name"]
        if selected_cust_label != "All Parties"
        else None
    )

    # ==========================================
    # QUERIES
    # ==========================================

    # 1 & 2. Sales: Current JC vs LY JC (Summary & Article-wise)
    sales_query = """
    SELECT 
        s.item_code,
        COALESCE(i.item_desc, s.item_code) AS item_desc,
        i.category_1,
        SUM(CASE WHEN s.sale_date BETWEEN :curr_start AND :curr_end THEN s.qty * s.sign_multiplier ELSE 0 END) AS curr_qty,
        SUM(CASE WHEN s.sale_date BETWEEN :curr_start AND :curr_end THEN s.net_value * s.sign_multiplier ELSE 0 END) AS curr_val,
        SUM(CASE WHEN s.sale_date BETWEEN :ly_start AND :ly_end THEN s.qty * s.sign_multiplier ELSE 0 END) AS ly_qty,
        SUM(CASE WHEN s.sale_date BETWEEN :ly_start AND :ly_end THEN s.net_value * s.sign_multiplier ELSE 0 END) AS ly_val
    FROM sales s
    LEFT JOIN items i 
        ON s.item_code = i.item_code AND s.division = i.division AND i.source_system = 'shoper'
    WHERE s.source_system = 'shoper'
      AND s.customer_code <> '1001'
      AND s.item_code <> '8901326926543'
      AND (
          (s.sale_date BETWEEN :curr_start AND :curr_end) OR 
          (s.sale_date BETWEEN :ly_start AND :ly_end)
      )
      AND (:cust_code IS NULL OR s.customer_code = :cust_code)
    GROUP BY s.item_code, COALESCE(i.item_desc, s.item_code), i.category_1
    """

    # 3 & 4. Orders & Fill Rate in Current JC
    orders_query = """
    SELECT 
        o.item_code,
        COALESCE(i.item_desc, o.item_code) AS item_desc,
        SUM(o.order_qty) AS order_qty,
        SUM(o.billed_qty) AS billed_qty,
        SUM(o.pending_qty) AS pending_qty
    FROM sales_orders o
    LEFT JOIN items i 
        ON o.item_code = i.item_code AND o.division = i.division AND i.source_system = 'shoper'
    WHERE o.source_system = 'shoper'
      AND o.order_date BETWEEN :curr_start AND :curr_end
      AND (:cust_code IS NULL OR o.customer_code = :cust_code)
      AND o.item_code <> '8901326926543'
    GROUP BY o.item_code, COALESCE(i.item_desc, o.item_code)
    """

    # 5. Receipts in Current JC
    receipts_query = """
    SELECT COALESCE(SUM(amount), 0) AS total_receipts
    FROM receipts
    WHERE (:full_name IS NULL OR customer_name = :full_name)
    AND((receipt_date BETWEEN :curr_start AND CURRENT_DATE AND mode_of_payment = 'Cash') 
    OR (instrument_date IS NOT NULL AND TO_DATE(instrument_date, 'YYYYMMDD') <= CURRENT_DATE and TO_DATE(instrument_date, 'YYYYMMDD') >= :curr_start))  
    """

    pdc_query = """
    SELECT COALESCE(SUM(amount), 0) AS total_pdc
    FROM receipts
    WHERE (:full_name IS NULL OR customer_name = :full_name)
    AND instrument_date IS NOT NULL
    AND TO_DATE(instrument_date, 'YYYYMMDD') > CURRENT_DATE
    """

    # 6. Current Outstanding & Aging Buckets
    outstanding_query = """
    SELECT 
        customer_name,
        invoice_reference,
        invoice_date,
        pending_amount,
        (CURRENT_DATE - invoice_date) AS days_outstanding
    FROM outstanding_debtors
    WHERE (:full_name IS NULL OR customer_name = :full_name)
    """
    clean_code = cust_code.strip() if cust_code else None
    clean_name = cust_name.strip() if cust_name else None
    params = {
        "curr_start": curr_start,
        "curr_end": curr_end,
        "ly_start": ly_start,
        "ly_end": ly_end,
        "cust_code": cust_code,
        "cust_name": cust_name,
        "full_name" : f"{clean_code}_{clean_name}" if clean_code and clean_name else None,
        "curr_start_ymd": curr_start.strftime("%Y%m%d"),
        "today_ymd": datetime.date.today().strftime("%Y%m%d"),}

    try:
        #st.warning(f"Python generated full_name: `{params['full_name']}`")
        with engine.begin() as conn:
            sales_df = pd.read_sql(text(sales_query), conn, params=params)
            orders_df = pd.read_sql(text(orders_query), conn, params=params)
            receipts_val = (
                pd.read_sql(text(receipts_query), conn, params=params)
                .iloc[0]["total_receipts"]
            )
            pdc_val = (
                pd.read_sql(text(pdc_query), conn, params=params)
                .iloc[0]["total_pdc"]
            )
            out_df = pd.read_sql(text(outstanding_query), conn, params=params)
            curr_fy_year = str(selected_fy)[:4]
            ly_fy_year = str(ly_fy)[:4]
            ytd_df = pd.read_sql(
                text(sales_query),
                conn,
                params={
                    **params,
                    "curr_start": f"{curr_fy_year}-04-01",
                    "curr_end": curr_end,
                    "ly_start": f"{ly_fy_year}-04-01",
                    "ly_end": ly_end,
                },
            )
        # ==========================================
        # ACCOUNT HEALTH EVALUATION & DISPLAY
        # ==========================================
        if not out_df.empty:
            out_df["days_outstanding"] = pd.to_numeric(
                out_df["days_outstanding"], errors="coerce"
            ).fillna(0)
            overdue_90_df = out_df[out_df["days_outstanding"] > 90]
            overdue_90_val = overdue_90_df["pending_amount"].sum()
        else:
            overdue_90_val = 0

        with health_placeholder.container():
            if selected_cust_label == "All Parties":
                if overdue_90_val > 0:
                    st.markdown(
                        f"""
                        <div style="border: 2px solid #dc3545; background-color: #fff5f5; border-radius: 6px; padding: 4px; text-align: center;">
                            <div style="color: #dc3545; font-size: 11px; font-weight: 700;">⚠️ PORTFOLIO OVERDUE</div>
                            <div style="background-color: #dc3545; color: white; font-size: 10px; font-weight: 700; border-radius: 3px; padding: 1px 4px; margin-top: 2px;">
                                {format_inr(overdue_90_val)} > 90D
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div style="border: 1px solid #198754; background-color: #f4fbf7; border-radius: 6px; padding: 6px; text-align: center;">
                            <span style="color: #198754; font-size: 11px; font-weight: 700;">✅ ALL CLEAR</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                if overdue_90_val > 0:
                    st.markdown(
                        f"""
                        <div style="border: 2px dashed #dc3545; background-color: #fff0f0; border-radius: 6px; padding: 4px; text-align: center; box-shadow: 0 0 5px rgba(220,53,69,0.2);">
                            <div style="color: #dc3545; font-weight: 800; font-size: 11px; letter-spacing: 0.5px;">⚠️ ILL HEALTH</div>
                            <div style="background-color: #dc3545; color: white; font-size: 11px; font-weight: 800; padding: 2px 5px; border-radius: 4px; margin-top: 2px; letter-spacing: 0.5px;">
                                ⛔ ADVISE: STOP BILL
                            </div>
                            <div style="color: #721c24; font-size: 10px; font-weight: 600; margin-top: 2px;">
                                {format_inr(overdue_90_val)} Overdue (>90D)
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div style="border: 1px solid #198754; background-color: #f4fbf7; border-radius: 6px; padding: 6px 4px; text-align: center;">
                            <div style="color: #198754; font-weight: 800; font-size: 11px;">✅ HEALTHY</div>
                            <div style="background-color: #198754; color: white; font-size: 10px; font-weight: 700; padding: 2px 4px; border-radius: 3px; margin-top: 2px;">
                                REGULAR BILLING
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )        
        # ==========================================
        # SECTION 1 & 4: TOP KPI CARDS
        # ==========================================
        curr_total_qty = sales_df["curr_qty"].sum()
        curr_total_val = sales_df["curr_val"].sum()
        ly_total_qty = sales_df["ly_qty"].sum()
        ly_total_val = sales_df["ly_val"].sum()
        ytd_total_qty = ytd_df['curr_qty'].sum()
        ytd_total_val = ytd_df["curr_val"].sum()
        ytd_ly_total_qty = ytd_df['ly_qty'].sum()
        ytd_ly_total_val = ytd_df["ly_val"].sum()

        qty_growth = (
            ((curr_total_qty - ly_total_qty) / ly_total_qty * 100)
            if ly_total_qty > 0
            else 0.0
        )
        val_growth = (
            ((curr_total_val - ly_total_val) / ly_total_val * 100)
            if ly_total_val > 0
            else 0.0
        )
        ytd_qty_growth = (
            ((ytd_total_qty - ytd_ly_total_qty) / ytd_ly_total_qty * 100)
            if ytd_ly_total_qty > 0
            else 0.0    
        )
        ytd_val_growth = (
            ((ytd_total_val - ytd_ly_total_val) / ytd_ly_total_val * 100)
            if ytd_ly_total_val > 0
            else 0.0
        )

        total_ordered = orders_df["order_qty"].sum()
        total_billed = sales_df["curr_qty"].sum()
        total_pending_order = orders_df["pending_qty"].sum()
        fill_rate_pct = (
            (total_billed / total_ordered * 100) if total_ordered > 0 else 0.0
        )
        a1, a2, a3, a4, a5, a6 = st.columns(6)  

        with a1:
            st.metric("YTD Sales: (Pcs)", 
                    f"{ytd_total_qty:,.0f}",
                    delta=f"{ytd_qty_growth:+.1f}% vs LY",
            )
            st.caption(f"LY: {ytd_ly_total_qty:,.0f} Pcs")

        with a2:
            st.metric("YTD Sales: (Value)", 
                    f"{ytd_total_val:,.0f}",
                    delta=f"{ytd_val_growth:+.1f}% vs LY",
            )
            st.caption(f"LY: {ytd_ly_total_val:,.0f}")
        with a3:
            st.metric(
                "JC Sales (Pcs)",
                f"{curr_total_qty:,.0f}",
                delta=f"{qty_growth:+.1f}% vs LY",
            )
            st.caption(f"LY: {ly_total_qty:,.0f} Pcs")
        with a4:
            st.metric(
                "JC Sales (Value)",
                format_inr(curr_total_val),
                delta=f"{val_growth:+.1f}% vs LY",
            )
            st.caption(f"LY: {format_inr(ly_total_val)}")

        with a5:
            collection_eff = (
                (receipts_val / curr_total_val * 100)
                if curr_total_val > 0
                else 0.0
            )
            st.metric(
                "JC Receipts",
                format_inr(receipts_val),
                delta=f"{collection_eff:.1f}% of Sales",
            )
            st.caption(curr_start)  
            st.caption(f"Sales: {format_inr(curr_total_val)}")
        with a6:
            total_due = out_df["pending_amount"].sum()
            st.metric("Total Outstanding", format_inr(total_due))
            st.metric("PDC:", format_inr(pdc_val))
            st.caption(f"Total Pending Bills: {len(out_df):,}")

        st.markdown("---")

        k1, k2 = st.columns(2)

        #with k3:
        #    st.metric(
        #        "Fill Rate %",
        #        f"{fill_rate_pct:.1f}%",
        #        delta=f"{total_billed:,.0f} / {total_ordered:,.0f} Pcs",
        #    )
        #    st.caption(f"Pending: {total_pending_order:,.0f} Pcs")


        # ==========================================
        # SECTION 5 & 6: CASHFLOW & AGING VISUALS
        # ==========================================
        r_col1, r_col2 = st.columns([1, 1.2])

        with r_col1:
            st.subheader("💵 Cashflow: Sales vs Receipts")
            cf_fig = go.Figure(
                data=[
                    go.Bar(
                        name="Billed Sales",
                        x=["Current JC"],
                        y=[curr_total_val],
                        text=[format_inr(curr_total_val)],
                        textposition="auto",
                        marker_color="#0d6efd",
                    ),
                    go.Bar(
                        name="Receipts / Collections",
                        x=["Current JC"],
                        y=[receipts_val],
                        text=[format_inr(receipts_val)],
                        textposition="auto",
                        marker_color="#198754",
                    ),
                ]
            )
            cf_fig.update_layout(
                barmode="group",
                height=240,
                margin=dict(l=10, r=10, t=20, b=10),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                ),
            )
            st.plotly_chart(cf_fig, use_container_width=True)

        with r_col2:
            st.subheader("📊 Outstanding Aging Breakdown")
            if not out_df.empty:
                out_df["days_outstanding"] = pd.to_numeric(
                    out_df["days_outstanding"], errors="coerce"
                ).fillna(0)

                def get_bucket(d):
                    if d > 90:
                        return "90+ Days"
                    elif d > 60:
                        return "61-90 Days"
                    elif d > 30:
                        return "31-60 Days"
                    else:
                        return "1-30 Days"

                out_df["Bucket"] = out_df["days_outstanding"].apply(get_bucket)
                bucket_order = ["1-30 Days", "31-60 Days", "61-90 Days", "90+ Days"]

                aging_grp = (
                    out_df.groupby("Bucket")
                    .agg(Value=("pending_amount", "sum"), Bills=("invoice_reference", "count"))
                    .reindex(bucket_order, fill_value=0)
                    .reset_index()
                )

                aging_grp["Value_Fmt"] = aging_grp["Value"].apply(format_inr)

                ag_fig = px.bar(
                    aging_grp,
                    x="Bucket",
                    y="Value",
                    text="Value_Fmt",
                    color="Bucket",
                    color_discrete_map={
                        "1-30 Days": "#198754",
                        "31-60 Days": "#0dcaf0",
                        "61-90 Days": "#ffc107",
                        "90+ Days": "#dc3545",
                    },
                )
                ag_fig.update_traces(textposition="auto")
                ag_fig.update_layout(
                    height=240,
                    margin=dict(l=10, r=10, t=20, b=10),
                    showlegend=False,
                    xaxis_title=None,
                    yaxis_title=None,
                )
                st.plotly_chart(ag_fig, use_container_width=True)
            else:
                st.success("🎉 No outstanding balance found.")

        st.markdown("---")

        # ==========================================
        # SECTION 2 & 3: DRILL-DOWN TABLES (TABS)
        # ==========================================
        tab_jc, tab_orders, tab_outstanding = st.tabs(
            [
                "📦 Article-wise JC Comparison (Current vs LY)",
                "⏳ Order Pendency & Fill Rate",
                "📋 Outstanding Bill Details",
            ]
        )

        # Tab 1: Current vs LY JC Article Details
        with tab_jc:
            if not sales_df.empty:
                art_df = sales_df.copy()
                art_df["Qty_Growth_%"] = art_df.apply(
                    lambda r: f"{((r['curr_qty'] - r['ly_qty']) / r['ly_qty'] * 100):+.1f}%"
                    if r["ly_qty"] > 0
                    else ("+100%" if r["curr_qty"] > 0 else "0.0%"),
                    axis=1,
                )
                art_df["curr_val_fmt"] = art_df["curr_val"].apply(format_inr)
                art_df["ly_val_fmt"] = art_df["ly_val"].apply(format_inr)

                st.dataframe(
                    art_df[
                        [
                            "item_code",
                            "item_desc",
                            "curr_qty",
                            "ly_qty",
                            "Qty_Growth_%",
                            "curr_val_fmt",
                            "ly_val_fmt",
                        ]
                    ].sort_values(by="curr_qty", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code"),
                        "item_desc": st.column_config.TextColumn("Description"),
                        "curr_qty": st.column_config.NumberColumn("Current JC Pcs", format="%d"),
                        "ly_qty": st.column_config.NumberColumn("LY JC Pcs", format="%d"),
                        "Qty_Growth_%": st.column_config.TextColumn("Qty Growth %"),
                        "curr_val_fmt": st.column_config.TextColumn("Current Value"),
                        "ly_val_fmt": st.column_config.TextColumn("LY Value"),
                    },
                )
            else:
                st.info("No sales records found for this period.")

        # Tab 2: Order Pendency & Article Fill Rate
        with tab_orders:
            if not orders_df.empty:
                ord_view = orders_df.copy()
                ord_view["Fill_%"] = ord_view.apply(
                    lambda r: f"{(r['billed_qty'] / r['order_qty'] * 100):.1f}%"
                    if r["order_qty"] > 0
                    else "0.0%",
                    axis=1,
                )
                st.dataframe(
                    ord_view[
                        [
                            "item_code",
                            "item_desc",
                            "order_qty",
                            "billed_qty",
                            "pending_qty",
                            "Fill_%",
                        ]
                    ].sort_values(by="pending_qty", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": st.column_config.TextColumn("Item Code"),
                        "item_desc": st.column_config.TextColumn("Description"),
                        "order_qty": st.column_config.NumberColumn("Order Qty", format="%d"),
                        "billed_qty": st.column_config.NumberColumn("Billed Qty", format="%d"),
                        "pending_qty": st.column_config.NumberColumn("Pending Qty", format="%d"),
                        "Fill_%": st.column_config.TextColumn("Fill Rate %"),
                    },
                )
            else:
                st.info("No orders placed during this JC period.")

        # Tab 3: Detailed Outstanding Invoices
        with tab_outstanding:
            if not out_df.empty:
                disp_out = out_df.copy()
                disp_out["pending_amount_fmt"] = disp_out["pending_amount"].apply(format_inr)
                disp_out["invoice_date"] = pd.to_datetime(
                    disp_out["invoice_date"]
                ).dt.strftime("%d-%b-%Y")

                st.dataframe(
                    disp_out[
                        [
                            "customer_name",
                            "invoice_reference",
                            "invoice_date",
                            "days_outstanding",
                            "Bucket",
                            "pending_amount_fmt",
                        ]
                    ].sort_values(by="days_outstanding", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "customer_name": st.column_config.TextColumn("Customer"),
                        "invoice_reference": st.column_config.TextColumn("Invoice Ref"),
                        "invoice_date": st.column_config.TextColumn("Invoice Date"),
                        "days_outstanding": st.column_config.NumberColumn("Days Due", format="%d"),
                        "Bucket": st.column_config.TextColumn("Aging Bucket"),
                        "pending_amount_fmt": st.column_config.TextColumn("Pending Amount"),
                    },
                )
            else:
                st.info("No pending invoices.")

    except Exception as e:
        st.error(f"Error compiling Sales 360° analytics: {e}")


if __name__ == "__main__":
    show_sales_360()