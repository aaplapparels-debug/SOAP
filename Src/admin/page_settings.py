import streamlit as st
from sqlalchemy import text
from analytics.ticker_helper import get_ticker_config, get_engine

def render_ticker_admin_settings():
    st.subheader("📢 Portal Ticker Settings")
    cfg = get_ticker_config() or {}
    engine = get_engine()

    with st.form("ticker_config_form"):
        col1, col2 = st.columns(2)
        with col1:
            is_enabled = st.checkbox("Enable Global Ticker", value=cfg.get("is_enabled", True))
            active_mode = st.selectbox(
                "Display Mode",
                options=["BROADCAST", "TOP_ITEMS", "TOP_CUSTOMERS"],
                index=["BROADCAST", "TOP_ITEMS", "TOP_CUSTOMERS"].index(cfg.get("active_mode", "BROADCAST"))
            )
        with col2:
            metric_type = st.selectbox(
                "Customer Metric (if Customers selected)",
                options=["QTY", "VALUE"],
                index=["QTY", "VALUE"].index(cfg.get("metric_type", "QTY"))
            )
            top_limit = st.number_input("Top N Entities", min_value=5, max_value=50, value=cfg.get("top_limit", 15))

        broadcast_msg = st.text_area(
            "Broadcast Announcement Message", 
            value=cfg.get("broadcast_message", "")
        )

        submitted = st.form_submit_button("💾 Save Ticker Configuration", type="primary")
        if submitted:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE portal_ticker_config
                        SET active_mode = :mode,
                            broadcast_message = :msg,
                            top_limit = :limit,
                            metric_type = :metric,
                            is_enabled = :enabled,
                            updated_at = NOW()
                        WHERE id = 1;
                    """),
                    {
                        "mode": active_mode,
                        "msg": broadcast_msg,
                        "limit": top_limit,
                        "metric": metric_type,
                        "enabled": is_enabled
                    }
                )
            st.cache_data.clear()
            st.success("Ticker configuration updated successfully!")
            st.rerun()