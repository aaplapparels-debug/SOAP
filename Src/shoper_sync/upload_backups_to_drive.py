"""
upload_backups_to_drive.py

Runs on the PRODUCTION machine (the one with live Shoper + Tally).
Watches the backup folder and uploads any new Day-End zip to a shared
Google Drive folder. Deliberately lightweight -- a file upload, not a
database operation -- so it's safe to run during business hours without
meaningfully competing with live POS activity.

Meant to be scheduled (Windows Task Scheduler) every 30-60 minutes
during business hours. It only uploads files it hasn't uploaded before,
so running it often and getting "nothing new" most of the time is by
design, not wasted work.

--------------------------------------------------------------------
SETUP -- do this once before running:

1. Follow the OAuth Client ID setup (drive_client_secret.json) --
   see drive_auth.py for why we use OAuth instead of a service account.

2. pip install google-api-python-client google-auth google-auth-oauthlib

3. In your own Google Drive, create a folder for these backups, open
   it in a browser, and copy the ID from the URL
   (drive.google.com/drive/folders/<THIS PART>) into config.dev.yaml
   under google_drive.shared_folder_id.
--------------------------------------------------------------------

New Python concepts in this file:
- `MediaFileUpload` is Google's wrapper for streaming a file up in
  chunks, rather than loading a huge file entirely into memory at once.
"""

import glob
import os

from googleapiclient.http import MediaFileUpload

from config_loader import load_config
from drive_auth import get_drive_service
from transfer_log import load_transfer_log, record_transferred


def upload_file(service, local_path: str, folder_id: str):
    filename = os.path.basename(local_path)
    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaFileUpload(local_path, resumable=True)
    service.files().create(body=file_metadata, media_body=media, fields="id").execute()


def run_upload_check():
    config = load_config()
    drive_cfg = config["google_drive"]
    watch_folder = config["backup"]["watch_folder"]
    log_path = drive_cfg.get("shipped_log_file", "shipped_files.log")

    service = get_drive_service(drive_cfg["client_secret_file"], drive_cfg["token_file"])
    already_shipped = load_transfer_log(log_path)

    found_anything_new = False

    # Check every division's pattern, not just one -- all four divisions'
    # zips live in the same watch_folder.
    for division in config["divisions"]:
        pattern = os.path.join(watch_folder, division["backup_file_pattern"])
        matches = glob.glob(pattern)
        if not matches:
            print(f"{division['name']}: no files in {watch_folder} match '{division['backup_file_pattern']}'")
            continue
        for local_file in matches:
            filename = os.path.basename(local_file)
            if filename in already_shipped:
                continue  # already logged as shipped, nothing to do
            found_anything_new = True
            print(f"Uploading {filename}...")
            upload_file(service, local_file, drive_cfg["shared_folder_id"])
            record_transferred(log_path, filename)
            print(f"Done: {filename}")

    if not found_anything_new:
        print(f"Nothing new to upload -- see {log_path} for what's already been sent.")


if __name__ == "__main__":
    run_upload_check()
