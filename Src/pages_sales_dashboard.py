"""Sales Performance & Dashboard - Target vs Achievement (JC Periods)"""

import datetime
import pandas as pd
import streamlit as st
from config_loader import load_config
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine():
    config = load_config()
    return create_engine(config["postgres"]["connection_string"])


def format_inr(val, decimals=2):
    """Formats numeric values to Indian Rupee currency string"""
    if pd.isna(val) or val is None:
        return "₹0.00" if decimals > 0 else "₹0"
    if decimals > 0:
        return f"₹{val:,.{decimals}f}"
    return f"₹{val:,.0f}"


def get_jc_periods(engine):
    """Fetches all JC periods ordered chronologically"""
    query = """
    SELECT jc_code, financial_year, start_date, end_date
    FROM jc_periods
    ORDER BY financial_year ASC, start_date ASC
    """
    try:
        with engine.begin() as conn:
            df = pd.read_sql(text(query), conn)
            df["start_date"] = pd.to_datetime(df["start_date"]).dt.date
            df["end_date"] = pd.to_datetime(df["end_date"]).dt.date
            return df
    except Exception:
        # Fallback 13 JC Months cycle
        start_dates = [
            (
                pd.Timestamp("2026-04-01") + pd.Timedelta(days=28 * i)
            ).date()
            for i in range(13)
        ]
        end_dates = [
            (
                pd.Timestamp("2026-04-01")
                + pd.Timedelta(days=28 * (i + 1) - 1)
            ).date()
            for i in range(13)
        ]
        return pd.DataFrame(
            {
                "jc_code": [f"M{i}" for i in range(1, 14)],
                "financial_year": [20262027] * 13,
                "start_date": start_dates,
                "end_date": end_dates,
            }
        )


def fetch_performance_data(engine, financial_year=None):
    """Fetches calculated performance data directly from the jc_achievement view."""
    query = """
    SELECT 
        jc_code,
        financial_year,
        division,
        start_date,
        end_date,
        target_pcs,
        achv_pcs,
        achv_value,
        achv_pct,
        balance_pcs
    FROM jc_achievement
    """
    params = {}
    if financial_year:
        query += " WHERE financial_year = :fy"
        params["fy"] = int(financial_year)
    query += " ORDER BY financial_year ASC, start_date ASC, division ASC"

    try:
        with engine.begin() as conn:
            return pd.read_sql(text(query), conn, params=params)
    except Exception:
        # Fallback direct calculation if view is not yet compiled
        fallback_query = """
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
           AND s.customer_code not in('1000','1001')
           AND s.item_code <> '8901326926543'
        GROUP BY t.jc_code, t.financial_year, t.division, p.start_date, p.end_date, t.target_pcs
        ORDER BY p.start_date ASC, t.division ASC
        """
        with engine.begin() as conn:
            return pd.read_sql(text(fallback_query), conn)


def show_sales_dashboard():
    st.title("📊 Sales Performance & Dashboard")

    engine = get_engine()

    periods_df = get_jc_periods(engine)
    if periods_df.empty:
        st.warning("No JC periods configured in database.")
        return

    today = datetime.date.today()

    # Match active JC Period based on today's date
    current_match = periods_df[
        (periods_df["start_date"] <= today) & (today <= periods_df["end_date"])
    ]
    if not current_match.empty:
        default_index = int(current_match.index[0])
    else:
        default_index = len(periods_df) - 1

    jc_list = periods_df["jc_code"].tolist()

    # --- Header Selection & Date Window Display ---
    col_sel, col_dates = st.columns([1, 2])

    with col_sel:
        selected_jc = st.selectbox(
            "Select JC Month:", jc_list, index=default_index
        )

    # Get selected period details
    selected_row = periods_df[periods_df["jc_code"] == selected_jc].iloc[0]
    selected_fy = selected_row["financial_year"]
    start_dt = selected_row["start_date"]
    end_dt = selected_row["end_date"]

    with col_dates:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        st.info(
            f"📅 **Period Range:** {start_dt.strftime('%d %b %Y')} &nbsp;➔&nbsp; {end_dt.strftime('%d %b %Y')}"
        )

    try:
        perf_df = fetch_performance_data(engine, financial_year=selected_fy)

        if perf_df.empty:
            st.warning("No sales or target data found.")
            return

        # Current Selected JC Data
        curr_df = perf_df[perf_df["jc_code"] == selected_jc].copy()

        # Numeric conversions
        curr_df["target_pcs"] = pd.to_numeric(curr_df["target_pcs"], errors="coerce").fillna(0)
        curr_df["achv_pcs"] = pd.to_numeric(curr_df["achv_pcs"], errors="coerce").fillna(0)
        curr_df["achv_value"] = pd.to_numeric(curr_df["achv_value"], errors="coerce").fillna(0)
        curr_df["balance_pcs"] = pd.to_numeric(curr_df["balance_pcs"], errors="coerce").fillna(0)

        total_target = curr_df["target_pcs"].sum()
        total_achv_pcs = curr_df["achv_pcs"].sum()
        total_achv_val = curr_df["achv_value"].sum()
        total_bal_pcs = max(total_target - total_achv_pcs, 0)
        total_achv_pct = (total_achv_pcs / total_target * 100) if total_target > 0 else 0.0

        # --- Top 5 Summary KPIs ---
        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        with kpi1:
            st.metric("Target (Pcs)", f"{total_target:,.0f}")
        with kpi2:
            st.metric("Achieved (Pcs)", f"{total_achv_pcs:,.0f}")
        with kpi3:
            st.metric("Achievement %", f"{total_achv_pct:.1f}%")
        with kpi4:
            st.metric("Balance Target (Pcs)", f"{total_bal_pcs:,.0f}")
        with kpi5:
            st.metric("Sales Achieved (Value)", format_inr(total_achv_val, 2))

        st.markdown("---")

        # --- Performance Tables Section ---
        st.subheader(f"📋 Sales Performance Tables ({selected_jc})")

        t_col1, t_col2 = st.columns([1.1, 1.2])

        # Left Table: Current Month Division Breakdown
        with t_col1:
            st.markdown(f"**Current Month ({selected_jc}) Division Breakdown**")

            curr_df["Achv_%"] = curr_df.apply(
                lambda r: f"{(r['achv_pcs'] / r['target_pcs'] * 100):.1f}%" if r["target_pcs"] > 0 else "0.0%",
                axis=1,
            )
            curr_df["Achv_Value_Fmt"] = curr_df["achv_value"].apply(lambda v: format_inr(v, 2))

            display_current = curr_df[
                ["division", "target_pcs", "achv_pcs", "balance_pcs", "Achv_Value_Fmt", "Achv_%"]
            ].rename(
                columns={
                    "division": "Division",
                    "target_pcs": "Target_Pcs",
                    "achv_pcs": "Achv_Pcs",
                    "balance_pcs": "Balance_Pcs",
                    "Achv_Value_Fmt": "Achv_Value",
                }
            )

            st.dataframe(
                display_current,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Division": st.column_config.TextColumn("Division"),
                    "Target_Pcs": st.column_config.NumberColumn("Target_Pcs", format="%d"),
                    "Achv_Pcs": st.column_config.NumberColumn("Achv_Pcs", format="%d"),
                    "Balance_Pcs": st.column_config.NumberColumn("Balance_Pcs", format="%d"),
                    "Achv_Value": st.column_config.TextColumn("Achv_Value"),
                    "Achv_%": st.column_config.TextColumn("Achv_%"),
                },
            )

        # Right Table: Prior Months Performance Summary
        with t_col2:
            st.markdown("**Prior Months Performance Summary (M1 to Prior)**")

            # Filter for prior months within the same financial year
            curr_start_date = selected_row["start_date"]
            prior_months_df = perf_df[perf_df["start_date"] < curr_start_date].copy()

            if prior_months_df.empty:
                st.info("No prior month records available for this financial year.")
            else:
                summary_prior = (
                    prior_months_df.groupby(["jc_code", "start_date"])
                    .agg({"target_pcs": "sum", "achv_pcs": "sum", "achv_value": "sum"})
                    .reset_index()
                    .sort_values(by="start_date", ascending=False)
                )

                summary_prior["Achv_%"] = summary_prior.apply(
                    lambda r: f"{(r['achv_pcs'] / r['target_pcs'] * 100):.1f}%" if r["target_pcs"] > 0 else "0.0%",
                    axis=1,
                )
                summary_prior["Achv_Value_Fmt"] = summary_prior["achv_value"].apply(lambda v: format_inr(v, 2))

                display_prior = summary_prior[
                    ["jc_code", "target_pcs", "achv_pcs", "Achv_%", "Achv_Value_Fmt"]
                ].rename(
                    columns={
                        "jc_code": "JC Month",
                        "target_pcs": "Target (Pcs)",
                        "achv_pcs": "Achv (Pcs)",
                        "Achv_%": "Achv %",
                        "Achv_Value_Fmt": "Achv (Value)",
                    }
                )

                st.dataframe(
                    display_prior,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "JC Month": st.column_config.TextColumn("JC Month"),
                        "Target (Pcs)": st.column_config.NumberColumn("Target (Pcs)", format="%d"),
                        "Achv (Pcs)": st.column_config.NumberColumn("Achv (Pcs)", format="%d"),
                        "Achv %": st.column_config.TextColumn("Achv %"),
                        "Achv (Value)": st.column_config.TextColumn("Achv (Value)"),
                    },
                )

    except Exception as e:
        st.error(f"Error loading sales performance data: {e}")


if __name__ == "__main__":
    show_sales_dashboard()