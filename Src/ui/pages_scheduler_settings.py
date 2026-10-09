"""
Src/ui/pages_scheduler_settings.py
Management console for:
1. Bucket configuration & WhatsApp templates in NeonDB (via ui.db_helper).
2. GitHub Actions cron scheduling via REST API.
"""

import base64
from datetime import time
import pandas as pd
import requests
import streamlit as st
import yaml
from sqlalchemy import text

# Import existing cached engine helper from ui
try:
    from ui.db_helper import get_engine
except ImportError:
    from db_helper import get_engine

# ==========================================
# GITHUB API HELPERS
# ==========================================

def get_github_file(repo: str, path: str, token: str, branch: str = "main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return data["sha"], content
    return None, None


def commit_github_file(repo: str, path: str, token: str, new_content: str, sha: str, message: str, branch: str = "main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    payload = {
        "message": message,
        "content": base64.b64encode(new_content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": branch
    }
    res = requests.put(url, headers=headers, json=payload)
    return res.status_code in [200, 201]


def trigger_workflow(repo: str, token: str, workflow_file: str, branch: str = "main"):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    res = requests.post(url, headers=headers, json={"ref": branch})
    return res.status_code == 204


# ==========================================
# MAIN PAGE RENDERER (ZERO ARGUMENTS)
# ==========================================

def render_scheduler_settings():
    st.title("⚙️ Outstanding Follow-up Engine Settings")

    engine = get_engine()

    tab1, tab2 = st.tabs(["📦 Bucket & WhatsApp Rules", "⏰ GitHub Cron Schedule"])

    # -------------------------------------------------------------
    # TAB 1: BUCKET CONFIGURATION & WHATSAPP TEMPLATES
    # -------------------------------------------------------------
    with tab1:
        st.subheader("Bucket Definitions & Message Templates")
        st.caption("Configure overdue day intervals, cadence cooldowns, and personalized WhatsApp messages.")

        query = """
            SELECT id, scope, COALESCE(party_name, 'ALL (Global)') AS party,
                   min_days, COALESCE(max_days, 9999) AS max_days, 
                   bucket_label, severity_level, channel, cooldown_days,
                   COALESCE(message_template, '') AS message_template, is_active
            FROM followup_bucket_config
            ORDER BY scope DESC, min_days ASC;
        """
        
        # Explicit connection checkout and instant release
        with engine.connect() as conn:
            df_buckets = pd.read_sql(text(query), conn)

        st.dataframe(
            df_buckets[[
                "id", "scope", "party", "bucket_label", "min_days", 
                "max_days", "severity_level", "channel", "cooldown_days", "is_active"
            ]],
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        with st.expander("✏️ Add or Edit Bucket Configuration", expanded=False):
            action = st.radio("Mode", ["Update Existing", "Create New Bucket"], horizontal=True)

            selected_id = None
            default_row = None

            if action == "Update Existing" and not df_buckets.empty:
                bucket_labels = (
                    df_buckets["bucket_label"] + " (" + df_buckets["scope"] + " - " + df_buckets["party"] + ")"
                ).tolist()
                selected_label = st.selectbox("Select Bucket to Edit", bucket_labels)
                selected_idx = bucket_labels.index(selected_label)
                default_row = df_buckets.iloc[selected_idx]
                selected_id = int(default_row["id"])

            c1, c2, c3 = st.columns(3)
            with c1:
                scope = st.selectbox("Scope", ["GLOBAL", "PARTY"], 
                                     index=0 if default_row is None or default_row["scope"] == "GLOBAL" else 1)
                party_name = st.text_input("Party Name (Exact match)", 
                                           value="" if default_row is None or default_row["party"] == "ALL (Global)" else default_row["party"]) if scope == "PARTY" else None
                label = st.text_input("Bucket Label", value=default_row["bucket_label"] if default_row is not None else "Bucket 1")

            with c2:
                min_days = st.number_input("Min Overdue Days", min_value=0, value=int(default_row["min_days"]) if default_row is not None else 0)
                max_days = st.number_input("Max Overdue Days (9999 = No upper bound)", min_value=0, value=int(default_row["max_days"]) if default_row is not None else 30)
                cooldown = st.number_input("Cooldown Days (Silence buffer)", min_value=1, value=int(default_row["cooldown_days"]) if default_row is not None else 3)

            with c3:
                severity = st.selectbox("Severity Level", ["REMINDER", "OVERDUE", "URGENT", "CRITICAL"],
                                        index=["REMINDER", "OVERDUE", "URGENT", "CRITICAL"].index(default_row["severity_level"]) if default_row is not None else 0)
                channel = st.selectbox("Channel", ["WHATSAPP", "MANUAL_CALL", "EMAIL"],
                                       index=["WHATSAPP", "MANUAL_CALL", "EMAIL"].index(default_row["channel"]) if default_row is not None else 0)
                is_active = st.checkbox("Active", value=bool(default_row["is_active"]) if default_row is not None else True)

            st.markdown("#### WhatsApp Message Template")
            st.caption("Tags: `{customer_name}`, `{overdue_amount}`, `{overdue_days}`, `{bill_refs}`, `{salesperson}`")
            
            template_val = default_row["message_template"] if default_row is not None else (
                "Dear {customer_name}, an overdue amount of ₹{overdue_amount:,.2f} "
                "remains pending ({overdue_days} days overdue). Bill Refs: {bill_refs}. "
                "Kindly arrange payment. Regards, AAPL."
            )

            message_template = st.text_area("Message Body", value=template_val, height=110)

            with st.container():
                st.markdown("**Preview:**")
                try:
                    preview_text = message_template.format(
                        customer_name="ABC Garments",
                        overdue_amount=45250.00,
                        overdue_days=18,
                        bill_refs="INV-1021, INV-1044",
                        salesperson="Rajesh"
                    )
                    st.info(preview_text)
                except Exception as e:
                    st.error(f"Template formatting error: {e}")

            if st.button("💾 Save Bucket to Database", type="primary"):
                actual_max = None if max_days >= 9999 else int(max_days)
                with engine.begin() as conn:
                    if action == "Create New Bucket":
                        insert_stmt = text("""
                            INSERT INTO followup_bucket_config 
                            (scope, party_name, min_days, max_days, bucket_label, severity_level, channel, cooldown_days, message_template, is_active)
                            VALUES (:scope, :party, :min_d, :max_d, :lbl, :sev, :chn, :cd, :tpl, :act)
                            ON CONFLICT (scope, party_name, min_days) DO UPDATE SET
                                max_days = EXCLUDED.max_days,
                                bucket_label = EXCLUDED.bucket_label,
                                severity_level = EXCLUDED.severity_level,
                                channel = EXCLUDED.channel,
                                cooldown_days = EXCLUDED.cooldown_days,
                                message_template = EXCLUDED.message_template,
                                is_active = EXCLUDED.is_active;
                        """)
                        conn.execute(insert_stmt, {
                            "scope": scope, "party": party_name, "min_d": int(min_days),
                            "max_d": actual_max, "lbl": label, "sev": severity,
                            "chn": channel, "cd": int(cooldown), "tpl": message_template,
                            "act": is_active
                        })
                    else:
                        update_stmt = text("""
                            UPDATE followup_bucket_config
                            SET scope = :scope, party_name = :party, min_days = :min_d, max_days = :max_d,
                                bucket_label = :lbl, severity_level = :sev, channel = :chn,
                                cooldown_days = :cd, message_template = :tpl, is_active = :act
                            WHERE id = :id;
                        """)
                        conn.execute(update_stmt, {
                            "id": selected_id, "scope": scope, "party": party_name,
                            "min_d": int(min_days), "max_d": actual_max, "lbl": label,
                            "sev": severity, "chn": channel, "cd": int(cooldown),
                            "tpl": message_template, "act": is_active
                        })

                st.success("Bucket configuration updated successfully!")
                st.rerun()

    # -------------------------------------------------------------
    # TAB 2: GITHUB CRON SCHEDULER
    # -------------------------------------------------------------
    with tab2:
        st.subheader("GitHub Actions Daily Runner")

        gh_cfg = st.secrets.get("github", {})
        token = gh_cfg.get("token")
        repo = gh_cfg.get("repo", "aaplapparels-debug/SOAP")
        path = gh_cfg.get("workflow_path", ".github/workflows/outstanding_followup.yml")
        branch = gh_cfg.get("branch", "main")

        if not token:
            st.warning("GitHub token missing in secrets.")
            return

        sha, yaml_raw = get_github_file(repo, path, token, branch)
        if not sha:
            st.error(f"Could not load workflow file `{path}` from branch `{branch}`.")
            return

        workflow_dict = yaml.safe_load(yaml_raw)
        current_cron = "30 4 * * *"
        try:
            current_cron = workflow_dict["on"]["schedule"][0]["cron"]
        except Exception:
            pass

        st.info(f"**Current Remote Cron Expression:** `{current_cron}` (UTC)")

        col_time, col_days = st.columns(2)
        with col_time:
            selected_time = st.time_input("Daily Execution Time (IST)", value=time(10, 0), step=1800)
        with col_days:
            active_days = st.multiselect(
                "Run Days",
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
                default=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            )

        total_mins_ist = selected_time.hour * 60 + selected_time.minute
        total_mins_utc = (total_mins_ist - 330) % 1440
        utc_h = total_mins_utc // 60
        utc_m = total_mins_utc % 60

        day_map = {
            "Monday": "1", "Tuesday": "2", "Wednesday": "3",
            "Thursday": "4", "Friday": "5", "Saturday": "6"
        }
        days_cron = ",".join(sorted([day_map[d] for d in active_days])) if active_days else "*"
        new_cron = f"{utc_m} {utc_h} * * {days_cron}"

        st.caption(f"Calculated UTC Schedule: `{new_cron}`")

        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("💾 Update GitHub Cron", type="primary"):
                if "on" not in workflow_dict:
                    workflow_dict["on"] = {}
                workflow_dict["on"]["schedule"] = [{"cron": new_cron}]
                workflow_dict["on"]["workflow_dispatch"] = None

                new_yaml = yaml.dump(workflow_dict, sort_keys=False, default_flow_style=False)
                with st.spinner("Pushing commit to GitHub..."):
                    ok = commit_github_file(
                        repo, path, token, new_yaml, sha,
                        f"chore: update scheduler cron to {selected_time.strftime('%H:%M')} IST",
                        branch
                    )
                if ok:
                    st.success("Workflow cron updated on GitHub!")
                    st.rerun()
                else:
                    st.error("Failed to update GitHub workflow.")

        with c_btn2:
            if st.button("⚡ Trigger Scheduler Run Now"):
                with st.spinner("Dispatching GitHub Action..."):
                    if trigger_workflow(repo, token, "outstanding_followup.yml", branch):
                        st.success("GitHub Action triggered! Check your Actions tab.")
                    else:
                        st.error("Workflow trigger failed.")