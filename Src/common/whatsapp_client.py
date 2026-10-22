"""
whatsapp_client.py
Central client for dispatching WhatsApp messages via Evolution API.
"""

import os
import time
import random
import requests

EVO_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVO_KEY = os.getenv("EVOLUTION_API_KEY", "soap_dev_secret_key_2026")
EVO_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "soap_instance")

def send_whatsapp_document(phone: str, pdf_bytes: bytes, filename: str, caption: str = "") -> dict:
    """
    Sends a PDF document with an optional caption via Evolution API sendMedia.
    """
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    endpoint = f"{EVOLUTION_API_URL}/message/sendMedia/{INSTANCE_NAME}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}

    b64_data = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "number": clean_phone,
        "mediatype": "document",
        "mimetype": "application/pdf",
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
    """Dispatches a single multiline WhatsApp message via Evolution API."""
    clean_digits = "".join(filter(str.isdigit, str(phone)))
    if len(clean_digits) == 10:
        target_number = f"91{clean_digits}"
    elif len(clean_digits) == 12 and clean_digits.startswith("91"):
        target_number = clean_digits
    else:
        return {"status": "error", "message": f"Invalid phone format: {phone}"}

    url = f"{EVO_URL}/message/sendText/{EVO_INSTANCE}"
    headers = {
        "apikey": EVO_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": target_number,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code in (200, 201):
            return {"status": "success", "data": response.json()}
        return {
            "status": "failed",
            "code": response.status_code,
            "error": response.text
        }
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


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