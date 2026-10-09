"""Src/common/outstanding_scheduler.py
Evaluates debtors, applies bucket rules, compiles customized WhatsApp templates,
and logs/dispatches follow-ups using the shared project engine from ui.db_helper.
"""

from datetime import date, datetime, timedelta
import os
import sys
import pandas as pd
import requests
from sqlalchemy import text

# Ensure Src/ directory is in sys.path so imports resolve cleanly from any runner
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from ui.db_helper import get_engine
except ImportError:
    from db_helper import get_engine


def load_bucket_configs(engine):
    """Loads active bucket definitions from NeonDB."""
    query = """
        SELECT scope, party_name, min_days, COALESCE(max_days, 99999) AS max_days, 
               bucket_label, severity_level, channel, cooldown_days,
               COALESCE(message_template, '') AS message_template
        FROM followup_bucket_config
        WHERE is_active = TRUE
        ORDER BY min_days ASC;
    """
    df = pd.read_sql(query, engine)
    global_buckets = []
    party_buckets = {}

    for _, r in df.iterrows():
        cfg = {
            "min_days": int(r["min_days"]),
            "max_days": int(r["max_days"]),
            "label": r["bucket_label"],
            "severity": r["severity_level"],
            "channel": r["channel"],
            "cooldown": int(r["cooldown_days"]),
            "template": r["message_template"],
        }
        if r["scope"] == "GLOBAL":
            global_buckets.append(cfg)
        else:
            party_buckets.setdefault(r["party_name"], []).append(cfg)

    return global_buckets, party_buckets


def resolve_bucket(days: int, party_name: str, global_buckets: list, party_buckets: dict):
    """Resolves applicable bucket rules prioritizing party-specific overrides."""
    rules = party_buckets.get(party_name, global_buckets)
    for b in rules:
        if b["min_days"] <= days <= b["max_days"]:
            return b
    return global_buckets[-1] if global_buckets else None


def send_whatsapp_message(phone: str, message: str) -> bool:
    """Dispatches WhatsApp message via configured gateway webhook/API."""
    api_key = os.environ.get("WHATSAPP_API_KEY")
    api_url = os.environ.get("WHATSAPP_API_URL")

    if not api_key or not api_url or not phone:
        return False

    try:
        clean_phone = "".join(filter(str.isdigit, str(phone)))
        if len(clean_phone) == 10:
            clean_phone = "91" + clean_phone

        payload = {
            "to": clean_phone,
            "type": "text",
            "text": {"body": message}
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        res = requests.post(api_url, json=payload, headers=headers, timeout=10)
        return res.status_code in [200, 201, 202]
    except Exception as err:
        print(f"Failed to dispatch WhatsApp to {phone}: {err}")
        return False


def run_scheduler():
    engine = get_engine()
    today = date.today()
    global_buckets, party_buckets = load_bucket_configs(engine)

    # Core Query matching canonical schema
    query = """
    WITH delivery_holds AS (
        SELECT doc_no, BOOL_OR(status = 'On Hold') AS is_on_hold
        FROM delivery_status
        GROUP BY doc_no
    ),
    active_exclusions AS (
        SELECT party_name, bill_ref
        FROM followup_exclusions
        WHERE valid_until IS NULL OR valid_until >= CURRENT_DATE
    )
    SELECT 
        o.customer_name,
        o.invoice_reference AS bill_ref,
        o.pending_amount,
        (CURRENT_DATE - o.invoice_date) AS overdue_days,
        c.phone,
        c.email,
        c.salesperson,
        COALESCE(dh.is_on_hold, FALSE) AS is_delivery_held,
        (ae_p.party_name IS NOT NULL) AS is_party_excluded,
        (ae_b.bill_ref IS NOT NULL) AS is_bill_excluded,
        pfs.last_contacted_at,
        pfs.active_promise_date,
        pfs.snooze_until
    FROM outstanding_debtors o
    LEFT JOIN (
        SELECT DISTINCT ON (customer_name) customer_name, phone, email, salesperson
        FROM customers
        WHERE phone IS NOT NULL OR email IS NOT NULL
    ) c ON o.customer_name = c.customer_name
    LEFT JOIN delivery_holds dh ON o.invoice_reference = dh.doc_no
    LEFT JOIN active_exclusions ae_p ON o.customer_name = ae_p.party_name AND ae_p.bill_ref IS NULL
    LEFT JOIN active_exclusions ae_b ON o.invoice_reference = ae_b.bill_ref
    LEFT JOIN party_followup_state pfs ON o.customer_name = pfs.customer_name
    WHERE o.pending_amount >= 1000 
      AND o.invoice_date < CURRENT_DATE;
    """

    df_debtors = pd.read_sql(query, engine)

    # Aggregate by customer
    parties = {}
    for _, r in df_debtors.iterrows():
        party = r["customer_name"]
        if party not in parties:
            parties[party] = {
                "bills": [],
                "phone": r["phone"],
                "email": r["email"],
                "salesperson": r["salesperson"],
                "party_excluded": bool(r["is_party_excluded"]),
                "last_contacted": r["last_contacted_at"],
                "promise_date": r["active_promise_date"],
                "snooze_until": r["snooze_until"],
            }
        
        # Only attach bill if not on dispatch hold or specifically excluded
        if not r["is_delivery_held"] and not r["is_bill_excluded"]:
            parties[party]["bills"].append({
                "ref": r["bill_ref"],
                "pending": float(r["pending_amount"]),
                "overdue_days": int(r["overdue_days"])
            })

    enqueued_count = 0
    dispatched_count = 0

    with engine.begin() as conn:
        for party, data in parties.items():
            # Evaluation filters & guardrails
            if data["party_excluded"]:
                continue
            if data["promise_date"] and data["promise_date"] >= today:
                continue
            if data["snooze_until"] and data["snooze_until"] >= today:
                continue
            if not data["bills"]:
                continue

            total_overdue = sum(b["pending"] for b in data["bills"])
            max_days = max(b["overdue_days"] for b in data["bills"])
            bill_refs = ", ".join([b["ref"] for b in data["bills"][:5]])

            bucket = resolve_bucket(max_days, party, global_buckets, party_buckets)
            if not bucket:
                continue

            # Cadence cooldown check
            if data["last_contacted"]:
                last_dt = pd.to_datetime(data["last_contacted"]).date()
                if today - last_dt < timedelta(days=bucket["cooldown"]):
                    continue

            # Format customized message template
            template_str = bucket["template"] or (
                "Dear {customer_name}, reminder: ₹{overdue_amount:,.2f} is overdue ({overdue_days} days). Ref: {bill_refs}."
            )
            try:
                formatted_msg = template_str.format(
                    customer_name=party,
                    overdue_amount=total_overdue,
                    overdue_days=max_days,
                    bill_refs=bill_refs,
                    salesperson=data["salesperson"] or "Accounts"
                )
            except Exception:
                formatted_msg = f"Dear {party}, ₹{total_overdue:,.2f} is overdue ({max_days} days)."

            # WhatsApp Dispatch
            was_sent = False
            if bucket["channel"] == "WHATSAPP" and data["phone"]:
                was_sent = send_whatsapp_message(data["phone"], formatted_msg)
                if was_sent:
                    dispatched_count += 1

            task_status = "SENT" if was_sent else "PENDING"

            # Insert execution log
            conn.execute(
                text("""
                    INSERT INTO customer_followup_logs 
                    (customer_name, phone, email, followup_type, severity_level, 
                     total_outstanding, overdue_amount, overdue_days, salesperson, notes, status)
                    VALUES (:party, :phone, :email, :ftype, :severity, :tot, :overdue, :days, :sp, :notes, :status);
                """),
                {
                    "party": party,
                    "phone": data["phone"],
                    "email": data["email"],
                    "ftype": bucket["channel"],
                    "severity": bucket["severity"],
                    "tot": total_overdue,
                    "overdue": total_overdue,
                    "days": max_days,
                    "sp": data["salesperson"],
                    "notes": formatted_msg,
                    "status": task_status
                }
            )

            # Upsert customer cadence state
            conn.execute(
                text("""
                    INSERT INTO party_followup_state (customer_name, last_contacted_at, current_bucket, updated_at)
                    VALUES (:party, CURRENT_TIMESTAMP, :bucket, CURRENT_TIMESTAMP)
                    ON CONFLICT (customer_name) DO UPDATE SET
                        last_contacted_at = EXCLUDED.last_contacted_at,
                        current_bucket = EXCLUDED.current_bucket,
                        updated_at = CURRENT_TIMESTAMP;
                """),
                {
                    "party": party,
                    "bucket": bucket["label"]
                }
            )

            enqueued_count += 1

    print(f"[{datetime.now()}] Followup run finished: {enqueued_count} processed ({dispatched_count} dispatched via WhatsApp).")


if __name__ == "__main__":
    run_scheduler()