import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.voice.events import ConversationItemAddedEvent

from voice_runtime import (
    TranscriptJournal,
    VoiceProfile,
    attach_observers,
    transcript_destination,
)


def test_profile_options_are_explicit():
    profile = VoiceProfile(interruption_mode="vad", min_interruption_duration=0.7)
    assert profile.interruption_options() == {
        "enabled": True,
        "mode": "vad",
        "min_duration": 0.7,
        "resume_false_interruption": True,
    }
    assert "warm and concise" in profile.response_instructions()


@pytest.mark.parametrize(
    "change",
    [
        {"interruption_mode": "invalid"},
        {"min_interruption_duration": -1},
        {"min_interruption_duration": True},
        {"name": ""},
        {"resume_false_interruption": "false"},
    ],
)
def test_invalid_profile_rejected(change):
    with pytest.raises(ValueError):
        VoiceProfile(**change)


def test_profile_load_and_unknown_fields(tmp_path: Path):
    file = tmp_path / "profile.json"
    file.write_text(json.dumps({"name": "Example", "language": "ar"}))
    assert VoiceProfile.load(str(file)).language == "ar"
    file.write_text('{"api_key":"not-permitted"}')
    with pytest.raises(TypeError):
        VoiceProfile.load(str(file))
    file.write_text(" " * 8193)
    with pytest.raises(ValueError):
        VoiceProfile.load(str(file))


def test_journal_bounds_updates_and_redaction():
    journal = TranscriptJournal(limit=2)
    journal.record("1", "user", "demo@example.test +968 9000 0000")
    assert journal.export()["items"][0]["text"] == "[email] [phone]"
    journal.record("2", "assistant", "Partial response", True)
    journal.record("2", "assistant", "Corrected partial", True)
    assert len(journal.items) == 2
    journal.record("3", "user", "Stop")
    assert journal.export()["interrupted_turns"] == 1
    assert journal.dropped == 1
    assert list(journal.items) == ["2", "3"]


def test_save_is_private_and_never_overwrites(tmp_path: Path):
    journal = TranscriptJournal()
    target = tmp_path / "transcript.json"
    journal.save(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        journal.save(target)


def test_transcripts_require_explicit_opt_in(tmp_path: Path):
    assert transcript_destination({}, "test") is None
    with pytest.raises(ValueError):
        transcript_destination({"VOICE_TRANSCRIPT_DIR": str(tmp_path)}, "test")
    target = transcript_destination(
        {"VOICE_TRANSCRIPT_DIR": str(tmp_path), "VOICE_TRANSCRIPT_CONSENT": "true"},
        "../../test",
    )
    assert target is not None and target.parent == tmp_path
    assert "/" not in target.name


@pytest.mark.asyncio
async def test_real_sdk_events_feed_journal_without_network():
    session = AgentSession()
    journal = TranscriptJournal()
    attach_observers(session, journal)
    message = llm.ChatMessage(
        id="event-1", role="assistant", content=["Heard portion"], interrupted=True
    )
    session.emit("conversation_item_added", ConversationItemAddedEvent(item=message))
    session.emit("agent_false_interruption", SimpleNamespace())
    assert journal.export()["interrupted_turns"] == 1
    assert journal.false_interruptions == 1
    assert journal.export()["items"][0]["text"] == "Heard portion"
