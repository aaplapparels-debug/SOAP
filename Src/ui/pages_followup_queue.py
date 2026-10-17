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
import os
import time
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


try:
    from ui.db_helper import get_engine
except ImportError:
    from db_helper import get_engine


def dispatch_whatsapp_via_selenium(tasks: list) -> list:
    """
    Opens Chrome with persistent profile, loops through selected tasks, 
    and automatically presses Enter to send each WhatsApp message.
    """
    options = Options()
    options.add_argument(r'--user-data-dir=C:\WhatsAppSeleniumProfile')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_experimental_option("detach", True)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    sent_ids = []

    try:
        for item in tasks:
            phone = item["phone"]
            msg = item["message"]
            encoded_message = urllib.parse.quote(msg)
            url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"

            driver.get(url)
            
            # Wait for message box to become clickable
            try:
                message_box = WebDriverWait(driver, 35).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        '//footer//div[@contenteditable="true"]'
                    ))
                )
                time.sleep(2)
                message_box.click()
                time.sleep(1)
                message_box.send_keys(Keys.ENTER)
                time.sleep(3)  # Buffer to allow WhatsApp to transmit
                
                sent_ids.append(item["id"])
            except Exception as ex:
                st.warning(f"Could not deliver to {item['customer']}: {ex}")

    finally:
        driver.quit()

    return sent_ids


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
    #return f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"
    return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"


def render_followup_queue():

    from ui.style_loader import load_css
    load_css()
    st.title("📋 Follow-up Queue")
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

# ---------------------------------------------------------
    # 3. Filters & Master Action Bar
    # ---------------------------------------------------------
    # 3a. Compute filters FIRST so filtered_df exists for the callback
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

    # 3b. Callback to sync session_state for all currently filtered records
    def toggle_all_selection():
        target_state = st.session_state.get("master_select_all", False)
        for _, r in filtered_df.iterrows():
            st.session_state[f"task_check_{int(r['id'])}"] = target_state

    # 3c. Master controls bar
    col_sel, col_action, col_dismiss = st.columns([2, 3, 2])
    with col_sel:
        st.checkbox(
            "Select All Accounts", 
            key="master_select_all",
            on_change=toggle_all_selection
        )

    # Initialize tracking of selected task IDs
    selected_tasks = []

    st.write(f"Showing **{len(filtered_df)}** queued items:")
# ---------------------------------------------------------
    # 4. Render Queue Cards
    # ---------------------------------------------------------
    st.markdown("---")
    
    for idx, row in filtered_df.iterrows():
        task_id = int(row["id"])
        phone = str(row["phone"] or "")
        clean_phone = clean_phone_number(phone)
        msg_text = str(row["notes"] or "")
        wa_url = build_whatsapp_url(phone, msg_text) if clean_phone else None

        card_col_check, card_col_details, card_col_btn = st.columns([1, 6, 2])

        # Ensure the session state key is initialized if absent
        if f"task_check_{task_id}" not in st.session_state:
            st.session_state[f"task_check_{task_id}"] = False

        with card_col_check:
            # Bind strictly through the key (DO NOT pass value=...)
            is_checked = st.checkbox(
                "Select",
                key=f"task_check_{task_id}",
                label_visibility="collapsed"
            )
            if is_checked and wa_url:
                selected_tasks.append({
                    "id": task_id,
                    "customer": row["customer_name"],
                    "phone": clean_phone,
                    "message": msg_text,
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
                st.markdown(
                    f'<a href="{wa_url}" target="_blank" style="text-decoration:none;">'
                    f'<button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; font-weight:bold; cursor:pointer;">'
                    f'💬 Share on WhatsApp</button></a>',
                    unsafe_allow_html=True,
                )
            else:
                st.button("⚠️ No Phone", disabled=True, key=f"disabled_{task_id}", use_container_width=True)

        st.divider()

    # 5. Bulk Trigger Operations
    with col_action:
        if st.button(f"🚀 Auto-Send Selected ({len(selected_tasks)}) via Selenium", type="primary", disabled=(len(selected_tasks) == 0)):
            with st.spinner("Automating WhatsApp messages in Chrome... Please leave the browser window in focus."):
                successful_ids = dispatch_whatsapp_via_selenium(selected_tasks)

            if successful_ids:
                with engine.begin() as conn:
                    conn.execute(
                        text("""
                            UPDATE customer_followup_logs
                            SET status = 'SENT'
                            WHERE id = ANY(:ids);
                        """),
                        {"ids": successful_ids}
                    )
                st.success(f"Successfully auto-dispatched {len(successful_ids)} of {len(selected_tasks)} messages!")
                st.rerun()
            else:
                st.error("No messages were dispatched. Check if WhatsApp Web logged in successfully.")

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