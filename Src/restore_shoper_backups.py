"""
restore_shoper_backups.py

Nightly orchestration: for each division in config.<env>.yaml, find the
latest backup zip, extract it, restore it into that division's staging
database, then clean up. Never touches or deletes the original zip in
watch_folder -- only ever reads it.

UPDATED: no more Docker. Everything now runs against a native SQL
Server install on this machine (instance STAGING_SERVER), which
removed a whole layer of Docker Desktop / WSL2 complexity that was the
leading suspect behind wildly inconsistent restore times (5 minutes vs
90+ minutes for essentially the same restore). Backup files are copied
into SQL Server's own data folder (not a container path) before
restoring -- this guarantees the SQL Server service account has read
access, since it's guaranteed to already have full access to its own
folder, which isn't necessarily true of just any folder on the PC.

New Python concepts in this file:
- `shutil.copy2(src, dst)` copies a file, preserving metadata like
  modification time -- the plain local equivalent of what `docker cp`
  was doing before, just without a container involved.
- Everything else (glob, try/except, os.path.join) is the same as
  before -- only the Docker-specific pieces changed.
"""

import glob
import os
import shutil
import subprocess
import zipfile
import re
from datetime import datetime
import pyodbc

from config_loader import load_config

def _parse_backup_timestamp(filepath: str) -> datetime:
    """Extracts backup generation timestamp from filename patterns like 'A_62X_260828_1200_C'.

    Parses YYMMDD (260828) and HHMM (1200) into a datetime object.
    """
    filename = os.path.basename(filepath)
    match = re.search(r"(\d{6})_(\d{4})", filename)
    if match:
        date_str, time_str = match.groups()
        try:
            return datetime.strptime(f"{date_str}{time_str}", "%y%m%d%H%M")
        except ValueError:
            pass
    return datetime.min

def find_latest_zip(watch_folder: str, pattern: str) -> str:
    """Finds the most recently modified file matching this division's
    pattern. Picking by modification time (not just 'first match')
    handles an old file matching the same pattern still sitting around
    from a previous run."""
    matches = glob.glob(os.path.join(watch_folder, pattern))
    if not matches:
        raise FileNotFoundError(f"No backup zip found matching '{pattern}' in {watch_folder}")
    return max(matches, key=_parse_backup_timestamp)


def extract_zip(zip_path: str, temp_folder: str, division_name: str) -> str:
    """Extracts into its own subfolder per division, so divisions never
    overwrite each other's files if this ever runs concurrently."""
    extract_to = os.path.join(temp_folder, division_name)
    os.makedirs(extract_to, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)
    return extract_to


def find_main_backup_file(extract_folder: str) -> str:
    """The extracted folder holds the main Shoper backup plus a smaller
    system-database backup (tspsysdb9, from our earlier reconnaissance).
    Picking by file size is more robust than guessing a name pattern
    that might not hold for every division or every Shoper version."""
    files = [os.path.join(extract_folder, f) for f in os.listdir(extract_folder)
             if os.path.isfile(os.path.join(extract_folder, f))]
    if not files:
        raise FileNotFoundError(f"No files found after extracting into {extract_folder}")
    return max(files, key=os.path.getsize)


def copy_to_sql_data_dir(local_file: str, data_dir: str, container_filename: str) -> str:
    """Copies the extracted backup file into SQL Server's own data
    folder -- a plain local file copy now, no container involved. This
    is the direct replacement for the old docker_cp_into_container."""
    destination = os.path.join(data_dir, container_filename)
    shutil.copy2(local_file, destination)
    return destination


def restore_database(sql_cfg: dict, backup_file_path: str, staging_db: str, data_dir: str, log_dir: str):
    """
    RESTORE FILELISTONLY still goes through pyodbc -- a quick read-only
    query, never once the source of trouble in any of our testing.

    The actual RESTORE DATABASE command is handed off to sqlcmd.exe as
    a real subprocess instead. Every restore that has ever succeeded in
    this whole project went through sqlcmd; every one that got stuck
    went through pyodbc's persistent connection issuing the command
    directly. Rather than keep theorizing why, this uses the method
    with the actual track record.
    """
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={sql_cfg['host']};"
        f"UID={sql_cfg['sa_username']};PWD={sql_cfg['sa_password']};"
        "TrustServerCertificate=yes;"
    )
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()
    cursor.execute(f"RESTORE FILELISTONLY FROM DISK = '{backup_file_path}'")
    file_list = cursor.fetchall()
    conn.close()

    move_clauses = []
    for row in file_list:
        logical_name = row.LogicalName
        file_type = row.Type  # 'D' = data file, 'L' = log file
        if file_type == "D":
            target_path = os.path.join(data_dir, f"{staging_db}_{logical_name}.mdf")
        else:
            target_path = os.path.join(log_dir, f"{staging_db}_{logical_name}.ldf")
        move_clauses.append(f"MOVE '{logical_name}' TO '{target_path}'")

    move_sql = ", ".join(move_clauses)
    restore_sql = (
        f"RESTORE DATABASE {staging_db} FROM DISK = '{backup_file_path}' "
        f"WITH {move_sql}, REPLACE, RECOVERY"
    )

    # subprocess.run blocks here until sqlcmd itself fully returns --
    # the same blocking behavior we relied on every time we typed this
    # by hand. No separate "wait and poll" needed for this part; sqlcmd
    # doesn't hand control back to Python until SQL Server is genuinely
    # done, including the full recovery phase.
    result = subprocess.run(
        [
            "sqlcmd", "-S", sql_cfg["host"], "-U", sql_cfg["sa_username"],
            "-P", sql_cfg["sa_password"], "-C", "-Q", restore_sql,
        ],
        capture_output=True, text=True, timeout=7200,  # 2 hour ceiling -- generous, not expected to be hit
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"sqlcmd restore failed:\n{result.stderr}")


def wait_for_database_online(sql_cfg: dict, staging_db: str, timeout_seconds: int = 1800, poll_interval: int = 10):
    """
    Deliberately opens its OWN fresh connection, separate from the one
    that issued the RESTORE command. RESTORE DATABASE streams back a
    series of informational messages as it progresses ("Processed X
    pages...", version-upgrade lines, etc.) -- if those aren't fully
    drained before the same connection is reused, it can behave
    unpredictably for anything queried on it right after. This
    happened identically in both the Docker and native environments,
    which is what pointed at the connection-reuse pattern itself as
    the real bug, rather than either environment.
    """
    import time
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={sql_cfg['host']};"
        f"UID={sql_cfg['sa_username']};PWD={sql_cfg['sa_password']};"
        "TrustServerCertificate=yes;"
    )
    check_conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = check_conn.cursor()
    elapsed = 0
    state = None
    try:
        while elapsed < timeout_seconds:
            cursor.execute("SELECT state_desc FROM sys.databases WHERE name = ?", staging_db)
            row = cursor.fetchone()
            state = row.state_desc if row else "NOT FOUND"
            if state == "ONLINE":
                return
            time.sleep(poll_interval)
            elapsed += poll_interval
    finally:
        check_conn.close()
    raise TimeoutError(
        f"{staging_db} did not reach ONLINE within {timeout_seconds}s (last state: {state})"
    )


def run_nightly_restore():
    config = load_config()
    watch_folder = config["backup"]["watch_folder"]
    temp_folder = config["backup"]["temp_extract_folder"]
    sql_cfg = config["sql_server"]

    for division in config["divisions"]:
        name = division["name"]
        print(f"--- {name} ---")
        try:
            zip_path = find_latest_zip(watch_folder, division["backup_file_pattern"])
            print(f"Found: {zip_path}")

            extract_folder = extract_zip(zip_path, temp_folder, name)
            backup_file = find_main_backup_file(extract_folder)
            print(f"Main backup file: {backup_file}")

            staged_filename = f"{division['staging_db']}_source.bak"
            staged_path = copy_to_sql_data_dir(backup_file, sql_cfg["data_dir"], staged_filename)
            print(f"Copied into SQL data folder: {staged_path}")

            restore_database(sql_cfg, staged_path, division["staging_db"], sql_cfg["data_dir"], sql_cfg["log_dir"])
            print(f"sqlcmd restore finished for {division['staging_db']}, confirming state...")

            wait_for_database_online(sql_cfg, division["staging_db"])
            print(f"{division['staging_db']} is ONLINE")

            # Clean up both the extracted files and the staged copy --
            # only on success, so a failed run leaves everything in
            # place for inspection.
            shutil.rmtree(extract_folder)
            os.remove(staged_path)
            print("Cleaned up temp files.")

        except Exception as e:
            print(f"FAILED for division {name}: {e}")
            # Deliberately not re-raising -- one division failing
            # shouldn't stop the other three from restoring.


if __name__ == "__main__":
    run_nightly_restore()