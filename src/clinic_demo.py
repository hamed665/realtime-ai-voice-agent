"""Replay a synthetic reception workflow without a LiveKit account."""

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from clinic import ClinicStore, Reception


def replay() -> dict:
    now = datetime(2026, 11, 12, 8, tzinfo=timezone.utc)
    with TemporaryDirectory() as directory:
        store = ClinicStore(Path(directory) / "demo.sqlite3")
        store.initialize()
        caller = Reception(store, "synthetic-demo")
        availability = caller.available(now)
        slot = availability["slots"][0]
        return {
            "policy": caller.policy("arrival"),
            "availability": availability,
            "offer": caller.offer(slot, now, availability),
            "confirmed_booking": caller.next_action("أكد الحجز", now)(),
            "reception_request": caller.next_action("human reception", now)(),
            "operator_queue": store.handoffs(),
        }


if __name__ == "__main__":
    print(json.dumps(replay(), ensure_ascii=False, indent=2))
