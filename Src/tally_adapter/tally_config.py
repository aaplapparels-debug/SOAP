"""Src/tally_adapter/config.py
Loads local Tally configuration from config.dev.yaml.
"""

import os
import yaml


def load_tally_config() -> dict:
    env = os.environ.get("APP_ENV", "dev")
    config_path = (
        f"config.{env}.yaml"
        if os.path.exists(f"config.{env}.yaml")
        else os.path.join("..", f"config.{env}.yaml")
    )

    with open(config_path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f)

    if "tally" not in full_config:
        raise KeyError("Missing 'tally' configuration section in config file.")

    return full_config["tally"]