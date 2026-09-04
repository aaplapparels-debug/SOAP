"""
dashboard.py

The new dashboard, reading from Neon (Postgres) instead of Google
Sheets. This file currently contains ONLY the login gate -- proving
authentication works before building any actual report pages on top
of it, same "test the foundation first" discipline as the rest of
this project.

Login flow, since this is genuinely different from the old OTP
approach: Google OAuth "Web application" flow, not the OTP email code
the old app.py used, and not the same OAuth client as the Drive relay
(that one's a "Desktop app" client for one person's local automation --
this needs a "Web application" client for multiple staff logging in
through a browser).

New Python/Streamlit concepts, since you're reading this while learning:

- `st.session_state` is Streamlit's way of remembering things ACROSS
  reruns. Streamlit re-runs your whole script top-to-bottom on every
  interaction (every click, every page load) -- without session_state,
  the app would "forget" that you're logged in the instant you clicked
  anything. Think of it as a dictionary that survives reruns, tied to
  one person's browser session.
- `st.query_params` reads the URL's query string parameters -- after
  Google redirects back to this app post-login, it appends a `code`
  parameter to the URL. Reading that is how the app knows "the user
  just came back from Google, with an authorization code to exchange
  for their identity."
- The OAuth "Flow" object here is Google's own library doing the actual
  protocol handshake: build an authorization URL to send the user to,
  then later exchange the code Google sends back for an access token,
  then use that token to ask Google "whose email is this."
"""

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
    None if the email isn't found or is marked inactive -- None is the
    signal used below to deny access."""
    engine = create_engine(config["postgres"]["connection_string"])
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT role FROM dashboard_users WHERE email = :e AND is_active = TRUE"),
            {"e": email.lower().strip()},
        ).fetchone()
    return result[0] if result else None


# session_state acts like a dict that survives Streamlit's reruns --
# initialize these keys once, on the very first run for this session.
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
        # We've been redirected back from Google with an authorization
        # code -- exchange it for a real access token, then use that
        # token to ask Google who the person actually is.
        #
        # IMPORTANT: this Flow object must reuse the SAME code_verifier
        # that was generated when the login link was built, a moment
        # ago in a completely separate script run (Streamlit reruns the
        # whole script on every page load). A fresh Flow object here
        # would have no memory of that verifier -- it only ever existed
        # in that earlier run's local variable, which is long gone.
        # Pulling it back out of session_state (where it was saved
        # below, in the "else" branch) is what makes this work.
        try:
            flow = get_oauth_flow()
            flow.code_verifier = st.session_state.get("oauth_code_verifier")
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
                st.query_params.clear()  # remove ?code=... from the URL
                st.rerun()
            else:
                st.error(f"Access Denied: {email} is not an authorized user.")
                st.query_params.clear()
        except Exception as e:
            st.error(f"Login failed: {e}")
            st.query_params.clear()
    else:
        # Not yet in a login attempt -- show the "log in" link, which
        # sends the user to Google's own consent screen. Save the
        # verifier this Flow object generates internally, so the
        # callback handler above can reuse the exact same one.
        flow = get_oauth_flow()
        auth_url, _ = flow.authorization_url(prompt="consent")
        st.session_state.oauth_code_verifier = flow.code_verifier
        st.link_button("Log in with Google", auth_url)

# -------------------------------------------------------------
# LOGGED IN -- placeholder for now, real pages come next
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