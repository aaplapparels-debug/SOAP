"""
config_loader.py

Loads settings from config.<env>.yaml, where <env> is picked up from an
environment variable (defaults to "dev" if you don't set one). This is
the one piece of code that knows *which* config file to read -- nothing
else in the project should hardcode a path or a password.

Python concepts here:
- `os.environ.get("NAME", "default")` reads an operating-system
  environment variable. This is the standard place to put secrets
  (passwords, API keys) -- NOT in a file that might get committed to
  git or shared in a chat. Set one in PowerShell with:
      $env:SHOPER_SA_PASSWORD = "your-real-password"
  It only lasts for that terminal session unless you set it more
  permanently through Windows' System Properties > Environment Variables.
- `with open(...) as f:` is Python's standard way to open a file safely
  -- it automatically closes the file when the block ends, even if
  something inside the block errors out. You'll see this pattern
  constantly in Python code.
- A dict (short for "dictionary") is Python's key-value structure --
  after `yaml.safe_load`, the whole config file becomes nested dicts
  and lists you can index into with square brackets, e.g.
  config["sql_server"]["host"].
"""
import json
import os
import yaml


def load_config() -> dict:
    env = os.environ.get("APP_ENV", "dev")
    config_path = f"config.{env}.yaml"
    
    
    # 1. Streamlit Cloud Secrets (Production)
    if hasattr(st, "secrets") and "postgres" in st.secrets:
        return st.secrets
        
    # 2. Local config file (Development)
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Fill in the password from the environment, never from the file.
    config["sql_server"]["sa_password"] = os.environ.get("SHOPER_SA_PASSWORD", "")

    if not config["sql_server"]["sa_password"]:
        # Fail loudly and immediately rather than silently connecting
        # with a blank password and getting a confusing error later.
        raise RuntimeError(
            "SHOPER_SA_PASSWORD environment variable is not set. "
            "Set it before running this script."
        )

    return config


if __name__ == "__main__":
    # Quick manual check: run `python config_loader.py` by itself to
    # confirm your config file and env var are both set up correctly,
    # without needing to touch SQL Server or Shoper at all.
    cfg = load_config()
    print(f"Loaded config for tenant: {cfg['tenant']}")
    print(f"Divisions found: {[d['name'] for d in cfg['divisions']]}")
    print(f"Backup watch folder: {cfg['backup']['watch_folder']}")
