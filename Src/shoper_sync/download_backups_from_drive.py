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
import sys
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from shoper_config import load_shoper_config

from drive_auth import get_drive_service
from transfer_log import load_transfer_log, record_transferred


def list_files_in_drive_folder(service, folder_id: str) -> list:
    """Returns [{'id': ..., 'name': ..., 'mimeType': ...}, ...] for everything in the
    folder -- supporting shared drives and returning metadata needed for shortcuts."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType, shortcutDetails)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_file(service, file_id: str, destination_path: str):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    try:
        with io.FileIO(destination_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    print(f"  {int(status.progress() * 100)}%")
    except Exception:
        # Avoid leaving corrupted 0-byte or partial downloads
        if os.path.exists(destination_path):
            try:
                os.remove(destination_path)
            except OSError:
                pass
        raise


def run_download_check():
    config = load_shoper_config()
    drive_cfg = config["google_drive"]
    watch_folder = config["backup"]["watch_folder"]
    log_path = drive_cfg.get("downloaded_log_file", "downloaded_files.log")

    service = get_drive_service(drive_cfg["client_secret_file"], drive_cfg["token_file"])
    drive_files = list_files_in_drive_folder(service, drive_cfg["shared_folder_id"])
    already_downloaded = load_transfer_log(log_path)

    found_anything_new = False

    for f in drive_files:
        # Ignore subfolders
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue

        file_id = f["id"]
        # Handle Google Drive shortcuts pointing to the actual target file
        if f.get("mimeType") == "application/vnd.google-apps.shortcut":
            file_id = f.get("shortcutDetails", {}).get("targetId", file_id)

        if f["name"] in already_downloaded:
            continue  # already logged as a complete download, nothing to do
        found_anything_new = True
        print(f"Downloading {f['name']}...")
        destination = os.path.join(watch_folder, f["name"])
        try:
            download_file(service, file_id, destination)
            record_transferred(log_path, f["name"])
            print(f"Done: {f['name']}")
        except HttpError as e:
            print(f"  Failed to download {f['name']}: {e}")
        except Exception as e:
            print(f"  Unexpected error downloading {f['name']}: {e}")

    if not found_anything_new:
        print(f"Nothing new to download -- see {log_path} for what's already been pulled.")


if __name__ == "__main__":
    run_download_check()
