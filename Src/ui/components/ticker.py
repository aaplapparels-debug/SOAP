"""
Src/ui/components/ticker.py
CSS-driven top ticker with quick settings popover.
Supports Divisions, Top Stock Items, Customers, and Broadcasts.
"""

import streamlit as st
from analytics.ticker_helper import (
    get_ticker_config, 
    get_division_sales_ticker_data,
    get_item_sales_ticker_data, 
    get_customer_sales_ticker_data
)


def render_global_ticker():
    config = get_ticker_config() or {}
    if not config.get("is_enabled", True):
        return

    # 1. State Initializations (Ensures current_scope is ALWAYS defined)
    db_mode = config.get("active_mode", "DIVISIONS")
    if "user_ticker_mode" not in st.session_state:
        st.session_state["user_ticker_mode"] = db_mode

    if "user_ticker_scope" not in st.session_state:
        st.session_state["user_ticker_scope"] = "JC"

    if "user_ticker_metric" not in st.session_state:
        st.session_state["user_ticker_metric"] = config.get("metric_type", "QTY")

    current_mode = st.session_state["user_ticker_mode"]
    current_scope = st.session_state["user_ticker_scope"]
    current_metric = st.session_state["user_ticker_metric"]
    limit = int(config.get("top_limit", 15))

    badges = []

    # 2. Render Selected View
    if current_mode == "DIVISIONS":
        data = get_division_sales_ticker_data(scope=current_scope, metric=current_metric)
        scope_tag = "JC" if current_scope == "JC" else "YTD"
        for d in data:
            arrow = "▲" if d["trend"] == "UP" else "▼"
            color = "#00E676" if d["trend"] == "UP" else "#FF5252"
            cy_disp = f"{int(d['cy']):,} pcs" if current_metric == "QTY" else f"₹{d['cy']:,.0f}"
            ly_disp = f"{int(d['ly']):,} pcs" if current_metric == "QTY" else f"₹{d['ly']:,.0f}"

            badges.append(
                f'<span class="ticker-badge">'
                f'🏢 <strong>DIV: {d["name"]}</strong> [{scope_tag}]: {cy_disp} '
                f'<span style="color:{color}; font-weight:700;">{arrow} {abs(d["pct"])}%</span> '
                f'<span class="ly-sub">(LY: {ly_disp})</span>'
                f'</span>'
            )

    elif current_mode == "TOP_ITEMS":
        data = get_item_sales_ticker_data(scope=current_scope, limit=limit)
        scope_tag = "JC" if current_scope == "JC" else "YTD"
        for d in data:
            arrow = "▲" if d["trend"] == "UP" else "▼"
            color = "#00E676" if d["trend"] == "UP" else "#FF5252"
            badges.append(
                f'<span class="ticker-badge">'
                f'📦 <strong>{d["name"]}</strong> [{scope_tag}]: {d["cy"]:,} pcs '
                f'<span style="color:{color}; font-weight:700;">{arrow} {abs(d["pct"])}%</span> '
                f'<span class="ly-sub">(LY: {d["ly"]:,})</span>'
                f'</span>'
            )

    elif current_mode == "TOP_CUSTOMERS":
        data = get_customer_sales_ticker_data(scope=current_scope, metric=current_metric, limit=limit)
        scope_tag = "JC" if current_scope == "JC" else "YTD"
        for d in data:
            arrow = "▲" if d["trend"] == "UP" else "▼"
            color = "#00E676" if d["trend"] == "UP" else "#FF5252"
            cy_disp = f"{int(d['cy']):,} pcs" if current_metric == "QTY" else f"₹{d['cy']:,.0f}"
            ly_disp = f"{int(d['ly']):,} pcs" if current_metric == "QTY" else f"₹{d['ly']:,.0f}"

            badges.append(
                f'<span class="ticker-badge">'
                f'👤 <strong>{d["name"]}</strong> [{scope_tag}]: {cy_disp} '
                f'<span style="color:{color}; font-weight:700;">{arrow} {abs(d["pct"])}%</span> '
                f'<span class="ly-sub">(LY: {ly_disp})</span>'
                f'</span>'
            )

    else:
        msg = config.get("broadcast_message", "Welcome to AAPL SOAP Portal.")
        badges.append(
            f'<span class="ticker-badge broadcast-msg">'
            f'📢 <strong>NOTICE:</strong> {msg}'
            f'</span>'
        )

    single_stream = "".join(badges)
    full_content = single_stream + single_stream

    ticker_html = (
        '<style>'
        '.ticker-wrapper {'
        '  width: 100%;'
        '  overflow: hidden;'
        '  background: #111827;'
        '  border-bottom: 2px solid #1F2937;'
        '  padding: 7px 0;'
        '  white-space: nowrap;'
        '  box-sizing: border-box;'
        '  border-radius: 6px;'
        '}'
        '.ticker-content {'
        '  display: inline-block;'
        '  white-space: nowrap;'
        '  vertical-align: middle;'
        '  animation: marquee 30s linear infinite;'
        '}'
        '.ticker-content:hover {'
        '  animation-play-state: paused;'
        '}'
        '.ticker-badge {'
        '  display: inline-block;'
        '  margin-right: 32px;'
        '  color: #E5E7EB;'
        '  font-size: 13px;'
        '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'
        '  vertical-align: middle;'
        '}'
        '.ly-sub {'
        '  color: #9CA3AF;'
        '  font-size: 11px;'
        '  margin-left: 4px;'
        '}'
        '.broadcast-msg {'
        '  font-size: 13.5px;'
        '  letter-spacing: 0.3px;'
        '  color: #F3F4F6;'
        '}'
        '@keyframes marquee {'
        '  0%   { transform: translateX(0%); }'
        '  100% { transform: translateX(-50%); }'
        '}'
        '</style>'
        f'<div class="ticker-wrapper"><div class="ticker-content">{full_content}</div></div>'
    )

    # 3. Two-Column Layout: Wide Marquee + Popover
    col_ticker, col_gear = st.columns([30, 1.2])

    with col_ticker:
        st.markdown(ticker_html, unsafe_allow_html=True)

    with col_gear:
        with st.popover("⚙️", help="Customize ticker view"):
            st.markdown("##### ⚙️ Ticker Preferences")

            mode_options = ["DIVISIONS", "TOP_ITEMS", "TOP_CUSTOMERS", "BROADCAST"]
            selected_mode = st.radio(
                "Display Mode",
                options=mode_options,
                format_func=lambda x: {
                    "DIVISIONS": "🏢 Division Summary",
                    "TOP_ITEMS": "📦 Top Stock Items",
                    "TOP_CUSTOMERS": "👤 Top Customers",
                    "BROADCAST": "📢 Broadcast Notice"
                }[x],
                index=mode_options.index(current_mode) if current_mode in mode_options else 0,
                key="radio_ticker_mode"
            )

            # Ensure selected_scope defaults cleanly to current_scope
            selected_scope = current_scope
            if selected_mode in ("DIVISIONS", "TOP_ITEMS", "TOP_CUSTOMERS"):
                selected_scope = st.radio(
                    "Comparison Scope",
                    options=["JC", "YTD"],
                    format_func=lambda x: "Current Journey Cycle (JC)" if x == "JC" else "Financial Year to Date (YTD)",
                    index=["JC", "YTD"].index(current_scope) if current_scope in ["JC", "YTD"] else 0,
                    key="radio_ticker_scope"
                )

            # Ensure selected_metric defaults cleanly to current_metric
            selected_metric = current_metric
            if selected_mode in ("DIVISIONS", "TOP_CUSTOMERS"):
                selected_metric = st.selectbox(
                    "Metric",
                    options=["QTY", "VALUE"],
                    format_func=lambda x: "Quantity (Pieces)" if x == "QTY" else "Value (₹ Net Amount)",
                    index=["QTY", "VALUE"].index(current_metric) if current_metric in ["QTY", "VALUE"] else 0,
                    key="select_ticker_metric"
                )

            # Refresh when any parameter is adjusted
            if (
                selected_mode != current_mode
                or selected_scope != current_scope
                or selected_metric != current_metric
            ):
                st.session_state["user_ticker_mode"] = selected_mode
                st.session_state["user_ticker_scope"] = selected_scope
                st.session_state["user_ticker_metric"] = selected_metric
                st.rerun()