from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from livekit.agents import ChatContext, ChatMessage

from clinic import ClinicStore, Reception
from clinic_agent import ClinicAssistant
from voice_runtime import VoiceProfile

NOW = datetime(2026, 11, 12, 8, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    result = ClinicStore(tmp_path / "clinic.sqlite3")
    result.initialize()
    return result


def stage(reception):
    availability = reception.available(NOW)
    slot = availability["slots"][0]
    assert reception.offer(slot, NOW, availability)["status"] == "awaiting_confirmation"
    return slot


@pytest.mark.parametrize("utterance", ["Confirm booking!", "أكِّد الحجز؟"])
def test_explicit_confirmation(store, utterance):
    caller = Reception(store, "session")
    assert caller.next_action(utterance, NOW)["status"] == "no_pending_offer"
    slot = stage(caller)
    assert slot in store.available(NOW)
    result = caller.next_action(utterance, NOW)()
    assert result["status"] == "booked"
    assert result["slot"] == slot
    assert slot not in store.available(NOW)
    assert store.book("session", slot) == result
    assert caller.next_action(utterance, NOW)["status"] == "no_pending_offer"


@pytest.mark.parametrize("utterance", ["don't confirm booking", "yes", "غير الموعد"])
def test_unrelated_turn_invalidates_offer(store, utterance):
    caller = Reception(store, "session")
    slot = stage(caller)
    assert caller.next_action(utterance, NOW) is None
    assert caller.next_action("confirm booking", NOW)["status"] == "no_pending_offer"
    assert slot in store.available(NOW)


def test_expired_offer(store):
    caller = Reception(store, "session")
    stage(caller)
    assert caller.next_action("confirm booking", NOW + timedelta(minutes=2)) == {
        "status": "slot_expired"
    }


def test_only_one_caller_can_book_same_slot(store):
    callers = [Reception(store, session) for session in ("first", "second")]
    assert stage(callers[0]) == stage(callers[1])
    actions = [caller.next_action("confirm booking", NOW) for caller in callers]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result() for future in [pool.submit(action) for action in actions]
        ]
    assert {result["status"] for result in results} == {"booked", "slot_taken"}


def test_reception_request_is_idempotent(store):
    caller = Reception(store, "session")
    stage(caller)
    first = caller.next_action("موظف الاستقبال", NOW)()
    assert first["status"] == "queued"
    assert caller.next_action("human reception", NOW)() == first
    assert caller.next_action("confirm booking", NOW)["status"] == "no_pending_offer"
    assert [item["reference"] for item in store.handoffs()] == [first["reference"]]


def test_policy_is_cited_and_unknown_topic_abstains(store):
    caller = Reception(store, "session")
    assert caller.policy("arrival")["source"] == "CLINIC-ARRIVAL-v1"
    assert caller.policy("unknown") == {"status": "no_source"}


def test_database_error_reports_unavailable(tmp_path):
    caller = Reception(ClinicStore(tmp_path / "missing" / "db"), "session")
    assert caller.available(NOW) == {"status": "booking_unavailable"}
    assert caller.next_action("human reception", NOW)() == {
        "status": "handoff_unavailable"
    }


async def test_livekit_tools_and_completed_caller_turn(store, monkeypatch):
    monkeypatch.setattr("clinic_agent.inference.LLM", lambda **kwargs: None)
    caller = Reception(store, "session")
    agent = ClinicAssistant(VoiceProfile(), caller)
    assert {tool.info.name for tool in agent.tools} == {
        "clinic_policy",
        "list_appointments",
        "prepare_booking",
    }
    now = datetime.now(timezone.utc)
    availability = caller.available(now)
    slot = availability["slots"][0]
    caller.offer(slot, now, availability)
    turn = ChatContext()
    await agent.on_user_turn_completed(
        turn, ChatMessage(role="user", content=["confirm booking"])
    )
    assert '"status": "booked"' in turn.items[-1].text_content
    assert slot not in store.available(now)
