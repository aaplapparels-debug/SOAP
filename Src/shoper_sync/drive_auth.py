"""
drive_auth.py

Shared helper for both upload_backups_to_drive.py and
download_backups_from_drive.py.

We switched here from a *service account* to *OAuth as your own Google
account*, because Google's Drive API flatly refuses to let a service
account write files into anyone's personal Drive -- it has zero storage
quota of its own, by design, no matter how a folder is shared with it.
(That's the exact error we hit: "Service Accounts do not have storage
quota.") The fix Google actually supports for a personal (non-Workspace)
account is signing in as yourself, once, and reusing that authorization
afterward -- which is what this file does.

New Python concepts:
- The first time this runs, it opens your web browser and asks you to
  log into your Google account and approve access -- a normal OAuth
  "Allow this app to access your Drive" screen, same pattern as
  "Sign in with Google" buttons on other websites.
- After you approve once, the resulting authorization is saved to a
  token file on disk. Every run after that reuses it silently -- no
  browser, no re-approving -- unless it expires, which refreshes
  automatically without your involvement either.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service(client_secret_file: str, token_file: str = "token.json"):
    creds = None

    # Reuse a saved authorization if we already have one from a
    # previous run -- this is what makes every run after the first one
    # silent, no browser involved.
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # No saved authorization at all -- this is the one-time
            # browser login. run_local_server briefly starts a tiny
            # local web server to catch Google's response after you
            # click "Allow" in the browser tab it opens.
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)

        # Save it so the next run doesn't need the browser again.
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)
