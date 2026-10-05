"""Src/shoper_sync/config_loader.py
Loads local SQL Server / Shoper 9 configuration from config.<env>.yaml.
"""

import os
import yaml


def load_shoper_config() -> dict:
    env = os.environ.get("APP_ENV", "dev")
    # Searches in root or current folder
    config_path = (
        f"config.{env}.yaml"
        if os.path.exists(f"config.{env}.yaml")
        else os.path.join("..", f"config.{env}.yaml")
    )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config["sql_server"]["sa_password"] = os.environ.get(
        "SHOPER_SA_PASSWORD", ""
    )

    if not config["sql_server"]["sa_password"]:
        raise RuntimeError(
            "SHOPER_SA_PASSWORD environment variable is not set. Set it before running sync."
        )

    return config


if __name__ == "__main__":
    cfg = load_shoper_config()
    print(f"Loaded config for tenant: {cfg.get('tenant')}")