"""
Src/ui/pages_followup_queue.py
Operational review and dispatch console for queued debtor follow-ups.
Allows single or multi-selected WhatsApp Web triggers and status updates.
"""

import json
import urllib.parse
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import text

try:
    from ui.db_helper import get_engine
except ImportError:
    from db_helper import get_engine


def clean_phone_number(raw_phone: str) -> str:
    """Sanitizes phone strings and standardizes to 91-prefixed format."""
    if not raw_phone:
        return ""
    digits = "".join(filter(str.isdigit, str(raw_phone)))
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits if len(digits) > 10 else ""


def build_whatsapp_url(phone: str, message: str) -> str:
    """Builds pre-filled WhatsApp Web deep link."""
    clean_phone = clean_phone_number(phone)
    encoded_text = urllib.parse.quote(message)
    return f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"


def render_followup_queue():
    st.title("📋 Outstanding Follow-up Queue")
    st.caption("Review pending debtor notices and launch WhatsApp chats individually or in batch.")

    engine = get_engine()

    # 1. Fetch pending follow-ups
    query = """
        SELECT id, customer_name, phone, email, severity_level,
               total_outstanding, overdue_amount, overdue_days,
               salesperson, notes, status, created_at
        FROM customer_followup_logs
        WHERE status = 'PENDING'
        ORDER BY overdue_days DESC, overdue_amount DESC;
    """

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    if df.empty:
        st.success("🎉 No pending follow-up notices in the queue. You are all caught up!")
        return

    # 2. Top Summary KPI Metrics
    total_pending = len(df)
    total_val = df["overdue_amount"].sum()
    critical_count = (df["severity_level"] == "CRITICAL").sum()

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Pending Follow-ups", f"{total_pending}")
    kpi2.metric("Total Queued Overdue", f"₹{total_val:,.2f}")
    kpi3.metric("Critical Accounts", f"{critical_count}")

    st.markdown("---")

    # 3. Master Action Bar
    col_sel, col_action, col_dismiss = st.columns([2, 3, 2])

    with col_sel:
        select_all = st.checkbox("Select All Accounts", value=False)

    # Initialize tracking of selected task IDs
    selected_tasks = []

    # Filter by search or severity if needed
    with st.expander("🔍 Filter Queue", expanded=False):
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            severity_filter = st.multiselect(
                "Filter by Severity",
                options=df["severity_level"].unique().tolist(),
                default=df["severity_level"].unique().tolist()
            )
        with f_col2:
            search_query = st.text_input("Search Customer Name", value="")

    filtered_df = df[df["severity_level"].isin(severity_filter)]
    if search_query.strip():
        filtered_df = filtered_df[filtered_df["customer_name"].str.contains(search_query.strip(), case=False, na=False)]

    st.write(f"Showing **{len(filtered_df)}** queued items:")

    # 4. Render Queue Cards
    st.markdown("---")
    
    for idx, row in filtered_df.iterrows():
        task_id = int(row["id"])
        phone = str(row["phone"] or "")
        clean_phone = clean_phone_number(phone)
        msg_text = str(row["notes"] or "")
        wa_url = build_whatsapp_url(phone, msg_text) if clean_phone else None

        card_col_check, card_col_details, card_col_btn = st.columns([1, 6, 2])

        with card_col_check:
            is_checked = st.checkbox(
                "Select",
                value=select_all,
                key=f"task_check_{task_id}",
                label_visibility="collapsed"
            )
            if is_checked and wa_url:
                selected_tasks.append({
                    "id": task_id,
                    "customer": row["customer_name"],
                    "phone": clean_phone,
                    "url": wa_url
                })

        with card_col_details:
            severity_color = {
                "CRITICAL": "red",
                "URGENT": "orange",
                "OVERDUE": "blue",
                "REMINDER": "gray"
            }.get(row["severity_level"], "gray")

            st.markdown(
                f"**{row['customer_name']}** "
                f"&nbsp; <span style='background-color:{severity_color};color:white;padding:2px 8px;border-radius:10px;font-size:11px;'>{row['severity_level']}</span> "
                f"&nbsp; `₹{row['overdue_amount']:,.2f}` ({row['overdue_days']} days overdue)",
                unsafe_allow_html=True
            )
            
            with st.expander(f"📝 Preview Message ({row['customer_name']})", expanded=False):
                st.caption(f"**Contact Number:** {clean_phone or '⚠️ No Phone Found'}")
                st.info(msg_text)

        with card_col_btn:
            if wa_url:
                st.link_button("📲 Send WhatsApp", wa_url, use_container_width=True)
            else:
                st.button("⚠️ No Phone", disabled=True, key=f"disabled_{task_id}", use_container_width=True)

        st.divider()

    # 5. Bulk Trigger Operations
    with col_action:
        if st.button(f"🚀 Open Selected ({len(selected_tasks)}) in WhatsApp", type="primary", disabled=(len(selected_tasks) == 0)):
            target_ids = [t["id"] for t in selected_tasks]
            target_urls = [t["url"] for t in selected_tasks]

            # Mark selected records as SENT in NeonDB
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE customer_followup_logs
                        SET status = 'SENT'
                        WHERE id = ANY(:ids);
                    """),
                    {"ids": target_ids}
                )

            # Client-side JavaScript to open each link sequentially with a 900ms stagger
            # Staggering prevents the browser from jamming WhatsApp Web tabs
            js_script = f"""
            <script>
                const urls = {json.dumps(target_urls)};
                urls.forEach((url, index) => {{
                    setTimeout(() => {{
                        window.open(url, '_blank');
                    }}, index * 900);
                }});
            </script>
            """
            components.html(js_script, height=0)
            st.success(f"Dispatched {len(target_ids)} chats! Note: Allow pop-ups in your browser if all tabs did not open.")
            st.rerun()

    with col_dismiss:
        if st.button(f"Mark Selected as Dismissed", disabled=(len(selected_tasks) == 0)):
            target_ids = [t["id"] for t in selected_tasks]
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE customer_followup_logs
                        SET status = 'DISMISSED'
                        WHERE id = ANY(:ids);
                    """),
                    {"ids": target_ids}
                )
            st.info(f"Dismissed {len(target_ids)} follow-up notices.")
            st.rerun()