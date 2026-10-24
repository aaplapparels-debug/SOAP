"""Outstanding Debtors Report with Interactive Chart Drilldown and WhatsApp Dispatch"""

import io
import datetime
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from ui.db_helper import get_engine
from common.whatsapp_client import send_whatsapp_document, send_whatsapp_reminder

today = datetime.date.today()
fy_start_year = today.year if today.month >= 4 else today.year - 1
fy_start_date = datetime.date(fy_start_year, 4, 1)
days_passed = (today - fy_start_date).days + 1


def format_inr(number):
    if pd.isna(number) or number is None:
        return "₹0"
    return f"₹{number:,.0f}"


def get_divisions(engine):
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT DISTINCT division FROM outstanding_debtors ORDER BY division"))
            return [row[0] for row in result]
    except Exception:
        return ["SPM", "SPW", "THM", "KTH"]


def get_customer_list(engine):
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT DISTINCT customer_name FROM outstanding_debtors ORDER BY customer_name"))
            return [row[0] for row in result]
    except Exception:
        return []


def get_customer_phone(engine, customer_name):
    """Lookup party phone number from canonical customers table."""
    try:
        with engine.begin() as conn:
            res = conn.execute(
                text("SELECT phone FROM customers WHERE customer_name = :cust AND phone IS NOT NULL AND TRIM(phone) <> '' LIMIT 1;"),
                {"cust": customer_name}
            ).fetchone()
            return str(res[0]).strip() if res else ""
    except Exception:
        return ""


def generate_outstanding_pdf(customer_name: str, df_sorted: pd.DataFrame, total_amt: float, pdc_amt: float) -> bytes:
    """Generates a clean PDF statement sorted by days_outstanding descending."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1F2937")
    )
    sub_style = ParagraphStyle(
        "SubTitle",
        parent=normal,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4B5563")
    )

    story = [
        Paragraph("<b>OUTSTANDING STATEMENT OF ACCOUNT</b>", title_style),
        Paragraph(f"<b>Customer:</b> {customer_name} &nbsp;|&nbsp; <b>As of:</b> {datetime.date.today().strftime('%d-%b-%Y')}", sub_style),
        Spacer(1, 14)
    ]

    # Summary table header
    summary_data = [
        [
            Paragraph("<b>Total Outstanding</b>", normal),
            Paragraph(f"<b>₹{total_amt:,.2f}</b>", normal),
            Paragraph("<b>Pending PDCs</b>", normal),
            Paragraph(f"<b>₹{pdc_amt:,.2f}</b>", normal),
            Paragraph("<b>Net Receivable</b>", normal),
            Paragraph(f"<b>₹{(total_amt - pdc_amt):,.2f}</b>", normal),
        ]
    ]
    t_summary = Table(summary_data, colWidths=[100, 90, 80, 80, 90, 100])
    t_summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D1D5DB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 16))

    # Table of bills sorted by days outstanding descending
    table_rows = [["Invoice Date", "Invoice Ref", "Division", "Days", "Amount (₹)"]]
    for _, r in df_sorted.iterrows():
        inv_dt = pd.to_datetime(r["invoice_date"]).strftime("%d-%b-%Y") if pd.notna(r["invoice_date"]) else "-"
        table_rows.append([
            inv_dt,
            str(r["invoice_reference"]),
            str(r["division"]),
            str(int(r["days_outstanding"])),
            f"₹{r['pending_amount']:,.2f}"
        ])

    t_bills = Table(table_rows, colWidths=[90, 150, 70, 70, 160])
    t_bills.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ALIGN", (0, 0), (2, -1), "LEFT"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))
    story.append(t_bills)

    doc.build(story)
    return buffer.getvalue()


def show_outstanding_report():
    from ui.style_loader import load_css
    load_css()
    st.title("📋 Outstanding Debtors Report")

    engine = get_engine()

    top_container = st.container()
    filter_container = st.container()
    table_container = st.container()

    # --- 1. Filters ---
    with filter_container:
        st.markdown("---")
        f_col1, f_col2, f_col3 = st.columns(3)

        with f_col1:
            divisions = get_divisions(engine)
            selected_division = st.multiselect("Division", divisions, default=divisions)

        with f_col2:
            customer_options = ["All Parties"] + get_customer_list(engine)
            selected_customer = st.selectbox("Customer", options=customer_options, index=0)

        with f_col3:
            sort_by = st.selectbox(
                "Sort By",
                ["Pending Amount", "Customer Name", "Invoice Date", "Days Outstanding"],
                index=0,
            )

    if not selected_division:
        st.warning("Please select at least one division.")
        return

    # --- 2. Database Queries ---
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
      AND (CAST(:cust_code AS VARCHAR) IS NULL OR customer_code = CAST(:cust_code AS VARCHAR))
      AND sale_date BETWEEN :fy_start_date AND CURRENT_DATE
    """

    cust_code = selected_customer.split("_")[0].strip() if selected_customer != "All Parties" else None

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

        net_sales = net_sales_df["total_net_sales"].iloc[0] if not net_sales_df.empty else 0.0
        pdc_total = pdc_df["amount"].sum() if not pdc_df.empty else 0.0

        if df.empty:
            st.warning("No outstanding debtors found with current filters.")
            return

        df["pending_amount"] = pd.to_numeric(df["pending_amount"], errors="coerce").fillna(0)
        df["days_outstanding"] = pd.to_numeric(df["days_outstanding"], errors="coerce").fillna(0)

        total_outstanding = df["pending_amount"].sum()
        credit_days = (((total_outstanding + pdc_total) * days_passed) / net_sales) if net_sales > 0 else 0

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
                    st.metric("Total Outstanding", format_inr(total_outstanding), delta=f"₹{pdc_total:,.0f} in PDCs")
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

                chart_event = st.plotly_chart(
                    fig_age,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="points",
                    key="aging_bar_chart",
                )

                if chart_event and chart_event.get("selection", {}).get("points"):
                    selected_bucket = chart_event["selection"]["points"][0].get("x")

        # --- 4. WhatsApp Dispatch Box (Active when a specific party is selected) ---
        if selected_customer != "All Parties":
            st.markdown("---")
            with st.container():
                st.markdown(f"#### 💬 Send WhatsApp Statement & Summary to `{selected_customer}`")
                
                # Compute Age Buckets for text message
                b_0_30 = df[df["_Age_Bucket"] == "0-30 Days"]["pending_amount"].sum()
                b_31_60 = df[df["_Age_Bucket"] == "31-60 Days"]["pending_amount"].sum()
                b_61_90 = df[df["_Age_Bucket"] == "61-90 Days"]["pending_amount"].sum()
                b_90_plus = df[df["_Age_Bucket"] == "90+ Days"]["pending_amount"].sum()

                # Compose WhatsApp text summary with clear formatting
                wa_msg = (
                    f"Dear *{selected_customer}*,\n\n"
                    f"Please find below your current ledger outstanding summary as of *{datetime.date.today().strftime('%d-%b-%Y')}*:\n\n"
                    f"📌 *Aging Bucket Breakdown:*  \n"
                    f"• 0–30 Days: ₹{b_0_30:,.0f}  \n  "
                    f"• 31–60 Days: ₹{b_31_60:,.0f}  \n  "
                    f"• 61–90 Days: ₹{b_61_90:,.0f}  \n  "
                    f"• 90+ Days: ₹{b_90_plus:,.0f}  \n\n  "
                    f"💰 *Total Outstanding:* *₹{total_outstanding:,.0f}*  \n  "
                )
                if pdc_total > 0:
                    wa_msg += f"🧾 *Pending PDCs:* ₹{pdc_total:,.0f}  \n"
                    wa_msg += f"⚖️ *Net Payable:* *₹{(total_outstanding - pdc_total):,.0f}*\n\n"
                else:
                    wa_msg += "  \n"

                wa_msg += "Detailed invoice-wise statement is attached as PDF for your verification. Kindly arrange clearance of overdue balances.\n\nThank you,  \n*Ashtavinayak Agencies Pvt Ltd*"

                # Customer Phone Lookup
                default_phone = get_customer_phone(engine, selected_customer)

                w_col1, w_col2 = st.columns([1.5, 2.5])
                with w_col1:
                    phone_input = st.text_input("Customer Phone Number", value=default_phone, placeholder="e.g. 98200XXXXX")
                    
                    # Prepare sorted dataframe for PDF
                    df_sorted_for_pdf = df.sort_values(by="days_outstanding", ascending=False)
                    pdf_bytes = generate_outstanding_pdf(
                        customer_name=selected_customer,
                        df_sorted=df_sorted_for_pdf,
                        total_amt=total_outstanding,
                        pdc_amt=pdc_total
                    )

                    # Download PDF locally option
                    st.download_button(
                        label="📄 Preview / Download PDF",
                        data=pdf_bytes,
                        file_name=f"Outstanding_{selected_customer.replace(' ', '_')}_{datetime.date.today()}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

                    # Direct WhatsApp Dispatch Button
                    if st.button("🚀 Send on WhatsApp (PDF + Summary)", type="primary", use_container_width=True):
                        clean_target_phone = "".join(filter(str.isdigit, str(phone_input)))
                        if not clean_target_phone or len(clean_target_phone) < 10:
                            st.error("Please enter a valid 10-digit customer phone number.")
                        else:
                            with st.spinner("Dispatching statement & PDF through Evolution API..."):

                                pdf_bytes = generate_outstanding_pdf(
                                    customer_name=selected_customer,
                                    df_sorted=df_sorted_for_pdf,
                                    total_amt=total_outstanding,
                                    pdc_amt=pdc_total
                                )
                                # Send PDF with caption
                                resp = send_whatsapp_document(
                                    phone=clean_target_phone,
                                    pdf_bytes=pdf_bytes,
                                    filename=f"Outstanding_Statement_{selected_customer.replace(' ', '_')}.pdf",
                                    caption=wa_msg
                                )
                                if resp.get("status") == "success":
                                    st.success(f"✅ Statement and PDF successfully sent to {clean_target_phone}!")
                                else:
                                    # Fallback: attempt sending as text if media fails
                                    err_msg = resp.get("message") or resp.get("error")
                                    st.warning(f"Media dispatch note ({err_msg}). Attempting text summary fallback...")
                                    txt_resp = send_whatsapp_reminder(phone=clean_target_phone, message=wa_msg)
                                    if txt_resp.get("status") == "success":
                                        st.success(f"✅ Text summary sent successfully to {clean_target_phone}!")
                                    else:
                                        st.error(f"Failed to dispatch: {txt_resp.get('message')}")

                with w_col2:
                    st.caption("WhatsApp Message Preview:")
                    st.info(wa_msg)

        # --- 5. Bottom Section: Data Tables ---
        with table_container:
            st.markdown("---")
            
            t_col1, t_col2 = st.columns([4, 1])
            with t_col1:
                if selected_bucket:
                    st.subheader(f"Outstanding Details — Filtered: `{selected_bucket}`")
                else:
                    st.subheader("Outstanding Details (All Buckets)")

            with t_col2:
                if selected_bucket:
                    if st.button("✖ Reset Filter", key="btn_clear_bucket"):
                        st.session_state["aging_bar_chart"] = {"selection": {"points": []}}
                        st.rerun()

            display_df = df[df["_Age_Bucket"] == selected_bucket].copy() if selected_bucket else df.copy()
            display_df["formatted_amount"] = display_df["pending_amount"].apply(lambda x: f"₹{x:,.2f}")
            display_df["invoice_date"] = pd.to_datetime(display_df["invoice_date"]).dt.strftime("%Y-%m-%d")

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
                    "days_outstanding": st.column_config.NumberColumn("Days Outstanding"),
                },
            )

            if not pdc_df.empty:
                st.subheader("Post-Dated Cheques (PDCs) Received")
                pdc_df["cheque_date"] = pd.to_datetime(pdc_df["cheque_date"]).dt.strftime("%Y-%m-%d")
                pdc_df["formatted_amount"] = pdc_df["amount"].apply(lambda x: f"₹{x:,.2f}")
                st.dataframe(
                    pdc_df[["customer_name", "cheque_no", "bank", "formatted_amount", "cheque_date", "division"]],
                    use_container_width=True,
                    hide_index=True
                )

    except Exception as e:
        st.error(f"Error loading data: {e}")


if __name__ == "__main__":
    show_outstanding_report()