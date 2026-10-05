"""
transfer_log.py

Shared by upload_backups_to_drive.py and download_backups_from_drive.py.

A plain text log, one filename per line, recording what's already been
successfully transferred. Open it any time in a text editor to see
exactly what's happened -- no need to query Drive or trust a directory
listing to know the current state.

Only ever written to AFTER a transfer fully succeeds -- never before,
and never in a batch at the end. That ordering matters: if the script
crashes mid-transfer, the in-progress file is never logged as done, so
the next run correctly retries it instead of wrongly assuming a
partial/corrupted file is a good one just because a file with that name
exists.
"""

import os


def load_transfer_log(log_path: str) -> set:
    if not os.path.exists(log_path):
        return set()
    with open(log_path, "r") as f:
        return {line.strip() for line in f if line.strip()}


def record_transferred(log_path: str, filename: str):
    with open(log_path, "a") as f:
        f.write(f"{filename}\n")
