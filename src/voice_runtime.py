"""Validated voice profiles and bounded, opt-in transcript observability."""

import json
import os
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class VoiceProfile:
    name: str = "Demo Assistant"
    language: str = "en"
    tone: str = "warm and concise"
    llm_model: str = "google/gemma-4-31b-it"
    interruption_mode: Literal["adaptive", "vad"] = "adaptive"
    min_interruption_duration: float = 0.5
    resume_false_interruption: bool = True

    def __post_init__(self):
        for field in (self.name, self.language, self.tone, self.llm_model):
            if not isinstance(field, str) or not field.strip() or len(field) > 160:
                raise ValueError("Profile strings must contain 1-160 characters")
        if self.interruption_mode not in ("adaptive", "vad"):
            raise ValueError("Unsupported interruption mode")
        duration = self.min_interruption_duration
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not 0.1 <= duration <= 3
        ):
            raise ValueError("Interruption duration must be between 0.1 and 3 seconds")
        if not isinstance(self.resume_false_interruption, bool):
            raise ValueError("resume_false_interruption must be boolean")

    @classmethod
    def load(cls, path: str | None = None):
        if not path:
            return cls()
        file = Path(path)
        if file.stat().st_size > 8192:
            raise ValueError("Profile is larger than 8 KiB")
        data = json.loads(file.read_text())
        if not isinstance(data, dict):
            raise ValueError("Profile must be a JSON object")
        return cls(**data)

    def response_instructions(self) -> str:
        return f"Your display name is {self.name}. Respond in language {self.language} with a {self.tone} tone. Keep the original safety and output rules."

    def interruption_options(self):
        return {
            "enabled": True,
            "mode": self.interruption_mode,
            "min_duration": self.min_interruption_duration,
            "resume_false_interruption": self.resume_false_interruption,
        }


def redact(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    return re.sub(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)", "[phone]", text)


@dataclass(frozen=True)
class TranscriptItem:
    id: str
    role: str
    text: str
    interrupted: bool


class TranscriptJournal:
    """Tracks finalized conversation items, not raw audio or partial STT guesses."""

    def __init__(self, limit: int = 500):
        if not 1 <= limit <= 1000:
            raise ValueError("Transcript limit must be 1-1000")
        self.limit = limit
        self.items: OrderedDict[str, TranscriptItem] = OrderedDict()
        self.false_interruptions = 0
        self.dropped = 0

    def record(self, item_id: str, role: str, text: str, interrupted: bool = False):
        if role not in ("user", "assistant") or not text.strip():
            return
        if len(item_id) > 200:
            raise ValueError("Invalid item ID")
        item = TranscriptItem(item_id, role, redact(text[:8000]), bool(interrupted))
        self.items[item_id] = item
        if len(self.items) > self.limit:
            self.items.popitem(last=False)
            self.dropped += 1

    def export(self):
        return {
            "schema_version": 1,
            "false_interruptions": self.false_interruptions,
            "interrupted_turns": sum(item.interrupted for item in self.items.values()),
            "dropped_items": self.dropped,
            "items": [asdict(item) for item in self.items.values()],
        }

    def save(self, path: Path):
        # New files only, restrictive permissions; no accidental overwrite.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(self.export(), stream, ensure_ascii=False, indent=2)


def transcript_destination(environ: dict[str, str], session_id: str) -> Path | None:
    directory = environ.get("VOICE_TRANSCRIPT_DIR", "")
    if not directory:
        return None
    if environ.get("VOICE_TRANSCRIPT_CONSENT") != "true":
        raise ValueError("Explicit transcript consent is required before saving")
    folder = Path(directory)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:100]
    if not filename:
        raise ValueError("Session ID is required")
    return folder / f"{filename}.json"


def attach_observers(session, journal: TranscriptJournal):
    @session.on("conversation_item_added")
    def on_item(event):
        item = event.item
        # Agent handoffs are not speech messages.
        if getattr(item, "type", None) != "message":
            return
        journal.record(item.id, item.role, item.text_content or "", item.interrupted)

    @session.on("agent_false_interruption")
    def on_false_interruption(_event):
        journal.false_interruptions += 1
