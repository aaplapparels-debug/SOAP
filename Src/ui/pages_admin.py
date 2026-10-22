"""
Src/ui/pages/pages_admin.py
Central Administration Hub:
  - Tab 1: User Control & Role-Based Access
  - Tab 2: JC Periods & Sales Targets Management
  - Tab 3: Division & Source System Setup
  - Tab 4: Sync Pipeline & Staging Health
"""

import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text
from ui.db_helper import get_engine
from ui.style_loader import load_css

import yaml
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path(f"config.{st.session_state.get('env', 'dev')}.yaml")

def render_yaml_config_editor():
    st.subheader("⚙️ System Configuration (`config.yaml`)")
    st.caption("Safely inspect and modify application parameters. Changes are validated before saving.")

    if not CONFIG_PATH.exists():
        st.error(f"Configuration file not found at `{CONFIG_PATH.resolve()}`")
        return

    # Read current configuration
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw_yaml_text = f.read()
    except Exception as e:
        st.error(f"Failed to read config file: {e}")
        return

    with st.form("yaml_editor_form"):
        edited_yaml = st.text_area(
            "YAML Content",
            value=raw_yaml_text,
            height=380,
            help="Ensure standard 2-space YAML indentation is preserved."
        )

        col_save, col_validate = st.columns([1.5, 4])
        with col_save:
            submit_save = st.form_submit_button("💾 Validate & Save Changes", type="primary")

        if submit_save:
            # Step 1: Validate syntax
            try:
                parsed_data = yaml.safe_load(edited_yaml)
                if not isinstance(parsed_data, dict):
                    st.error("Invalid YAML structure: Root configuration must be a dictionary/mapping.")
                    return
            except yaml.YAMLError as exc:
                st.error(f"YAML Syntax Error: {exc}")
                return

            # Step 2: Create automated backup before overwriting
            backup_dir = Path("backups/config")
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_filename = backup_dir / f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml.bak"

            try:
                with open(backup_filename, "w", encoding="utf-8") as bf:
                    bf.write(raw_yaml_text)

                # Step 3: Write validated YAML
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    f.write(edited_yaml)

                st.success(f"Configuration successfully saved! (Backup created at `{backup_filename.name}`)")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Error saving configuration: {e}")

def show_admin_page():
    load_css()
    st.title("🛡️ Enterprise Administration Hub")
    st.caption("Manage access permissions, Journey Cycle configurations, targets, and integration bridges.")

    engine = get_engine()

    tab_users, tab_jc_targets, tab_general, tab_sync = st.tabs([
        "👥 User Access & Roles",
        "🎯 JC Periods & Targets",
        "🏢 General Setup & Divisions",
        "🔄 Pipeline & Staging Health"
    ])

    # =========================================================================
    # TAB 1: USER CONTROL & ROLES
    # =========================================================================
    with tab_users:
        st.subheader("Dashboard User Management")
        
        # 1. New User Invocation / Creation Form
        with st.expander("➕ Register New Portal User", expanded=False):
            with st.form("new_user_form", clear_on_submit=True):
                col_u1, col_u2, col_u3 = st.columns([3, 2, 1.5])
                with col_u1:
                    new_email = st.text_input("User Email Address", placeholder="user@lanzdaun.com").strip().lower()
                with col_u2:
                    new_role = st.selectbox("Assigned Role", ["Admin", "Manager", "Sales", "Viewer"])
                with col_u3:
                    is_active = st.checkbox("Active Account", value=True)
                
                submitted_user = st.form_submit_button("Grant Access", type="primary")
                if submitted_user:
                    if not new_email or "@" not in new_email:
                        st.error("Please provide a valid email address.")
                    else:
                        try:
                            with engine.begin() as conn:
                                conn.execute(
                                    text("""
                                        INSERT INTO dashboard_users (email, role, is_active, created_at)
                                        VALUES (:email, :role, :is_active, NOW())
                                        ON CONFLICT (email) 
                                        DO UPDATE SET role = EXCLUDED.role, is_active = EXCLUDED.is_active;
                                    """),
                                    {"email": new_email, "role": new_role, "is_active": is_active}
                                )
                            st.success(f"Access privileges updated for {new_email}.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error registering user: {e}")

        # 2. Existing Users Table & Status Toggle
        try:
            with engine.connect() as conn:
                users_df = pd.read_sql(
                    text("SELECT email, role, is_active, created_at FROM dashboard_users ORDER BY created_at DESC;"),
                    conn
                )

            if users_df.empty:
                st.info("No dashboard users registered yet.")
            else:
                st.markdown("##### Registered Accounts")
                for _, row in users_df.iterrows():
                    u_col1, u_col2, u_col3, u_col4 = st.columns([3, 2, 1.5, 1.5])
                    with u_col1:
                        st.write(f"**{row['email']}**")
                    with u_col2:
                        st.write(f"🏷️ `{row['role']}`")
                    with u_col3:
                        status_str = "🟢 Active" if row["is_active"] else "🔴 Inactive"
                        st.write(status_str)
                    with u_col4:
                        toggle_label = "Deactivate" if row["is_active"] else "Activate"
                        if st.button(toggle_label, key=f"tgl_{row['email']}", use_container_width=True):
                            with engine.begin() as conn:
                                conn.execute(
                                    text("UPDATE dashboard_users SET is_active = :status WHERE email = :email;"),
                                    {"status": not row["is_active"], "email": row["email"]}
                                )
                            st.rerun()
                    st.divider()
        except Exception as e:
            st.error(f"Error fetching users: {e}")

    # =========================================================================
    # TAB 2: JC & TARGETS ADMINISTRATION
    # =========================================================================
    with tab_jc_targets:
        st.subheader("Journey Cycle (JC) Calendar & Target Allocation")
        
        jc_col_left, jc_col_right = st.columns([1.5, 2.5])

        with jc_col_left:
            st.markdown("##### Define Journey Cycle Period")
            with st.form("jc_period_form", clear_on_submit=True):
                jc_code = st.text_input("JC Code (e.g. M1, M2, JC-01)", placeholder="M1").strip().upper()
                fy_code = st.number_input("Financial Year (e.g. 20262027)", min_value=20242025, max_value=20352036, value=20262027, step=10001)
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date = st.date_input("Start Date", value=date.today())
                with col_d2:
                    end_date = st.date_input("End Date", value=date.today())

                submit_jc = st.form_submit_button("Save Period Window", type="primary")
                if submit_jc:
                    if not jc_code:
                        st.error("JC Code cannot be blank.")
                    elif start_date > end_date:
                        st.error("Start Date cannot be after End Date.")
                    else:
                        try:
                            with engine.begin() as conn:
                                conn.execute(
                                    text("""
                                        INSERT INTO jc_periods (jc_code, financial_year, start_date, end_date)
                                        VALUES (:code, :fy, :s_date, :e_date)
                                        ON CONFLICT (jc_code, financial_year)
                                        DO UPDATE SET start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date;
                                    """),
                                    {"code": jc_code, "fy": fy_code, "s_date": start_date, "e_date": end_date}
                                )
                            st.success(f"JC Period {jc_code} ({fy_code}) saved successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving JC period: {e}")

        with jc_col_right:
            st.markdown("##### Allocate Division Target Pieces")
            
            # Fetch existing periods to populate target dropdown
            try:
                with engine.connect() as conn:
                    periods_df = pd.read_sql(
                        text("SELECT jc_code, financial_year, start_date, end_date FROM jc_periods ORDER BY financial_year DESC, start_date DESC;"),
                        conn
                    )
                    divs_result = conn.execute(text("SELECT DISTINCT division FROM items WHERE division IS NOT NULL;")).fetchall()
                    avail_divs = [d[0] for d in divs_result] if divs_result else ["SPM", "SPW", "Thermal", "KTH"]

                if periods_df.empty:
                    st.info("Please define at least one JC period on the left before allocating targets.")
                else:
                    periods_df["label"] = periods_df["jc_code"] + " (" + periods_df["financial_year"].astype(str) + ")"
                    selected_period_lbl = st.selectbox("Select JC Target Window", periods_df["label"].tolist())
                    
                    selected_jc_row = periods_df[periods_df["label"] == selected_period_lbl].iloc[0]
                    target_jc = selected_jc_row["jc_code"]
                    target_fy = int(selected_jc_row["financial_year"])

                    with st.form("target_allocation_form"):
                        st.write(f"Setting targets for **{target_jc} (FY {target_fy})**")
                        
                        target_inputs = {}
                        cols = st.columns(len(avail_divs)) if avail_divs else [st.container()]
                        
                        # Load current values if they exist
                        with engine.connect() as conn:
                            curr_targs = pd.read_sql(
                                text("SELECT division, target_pcs FROM jc_targets WHERE jc_code = :jc AND financial_year = :fy;"),
                                conn,
                                params={"jc": target_jc, "fy": target_fy}
                            ).set_index("division")["target_pcs"].to_dict()

                        for i, div in enumerate(avail_divs):
                            with cols[i % len(cols)]:
                                default_val = int(curr_targs.get(div, 0))
                                target_inputs[div] = st.number_input(
                                    f"Target: {div} (pcs)",
                                    min_value=0,
                                    value=default_val,
                                    step=500,
                                    key=f"targ_{div}"
                                )

                        submit_targets = st.form_submit_button("💾 Save Division Targets", type="primary")
                        if submit_targets:
                            with engine.begin() as conn:
                                for div, val in target_inputs.items():
                                    conn.execute(
                                        text("""
                                            INSERT INTO jc_targets (jc_code, financial_year, division, target_pcs)
                                            VALUES (:jc, :fy, :div, :pcs)
                                            ON CONFLICT (jc_code, financial_year, division)
                                            DO UPDATE SET target_pcs = EXCLUDED.target_pcs;
                                        """),
                                        {"jc": target_jc, "fy": target_fy, "div": div, "pcs": val}
                                    )
                            st.success("Target pieces updated in `jc_targets`! Achievement views synced.")
                            st.rerun()

            except Exception as e:
                st.error(f"Error managing targets: {e}")
            

        # Show Achievement Summary View Live
        st.markdown("---")
        st.markdown("##### Current Journey Cycle Performance Register (`jc_achievement` View)")
        try:
            with engine.connect() as conn:
                achv_df = pd.read_sql(text("SELECT * FROM jc_achievement ORDER BY financial_year DESC, start_date DESC, division;"), conn)
            
            if not achv_df.empty:
                st.dataframe(
                    achv_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "financial_year": st.column_config.NumberColumn("FY", format="%d"),
                        "jc_code": st.column_config.TextColumn("JC"),
                        "division": st.column_config.TextColumn("Div"),
                        "target_pcs": st.column_config.NumberColumn("Target (pcs)", format="%d"),
                        "achv_pcs": st.column_config.NumberColumn("Achieved (pcs)", format="%d"),
                        "achv_value": st.column_config.NumberColumn("Achieved (₹)", format="₹%d"),
                        "achv_pct": st.column_config.ProgressColumn("Achv %", min_value=0, max_value=120, format="%.1f%%"),
                        "balance_pcs": st.column_config.NumberColumn("Balance (pcs)", format="%d")
                    }
                )
        except Exception as e:
            st.warning(f"Could not load `jc_achievement` view: {e}")

    # =========================================================================
    # TAB 3: GENERAL SETUP & DIVISIONS
    # =========================================================================
    with tab_general:
        st.subheader("Global Enterprise Parameters")

        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.markdown("##### Operational Divisions")
            st.caption("Active operational divisions recognized across staging and canonical catalogs.")
            
            try:
                with engine.connect() as conn:
                    divisions_summary = pd.read_sql(text("""
                        SELECT 
                            division,
                            COUNT(DISTINCT item_code) AS items_count,
                            source_system
                        FROM items 
                        WHERE division IS NOT NULL
                        GROUP BY division, source_system
                        ORDER BY division;
                    """), conn)
                
                st.dataframe(
                    divisions_summary,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "division": st.column_config.TextColumn("Division Code"),
                        "items_count": st.column_config.NumberColumn("Cataloged SKUs", format="%d"),
                        "source_system": st.column_config.TextColumn("Primary System")
                    }
                )
            except Exception as e:
                st.error(f"Error fetching division catalog: {e}")

        with col_g2:
            st.markdown("##### Global Ticker Broadcast Setup")
            st.caption("Push company-wide banners or lock global ticker modes.")
            
            try:
                with engine.connect() as conn:
                    ticker_cfg = pd.read_sql(text("SELECT * FROM portal_ticker_config WHERE id = 1;"), conn)
                
                if not ticker_cfg.empty:
                    cfg_row = ticker_cfg.iloc[0]
                    with st.form("admin_ticker_broadcast_form"):
                        is_enabled = st.checkbox("Ticker Enabled Globally", value=bool(cfg_row.get("is_enabled", True)))
                        active_mode = st.selectbox(
                            "Default Broadcast Mode",
                            ["DIVISIONS", "TOP_ITEMS", "TOP_CUSTOMERS", "BROADCAST"],
                            index=["DIVISIONS", "TOP_ITEMS", "TOP_CUSTOMERS", "BROADCAST"].index(cfg_row.get("active_mode", "DIVISIONS"))
                        )
                        b_msg = st.text_area("Broadcast Announcement Message", value=str(cfg_row.get("broadcast_message", "")))
                        
                        submit_tick = st.form_submit_button("Update Global Notice", type="primary")
                        if submit_tick:
                            with engine.begin() as conn:
                                conn.execute(
                                    text("""
                                        UPDATE portal_ticker_config 
                                        SET is_enabled = :en, active_mode = :mode, broadcast_message = :msg, updated_at = NOW()
                                        WHERE id = 1;
                                    """),
                                    {"en": is_enabled, "mode": active_mode, "msg": b_msg}
                                )
                            st.cache_data.clear()
                            st.success("Global ticker settings refreshed.")
                            st.rerun()
            except Exception as e:
                st.warning(f"Error loading ticker configuration: {e}")
                
        # Call the YAML editor here inside an expander
        with st.expander("🛠️ Advanced: Application Configuration (`config.yaml`)", expanded=False):
            render_yaml_config_editor()
    # =========================================================================
    # TAB 4: SYNC PIPELINE & STAGING HEALTH
    # =========================================================================
    with tab_sync:
        st.subheader("Data Bridges & Staging Synchronization Monitor")
        st.caption("Live high-watermark timestamps tracking incremental syncs from Shoper, Tally, and staging pipelines.")

        try:
            with engine.connect() as conn:
                sync_df = pd.read_sql(
                    text("SELECT source_table, source_system, last_synced_at FROM sync_state ORDER BY last_synced_at DESC;"),
                    conn
                )

            if sync_df.empty:
                st.info("No sync watermarks logged yet in `sync_state`.")
            else:
                col_s1, col_s2, col_s3 = st.columns(3)
                col_s1.metric("Synced Canonical Bridges", len(sync_df))
                
                shoper_last = sync_df[sync_df["source_system"] == "shoper"]["last_synced_at"].max()
                tally_last = sync_df[sync_df["source_system"] == "tally"]["last_synced_at"].max()
                
                col_s2.metric("Shoper POS Sync", str(shoper_last)[:16] if pd.notna(shoper_last) else "No Runs")
                col_s3.metric("Tally ERP Sync", str(tally_last)[:16] if pd.notna(tally_last) else "No Runs")

                st.markdown("---")
                st.dataframe(
                    sync_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "source_table": st.column_config.TextColumn("Canonical Entity / Table"),
                        "source_system": st.column_config.TextColumn("Source Origin (Shoper / Tally)"),
                        "last_synced_at": st.column_config.DatetimeColumn("High-Watermark Sync Timestamp", format="YYYY-MM-DD HH:mm:ss")
                    }
                )
        except Exception as e:
            st.error(f"Error loading sync health state: {e}")


if __name__ == "__main__":
    show_admin_page()