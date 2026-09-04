"""config_loader.py

Unified configuration loader supporting both Streamlit Community Cloud
(via st.secrets) and local development (via YAML/JSON or environment variables).
"""

import json
import os
import yaml

try:
    import streamlit as st
except ImportError:
    st = None


def load_config() -> dict:
    config = {}

    # 1. Streamlit Secrets (Priority for Cloud Deployment)
    if st is not None:
        try:
            if "postgres" in st.secrets:
                return st.secrets
        except Exception:
            # st.secrets raises FileNotFoundError if .streamlit/secrets.toml doesn't exist locally
            pass

    # 2. Local config files (Search in current folder, Src/, and project root)
    env = os.environ.get("APP_ENV", "dev")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, ".."))

    search_dirs = [os.getcwd(), current_dir, parent_dir]
    file_candidates = [
        f"config.{env}.yaml",
        f"config.{env}.yml",
        "config.yaml",
        "config.yml",
        "config.json",
    ]

    config_path = None
    for directory in search_dirs:
        for filename in file_candidates:
            candidate = os.path.join(directory, filename)
            if os.path.exists(candidate):
                config_path = candidate
                break
        if config_path:
            break

    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.endswith((".yaml", ".yml")):
                config = yaml.safe_load(f) or {}
            elif config_path.endswith(".json"):
                config = json.load(f) or {}

    # 3. Environment Variables Fallback
    env_postgres = os.environ.get("POSTGRES_CONNECTION_STRING") or os.environ.get(
        "DATABASE_URL"
    )
    if env_postgres:
        config.setdefault("postgres", {})["connection_string"] = env_postgres

    # Support legacy SQL Server env password if applicable
    if "sql_server" in config:
        sa_password = os.environ.get("SHOPER_SA_PASSWORD")
        if sa_password:
            config["sql_server"]["sa_password"] = sa_password

    # 4. Validation
    if "postgres" in config and "connection_string" in config["postgres"]:
        return config

    if config:
        return config

    raise RuntimeError(
        "PostgreSQL configuration not found. Please provide credentials via:\n"
        "1. Streamlit Cloud Secrets: [postgres] connection_string\n"
        "2. Local .streamlit/secrets.toml\n"
        "3. config.dev.yaml or config.json containing a 'postgres' -> 'connection_string' key."
    )


if __name__ == "__main__":
    cfg = load_config()
    print("Configuration loaded successfully.")
    if "postgres" in cfg:
        print("PostgreSQL connection string detected.")
