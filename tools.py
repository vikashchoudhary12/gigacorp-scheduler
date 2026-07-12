"""
tools.py — enhanced tools for the Booking Specialist.

Includes new tools: cancel booking, reschedule, get user bookings, etc.
"""

import json
import os
import re
from datetime import datetime

import requests
from langchain_core.tools import tool

from db import (
    BUSINESS_HOURS,
    SERVICE_TYPES,
    get_available_slots,
    insert_booking,
    cancel_booking,
    reschedule_booking,
    get_user_bookings,
    get_all_bookings
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Mock notification endpoint
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://httpbin.org/post")


@tool
def check_availability(date: str) -> str:
    """Check available appointment slots for a given date.

    Args:
        date: Date in YYYY-MM-DD format.
    """
    if not DATE_RE.match(date):
        return json.dumps(
            {"error": f"'{date}' is not in YYYY-MM-DD format. Resolve it to an absolute date first."}
        )
    slots = get_available_slots(date)
    if not slots:
        return json.dumps({"date": date, "available_slots": [], "note": "Fully booked."})
    return json.dumps({"date": date, "available_slots": slots})


@tool
def reserve_slot(date: str, time: str, email: str, service_type: str) -> str:
    """Reserve an appointment slot.

    Args:
        date: Date in YYYY-MM-DD format.
        time: Time in 24-hour HH:MM format.
        email: The customer's email address.
        service_type: Type of service (must be one of: General Consultation (30 min), Strategy Session (60 min), Technical Support (45 min), Demo Call (30 min), Feedback Review (60 min)).
    """
    if not DATE_RE.match(date):
        return json.dumps({"success": False, "reason": f"'{date}' is not YYYY-MM-DD."})
    if not TIME_RE.match(time):
        return json.dumps({"success": False, "reason": f"'{time}' is not HH:MM (24h)."})
    if "@" not in email:
        return json.dumps({"success": False, "reason": f"'{email}' doesn't look like a valid email."})
    if service_type not in SERVICE_TYPES:
        return json.dumps({"success": False, "reason": f"Invalid service type. Choose from: {', '.join(SERVICE_TYPES)}"})

    success, message, booking_id = insert_booking(
        date, time, email, service_type, 
        details=f"{service_type} on {date} at {time}"
    )
    if success:
        return json.dumps({
            "success": True, 
            "message": message, 
            "date": date, 
            "time": time, 
            "email": email, 
            "service_type": service_type,
            "booking_id": booking_id
        })

    alternatives = get_available_slots(date)
    return json.dumps({
        "success": False,
        "reason": message,
        "alternative_slots_same_day": alternatives,
        "suggestion": "Offer alternatives or a different date."
    })


@tool
def cancel_booking_tool(booking_id: int, email: str) -> str:
    """Cancel an existing booking.

    Args:
        booking_id: ID of the booking to cancel.
        email: Email address associated with the booking.
    """
    success, message = cancel_booking(booking_id, email)
    return json.dumps({"success": success, "message": message})


@tool
def reschedule_booking_tool(booking_id: int, email: str, new_date: str, new_time: str) -> str:
    """Reschedule an existing booking to a new date/time.

    Args:
        booking_id: ID of the booking to reschedule.
        email: Email address associated with the booking.
        new_date: New date in YYYY-MM-DD format.
        new_time: New time in HH:MM format.
    """
    success, message = reschedule_booking(booking_id, email, new_date, new_time)
    if success:
        return json.dumps({
            "success": True, "message": message, "new_date": new_date, "new_time": new_time})
    alternatives = get_available_slots(new_date)
    return json.dumps({
        "success": False,
        "reason": message,
        "alternative_slots": alternatives
    })


@tool
def get_user_bookings_tool(email: str) -> str:
    """Get all bookings for a specific email address.

    Args:
        email: Email address to look up bookings for.
    """
    bookings = get_user_bookings(email)
    return json.dumps({"email": email, "bookings": bookings})


@tool
def get_service_types() -> str:
    """Get list of available service types."""
    return json.dumps({"service_types": SERVICE_TYPES})


@tool
def send_booking_notification(email: str, details: str) -> str:
    """Send a booking confirmation notification (either via webhook or real email).

    Args:
        email: The recipient's email address.
        details: A short human-readable summary of the booking.
    """
    # First, try to send real email if SendGrid API key is available
    sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("FROM_EMAIL", "notifications@gigacorp.com")
    
    if sendgrid_api_key:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            
            message = Mail(
                from_email=from_email,
                to_emails=email,
                subject="Your GigaCorp Appointment Confirmation",
                html_content=f"""
                <h1>Appointment Confirmed!</h1>
                <p>Hi there,</p>
                <p>Your appointment has been booked successfully:</p>
                <p><strong>{details}</strong></p>
                <p>Thanks for booking with GigaCorp!</p>
                """
            )
            sg = SendGridAPIClient(sendgrid_api_key)
            response = sg.send(message)
            return json.dumps({
                "success": True,
                "method": "email",
                "status_code": response.status_code
            })
        except Exception as e:
            # If email fails, fall back to webhook
            pass
    
    # Fallback to webhook (demo mode)
    payload = {
        "to": email,
        "details": details,
        "sent_at": datetime.utcnow().isoformat(),
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=6)
        return json.dumps({
            "success": resp.ok,
            "method": "webhook",
            "status_code": resp.status_code,
            "webhook_url": WEBHOOK_URL,
        })
    except requests.RequestException as e:
        return json.dumps({"success": False, "error": str(e)})


ALL_TOOLS = [
    check_availability, reserve_slot, cancel_booking_tool, 
    reschedule_booking_tool, get_user_bookings_tool, 
    get_service_types, send_booking_notification
]
