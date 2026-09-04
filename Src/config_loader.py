"""Src/config_loader.py

Loads PostgreSQL connection settings from Streamlit Cloud Secrets,
local JSON/YAML configs, or environment variables.
"""

import json
import os

try:
    import streamlit as st
except ImportError:
    st = None


def load_config() -> dict:
    # 1. Streamlit Cloud Secrets (Production on Cloud)
    if st is not None:
        try:
            if "postgres" in st.secrets:
                return st.secrets
        except Exception:
            pass

    # 2. Local config.json (Development)
    paths_to_check = [
        "config.json",
        os.path.join(os.path.dirname(__file__), "config.json"),
        os.path.join(os.path.dirname(__file__), "..", "config.json"),
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    # 3. Environment Variable Fallback
    env_conn = os.environ.get("DATABASE_URL") or os.environ.get(
        "POSTGRES_CONNECTION_STRING"
    )
    if env_conn:
        return {"postgres": {"connection_string": env_conn}}

    raise RuntimeError(
        "Database credentials missing. Please set [postgres] in Streamlit Cloud"
        " Secrets."
    )


if __name__ == "__main__":
    cfg = load_config()
    print("Configuration loaded successfully.")
