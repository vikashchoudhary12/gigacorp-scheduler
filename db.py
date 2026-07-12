"""
db.py — tiny SQLite layer for the scheduling assistant.

One table, `bookings`, with a UNIQUE(date, time) constraint so double-booking
a slot fails cleanly and predictably — the agent then negotiates an
alternative instead of silently overwriting someone else's booking.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "scheduler.db"

# Fixed daily business-hour slots (24h clock). Keep small & predictable so the
# demo is easy to reason about and to exhaust (for testing "slot taken").
BUSINESS_HOURS = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00", "16:00"]


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
            details TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(date, time)
        )
        """
    )
    conn.commit()
    conn.close()


def get_booked_slots(date: str) -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT time FROM bookings WHERE date = ?", (date,)).fetchall()
    conn.close()
    return [r["time"] for r in rows]


def get_available_slots(date: str) -> list[str]:
    booked = set(get_booked_slots(date))
    return [t for t in BUSINESS_HOURS if t not in booked]


def insert_booking(date: str, time: str, email: str, details: str) -> tuple[bool, str]:
    """Returns (success, message). Fails cleanly on a UNIQUE constraint clash
    (slot already taken) instead of raising, so callers can negotiate."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO bookings (date, time, email, details, created_at) VALUES (?, ?, ?, ?, ?)",
            (date, time, email, details, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return True, "Slot reserved successfully."
    except sqlite3.IntegrityError:
        return False, "That slot was just taken by someone else."
    finally:
        conn.close()
