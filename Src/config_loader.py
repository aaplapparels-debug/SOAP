"""Src/config_loader.py
Loads PostgreSQL connection settings from Streamlit Cloud Secrets
or local config.<env>.yaml.
"""

import os
import yaml

try:
    import streamlit as st
except ImportError:
    st = None


def load_config() -> dict:
    # 1. Streamlit Cloud Secrets (Production on Cloud)
    if st is not None:
        try:
            if "postgres" in st.secrets:
                return dict(st.secrets)
        except Exception:
            pass

    # 2. Local config.<env>.yaml (Single Source of Truth)
    env = os.environ.get("APP_ENV", "dev")
    yaml_candidates = [
        f"config.{env}.yaml",
        os.path.join("..", f"config.{env}.yaml"),
        os.path.join(os.path.dirname(__file__), "..", f"config.{env}.yaml"),
    ]

    for path in yaml_candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if "postgres" in cfg:
                    return cfg

    # 3. Environment Variable Fallback
    env_conn = os.environ.get("DATABASE_URL") or os.environ.get(
        "POSTGRES_CONNECTION_STRING"
    )
    if env_conn:
        return {"postgres": {"connection_string": env_conn}}
    
    # 4. Discrete Component Fallback (GitHub Actions / CI runner)
    host = os.environ.get("POSTGRES_HOST")
    user = os.environ.get("POSTGRES_USER")
    pwd = os.environ.get("POSTGRES_PASSWORD")
    db = os.environ.get("POSTGRES_DB")
    port = os.environ.get("POSTGRES_PORT", "5432")

    if host and user and pwd and db:
        conn_str = f"postgresql+pg8000://{user}:{pwd}@{host}:{port}/{db}"
        return {"postgres": {"connection_string": conn_str}}

    raise RuntimeError(
        f"Database credentials missing. Checked Streamlit Secrets and config.{env}.yaml."
    )


# Export both names for backwards compatibility
load_ui_config = load_config

if __name__ == "__main__":
    cfg = load_config()
    print("Configuration loaded successfully from YAML/Secrets.")
    