"""
AAPL Sales & Operations Automation Portal (SOAP)
Main entry point with Google OAuth, Mobile-First Action Hub, and Page Routing.
"""

from datetime import date
import secrets
from config_loader import load_config
from google_auth_oauthlib.flow import Flow
from pages_delivery_dashboard import show_delivery_dashboard
from pages_executive import show_executive_dashboard
from pages_outstanding import show_outstanding_report
from pages_sales360 import show_sales_360
from pages_sales_dashboard import show_sales_dashboard
from pages_stock import show_stock_position
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import streamlit as st

st.set_page_config(
    page_title="AAPL Sales & Operations Portal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = load_config()
dashboard_cfg = config["dashboard"]
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


# =====================================================================
# 1. DATABASE & LIVE METRICS ENGINE
# =====================================================================
@st.cache_resource
def get_engine():
    return create_engine(
        config["postgres"]["connection_string"], poolclass=NullPool
    )


def format_inr(val):
    if val is None or val == 0:
        return "₹0"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 10000000:
        return f"{sign}₹{abs_val / 10000000:.2f} Cr"
    elif abs_val >= 100000:
        return f"{sign}₹{abs_val / 100000:.2f} L"
    elif abs_val >= 1000:
        return f"{sign}₹{abs_val / 1000:.1f} K"
    else:
        return f"{sign}₹{abs_val:,.0f}"


@st.cache_data(ttl=180)
def fetch_hub_live_metrics():
    """Fetches fast aggregated metrics for the mobile action tiles."""
    engine = get_engine()
    with engine.connect() as conn:
        # 1. Dispatches Pending (Last 30 days)
        open_disp = (
            conn.execute(
                text("""
            SELECT COUNT(DISTINCT CONCAT(s.division, '-', s.doc_prefix, '-', s.doc_no))
            FROM sales s
            LEFT JOIN delivery_status d 
                ON s.division = d.division 
                AND s.doc_prefix = d.doc_prefix 
                AND CAST(s.doc_no AS VARCHAR) = d.doc_no
            WHERE s.source_system = 'shoper'
              AND s.sale_date >= CURRENT_DATE - INTERVAL '30 days'
              AND COALESCE(d.status, 'Open') = 'Open'
        """)
            ).scalar()
            or 0
        )

        # 2. Total Outstanding Receivables (Tally)
        total_os = (
            conn.execute(
                text("""
            SELECT COALESCE(SUM(pending_amount), 0) FROM outstanding_debtors
        """)
            ).scalar()
            or 0
        )

        # 3. Stock Value (Shoper)
        total_stock = (
            conn.execute(
                text("""
            SELECT COALESCE(SUM(stock_value), 0) FROM items WHERE source_system = 'shoper'
        """)
            ).scalar()
            or 0
        )

        # 4. MTD Sales (Current Month Achievement)
        mtd_sales = (
            conn.execute(
                text("""
            SELECT COALESCE(SUM(s.net_value * COALESCE(s.sign_multiplier, 1)), 0)
            FROM sales s
            WHERE s.source_system = 'shoper'
              AND s.sale_date >= DATE_TRUNC('month', CURRENT_DATE)
        """)
            ).scalar()
            or 0
        )

        # 5. Bottleneck Invoices (Pending > 48 Hours)
        bottlenecks = (
            conn.execute(
                text("""
            SELECT COUNT(DISTINCT CONCAT(s.division, '-', s.doc_prefix, '-', s.doc_no))
            FROM sales s
            LEFT JOIN delivery_status d 
                ON s.division = d.division 
                AND s.doc_prefix = d.doc_prefix 
                AND CAST(s.doc_no AS VARCHAR) = d.doc_no
            WHERE s.source_system = 'shoper'
              AND s.sale_date BETWEEN CURRENT_DATE - INTERVAL '20 days' AND CURRENT_DATE - INTERVAL '2 days'
              AND COALESCE(d.status, 'Open') = 'Open'
        """)
            ).scalar()
            or 0
        )

    return {
        "open_dispatches": int(open_disp),
        "outstanding_str": format_inr(total_os),
        "stock_str": format_inr(total_stock),
        "mtd_sales_str": format_inr(mtd_sales),
        "bottlenecks": int(bottlenecks),
    }


# =====================================================================
# 2. OAUTH HELPERS
# =====================================================================
def get_oauth_flow() -> Flow:
    if "oauth" in dashboard_cfg:
        oauth_cfg = dashboard_cfg["oauth"]
        redirect_uri = oauth_cfg["web"]["redirect_uris"][0]
        return Flow.from_client_config(
            client_config=dict(oauth_cfg),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
    return Flow.from_client_secrets_file(
        dashboard_cfg.get("oauth_client_secret_file", "client_secret.json"),
        scopes=SCOPES,
        redirect_uri=dashboard_cfg.get(
            "redirect_uri", "https://aapl-soap.streamlit.app"
        ),
    )


def get_user_role(email: str):
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT role FROM dashboard_users WHERE email = :e AND"
                " is_active = TRUE"
            ),
            {"e": email.lower().strip()},
        ).fetchone()
    return result[0] if result else None


# =====================================================================
# 3. MOBILE-OPTIMIZED HOME PAGE
# =====================================================================
def show_home():
    # --- Inject Mobile-First Responsive CSS ---
    st.markdown(
        """
    <style>
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
        }
        .mobile-header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #ffffff;
            padding: 10px 14px;
            border-radius: 12px;
            margin-bottom: 12px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
            border: 1px solid #E2E8F0;
        }
        .pulse-card {
            background: linear-gradient(135deg, #FFF5F5 0%, #FED7D7 100%);
            border-left: 5px solid #E53E3E;
            padding: 12px 14px;
            border-radius: 12px;
            margin-top: 10px;
            margin-bottom: 14px;
        }
        .pulse-card-title {
            font-size: 12px;
            font-weight: 700;
            color: #9B2C2C;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .pulse-card-desc {
            font-size: 13px;
            color: #2D3748;
            margin-top: 2px;
        }
        /* Lock columns into a 2x2 grid on mobile viewports */
        @media (max-width: 640px) {
            div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
                gap: 8px !important;
            }
            div[data-testid="column"] {
                flex: 1 1 calc(50% - 10px) !important;
                min-width: calc(50% - 10px) !important;
            }
        }
        /* Touch Card Button Styling */
        div[data-testid="column"] .stButton > button {
            width: 100% !important;
            height: 90px !important;
            border-radius: 14px !important;
            border: 1px solid #CBD5E0 !important;
            background-color: #FFFFFF !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important;
            padding: 8px !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            color: #2D3748 !important;
            white-space: pre-wrap !important;
            line-height: 1.4 !important;
        }
        div[data-testid="column"] .stButton > button:active {
            transform: scale(0.97) !important;
            background-color: #EDF2F7 !important;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # 1. Top Header Bar
    user_display = (
        st.session_state.user_email.split("@")[0]
        if st.session_state.user_email
        else "User"
    )
    role_display = st.session_state.get("user_role", "Viewer")
    st.markdown(
        f"""
        <div class="mobile-header-bar">
            <div>
                <span style="font-size: 11px; color: #718096; text-transform: uppercase; font-weight: 700;">AAPL Operations Hub</span><br>
                <span style="font-size: 15px; font-weight: 700; color: #1A202C;">📍 All Operating Divisions</span>
            </div>
            <div style="background: #EDF2F7; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; color: #2D3748;">
                👤 {user_display} ({role_display})
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. Fetch Live Metrics
    metrics = fetch_hub_live_metrics()

    # 3. The 4 Live Action Tiles
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button(
            f"🚚 Dispatch\n{metrics['open_dispatches']} Pending",
            key="hub_btn_disp",
            use_container_width=True,
        ):
            st.switch_page(page_delivery)

    with col2:
        if st.button(
            f"📋 Debtors\n{metrics['outstanding_str']}",
            key="hub_btn_os",
            use_container_width=True,
        ):
            st.switch_page(page_outstanding)

    with col3:
        if st.button(
            f"📦 Inventory\n{metrics['stock_str']}",
            key="hub_btn_stk",
            use_container_width=True,
        ):
            st.switch_page(page_stock)

    with col4:
        if st.button(
            f"🎯 MTD Sales\n{metrics['mtd_sales_str']}",
            key="hub_btn_sal",
            use_container_width=True,
        ):
            st.switch_page(page_sales)

    # 4. Operational Bottleneck Banner
    if metrics["bottlenecks"] > 0:
        st.markdown(
            f"""
            <div class="pulse-card">
                <div class="pulse-card-title">⚠️ Operational Bottleneck Alert</div>
                <div class="pulse-card-desc">
                    <b>{metrics['bottlenecks']} invoice(s)</b> have remained in <b>Open</b> status for over 48 hours. 
                    Tap the <b>Dispatch</b> tile above to assign transporters or update tracking details.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")
    # Render primary operational dashboard underneath
    show_sales_dashboard()


# =====================================================================
# 4. INITIALIZE AUTHENTICATION STATE
# =====================================================================
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None

if not st.session_state.user_email:
    st.title("🔐 AAPL Sales & Operations Portal")
    st.subheader("Login")

    query_params = st.query_params
    if "code" in query_params:
        try:
            flow = get_oauth_flow()
            flow.code_verifier = query_params.get("state")
            flow.fetch_token(code=query_params["code"])
            credentials = flow.credentials

            userinfo = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
                timeout=10,
            ).json()
            email = userinfo.get("email", "").lower().strip()

            role = get_user_role(email)
            if role:
                st.session_state.user_email = email
                st.session_state.user_role = role
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"❌ Access Denied: {email} is not an authorized user.")
                st.query_params.clear()
        except Exception as e:
            st.error(f"❌ Login failed: {e}")
            st.query_params.clear()
    else:
        flow = get_oauth_flow()
        code_verifier = secrets.token_urlsafe(48)
        flow.code_verifier = code_verifier
        auth_url, _ = flow.authorization_url(
            prompt="consent", state=code_verifier
        )
        st.link_button("📧 Log in with Google", auth_url)

# =====================================================================
# 5. AUTHENTICATED NAVIGATION GATE
# =====================================================================
else:
    top_col1, top_col2 = st.columns([5, 1])
    with top_col1:
        st.caption(
            f"👤 **{st.session_state.user_email}** | Role:"
            f" **{st.session_state.user_role}**"
        )
    with top_col2:
        if st.button("🚪 Logout"):
            st.session_state.user_email = None
            st.session_state.user_role = None
            st.rerun()

    # Define Navigation Pages
    page_home = st.Page(show_home, title="Home", icon="🏠", default=True)
    page_outstanding = st.Page(
        show_outstanding_report, title="Outstanding Report", icon="📋"
    )
    page_sales = st.Page(
        show_sales_dashboard, title="Sales vs Target", icon="🎯"
    )
    page_exec = st.Page(
        show_executive_dashboard, title="Executive Dashboard", icon="👔"
    )
    page_stock = st.Page(
        show_stock_position, title="Stock Position", icon="📦"
    )
    page_sales360 = st.Page(show_sales_360, title="Sales 360°", icon="🔄")
    page_delivery = st.Page(
        show_delivery_dashboard, title="Delivery Dashboard", icon="🚚"
    )
    log_out = st.Page(" ", title="Log Out", icon ="🚪")
    

    pages = [
        page_home,
        page_outstanding,
        page_sales,
        page_exec,
        page_stock,
        page_sales360,
        page_delivery,
        log_out,
    ]

    pg = st.navigation(pages, position="sidebar", expanded=True)
    pg.run()
