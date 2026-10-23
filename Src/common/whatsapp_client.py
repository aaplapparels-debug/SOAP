"""
whatsapp_client.py
Central client for dispatching WhatsApp messages via Evolution API.
"""

import os
import time
import random
import requests
import base64


def _get_api_credentials():
    """Extracts disguised credentials from Streamlit secrets with fallback."""
    if "telemetry_bridge" in st.secrets:
        url = st.secrets["telemetry_bridge"]["endpoint"].rstrip("/")
        key = st.secrets["telemetry_bridge"]["access_token"]
        instance = st.secrets["telemetry_bridge"]["session_id"]
    else:
        # Local development fallback
        url = "http://localhost:8080"
        key = "soap_dev_secret_key_2026"
        instance = "soap_instance"
    return url, key, instance

def send_whatsapp_document(phone: str, file_bytes: bytes, filename: str, caption: str = "") -> dict:
    url, key, instance = _get_api_credentials()
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    endpoint = f"{url}/message/sendMedia/{instance}"
    headers = {"apikey": key, "Content-Type": "application/json"}

    b64_data = base64.b64encode(file_bytes).decode("utf-8")
    mime_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if filename.endswith(".xlsx")
        else "application/pdf"
    )

    payload = {
        "number": clean_phone,
        "mediatype": "document",
        "mimetype": mime_type,
        "caption": caption,
        "media": b64_data,
        "fileName": filename
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=25)
        if resp.status_code in (200, 201):
            return {"status": "success", "data": resp.json()}
        return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
        
def send_whatsapp_reminder(phone: str, message: str) -> dict:
    url, key, instance = _get_api_credentials()
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    endpoint = f"{url}/message/sendText/{instance}"
    headers = {"apikey": key, "Content-Type": "application/json"}
    payload = {"number": clean_phone, "text": message}

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        if resp.status_code in (200, 201):
            return {"status": "success", "data": resp.json()}
        return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def batch_dispatch_with_delay(reminders: list[dict], progress_callback=None) -> dict:
    """Iterates through reminder items using humanized anti-ban sleep jitter.

    reminders format: [{"id": 12, "phone": "91...", "message": "...",
    "customer": "ABC"}, ...] Returns: {"successful_ids": [...],
    "failed_accounts": [...]}
    """
    successful_ids = []
    failed_accounts = []
    total = len(reminders)

    for idx, item in enumerate(reminders):
        recipient = item["phone"]
        msg_text = item["message"]
        cust_name = item.get("customer", recipient)

        if progress_callback:
            progress_callback(idx + 1, total, cust_name)

        result = send_whatsapp_reminder(recipient, msg_text)

        if result.get("status") == "success":
            successful_ids.append(item["id"])
        else:
            err_msg = result.get("error") or result.get("message") or "Failed"
            failed_accounts.append(f"{cust_name} ({err_msg})")

        # Anti-ban sleep jitter: 6 to 15 seconds between dispatches (skip on last message)
        if idx < total - 1:
            time.sleep(random.uniform(30, 45.0))

    return {
        "successful_ids": successful_ids,
        "failed_accounts": failed_accounts
    }