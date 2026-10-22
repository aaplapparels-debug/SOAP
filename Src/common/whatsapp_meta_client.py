import os
import requests
import streamlit as st

def get_meta_config():
    """Fetches Meta credentials from st.secrets or environment variables."""
    token = st.secrets.get("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_TOKEN")
    phone_number_id = st.secrets.get("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    return token, phone_number_id

def send_whatsapp_template(to_phone: str, customer_name: str, overdue_amt: str, overdue_days: str, bill_refs: str) -> bool:
    """
    Dispatches a business-initiated template message via Meta WhatsApp Cloud API.
    Note: Variables map directly to {{1}}, {{2}}, {{3}}, {{4}} in your approved template.
    """
    token, phone_number_id = get_meta_config()
    if not token or not phone_number_id:
        st.error("WhatsApp Cloud API credentials not configured.")
        return False

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": st.secrets.get("WHATSAPP_TEMPLATE_NAME", "debtor_followup"),
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(customer_name)},
                        {"type": "text", "text": str(overdue_amt)},
                        {"type": "text", "text": str(overdue_days)},
                        {"type": "text", "text": str(bill_refs)},
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        res_data = response.json()
        if response.status_code in (200, 201) and "messages" in res_data:
            return True
        else:
            st.warning(f"Failed sending to {to_phone}: {res_data.get('error', {}).get('message', 'Unknown error')}")
            return False
    except Exception as e:
        st.error(f"Request exception for {to_phone}: {e}")
        return False