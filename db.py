"""
db.py — SQLite layer for the enhanced scheduling assistant.
Features: service types, cancellations, rescheduling, user booking history.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "scheduler.db"

# Fixed daily business-hour slots (24h clock)
BUSINESS_HOURS = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"]

# Available service types (real-life use case)
SERVICE_TYPES = [
    "General Consultation (30 min)",
    "Strategy Session (60 min)",
    "Technical Support (45 min)",
    "Demo Call (30 min)",
    "Feedback Review (60 min)"
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            email TEXT NOT NULL,
            service_type TEXT NOT NULL,
            details TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(date, time)
        )
        """
    )
    conn.commit()
    conn.close()


def get_booked_slots(date: str) -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT time FROM bookings WHERE date = ? AND status = 'confirmed'",
        (date,)
    ).fetchall()
    conn.close()
    return [r["time"] for r in rows]


def get_available_slots(date: str) -> list[str]:
    booked = set(get_booked_slots(date))
    return [t for t in BUSINESS_HOURS if t not in booked]


def insert_booking(date: str, time: str, email: str, service_type: str, details: str) -> tuple[bool, str, int]:
    """Returns (success, message, booking_id)."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO bookings (date, time, email, service_type, details, status, created_at) 
            VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (date, time, email, service_type, details, datetime.utcnow().isoformat()),
        )
        booking_id = cursor.lastrowid
        conn.commit()
        return True, "Slot reserved successfully.", booking_id
    except sqlite3.IntegrityError:
        return False, "That slot was just taken by someone else.", -1
    finally:
        conn.close()


def cancel_booking(booking_id: int, email: str) -> tuple[bool, str]:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE bookings SET status = 'cancelled', updated_at = ? WHERE id = ? AND email = ?",
            (datetime.utcnow().isoformat(), booking_id, email)
        )
        if cursor.rowcount > 0:
            conn.commit()
            return True, "Booking cancelled successfully."
        else:
            return False, "Booking not found or email doesn't match."
    finally:
        conn.close()


def reschedule_booking(booking_id: int, email: str, new_date: str, new_time: str) -> tuple[bool, str]:
    conn = get_connection()
    try:
        # Check if new slot is available
        booked = get_booked_slots(new_date)
        if new_time in booked:
            return False, "New slot is already taken."

        # Update the booking
        cursor = conn.execute(
            """
            UPDATE bookings 
            SET date = ?, time = ?, status = 'confirmed', updated_at = ? 
            WHERE id = ? AND email = ?
            """,
            (new_date, new_time, datetime.utcnow().isoformat(), booking_id, email)
        )
        if cursor.rowcount > 0:
            conn.commit()
            return True, "Booking rescheduled successfully."
        else:
            return False, "Booking not found or email doesn't match."
    except sqlite3.IntegrityError:
        return False, "New slot is already taken."
    finally:
        conn.close()


def get_user_bookings(email: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE email = ? ORDER BY date, time",
        (email,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_bookings() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM bookings ORDER BY date, time"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
