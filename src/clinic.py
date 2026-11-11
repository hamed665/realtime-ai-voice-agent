"""Synthetic reception workflows, independent of LiveKit and model providers."""

import argparse
import json
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

MUSCAT = timezone(timedelta(hours=4), "Asia/Muscat")
CONFIRMATIONS = {"confirm booking", "أكد الحجز", "اكد الحجز", "تأكيد الحجز"}
RECEPTION_REQUESTS = {"human reception", "موظف الاستقبال", "الاستقبال"}
OFFER_TTL = timedelta(minutes=2)
POLICIES = {
    "arrival": {
        "source": "CLINIC-ARRIVAL-v1",
        "en": "The clinic arrival policy asks you to arrive ten minutes early.",
        "ar": "حسب سياسة الوصول للعيادة، يرجى الحضور قبل الموعد بعشر دقائق.",
    },
    "hours": {
        "source": "CLINIC-HOURS-v1",
        "en": "The demo clinic policy lists opening hours from nine to five, Muscat time.",
        "ar": "حسب سياسة العيادة التجريبية، الدوام من التاسعة إلى الخامسة بتوقيت مسقط.",
    },
    "changes": {
        "source": "CLINIC-CHANGES-v1",
        "en": "The clinic booking policy asks you to contact reception to change a booking.",
        "ar": "حسب سياسة الحجز، تواصل مع الاستقبال لتعديل الموعد.",
    },
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.strip().strip(".!؟?،").split())


class ClinicStore:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        return closing(sqlite3.connect(self.path, timeout=3))

    def initialize(self):
        with self.connect() as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bookings (
                    slot TEXT PRIMARY KEY, session TEXT UNIQUE NOT NULL,
                    reference TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    session TEXT PRIMARY KEY, reference TEXT UNIQUE NOT NULL,
                    reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def available(self, now: datetime) -> list[str]:
        start = now.astimezone(MUSCAT).date() + timedelta(days=1)
        with self.connect() as db:
            booked = {
                row[0]
                for row in db.execute(
                    "SELECT slot FROM bookings WHERE slot >= ?", (start.isoformat(),)
                )
            }
        return [
            f"{start.isoformat()}T{hour:02}:00+04:00"
            for hour in (10, 14)
            if f"{start.isoformat()}T{hour:02}:00+04:00" not in booked
        ]

    def book(self, session: str, slot: str) -> dict:
        with self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT slot, reference FROM bookings WHERE session = ?", (session,)
            ).fetchone()
            if previous:
                if previous[0] == slot:
                    return {"status": "booked", "slot": slot, "reference": previous[1]}
                return {"status": "already_booked", "slot": previous[0]}
            reference = uuid4().hex[:10]
            cursor = db.execute(
                "INSERT INTO bookings VALUES (?, ?, ?) ON CONFLICT(slot) DO NOTHING",
                (slot, session, reference),
            )
            if cursor.rowcount == 0:
                return {"status": "slot_taken", "slot": slot}
            return {"status": "booked", "slot": slot, "reference": reference}

    def handoff(self, session: str, reason: str) -> dict:
        with self.connect() as db, db:
            db.execute(
                """INSERT INTO handoffs (session, reference, reason) VALUES (?, ?, ?)
                   ON CONFLICT(session) DO NOTHING""",
                (session, uuid4().hex[:10], reason),
            )
            reference = db.execute(
                "SELECT reference FROM handoffs WHERE session = ?", (session,)
            ).fetchone()[0]
        return {"status": "queued", "reference": reference}

    def handoffs(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT reference, reason, created_at FROM handoffs
                   ORDER BY rowid DESC LIMIT 50"""
            ).fetchall()
        return [dict(zip(("reference", "reason", "created_at"), row)) for row in rows]


class Reception:
    def __init__(self, store: ClinicStore, session: str):
        self.store = store
        self.session = session
        self.pending: tuple[str, datetime] | None = None

    def policy(self, topic: str) -> dict:
        return POLICIES.get(topic, {"status": "no_source"}).copy()

    def available(self, now: datetime) -> dict:
        try:
            return {"status": "ok", "slots": self.store.available(now)}
        except sqlite3.Error:
            return {"status": "booking_unavailable"}

    def offer(self, slot: str, now: datetime, availability: dict) -> dict:
        if availability["status"] != "ok":
            return availability
        if slot not in availability["slots"]:
            return {"status": "slot_unavailable"}
        if self.pending is not None:
            return {"status": "offer_already_pending", "slot": self.pending[0]}
        self.pending = (slot, now + OFFER_TTL)
        return {"status": "awaiting_confirmation", "slot": slot}

    def next_action(self, transcript: str, now: datetime):
        pending, self.pending = self.pending, None
        utterance = normalize(transcript)
        if utterance in RECEPTION_REQUESTS:
            return self.queue_reception
        if utterance not in CONFIRMATIONS:
            return None
        if pending is None:
            return {"status": "no_pending_offer"}
        slot, deadline = pending
        if now >= deadline or datetime.fromisoformat(slot) <= now:
            return {"status": "slot_expired"}
        return lambda: self.book(slot)

    def book(self, slot: str) -> dict:
        try:
            return self.store.book(self.session, slot)
        except sqlite3.Error:
            return {"status": "booking_unavailable"}

    def queue_reception(self) -> dict:
        try:
            return self.store.handoff(self.session, "caller_request")
        except sqlite3.Error:
            return {"status": "handoff_unavailable"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="View synthetic reception requests")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    store = ClinicStore(args.database)
    if not args.database.is_file():
        parser.error("database does not exist")
    print(json.dumps(store.handoffs(), indent=2))
