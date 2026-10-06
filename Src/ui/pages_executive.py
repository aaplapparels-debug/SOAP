"""Executive Dashboard - High Level Overview"""

from config_loader import load_config
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import streamlit as st


from ui.db_helper import get_engine


def format_inr(val):
    """Format numeric values into standard Indian numbering (Cr, L, or K)."""
    if val is None:
        return "₹0"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 10000000:
        return f"{sign}₹{abs_val / 10000000:.2f} Cr"
    elif abs_val >= 100000:
        return f"{sign}₹{abs_val / 100000:.2f} L"
    elif abs_val >= 1000:
        return f"{sign}₹{abs_val / 1000:.1f} K"
    else:
        return f"{sign}₹{abs_val:,.0f}"


def show_executive_dashboard():
    from ui.style_loader import load_css
    load_css()
    st.title("👔 Executive Dashboard")

    engine = get_engine()

    # ---------------------------------------------------------
    # 0. Executive Control Parameters (Expander / Sidebar)
    # ---------------------------------------------------------
    with st.expander(
        "⚙️ Executive Parameters & Operational Expenses", expanded=False
    ):
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns(4)
        with ctrl_col1:
            period_days = st.selectbox(
                "Sales & Performance Window",
                options=[30, 60, 90, 180, 365],
                index=0,
                format_func=lambda x: f"Last {x} Days",
            )
        with ctrl_col2:
            fixed_expenses = st.number_input(
                "Fixed Overheads (Rent, Admin, Payroll)",
                min_value=0.0,
                value=350000.0,
                step=25000.0,
                format="%.0f",
            )
        with ctrl_col3:
            variable_expenses = st.number_input(
                "Variable Overheads (Logistics, Promo)",
                min_value=0.0,
                value=150000.0,
                step=10000.0,
                format="%.0f",
            )
        with ctrl_col4:
            target_roi = st.number_input(
                "Target RoI %",
                min_value=1.0,
                max_value=100.0,
                value=18.0,
                step=1.0,
            )

    try:
        # Use engine.connect() for read-only schema inspection
        with engine.connect() as conn:
            item_cols_df = pd.read_sql(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE"
                    " table_name = 'items'"
                ),
                conn,
            )
            item_cols = set(item_cols_df["column_name"].str.lower().tolist())

            sales_cols_df = pd.read_sql(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE"
                    " table_name = 'sales'"
                ),
                conn,
            )
            sales_cols = set(sales_cols_df["column_name"].str.lower().tolist())

        # Determine cost expression for item-level purchase cost
        if "current_cost" in item_cols:
            cost_expr = "COALESCE(i.current_cost, 0)"
        elif "pur_rate" in item_cols:
            cost_expr = "COALESCE(i.pur_rate, 0)"
        elif "cost_rate" in item_cols:
            cost_expr = "COALESCE(i.cost_rate, 0)"
        elif "cost_price" in item_cols:
            cost_expr = "COALESCE(i.cost_price, 0)"
        elif "stock_value" in item_cols and "stock_qty" in item_cols:
            cost_expr = "CASE WHEN i.stock_qty > 0 THEN (i.stock_value / i.stock_qty) ELSE 0 END"
        else:
            cost_expr = "0"

        sign_mult_expr = (
            "s.sign_multiplier" if "sign_multiplier" in sales_cols else "1"
        )

        # ---------------------------------------------------------
        # 1. Database Queries
        # ---------------------------------------------------------
        outstanding_query = """
        SELECT 
            SUM(pending_amount) as total_outstanding,
            COUNT(DISTINCT customer_name) as customer_count
        FROM outstanding_debtors
        """

        stock_query = """
        SELECT 
            SUM(stock_value) as total_stock_value,
            SUM(stock_qty) as total_qty
        FROM items
        WHERE source_system = 'shoper'
        """

        pdc_query = """
        SELECT 
            COUNT(*) as pdc_count,
            SUM(amount) as pdc_amount,
            MIN(instrument_date) as earliest_pdc_date
        FROM receipts
        WHERE instrument_date IS NOT NULL
            AND CAST(instrument_date AS DATE) > CURRENT_DATE
        """

        # Aliased 'items i' inside the CTE and cast item_code for type safety
        sales_perf_query = f"""
        WITH deduped_item_costs AS (
            SELECT 
                item_code,
                division,
                MAX({cost_expr}) AS unit_cost
            FROM items i
            WHERE source_system = 'shoper'
            GROUP BY item_code, division
        )
        SELECT 
            COALESCE(SUM(s.net_value * {sign_mult_expr}), 0) as gross_sales,
            COALESCE(SUM(s.qty * {sign_mult_expr} * COALESCE(ic.unit_cost, 0)), 0) as gross_purchases,
            COUNT(DISTINCT s.customer_code) as unique_customers,
            MAX(s.sale_date) as last_sale_date
        FROM sales s
        LEFT JOIN deduped_item_costs ic 
            ON CAST(s.item_code AS VARCHAR) = CAST(ic.item_code AS VARCHAR)
            AND s.division = ic.division
        WHERE s.source_system = 'shoper'
            AND s.sale_date >= CURRENT_DATE - INTERVAL '{period_days} days'
        """

        with engine.connect() as conn:
            outstanding = pd.read_sql(text(outstanding_query), conn)
            stock = pd.read_sql(text(stock_query), conn)
            pdc = pd.read_sql(text(pdc_query), conn)
            sales_perf = pd.read_sql(text(sales_perf_query), conn)

        # Extract values cleanly
        outstanding_val = (
            float(outstanding.iloc[0]["total_outstanding"] or 0)
            if not outstanding.empty
            else 0.0
        )
        stock_value = (
            float(stock.iloc[0]["total_stock_value"] or 0)
            if not stock.empty
            else 0.0
        )
        pdc_amount = (
            float(pdc.iloc[0]["pdc_amount"] or 0) if not pdc.empty else 0.0
        )
        pdc_count = (
            int(pdc.iloc[0]["pdc_count"] or 0) if not pdc.empty else 0
        )
        gross_sales = (
            float(sales_perf.iloc[0]["gross_sales"] or 0)
            if not sales_perf.empty
            else 0.0
        )
        gross_purchases = (
            float(sales_perf.iloc[0]["gross_purchases"] or 0)
            if not sales_perf.empty
            else 0.0
        )

        # ---------------------------------------------------------
        # 2. Executive Math Core
        # ---------------------------------------------------------
        total_investment = outstanding_val + pdc_amount + stock_value
        gross_profit = gross_sales - gross_purchases
        total_overhead = fixed_expenses + variable_expenses
        net_operating_profit = gross_profit - total_overhead

        roi_pct = (
            (net_operating_profit / total_investment) * 100
            if total_investment > 0
            else 0.0
        )
        gp_margin_pct = (
            (gross_profit / gross_sales * 100) if gross_sales > 0 else 0.0
        )

        # ---------------------------------------------------------
        # 3. High-Level KPI Header Ribbon
        # ---------------------------------------------------------
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric(
                "💼 Total Investment",
                format_inr(total_investment),
                "O/S + PDC + Stock",
            )
        with kpi2:
            st.metric(
                f"📈 Gross Profit ({period_days}D)",
                format_inr(gross_profit),
                f"{gp_margin_pct:.1f}% GP Margin",
            )
        with kpi3:
            st.metric(
                "💵 Net Operating Profit",
                format_inr(net_operating_profit),
                f"-{format_inr(total_overhead)} Exp",
                delta_color="inverse",
            )
        with kpi4:
            st.metric(
                "🎯 Capital RoI",
                f"{roi_pct:.1f}%",
                delta=f"{roi_pct - target_roi:.1f}% vs {target_roi:.0f}% Target",
            )

        # ---------------------------------------------------------
        # 4. Division Breakdown Table
        # ---------------------------------------------------------
        st.markdown("---")
        st.header("Division Breakdown")

        div_query = f"""
        SELECT 
            s.division,
            COALESCE((SELECT SUM(pending_amount) FROM outstanding_debtors WHERE division = s.division), 0) as outstanding,
            COALESCE((SELECT SUM(stock_value) FROM items WHERE division = s.division AND source_system = 'shoper'), 0) as stock_value,
            COALESCE(SUM(s.net_value * {sign_mult_expr}), 0) as sales_period
        FROM sales s
        WHERE s.source_system = 'shoper'
            AND s.sale_date >= CURRENT_DATE - INTERVAL '{period_days} days'
        GROUP BY s.division
        ORDER BY s.division
        """

        with engine.connect() as conn:
            div_df = pd.read_sql(text(div_query), conn)

        if not div_df.empty:
            div_df["outstanding"] = div_df["outstanding"].apply(format_inr)
            div_df["stock_value"] = div_df["stock_value"].apply(format_inr)
            div_df["sales_period"] = div_df["sales_period"].apply(format_inr)

            st.dataframe(
                div_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "division": st.column_config.TextColumn("Division"),
                    "outstanding": st.column_config.TextColumn("Outstanding"),
                    "stock_value": st.column_config.TextColumn("Stock Value"),
                    "sales_period": st.column_config.TextColumn(
                        f"Sales ({period_days}D)"
                    ),
                },
            )

        st.markdown("---")

        # ---------------------------------------------------------
        # 5. Visual Charts: Working Capital vs. RoI Gauge
        # ---------------------------------------------------------
        chart_col1, chart_col2 = st.columns([1.1, 1])

        with chart_col1:
            st.subheader("Working Capital Allocation")
            fig_donut = go.Figure(
                data=[
                    go.Pie(
                        labels=[
                            "Receivables (O/S)",
                            "PDC in Hand",
                            "Stock on Hand",
                        ],
                        values=[outstanding_val, pdc_amount, stock_value],
                        hole=0.60,
                        marker=dict(
                            colors=["#EF553B", "#FFA15A", "#00CC96"],
                            line=dict(color="#ffffff", width=2),
                        ),
                        textinfo="label+percent",
                        hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.0f}<br>Share: %{percent}<extra></extra>",
                    )
                ]
            )
            fig_donut.update_layout(
                height=350,
                margin=dict(t=20, b=20, l=10, r=10),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.2,
                    xanchor="center",
                    x=0.5,
                ),
                annotations=[
                    dict(
                        text=f"Total Invested<br><b>{format_inr(total_investment)}</b>",
                        x=0.5,
                        y=0.5,
                        font_size=15,
                        showarrow=False,
                    )
                ],
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        with chart_col2:
            st.subheader("RoI Target Efficiency")
            max_gauge_range = max(40.0, float(target_roi * 1.5))
            fig_gauge = go.Figure(
                go.Indicator(
                    mode="gauge+number+delta",
                    value=roi_pct,
                    domain={"x": [0, 1], "y": [0, 1]},
                    delta={"reference": target_roi, "suffix": "%"},
                    number={"suffix": "%", "font": {"size": 36}},
                    gauge={
                        "axis": {
                            "range": [0, max_gauge_range],
                            "ticksuffix": "%",
                        },
                        "bar": {"color": "#1f77b4", "thickness": 0.3},
                        "steps": [
                            {"range": [0, 10], "color": "#FFCCCC"},
                            {
                                "range": [10, target_roi],
                                "color": "#FFF3CD",
                            },
                            {
                                "range": [target_roi, max_gauge_range],
                                "color": "#D4EDDA",
                            },
                        ],
                        "threshold": {
                            "line": {"color": "#D9534F", "width": 4},
                            "thickness": 0.8,
                            "value": target_roi,
                        },
                    },
                )
            )
            fig_gauge.update_layout(
                height=350,
                margin=dict(t=30, b=20, l=30, r=30),
            )
            st.plotly_chart(fig_gauge, use_container_width=True)

        # ---------------------------------------------------------
        # 6. P&L to RoI Waterfall Realization Bridge
        # ---------------------------------------------------------
        st.subheader(f"P&L to Profit Realization Bridge ({period_days} Days)")

        fig_waterfall = go.Figure(
            go.Waterfall(
                name="Profit Flow",
                orientation="v",
                measure=[
                    "relative",
                    "relative",
                    "total",
                    "relative",
                    "relative",
                    "total",
                ],
                x=[
                    "Gross Sales",
                    "Purchase (COGS)",
                    "Gross Profit",
                    "Fixed Overhead",
                    "Variable Overhead",
                    "Net Operating Profit",
                ],
                y=[
                    gross_sales,
                    -gross_purchases,
                    gross_profit,
                    -fixed_expenses,
                    -variable_expenses,
                    net_operating_profit,
                ],
                text=[
                    format_inr(gross_sales),
                    f"-{format_inr(gross_purchases)}",
                    format_inr(gross_profit),
                    f"-{format_inr(fixed_expenses)}",
                    f"-{format_inr(variable_expenses)}",
                    format_inr(net_operating_profit),
                ],
                textposition="outside",
                decreasing={"marker": {"color": "#E74C3C"}},
                increasing={"marker": {"color": "#27AE60"}},
                totals={"marker": {"color": "#2980B9"}},
                connector={"line": {"color": "#7F8C8D"}},
            )
        )

        fig_waterfall.update_layout(
            height=380,
            margin=dict(t=30, b=30, l=20, r=20),
            yaxis=dict(title="Amount (₹)", tickprefix="₹", tickformat=","),
            waterfallgap=0.3,
        )
        st.plotly_chart(fig_waterfall, use_container_width=True)

        # ---------------------------------------------------------
        # 7. Business Health Checks
        # ---------------------------------------------------------
        st.markdown("---")
        st.header("📊 Business Health & Capital Guardrails")

        h_col1, h_col2, h_col3 = st.columns(3)

        with h_col1:
            if outstanding_val > stock_value * 1.5:
                st.warning(
                    "⚠️ High Receivables: Outstanding exceeds 1.5x inventory"
                    " value."
                )
            else:
                st.success("✅ Receivables in healthy balance with stock.")

        with h_col2:
            if pdc_count > 50:
                st.warning(
                    f"⚠️ High PDC Count ({pdc_count} cheques): Monitor"
                    " clearance dates."
                )
            else:
                st.info(f"ℹ️ {pdc_count} Post-Dated Cheques awaiting deposit.")

        with h_col3:
            if gross_sales > 0:
                daily_run_rate = gross_sales / period_days
                days_sales_os = outstanding_val / daily_run_rate
                st.metric(
                    "DSO (Days Sales Outstanding)",
                    f"{days_sales_os:.1f} Days",
                    "Target < 45 Days",
                )

    except Exception as e:
        st.error(f"Error compiling Executive Dashboard: {e}")
        import traceback

        st.error(traceback.format_exc())


if __name__ == "__main__":
    show_executive_dashboard()
