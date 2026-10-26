"""common/auth.py"""
from datetime import datetime, timedelta
import time
import jwt
import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME = "aapl_soap_session"
JWT_ALGORITHM = "HS256"


def _get_jwt_secret():
    return st.secrets.get("auth", {}).get(
        "jwt_secret", "aapl-soap-secret-key-2026"
    )


def get_cookie_controller():
    if "_cookie_controller" not in st.session_state:
        st.session_state["_cookie_controller"] = CookieController()
    return st.session_state["_cookie_controller"]


def set_auth_cookie(email: str, role: str):
    """Sets a signed 30-day persistent session cookie."""
    controller = get_cookie_controller()
    exp_date = datetime.now() + timedelta(days=30)
    payload = {
        "email": email.lower().strip(),
        "role": role,
        "exp": exp_date,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)
    controller.set(
        COOKIE_NAME,
        token,
        max_age=30 * 86400,
        same_site="lax",
    )


def get_authenticated_user():
    """Checks session_state first, then inspects browser cookies with a short sync check."""
    # 1. Check active memory state
    if st.session_state.get("user_email") and st.session_state.get("user_role"):
        return {
            "email": st.session_state.user_email,
            "role": st.session_state.user_role,
        }

    controller = get_cookie_controller()
    
    # 2. Inspect cookie value
    token = controller.get(COOKIE_NAME)

    # 3. If None on hard refresh (F5), give the component 0.15s to handshake
    if not token and not st.session_state.get("_cookie_checked", False):
        time.sleep(0.15)
        token = controller.get(COOKIE_NAME)
        st.session_state["_cookie_checked"] = True

    if token:
        try:
            payload = jwt.decode(
                token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM]
            )
            email = payload.get("email")
            role = payload.get("role")
            if email and role:
                st.session_state.user_email = email
                st.session_state.user_role = role
                return {"email": email, "role": role}
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            controller.remove(COOKIE_NAME)

    return None


def logout_user():
    """Purges session state and the persistent cookie."""
    controller = get_cookie_controller()
    controller.remove(COOKIE_NAME)
    st.session_state.user_email = None
    st.session_state.user_role = None
    st.session_state.pop("_cookie_checked", None)
    st.rerun()