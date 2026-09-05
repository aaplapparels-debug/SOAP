"""
Main dashboard entry point with authentication.
Handles Google OAuth login and routes to report pages.
"""

import secrets
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from sqlalchemy import create_engine, text

from config_loader import load_config
from pages_outstanding import show_outstanding_report
from pages_sales_dashboard import show_sales_dashboard
from pages_executive import show_executive_dashboard
from pages_stock import show_stock_position
from pages_sales360 import show_sales_360



st.set_page_config(
    page_title="AAPL Sales & Operations Portal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = load_config()
dashboard_cfg = config.get("dashboard", {})
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def get_oauth_flow():
    scopes = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]

    # Check if OAuth configuration is passed directly as a dictionary in secrets
    if "oauth" in dashboard_cfg:
        client_config = (
            dashboard_cfg["oauth"].to_dict()
            if hasattr(dashboard_cfg["oauth"], "to_dict")
            else dict(dashboard_cfg["oauth"])
        )
        return Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri="https://aapl-soap.streamlit.app",  # Your production Streamlit URL
        )

    # Fallback to local client_secret.json file for local development
    secret_file = dashboard_cfg.get(
        "oauth_client_secret_file", "dashboard_client_secret.json"
    )
    return Flow.from_client_secrets_file(
        secret_file, scopes=scopes, redirect_uri="http://localhost:8501"
    )


def get_user_role(email: str):
    """Looks up an authorized, active user's role in Postgres."""
    engine = create_engine(config["postgres"]["connection_string"])
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT role FROM dashboard_users WHERE email = :e AND is_active = TRUE"),
            {"e": email.lower().strip()},
        ).fetchone()
    return result[0] if result else None

    
#1. Define the Home/Welcome page function
def show_home():
    #st.title("📌 Welcome to AAPL Sales & Operations Dashboard")
    show_sales_dashboard()  # Display the Sales Dashboard by default on the home page

    st.info("Select a report from the sidebar menu to begin analysis.")
    st.markdown("""
    ### 📊 Available Reports
    
    1. **📋 Outstanding Report**
       - View all outstanding debtors
       - Filter by division and minimum amount
       - Track days outstanding
    
    2. **🎯 Sales Dashboard**
       - Sales vs Achievement analysis
       - Trends by time period and division
       - Top customers by sales
    
    3. **👔 Executive Dashboard**
       - Key performance indicators
       - Working capital analysis
       - Business health metrics
    
    4. **📦 Stock Position**
       - Current inventory levels across divisions
       - Fast-moving vs slow-moving stock
    
    5. **🔄 Sales 360°**
       - Comprehensive multi-dimension customer & item drill-down
    """)


# Initialize session state
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None


# =====================================================================
# LOGIN GATE
# =====================================================================
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
        auth_url, _ = flow.authorization_url(prompt="consent", state=code_verifier)
        st.link_button("📧 Log in with Google", auth_url)

# =====================================================================
# LOGGED IN - DASHBOARD HOME
# =====================================================================
else:
    # Top bar with user info and logout
    top_col1, top_col2 = st.columns([5, 1])
    with top_col1:
        st.caption(f"👤 **{st.session_state.user_email}** | Role: **{st.session_state.user_role}**")
    with top_col2:
        if st.button("🚪 Logout"):
            st.session_state.user_email = None
            st.session_state.user_role = None
            st.rerun()

    #st.title("📊 AAPL Sales & Operations Dashboard")

  
    # Navigation

    pages = [
        st.Page(show_home, title="Home", icon="🏠", default=True),
        st.Page(show_outstanding_report, title="Outstanding Report", icon="📋"),
        st.Page(show_sales_dashboard, title="Sales vs Target", icon="🎯"),
        st.Page(show_executive_dashboard, title="Executive Dashboard", icon="👔"),
        st.Page(show_stock_position, title="Stock Position", icon="📦"),
        st.Page(show_sales_360, title="Sales 360°", icon="🔄"),
    ]

    pg = st.navigation(pages, position="sidebar", expanded=True)
    pg.run()
