"""
tools.py — the three tools the Booking Specialist can call.

All are decorated with @tool so LangGraph's ToolNode can execute them
automatically from the LLM's tool-call requests. Each returns a small dict
(as a string) so the agent gets clean, parseable feedback — including
negotiation info on failure, per the assignment's error-handling requirement.
"""

import json
import os
import re
from datetime import datetime

import requests
from langchain_core.tools import tool

from db import BUSINESS_HOURS, get_available_slots, insert_booking

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Mock notification endpoint. Defaults to httpbin.org/post (public, free, no
# signup) which simply echoes back whatever was POSTed — enough to prove the
# webhook fired. Override with a real https://webhook.site URL (via the
# WEBHOOK_URL env var / Streamlit secret) to *watch* notifications arrive live.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://httpbin.org/post")


@tool
def check_availability(date: str) -> str:
    """Check available appointment slots for a given date.

    Args:
        date: Date in YYYY-MM-DD format (must already be resolved from any
            relative phrase like "tomorrow" before calling this tool).
    """
    if not DATE_RE.match(date):
        return json.dumps(
            {"error": f"'{date}' is not in YYYY-MM-DD format. Resolve it to an "
                      f"absolute date before calling this tool."}
        )
    slots = get_available_slots(date)
    if not slots:
        return json.dumps({"date": date, "available_slots": [], "note": "Fully booked."})
    return json.dumps({"date": date, "available_slots": slots})


@tool
def reserve_slot(date: str, time: str, email: str) -> str:
    """Reserve an appointment slot.

    Args:
        date: Date in YYYY-MM-DD format.
        time: Time in 24-hour HH:MM format (must be one of the business-hour
            slots returned by check_availability).
        email: The customer's email address, used for the confirmation.
    """
    if not DATE_RE.match(date):
        return json.dumps({"success": False, "reason": f"'{date}' is not YYYY-MM-DD."})
    if not TIME_RE.match(time):
        return json.dumps({"success": False, "reason": f"'{time}' is not HH:MM (24h)."})
    if "@" not in email:
        return json.dumps({"success": False, "reason": f"'{email}' doesn't look like a valid email."})

    success, message = insert_booking(date, time, email, details=f"Appointment on {date} at {time}")
    if success:
        return json.dumps({"success": True, "message": message, "date": date, "time": time, "email": email})

    # Negotiation: slot was taken — hand back live alternatives instead of
    # just failing, so the agent can offer them to the user.
    alternatives = get_available_slots(date)
    return json.dumps(
        {
            "success": False,
            "reason": message,
            "alternative_slots_same_day": alternatives,
            "suggestion": "Offer the user one of the alternative_slots_same_day, "
                          "or ask if they'd like to try a different date.",
        }
    )


@tool
def send_booking_notification(email: str, details: str) -> str:
    """Send a mock booking confirmation notification (simulates an email/WhatsApp send).

    Args:
        email: The recipient's email address.
        details: A short human-readable summary of the booking to include in the notification.
    """
    payload = {
        "to": email,
        "details": details,
        "sent_at": datetime.utcnow().isoformat(),
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=6)
        return json.dumps(
            {
                "success": resp.ok,
                "webhook_status_code": resp.status_code,
                "webhook_url": WEBHOOK_URL,
            }
        )
    except requests.RequestException as e:
        return json.dumps({"success": False, "error": str(e)})


ALL_TOOLS = [check_availability, reserve_slot, send_booking_notification]
