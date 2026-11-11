"""LiveKit adapter for the synthetic clinic reception workflow."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Literal

from livekit.agents import (
    Agent,
    ChatContext,
    ChatMessage,
    RunContext,
    function_tool,
    inference,
)

from clinic import Reception
from voice_runtime import VoiceProfile


class ClinicAssistant(Agent):
    def __init__(self, profile: VoiceProfile, reception: Reception):
        self.reception = reception
        super().__init__(
            llm=inference.LLM(model=profile.llm_model),
            instructions=(
                "You are the AI receptionist for a fictional clinic. Speak natural, concise "
                "Arabic or English matching the caller. Explain that bookings are simulated. "
                "Handle only administrative topics. Do not collect names, phone numbers, "
                "identifiers or medical details. Never give medical advice. "
                "For policies, use clinic_policy and name the policy as the source. "
                "For availability, list slots using Muscat time and never invent a slot. "
                "When the caller chooses, call prepare_booking. Read back the date and time "
                "and ask the caller to say exactly 'confirm booking' or 'أكد الحجز' "
                "in their next turn. Do not claim success until the trusted workflow result "
                "says booked. If they change their mind or ask another question, prepare a "
                "fresh offer before asking for confirmation again. If a slot is taken, "
                "offer to recheck. Offer reception on service failure or out-of-scope "
                "requests. To queue a reception request, ask the caller to say exactly 'human reception' or 'موظف الاستقبال'. "
                "A queued request is a demo queue entry, not a live call transfer. "
                "Keep responses short and suitable for speech."
            ),
        )

    @function_tool
    async def clinic_policy(
        self, context: RunContext, topic: Literal["arrival", "hours", "changes"]
    ) -> str:
        """Retrieve a named, versioned administrative clinic policy."""
        return json.dumps(self.reception.policy(topic), ensure_ascii=False)

    @function_tool
    async def list_appointments(self, context: RunContext) -> str:
        """Read open demo appointment times in Muscat."""
        result = await asyncio.to_thread(
            self.reception.available, datetime.now(timezone.utc)
        )
        return json.dumps(result)

    @function_tool
    async def prepare_booking(self, context: RunContext, slot: str) -> str:
        """Stage a slot returned by list_appointments for readback, without booking it."""
        now = datetime.now(timezone.utc)
        availability = await asyncio.to_thread(self.reception.available, now)
        return json.dumps(self.reception.offer(slot, now, availability))

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        result = self.reception.next_action(
            new_message.text_content or "", datetime.now(timezone.utc)
        )
        if callable(result):
            result = await asyncio.to_thread(result)
        if result is not None:
            turn_ctx.add_message(
                role="assistant",
                content=f"Trusted reception workflow result: {json.dumps(result)}",
            )
