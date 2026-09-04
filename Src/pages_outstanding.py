"""Outstanding Debtors Report with Interactive Chart Drilldown"""

import pandas as pd
import plotly.express as px
import streamlit as st
from config_loader import load_config
from sqlalchemy import create_engine, text
import datetime
today = datetime.date.today()

# If currently in Jan-Mar, FY started April 1 of the previous year; otherwise April 1 of this year
fy_start_year = today.year if today.month >= 4 else today.year - 1
fy_start_date = datetime.date(fy_start_year, 4, 1)

# +1 to include today in the count
days_passed = (today - fy_start_date).days + 1


@st.cache_resource
def get_engine():
    config = load_config()
    return create_engine(config["postgres"]["connection_string"])


def format_inr(number):
    """Formats numeric values to Indian Rupee currency string"""
    if pd.isna(number) or number is None:
        return "₹0"
    return f"₹{number:,.0f}"


def get_divisions(engine):
    """Get unique divisions from database"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "SELECT DISTINCT division FROM outstanding_debtors ORDER BY division"
                )
            )
            return [row[0] for row in result]
    except Exception:
        return ["SPM", "SPW", "THM", "KTH"]


def get_customer_list(engine):
    """Get unique customer List"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "SELECT DISTINCT customer_name FROM outstanding_debtors ORDER BY customer_name"
                )
            )
            return [row[0] for row in result]
    except Exception:
        return []


def show_outstanding_report():
    st.title("📋 Outstanding Debtors Report")

    engine = get_engine()

    top_container = st.container()
    filter_container = st.container()
    table_container = st.container()

    # --- 1. Selection Boxes / Filters ---
    with filter_container:
        st.markdown("---")
        f_col1, f_col2, f_col3 = st.columns(3)

        with f_col1:
            divisions = get_divisions(engine)
            selected_division = st.multiselect(
                "Division", divisions, default=divisions
            )

        with f_col2:
            customer_options = ["All Parties"] + get_customer_list(engine)
            selected_customer = st.selectbox(
                "Customer", options=customer_options, index=0
            )

        with f_col3:
            sort_by = st.selectbox(
                "Sort By",
                [
                    "Pending Amount",
                    "Customer Name",
                    "Invoice Date",
                    "Days Outstanding",
                ],
                index=0,
            )

    if not selected_division:
        st.warning("Please select at least one division.")
        return

    # --- 2. Database Query ---
    query = """
    SELECT 
        customer_name,
        invoice_date,
        invoice_reference,
        pending_amount,
        division,
        (CURRENT_DATE - invoice_date) as days_outstanding
    FROM outstanding_debtors
    WHERE division = ANY(:divisions)
        AND (:customer = 'All Parties' OR customer_name = :customer)
    ORDER BY 
        CASE WHEN :sort_by = 'Pending Amount' THEN pending_amount END DESC,
        CASE WHEN :sort_by = 'Customer Name' THEN customer_name END ASC,
        CASE WHEN :sort_by = 'Invoice Date' THEN invoice_date END ASC,
        CASE WHEN :sort_by = 'Days Outstanding' THEN (CURRENT_DATE - invoice_date) END DESC
    """
    pdc_query = """
    SELECT 
        customer_name,
        voucher_number,
        receipt_date,
        instrument AS cheque_no,
        TO_DATE(instrument_date, 'YYYYMMDD') AS cheque_date,
        bank,
        amount,
        division
    FROM receipts
    WHERE instrument_date IS NOT NULL 
      AND instrument_date ~ '^\d{8}$'
      AND TO_DATE(instrument_date, 'YYYYMMDD') > CURRENT_DATE
      AND (:customer = 'All Parties' OR customer_name = :customer)
    ORDER BY cheque_date ASC
    """
    net_sales_query = """
    SELECT COALESCE(SUM(net_value * sign_multiplier), 0) AS total_net_sales
    FROM sales
    WHERE customer_code <> '1001'
      AND item_code <> '8901326926543'
      AND (:cust_code IS NULL OR customer_code = :cust_code)
      AND sale_date BETWEEN :fy_start_date AND CURRENT_DATE
    """

    cust_code = (
        selected_customer.split("_")[0].strip()
            if selected_customer != "All Parties"
            else None
        )
    try:

        
        with engine.begin() as conn:
            df = pd.read_sql(
                text(query),
                conn,
                params={
                    "divisions": selected_division,
                    "customer": selected_customer,
                    "sort_by": sort_by,
                },
            )
            pdc_df = pd.read_sql(
                text(pdc_query), 
                conn, 
                params={
                    "divisions": selected_division,
                    "customer": selected_customer,
                    "sort_by": sort_by,
                },
            )
            net_sales_df = pd.read_sql(
                text(net_sales_query),
                conn,
                params={
                    "divisions": selected_division,
                    "customer": selected_customer,
                    "fy_start_date": fy_start_date,
                    "cust_code": cust_code,
                },
            )
        net_sales= net_sales_df["total_net_sales"].iloc[0] if not net_sales_df.empty else 0.0
        pdc_total = pdc_df["amount"].sum() if not pdc_df.empty else 0.0
        if df.empty:
            st.warning("No outstanding debtors found with current filters.")
            return
        df["pending_amount"] = pd.to_numeric(
            df["pending_amount"], errors="coerce"
        ).fillna(0)
        df["days_outstanding"] = pd.to_numeric(
            df["days_outstanding"], errors="coerce"
        ).fillna(0)

        total_outstanding = df["pending_amount"].sum()
        if total_outstanding > 0:
            credit_days = (
                ((total_outstanding+ pdc_total) * days_passed)/net_sales
                )
        else:
            credit_days = 0

        # Assign Age Buckets
        def assign_bucket(d):
            if d > 90:
                return "90+ Days"
            elif d > 60:
                return "61-90 Days"
            elif d > 30:
                return "31-60 Days"
            else:
                return "0-30 Days"

        df["_Age_Bucket"] = df["days_outstanding"].apply(assign_bucket)

        selected_bucket = None
        
        # --- 3. Top Section: Left KPIs & Right Interactive Chart ---
        with top_container:
            kpi_col, chart_col = st.columns([3, 2])

            with kpi_col:
                st.subheader("Receivables Overview")
                m_row1_col1, m_row1_col2 = st.columns(2)
                with m_row1_col1:
                    st.metric("Total Outstanding", format_inr(total_outstanding))
                    st.caption(f"Includes ₹{pdc_total:,.0f} in post-dated cheques (PDCs) received.")
                    st.metric("Number of Customers", f"{df['customer_name'].nunique():,}")
                with m_row1_col2:
                    st.metric("Number of Invoices", f"{len(df):,}")
                    st.metric("Credit Utilization Days", f"{credit_days:.0f} days")

            with chart_col:
                st.subheader("Aging Breakdown")
                bucket_order = ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"]
                age_summary = (
                    df.groupby("_Age_Bucket")["pending_amount"]
                    .sum()
                    .reindex(bucket_order, fill_value=0)
                    .reset_index()
                )
                age_summary["Full_Text"] = age_summary["pending_amount"].apply(
                    lambda x: f"₹{x:,.0f}" if x > 0 else "₹0"
                )

                fig_age = px.bar(
                    age_summary,
                    x="_Age_Bucket",
                    y="pending_amount",
                    text="Full_Text",
                    labels={"_Age_Bucket": "Bucket", "pending_amount": "Amount"},
                    color="_Age_Bucket",
                    color_discrete_map={
                        "0-30 Days": "#198754",
                        "31-60 Days": "#0dcaf0",
                        "61-90 Days": "#ffc107",
                        "90+ Days": "#dc3545",
                    },
                )
                fig_age.update_traces(textposition="auto")
                fig_age.update_layout(
                    height=200,
                    margin=dict(l=10, r=10, t=10, b=10),
                    showlegend=False,
                    xaxis_title=None,
                    yaxis_title=None,
                    clickmode="event+select",
                )

                # Capture user click on chart bars
                chart_event = st.plotly_chart(
                    fig_age,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="points",
                    key="aging_bar_chart",
                )

                # Extract selected bucket name from the click event
                if chart_event and chart_event.get("selection", {}).get("points"):
                    selected_bucket = chart_event["selection"]["points"][0].get("x")

        # --- 4. Bottom Section: Filtered Table based on Drilldown ---
        with table_container:
            st.markdown("---")
            
            t_col1, t_col2 = st.columns([4, 1])
            with t_col1:
                if selected_bucket:
                    st.subheader(f"Outstanding Details — Filtered: `{selected_bucket}`")
                    st.caption(f"Showing only records belonging to the **{selected_bucket}** bucket. Click the bar again to reset.")
                else:
                    st.subheader("Outstanding Details (All Buckets)")
                    st.caption("Click any bar in the aging chart above to filter this table by bucket.")

            with t_col2:
                if selected_bucket:
                    if st.button("✖ Reset Filter", key="btn_clear_bucket"):
                        st.session_state["aging_bar_chart"] = {"selection": {"points": []}}
                        st.rerun()

            # Filter data table if a bucket was clicked
            if selected_bucket:
                display_df = df[df["_Age_Bucket"] == selected_bucket].copy()
            else:
                display_df = df.copy()

            display_df["formatted_amount"] = display_df["pending_amount"].apply(
                lambda x: f"₹{x:,.2f}"
            )
            display_df["invoice_date"] = pd.to_datetime(
                display_df["invoice_date"]
            ).dt.strftime("%Y-%m-%d")

            st.dataframe(
                display_df[
                    [
                        "customer_name",
                        "invoice_date",
                        "invoice_reference",
                        "formatted_amount",
                        "division",
                        "days_outstanding",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "customer_name": st.column_config.TextColumn("Customer"),
                    "invoice_date": st.column_config.TextColumn("Invoice Date"),
                    "invoice_reference": st.column_config.TextColumn("Invoice Ref"),
                    "formatted_amount": st.column_config.TextColumn("Amount"),
                    "division": st.column_config.TextColumn("Division"),
                    "days_outstanding": st.column_config.NumberColumn(
                        "Days Outstanding"
                    ),
                },
            )

            st.subheader("Post-Dated Cheques (PDCs) Received")
            st.dataframe(
                pdc_df[
                    [
                        "customer_name",
                        "cheque_no",
                        "bank",
                        "amount",
                        "cheque_date",
                        "division",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "customer_name": st.column_config.TextColumn("Customer"),
                    "cheque_no": st.column_config.TextColumn("cheque_no"),
                    "bank": st.column_config.TextColumn("bank"),
                    "amount": st.column_config.TextColumn("amount"),
                    "cheque_date": st.column_config.TextColumn("cheque_date"),
                    "division": st.column_config.TextColumn("division"),
                }
            )
            
            # Download CSV (downloads currently filtered view)
            csv = display_df.to_csv(index=False)
            st.download_button(
                label=f"📥 Download {'Filtered' if selected_bucket else 'All'} as CSV",
                data=csv,
                file_name=f"outstanding_{selected_bucket.replace('+', 'plus').replace(' ', '_') if selected_bucket else 'all'}.csv",
                mime="text/csv",
            )

    except Exception as e:
        st.error(f"Error loading data: {e}")


if __name__ == "__main__":
    show_outstanding_report()