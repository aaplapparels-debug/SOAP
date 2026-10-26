"""
Legacy Tally / Google Sheets Sales Performance Dashboard
Integrated directly into SOAP Portal (bypasses legacy OTP login).
"""
import os
import gspread
import pandas as pd
import plotly.express as px
import streamlit as st
from google.oauth2.service_account import Credentials
from ui.style_loader import load_css


SPREADSHEET_NAME = "AAPL-Jockey-Reporter"
WORKSHEET_JC = "JC_Master"


def format_inr(val):
    try:
        val = float(val)
        is_neg = val < 0
        val = abs(val)
        s, *d = f"{val:.2f}".split(".")
        r = s[-3:]
        s = s[:-3]
        groups = []
        while s:
            groups.append(s[-2:])
            s = s[:-2]
        groups.reverse()
        formatted_int = ",".join(groups + [r]) if groups else r
        res = f"₹{formatted_int}.{d[0]}"
        return f"-{res}" if is_neg else res
    except Exception:
        return f"₹{val}"


def sort_jc_months(months_list):
    def parse_m(m):
        m_str = str(m).strip().upper()
        if m_str.startswith("M") and m_str[1:].isdigit():
            return int(m_str[1:])
        return 999
    return sorted(
        [m for m in set(months_list) if str(m).strip() != ""],
        key=parse_m,
        reverse=True,
    )


def get_gspread_client():
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        return gspread.service_account_from_dict(creds_dict)
    elif os.path.exists("credentials.json"):
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        return gspread.authorize(creds)
    else:
        st.error("Missing GCP Service Account in secrets.toml or credentials.json")
        return None


@st.cache_data(ttl=300)
def load_legacy_jc_data():
    try:
        gc = get_gspread_client()
        if not gc:
            return pd.DataFrame()
        sh = gc.open(SPREADSHEET_NAME)
        ws_jc = sh.worksheet(WORKSHEET_JC).get_all_records()
        df_jc = pd.DataFrame(ws_jc)
        if not df_jc.empty:
            df_jc.columns = df_jc.columns.astype(str).str.strip()
            col_map = {
                "Achv Value": "Achv_Value",
                "Achv_value": "Achv_Value",
                "Achieved Value": "Achv_Value",
                "Achieved_Value": "Achv_Value",
                "Sales Value": "Achv_Value",
            }
            df_jc.rename(columns=col_map, inplace=True)
        return df_jc
    except Exception as e:
        st.error(f"Error connecting to Google Sheet: {e}")
        return pd.DataFrame()


def show_legacy_sales_dashboard():
    load_css()
    st.title("📊 Legacy Tally Sales Performance (EOD Sheet)")
    st.caption("Live feed from Google Sheet (`AAPL-Jockey-Reporter` → `JC_Master`).")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Refresh Sheet Data", key="btn_refresh_legacy_sheet"):
            st.cache_data.clear()
            st.rerun()

    df_jc = load_legacy_jc_data()
    if df_jc.empty:
        st.warning("No data retrieved from JC_Master sheet.")
        return

    # User role check from existing session
    user_role = st.session_state.get("user_role", "Sales")
    is_admin_or_mgr = user_role in ["Admin", "Manager"]

    all_jcs = (
        sort_jc_months(df_jc["JC_Month"].tolist())
        if "JC_Month" in df_jc.columns
        else ["M1"]
    )
    selected_jc = st.selectbox("Select JC Month:", options=all_jcs, key="legacy_sel_jc")

    current_m_num = (
        int(selected_jc.replace("M", ""))
        if selected_jc.startswith("M") and selected_jc[1:].isdigit()
        else 1
    )

    df_jc_curr = df_jc[df_jc["JC_Month"] == selected_jc].copy()
    for col in ["Target_Pcs", "Achv_Pcs", "Balance_Pcs"]:
        if col in df_jc_curr.columns:
            df_jc_curr[col] = pd.to_numeric(df_jc_curr[col], errors="coerce").fillna(0)

    if is_admin_or_mgr and "Achv_Value" in df_jc_curr.columns:
        df_jc_curr["Achv_Value"] = pd.to_numeric(
            df_jc_curr["Achv_Value"], errors="coerce"
        ).fillna(0)

    tot_target_pcs = df_jc_curr["Target_Pcs"].sum()
    tot_achv_pcs = df_jc_curr["Achv_Pcs"].sum()
    tot_bal_pcs = df_jc_curr["Balance_Pcs"].sum()
    overall_pct = (tot_achv_pcs / tot_target_pcs * 100) if tot_target_pcs > 0 else 0.0

    # KPI Metrics
    if is_admin_or_mgr:
        tot_achv_val = (
            df_jc_curr["Achv_Value"].sum()
            if "Achv_Value" in df_jc_curr.columns
            else 0
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Target (Pcs)", f"{tot_target_pcs:,.0f}")
        c2.metric("Achieved (Pcs)", f"{tot_achv_pcs:,.0f}")
        c3.metric("Achievement %", f"{overall_pct:.1f}%")
        c4.metric("Balance Target (Pcs)", f"{tot_bal_pcs:,.0f}")
        c5.metric("Sales Achieved (Value)", format_inr(tot_achv_val))
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Target (Pcs)", f"{tot_target_pcs:,.0f}")
        c2.metric("Achieved (Pcs)", f"{tot_achv_pcs:,.0f}")
        c3.metric("Achievement %", f"{overall_pct:.1f}%")
        c4.metric("Balance Target (Pcs)", f"{tot_bal_pcs:,.0f}")

    st.divider()

    # Tables: Current Division Breakdown & History Summary
    st.subheader(f"📋 Sales Performance Tables ({selected_jc})")
    col_left, col_right = st.columns([6, 4])

    with col_left:
        st.markdown(f"**Current Month ({selected_jc}) Division Breakdown**")
        display_cols = ["Division", "Target_Pcs", "Achv_Pcs", "Balance_Pcs"]
        if is_admin_or_mgr and "Achv_Value" in df_jc_curr.columns:
            display_cols.append("Achv_Value")

        df_curr_table = df_jc_curr[[c for c in display_cols if c in df_jc_curr.columns]].copy()
        df_curr_table["Achv_%"] = df_curr_table.apply(
            lambda r: f"{(r['Achv_Pcs']/r['Target_Pcs']*100):.1f}%" if r["Target_Pcs"] > 0 else "0.0%",
            axis=1,
        )
        if is_admin_or_mgr and "Achv_Value" in df_curr_table.columns:
            df_curr_table["Achv_Value"] = df_curr_table["Achv_Value"].apply(format_inr)

        st.dataframe(df_curr_table, use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("**Prior Months Performance Summary**")
        prior_jcs = [
            m for m in all_jcs
            if (int(m.replace("M", "")) if m.startswith("M") and m[1:].isdigit() else 999) < current_m_num
        ]
        if prior_jcs:
            hist_records = []
            for m_code in prior_jcs:
                df_m = df_jc[df_jc["JC_Month"] == m_code]
                m_tgt_pcs = pd.to_numeric(df_m["Target_Pcs"], errors="coerce").sum()
                m_achv_pcs = pd.to_numeric(df_m["Achv_Pcs"], errors="coerce").sum()
                m_pct = (m_achv_pcs / m_tgt_pcs * 100) if m_tgt_pcs > 0 else 0.0

                row_dict = {
                    "JC Month": m_code,
                    "Target (Pcs)": f"{m_tgt_pcs:,.0f}",
                    "Achv (Pcs)": f"{m_achv_pcs:,.0f}",
                    "Achv %": f"{m_pct:.1f}%",
                }
                if is_admin_or_mgr and "Achv_Value" in df_m.columns:
                    m_val = pd.to_numeric(df_m["Achv_Value"], errors="coerce").sum()
                    row_dict["Achv (Value)"] = format_inr(m_val)
                hist_records.append(row_dict)

            st.dataframe(pd.DataFrame(hist_records), use_container_width=True, hide_index=True)
        else:
            st.info("Currently viewing M1. Prior month history will appear from M2 onwards.")

    st.divider()

    # Performance Trend Chart
    st.subheader("📈 Journey Cycle Performance Trend")
    df_trend = df_jc.groupby("JC_Month", as_index=False)[["Target_Pcs", "Achv_Pcs"]].sum()
    df_trend["_order"] = df_trend["JC_Month"].apply(
        lambda x: int(str(x).replace("M", "")) if str(x).startswith("M") and str(x)[1:].isdigit() else 999
    )
    df_trend = df_trend.sort_values("_order").drop(columns=["_order"])
    df_trend["Achv_Pct"] = df_trend.apply(
        lambda r: f"{(r['Achv_Pcs'] / r['Target_Pcs'] * 100):.1f}%" if r["Target_Pcs"] > 0 else "0.0%",
        axis=1,
    )

    fig_perf = px.bar(
        df_trend,
        x="JC_Month",
        y=["Target_Pcs", "Achv_Pcs"],
        barmode="group",
        labels={"value": "Units (Pcs)", "variable": "Metrics", "JC_Month": "Journey Cycle"},
        color_discrete_sequence=["#0d6efd", "#198754"],
    )
    for trace in fig_perf.data:
        if trace.name == "Target_Pcs":
            trace.name = "Target (Pcs)"
        elif trace.name == "Achv_Pcs":
            trace.name = "Achieved (Pcs)"
            trace.text = df_trend["Achv_Pct"]
            trace.textposition = "auto"

    st.plotly_chart(fig_perf, use_container_width=True)