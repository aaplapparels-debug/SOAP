"""
restore_shoper_backups.py

Nightly orchestration: for each division in config.<env>.yaml, find
tonight's backup zip, extract it, restore it into that division's
staging database, then clean up the extracted files. Never touches or
deletes the original zip in watch_folder -- only ever reads it.

Run this before shoper_adapter.py each night -- it's what makes sure
"tonight's data" actually exists in the ShoperStaging_* databases
before extraction tries to read from them.

PREREQUISITE (one-time): the container needs to be on a named volume,
NOT a bind mount. Bind mounts on Docker Desktop for Windows go through
a WSL2 <-> Windows filesystem translation layer that's dramatically
slower for I/O-heavy work like a database restore -- likely the actual
cause if a restore that should take a few minutes was taking 30+.

    docker stop shoper-staging
    docker rm shoper-staging
    docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=YourPasswordHere" -p 14330:1433 --name shoper-staging -v shoper_data:/var/opt/mssql -d mcr.microsoft.com/mssql/server:2022-latest

This script now uses `docker cp` to deliver the extracted backup file
into the container -- a single bulk copy, not continuous I/O through a
bind mount -- while SQL Server's actual data/log files land on the fast
named volume.

New Python concepts in this file:
- `glob.glob(pattern)` searches for files matching a wildcard pattern,
  the same way typing "A_62X_*.ZIP" into Windows Explorer's search box
  would -- `*` means "anything."
- `try / except` catches errors instead of letting them crash the whole
  program. Here, one division failing (e.g. tonight's zip missing)
  shouldn't stop the other three from restoring -- we catch the error,
  print it, and move on to the next division.
- `os.path.join(...)` builds file paths safely -- it's the correct way
  to combine folder + filename without worrying about missing slashes
  or Windows-vs-Linux differences.
- `subprocess.run([...])` runs an external command-line program (here,
  the `docker` CLI itself) from inside Python and waits for it to
  finish -- the list of strings is the command broken into the pieces
  you'd normally type separated by spaces.
"""

import glob
import os
import shutil
import subprocess
import time
import zipfile

import pyodbc

from config_loader import load_config


CONTAINER_NAME = "shoper-staging"
CONTAINER_DATA_PATH = "/var/opt/mssql/data"  # lives on the fast named volume, not a bind mount


def find_latest_zip(watch_folder: str, pattern: str) -> str:
    """Finds the most recently modified file matching this division's
    pattern. Picking by modification time (not just 'first match') 
    handles an old file matching the same pattern still sitting around
    from a previous night."""
    matches = glob.glob(os.path.join(watch_folder, pattern))
    if not matches:
        raise FileNotFoundError(f"No backup zip found matching '{pattern}' in {watch_folder}")
    return max(matches, key=os.path.getmtime)


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


def docker_cp_into_container(local_file: str, container_filename: str) -> str:
    """Copies one file from the host into the container's fast named-
    volume storage. This is a single bulk transfer -- much faster than
    a bind mount for a large file, since it's one operation rather than
    the constant back-and-forth I/O a restore does. Returns the path as
    SQL Server will see it inside the container."""
    container_path = f"{CONTAINER_DATA_PATH}/{container_filename}"
    subprocess.run(
        ["docker", "cp", local_file, f"{CONTAINER_NAME}:{container_path}"],
        check=True,  # raises an exception if the docker command fails, instead of failing silently
    )
    return container_path


def cleanup_container_file(container_path: str):
    """Removes the copied backup file from inside the container once the
    restore is done, so temp copies don't quietly pile up on the volume
    over time."""
    subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "rm", "-f", container_path],
        check=False,  # don't crash the whole run just because cleanup failed
    )


def restore_database(conn, backup_file_container_path: str, staging_db: str):
    """RESTORE FILELISTONLY first, to discover this specific backup's
    logical file names (they vary by database -- can't hardcode them),
    then builds and runs the real RESTORE DATABASE from that."""
    cursor = conn.cursor()

    cursor.execute(f"RESTORE FILELISTONLY FROM DISK = '{backup_file_container_path}'")
    file_list = cursor.fetchall()

    move_clauses = []
    for row in file_list:
        logical_name = row.LogicalName
        file_type = row.Type  # 'D' = data file, 'L' = log file
        extension = "mdf" if file_type == "D" else "ldf"
        target_path = f"/var/opt/mssql/data/{staging_db}_{logical_name}.{extension}"
        move_clauses.append(f"MOVE '{logical_name}' TO '{target_path}'")

    move_sql = ", ".join(move_clauses)
    restore_sql = (
        f"RESTORE DATABASE {staging_db} FROM DISK = '{backup_file_container_path}' "
        f"WITH {move_sql}, REPLACE, RECOVERY"
    )
    cursor.execute(restore_sql)
    conn.commit()


def wait_for_database_online(conn, staging_db: str, timeout_seconds: int = 1800, poll_interval: int = 10):
    """
    The RESTORE DATABASE command returning without an error only means
    the data/log copy finished -- it does NOT guarantee the database has
    actually finished recovery and is usable yet. We found this out the
    hard way: all four divisions restored "successfully" according to
    the script's own printout, but SQL Server still showed them stuck in
    RESTORING. Trusting execute() alone was the bug.

    Instead, poll sys.databases (the same query we ran manually to
    diagnose the stuck state) until it reports ONLINE, with a timeout so
    a genuinely broken restore fails loudly instead of hanging forever.
    """
    cursor = conn.cursor()
    elapsed = 0
    state = None
    while elapsed < timeout_seconds:
        cursor.execute("SELECT state_desc FROM sys.databases WHERE name = ?", staging_db)
        row = cursor.fetchone()
        state = row.state_desc if row else "NOT FOUND"
        if state == "ONLINE":
            return
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise TimeoutError(
        f"{staging_db} did not reach ONLINE within {timeout_seconds}s (last state: {state})"
    )


def run_nightly_restore():
    config = load_config()
    watch_folder = config["backup"]["watch_folder"]
    temp_folder = config["backup"]["temp_extract_folder"]
    sql_cfg = config["sql_server"]

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={sql_cfg['host']};"
        f"UID={sql_cfg['sa_username']};PWD={sql_cfg['sa_password']};"
        "TrustServerCertificate=yes;"
    )
    # autocommit=True because RESTORE DATABASE can't run inside an
    # explicit transaction -- SQL Server rejects it otherwise.
    conn = pyodbc.connect(conn_str, autocommit=True)

    for division in config["divisions"]:
        name = division["name"]
        print(f"--- {name} ---")
        try:
            zip_path = find_latest_zip(watch_folder, division["backup_file_pattern"])
            print(f"Found: {zip_path}")

            extract_folder = extract_zip(zip_path, temp_folder, name)
            backup_file = find_main_backup_file(extract_folder)
            print(f"Main backup file: {backup_file}")

            container_filename = f"{division['staging_db']}_source.bak"
            container_path = docker_cp_into_container(backup_file, container_filename)
            print(f"Copied into container: {container_path}")

            restore_database(conn, container_path, division["staging_db"])
            print(f"Restore command completed for {division['staging_db']}, waiting for recovery...")

            wait_for_database_online(conn, division["staging_db"])
            print(f"{division['staging_db']} is ONLINE")

            # Clean up both the host-side extracted files and the copy
            # left inside the container -- only on success, so a failed
            # run leaves everything in place for inspection.
            shutil.rmtree(extract_folder)
            cleanup_container_file(container_path)
            print("Cleaned up temp files.")

        except Exception as e:
            print(f"FAILED for division {name}: {e}")
            # Deliberately not re-raising -- one division's zip missing
            # shouldn't stop the other three from restoring. Once this
            # runs unattended overnight, this print should become a log
            # line or alert you'll actually see the next morning.

    conn.close()


if __name__ == "__main__":
    run_nightly_restore()