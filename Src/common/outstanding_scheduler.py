"""Src/common/outstanding_scheduler.py
Evaluates Tally outstanding against customer master, delivery status, and custom buckets.
"""

from datetime import date, datetime, timedelta
import os
import pg8000.native


def get_connection():
    conn_str = os.environ.get("DATABASE_URL") or os.environ.get(
        "POSTGRES_CONNECTION_STRING"
    )
    if conn_str:
        # Standard postgresql connection url parsing or direct env passing
        user = os.environ.get("POSTGRES_USER", "neondb_owner")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        host = os.environ.get("POSTGRES_HOST", "")
        database = os.environ.get("POSTGRES_DB", "neondb")
        port = int(os.environ.get("POSTGRES_PORT", 5432))
        return pg8000.native.Connection(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database,
            ssl_context=True,
        )

    from config_loader import load_config

    cfg = load_config()["postgres"]
    return pg8000.native.Connection(
        user=cfg.get("user"),
        password=cfg.get("password"),
        host=cfg.get("host"),
        port=int(cfg.get("port", 5432)),
        database=cfg.get("database"),
        ssl_context=True,
    )


def load_bucket_configs(conn):
    """Loads all active bucket configs, grouping them by scope."""
    rows = conn.run(
        """
        SELECT scope, party_name, min_days, COALESCE(max_days, 99999), 
               bucket_label, severity_level, channel, cooldown_days
        FROM followup_bucket_config
        WHERE is_active = TRUE
        ORDER BY min_days ASC
    """
    )
    global_buckets = []
    party_buckets = {}

    for r in rows:
        cfg = {
            "min_days": r[2],
            "max_days": r[3],
            "label": r[4],
            "severity": r[5],
            "channel": r[6],
            "cooldown": r[7],
        }
        if r[0] == "GLOBAL":
            global_buckets.append(cfg)
        else:
            party_buckets.setdefault(r[1], []).append(cfg)

    return global_buckets, party_buckets


def resolve_bucket(days, party_name, global_buckets, party_buckets):
    rules = party_buckets.get(party_name, global_buckets)
    for b in rules:
        if b["min_days"] <= days <= b["max_days"]:
            return b
    return global_buckets[-1] if global_buckets else None


def run_scheduler():
    conn = get_connection()
    today = date.today()
    global_buckets, party_buckets = load_bucket_configs(conn)

    # Core Query: Pulls bills, contact data from master, delivery hold status, and active exclusions
    query = """
    WITH bill_delivery_status AS (
        -- Cross check: Flag invoices on dispatch hold
        SELECT 
            bill_no, 
            BOOL_OR(is_on_hold) AS delivery_held
        FROM delivery_manifest_status
        GROUP BY bill_no
    ),
    active_exclusions AS (
        SELECT party_name, bill_ref
        FROM followup_exclusions
        WHERE valid_until IS NULL OR valid_until >= CURRENT_DATE
    )
    SELECT 
        b.party_name,
        b.bill_ref,
        b.pending_amount,
        (CURRENT_DATE - b.due_date) AS overdue_days,
        cm.phone,
        cm.email,
        cm.salesperson_name,
        cm.is_ignored AS master_ignored,
        COALESCE(ds.delivery_held, FALSE) AS is_delivery_held,
        (ae_p.party_name IS NOT NULL) AS is_party_excluded,
        (ae_b.bill_ref IS NOT NULL) AS is_bill_excluded,
        pfs.last_contacted_at,
        pfs.active_promise_date,
        pfs.snooze_until
    FROM tally_bills_outstanding b
    LEFT JOIN customer_master cm ON b.party_name = cm.party_name
    LEFT JOIN bill_delivery_status ds ON b.bill_ref = ds.bill_no
    LEFT JOIN active_exclusions ae_p ON b.party_name = ae_p.party_name AND ae_p.bill_ref IS NULL
    LEFT JOIN active_exclusions ae_b ON b.bill_ref = ae_b.bill_ref
    LEFT JOIN party_followup_state pfs ON b.party_name = pfs.party_name
    WHERE b.pending_amount >= 1000 AND b.due_date < CURRENT_DATE;
    """

    rows = conn.run(query)

    # Aggregate by party to enforce account-level cadence
    parties = {}
    for r in rows:
        party = r[0]
        if party not in parties:
            parties[party] = {
                "party_name": party,
                "bills": [],
                "phone": r[4],
                "email": r[5],
                "salesperson": r[6],
                "master_ignored": r[7],
                "party_excluded": r[9],
                "last_contacted": r[11],
                "promise_date": r[12],
                "snooze_until": r[13],
            }

        # Filter individual bills based on delivery hold or explicit bill exclusion
        is_delivery_held = r[8]
        is_bill_excluded = r[10]
        if not is_delivery_held and not is_bill_excluded:
            parties[party]["bills"].append(
                {"bill_ref": r[1], "pending": float(r[2]), "overdue_days": r[3]}
            )

    enqueued_count = 0

    for party, data in parties.items():
        # Exclusion rules
        if data["master_ignored"] or data["party_excluded"]:
            continue
        if data["promise_date"] and data["promise_date"] >= today:
            continue
        if data["snooze_until"] and data["snooze_until"] >= today:
            continue
        if not data["bills"]:
            continue

        total_overdue = sum(b["pending"] for b in data["bills"])
        max_days = max(b["overdue_days"] for b in data["bills"])

        bucket = resolve_bucket(
            max_days, party, global_buckets, party_buckets
        )
        if not bucket:
            continue

        # Enforce cadence cooldown
        if data["last_contacted"]:
            last_date = (
                data["last_contacted"].date()
                if isinstance(data["last_contacted"], datetime)
                else data["last_contacted"]
            )
            if today - last_date < timedelta(days=bucket["cooldown"]):
                continue

        # Insert actionable log
        conn.run(
            """
            INSERT INTO customer_followup_logs 
            (party_name, phone, email, followup_type, severity_level, total_outstanding, 
             overdue_amount, overdue_days, salesperson_name, status)
            VALUES (:party, :phone, :email, :ftype, :severity, :tot, :overdue, :days, :sp, 'PENDING');
        """,
            party=party,
            phone=data["phone"],
            email=data["email"],
            ftype=bucket["channel"],
            severity=bucket["severity"],
            tot=total_overdue,
            overdue=total_overdue,
            days=max_days,
            sp=data["salesperson"],
        )

        # Update state
        conn.run(
            """
            INSERT INTO party_followup_state (party_name, last_contacted_at, current_bucket, updated_at)
            VALUES (:party, CURRENT_TIMESTAMP, :bucket, CURRENT_TIMESTAMP)
            ON CONFLICT (party_name) DO UPDATE SET
                last_contacted_at = EXCLUDED.last_contacted_at,
                current_bucket = EXCLUDED.current_bucket,
                updated_at = CURRENT_TIMESTAMP;
        """,
            party=party,
            bucket=bucket["label"],
        )

        enqueued_count += 1

    print(
        f"[{datetime.now()}] Follow-up run completed. Enqueued {enqueued_count} actions."
    )
    conn.close()


if __name__ == "__main__":
    run_scheduler()