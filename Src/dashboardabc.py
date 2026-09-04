"""
dashboard.py

The new dashboard, reading from Neon (Postgres) instead of Google Sheets.
Authentication uses Google OAuth Web Application flow with stateless PKCE
state passing to survive Streamlit session/tab resets.
"""

import secrets
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from sqlalchemy import create_engine, text

from config_loader import load_config

st.set_page_config(
    page_title="AAPL Sales & Operations Portal",
    page_icon="\U0001F4CA",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = load_config()
dashboard_cfg = config["dashboard"]
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def get_oauth_flow() -> Flow:
    return Flow.from_client_secrets_file(
        dashboard_cfg["oauth_client_secret_file"],
        scopes=SCOPES,
        redirect_uri=dashboard_cfg["redirect_uri"],
    )


def get_user_role(email: str):
    """Looks up an authorized, active user's role in Postgres. Returns
    None if the email isn't found or is marked inactive."""
    engine = create_engine(config["postgres"]["connection_string"])
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT role FROM dashboard_users WHERE email = :e AND is_active = TRUE"),
            {"e": email.lower().strip()},
        ).fetchone()
    return result[0] if result else None


# Initialize session state for user session
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None


# -------------------------------------------------------------
# LOGIN GATE
# -------------------------------------------------------------
if not st.session_state.user_email:
    st.title("\U0001F511 AAPL Sales & Operations Portal")
    st.subheader("Login")

    query_params = st.query_params
    if "code" in query_params:
        try:
            flow = get_oauth_flow()
            # Retrieve the code_verifier from the returned OAuth 'state' parameter
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
                st.error(f"Access Denied: {email} is not an authorized user.")
                st.query_params.clear()
        except Exception as e:
            st.error(f"Login failed: {e}")
            st.query_params.clear()
    else:
        flow = get_oauth_flow()
        # Generate a verifier and pass it inside the state parameter
        code_verifier = secrets.token_urlsafe(48)
        flow.code_verifier = code_verifier
        auth_url, _ = flow.authorization_url(prompt="consent", state=code_verifier)
        st.link_button("Log in with Google", auth_url)

# -------------------------------------------------------------
# LOGGED IN
# -------------------------------------------------------------
else:
    top_col1, top_col2 = st.columns([5, 1])
    with top_col1:
        st.caption(f"Logged in as: **{st.session_state.user_email}** | Role: **{st.session_state.user_role}**")
    with top_col2:
        if st.button("Logout"):
            st.session_state.user_email = None
            st.session_state.user_role = None
            st.rerun()

    st.title("\U0001F4CA Dashboard")
    st.info("Login is working. Report pages go here next.")