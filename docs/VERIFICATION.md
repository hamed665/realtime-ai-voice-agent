# Voice agent verification

Date: 2026-10-19. Upstream baseline: `e965b2ce057679da1bdd7ebfc8b6716053b2d838`, committed 2026-10-15. Public repository, not archived; MIT license Copyright 2025 LiveKit, Inc. preserved.

## Baseline

- `uv sync --group dev` succeeded on Python 3.12.14 (88 resolved dependency records).
- Original `uv run ruff check`: pass.
- Original `uv run pytest`: zero collected tests; exit 5. Upstream's test file is a commented example, not an executable test suite.
- Original CLI import/help executed successfully with `uv run python src/agent.py --help`.
- No disposable LiveKit project was configured and no real inference request was made.

## Extension results

- `uv run pytest`: 11 passed, including actual SDK conversation-event emission without starting a network session.
- `uv run ruff check` and `uv run ruff format --check`: pass.
- Modified CLI import/help: pass.
- `uv run python src/demo.py`: pass; output committed as the explicitly synthetic `examples/demo-transcript.json`.
- `pip-audit` of the installed environment: no known vulnerabilities found. This is not a security guarantee; model/service dependencies need their own review.
- Console runtime probe failed because the local PortAudio library is unavailable. Real audio, microphone capture, TTS, latency, model grounding and adaptive interruption accuracy were not verified.
- LiveKit simulation/debugger runs are blocked by the lack of a disposable authenticated, funded LiveKit project. A scenario was added before instruction changes, but has not been run against an LLM. Do not call the agent production-ready.
- The current environment does not include LiveKit's optional agent skill bundle. A developer running live verification should install it with `lk skills install`, as recommended by upstream AGENTS.md.

## Source references consulted

- https://docs.livekit.io/agents/logic/sessions/
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/reference/agents/events/
- https://docs.livekit.io/testing/simulations/

The installed SDK's `voice/turn.py` and `voice/events.py` were also inspected to confirm exact interruption keys and event fields. The extension uses supported SDK events and delegates audio processing to LiveKit.

## Remaining gates

Run the LiveKit debugger and cloud text scenarios with disposable credentials, then real audio scenarios covering interruption, backchannel resumption, disconnect/close exports and language-provider compatibility. Review all provider and model terms before paid use. The added offline CI cannot substitute for those checks.
