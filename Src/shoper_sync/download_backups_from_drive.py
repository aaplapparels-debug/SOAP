"""
download_backups_from_drive.py

Runs on the PROCESSING machine (your dev PC, for now). Checks the
shared Google Drive folder for backup zips not yet present locally, and
downloads any new ones into config's backup.watch_folder -- the exact
same folder restore_shoper_backups.py already reads from.

That's deliberate: this script's only job is "make sure new files show
up locally." It doesn't know or care about restoring -- run this first,
then run restore_shoper_backups.py after, same as if the files had
appeared there by any other means. Two small scripts, each doing one
thing, rather than one script trying to do everything.

New Python concept in this file:
- `io.FileIO` + `MediaIoBaseDownload` is Google's pattern for writing a
  downloaded file to disk in chunks (a loop that runs `next_chunk()`
  until done), rather than pulling the whole file into memory at once
  -- matters once files get into the hundreds of MB, like these zips.
"""

import io
import os

from googleapiclient.http import MediaIoBaseDownload

from config_loader import load_config
from drive_auth import get_drive_service
from transfer_log import load_transfer_log, record_transferred


def list_files_in_drive_folder(service, folder_id: str) -> list:
    """Returns [{'id': ..., 'name': ...}, ...] for everything in the
    folder -- we need both the id (to download) and the name (to check
    against what's already local)."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name)",
    ).execute()
    return results.get("files", [])


def download_file(service, file_id: str, destination_path: str):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(destination_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  {int(status.progress() * 100)}%")


def run_download_check():
    config = load_config()
    drive_cfg = config["google_drive"]
    watch_folder = config["backup"]["watch_folder"]
    log_path = drive_cfg.get("downloaded_log_file", "downloaded_files.log")

    service = get_drive_service(drive_cfg["client_secret_file"], drive_cfg["token_file"])
    drive_files = list_files_in_drive_folder(service, drive_cfg["shared_folder_id"])
    already_downloaded = load_transfer_log(log_path)

    found_anything_new = False

    for f in drive_files:
        if f["name"] in already_downloaded:
            continue  # already logged as a complete download, nothing to do
        found_anything_new = True
        print(f"Downloading {f['name']}...")
        destination = os.path.join(watch_folder, f["name"])
        download_file(service, f["id"], destination)
        # Only logged here, after download_file has fully returned --
        # if it crashed partway, this line never runs, so next time
        # this file is correctly retried instead of wrongly skipped.
        record_transferred(log_path, f["name"])
        print(f"Done: {f['name']}")

    if not found_anything_new:
        print(f"Nothing new to download -- see {log_path} for what's already been pulled.")


if __name__ == "__main__":
    run_download_check()
