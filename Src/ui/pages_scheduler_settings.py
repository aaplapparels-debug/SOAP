import base64
from datetime import time
import requests
import streamlit as st
import yaml

def trigger_manual_workflow(
    repo: str, token: str, workflow_file: str, branch: str = "main"
):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    res = requests.post(url, headers=headers, json={"ref": branch})
    return res.status_code == 204


# In Streamlit UI:
# (Moved inside the render_scheduler_config_tab function below)

def get_github_file(repo: str, path: str, token: str, branch: str = "main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return data["sha"], content
    return None, None


def commit_github_file(
    repo: str,
    path: str,
    token: str,
    new_content: str,
    sha: str,
    message: str,
    branch: str = "main",
):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "message": message,
        "content": base64.b64encode(new_content.encode("utf-8")).decode(
            "utf-8"
        ),
        "sha": sha,
        "branch": branch,
    }
    res = requests.put(url, headers=headers, json=payload)
    return res.status_code in [200, 201]


def render_scheduler_config_tab():
    st.subheader("⚙️ Automated Scheduler Timing")

    # Read config gracefully (handles local dev without secrets.toml)
    gh_cfg = {}
    try:
        if hasattr(st, "secrets") and "github" in st.secrets:
            gh_cfg = st.secrets["github"]
    except Exception:
        pass  # Fallback gracefully if secrets.toml is entirely missing

    token = gh_cfg.get("token")
    repo = gh_cfg.get("repo")
    path = gh_cfg.get("workflow_path", ".github/workflows/outstanding_followup.yml")
    branch = gh_cfg.get("branch", "main")

    if not token or not repo:
        st.warning(
            "GitHub token not configured in secrets. Cannot edit workflow directly."
        )
        return
        
    if st.button("⚡ Run Scheduler Right Now"):
        if trigger_manual_workflow(
            repo, token, "outstanding_followup.yml", branch
        ):
            st.success(
                "Triggered! GitHub Action is executing in the cloud right now."
            )
        else:
            st.error("Failed to trigger workflow. Verify workflow_dispatch is enabled.")

    sha, yaml_raw = get_github_file(repo, path, token, branch)
    if not sha:
        st.error(f"Could not load workflow file from GitHub: `{path}`")
        return

    # Parse YAML to find current cron
    workflow_dict = yaml.safe_load(yaml_raw)
    current_cron = "30 4 * * *"
    try:
        current_cron = workflow_dict["on"]["schedule"][0]["cron"]
    except (KeyError, IndexError, TypeError):
        pass

    st.info(f"**Current Remote Cron:** `{current_cron}` (UTC)")

    # Time Picker in IST
    col1, col2 = st.columns(2)
    with col1:
        selected_time = st.time_input(
            "Daily Run Time (IST)", value=time(10, 0), step=1800
        )
    with col2:
        run_days = st.multiselect(
            "Active Days",
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ],
            default=[
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ],
        )

    # Convert IST (UTC+5:30) to UTC cron expression
    total_minutes_ist = selected_time.hour * 60 + selected_time.minute
    total_minutes_utc = (total_minutes_ist - 330) % 1440
    utc_hour = total_minutes_utc // 60
    utc_minute = total_minutes_utc % 60

    day_map = {
        "Monday": "1",
        "Tuesday": "2",
        "Wednesday": "3",
        "Thursday": "4",
        "Friday": "5",
        "Saturday": "6",
    }
    days_cron = (
        ",".join(sorted([day_map[d] for d in run_days])) if run_days else "*"
    )
    new_cron = f"{utc_minute} {utc_hour} * * {days_cron}"

    st.caption(f"Evaluates to UTC cron: `{new_cron}`")

    if st.button("💾 Save Schedule to GitHub"):
        # Update workflow dictionary
        if "on" not in workflow_dict:
            workflow_dict["on"] = {}
        workflow_dict["on"]["schedule"] = [{"cron": new_cron}]

        # Keep workflow_dispatch enabled so manual trigger continues to work
        workflow_dict["on"]["workflow_dispatch"] = None

        new_yaml_text = yaml.dump(
            workflow_dict, sort_keys=False, default_flow_style=False
        )

        with st.spinner("Committing update to GitHub..."):
            success = commit_github_file(
                repo=repo,
                path=path,
                token=token,
                new_content=new_yaml_text,
                sha=sha,
                message=f"chore: update outstanding scheduler cron to {selected_time.strftime('%H:%M')} IST",
                branch=branch,
            )

        if success:
            st.success("GitHub Actions schedule updated and active!")
            st.rerun()
        else:
            st.error("Failed to commit to GitHub. Check token permissions.")