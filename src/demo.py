"""Offline event replay; does not synthesize or capture voice."""

import json

from voice_runtime import TranscriptJournal, VoiceProfile


def main():
    profile = VoiceProfile.load("examples/voice-profile.json")
    journal = TranscriptJournal()
    journal.record("demo-1", "user", "Hello, what can you help with?")
    journal.record("demo-2", "assistant", "I can help explain", interrupted=True)
    journal.record("demo-3", "user", "Please keep it brief.")
    journal.record("demo-4", "assistant", "Of course. What would you like to know?")
    print(
        json.dumps(
            {
                "demo": "synthetic event replay, not live audio",
                "interruption": profile.interruption_options(),
                "transcript": journal.export(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
