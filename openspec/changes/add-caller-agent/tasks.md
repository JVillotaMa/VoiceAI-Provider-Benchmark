## 1. Dependencies

- [x] 1.1 `uv add "pipecat-ai[openai,deepgram,cartesia,silero,webrtc]" pipecat-ai-small-webrtc-prebuilt python-dotenv` — resolved `pipecat-ai 1.7.0`
- [x] 1.2 Bounded `pipecat-ai>=1.7.0,<2` and the prebuilt UI `<3`, with the reason in a comment — a major bump would silently reconfigure the instrument
- [x] 1.3 pyaudio failed to build (`portaudio.h` missing, only the runtime `libportaudio2` present). Switched to the WebRTC transport per the documented fallback — no sudo, no native build
- [x] 1.4 Ran `npx autoskills -a claude-code`; installed `pydantic`, `python-testing-patterns`, `python-executor`. Read `python-executor` (flagged): it ships code to a third-party remote sandbox (inference.sh) behind an external login. Inert today — `belt` is not installed — but it is an off-machine path in a repo holding five platforms' API keys, and `uv run` covers every local need. Recommend removing it

## 2. Prompt

- [x] 2.1 Pick the product — a concrete model name, not a category — and record it in `design.md` as resolved
- [x] 2.2 Write `src/voicebench/caller/prompt.py` with `TASK`: the seven intents in order, one intent per turn, no advancing without an answer, accept the second counteroffer unconditionally, English, end with `end_call`
- [x] 2.3 Add `PERSONALITY_EASY`: easy-going, cooperative, 1–2 sentences per turn, no trailing tags or filler at the end of an utterance
- [x] 2.4 Add `build_system_prompt(personality: str) -> str` — pure, no network, no credentials

## 3. Agent

- [x] 3.1 Write `src/voicebench/caller/agent.py`: Deepgram STT → OpenAI LLM → Cartesia TTS pipeline with the context aggregator pair
- [x] 3.2 Pin the LLM to `gpt-4.1-mini-2025-04-14` and the Cartesia voice to `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`, both as module constants, neither exposed as a parameter
- [x] 3.3 Add the `end_call` function tool and wire it to terminate the pipeline task
- [x] 3.4 Set the VAD `stop_secs` and `user_turn_stop_timeout` explicitly and conservatively on `LLMUserAggregatorParams` so the caller never talks over the agent under test; leave `user_mute_strategies` empty so the caller yields when talked over; set `idle_timeout_secs=20` on the pipeline task
- [x] 3.5 Confirm the caller does not speak first — no kickoff frame, it waits for the other party
- [x] 3.6 Define `run_caller(transport, personality=PERSONALITY_EASY)` taking the transport as an argument
- [x] 3.7 Log the per-turn transcript for both parties to stdout
- [x] 3.8 ~~Add a dev entry point~~ — dropped. A WebRTC browser entry point was built and then removed: it validates nothing that the telephony change will not validate better, and it dragged a transport dependency into a module whose whole point is that the transport is an argument
- [x] 3.9 Load credentials from `.env` via python-dotenv; fail with a clear message naming the missing variable rather than a stack trace

## 4. Check

- [x] 4.1 Write `tests/test_caller_prompt.py`: composed prompt contains TASK and the given personality, the seven intents appear in order, and two different personalities yield identical TASK text
- [x] 4.2 `uv run ruff check --fix . && uv run ruff format .`
- [x] 4.3 `uv run mypy`
- [x] 4.4 `uv run deptry src`
- [x] 4.5 `uv run pytest`

## 5. Behavioural validation — done over real telephony

Deferred out of this change on purpose and completed in `add-twilio-test-call`: a browser loop at
16 kHz answers nothing about 8 kHz mu-law over PSTN, and the first real conversation was always
going to happen over the phone.

**Validated on a real outbound call**, author playing the shop employee. The caller holds the
script, ends the call itself, and hangs up on silence rather than re-prompting.

- [x] 5.1 The caller stays silent until you greet it
- [x] 5.2 It asks the seven intents in order, one per turn, never two in one utterance
- [x] 5.3 Answer evasively on one intent — it re-addresses that intent instead of advancing
- [x] 5.4 Counter three times — it accepts on the second counteroffer
- [x] 5.5 Stay silent for 25 seconds mid-call — it never re-prompts, and the call ends at the timeout
- [x] 5.6 It thanks you, calls `end_call`, and the call terminates
- [x] 5.7 Iterate `TASK` / `PERSONALITY_EASY` until 5.1–5.6 hold, then stop touching the prompt

## 6. Documentation and landing

- [x] 6.1 Update `CLAUDE.md`: caller is 7 intents with variable turn count, not "6 turns"
- [x] 6.2 Add the no-filler constraint on agents under test to the measurement design section of `CLAUDE.md`, so `providers/` inherits it
- [x] 6.3 Note in `CLAUDE.md` that the caller LLM snapshot and TTS voice id are frozen, and that changing either invalidates comparability
- [x] 6.4 Conventional commits on `dev`, scoped small (`feat(caller): ...`, `docs: ...`)
- [x] 6.5 Ask before running `/code-review` (rule 2); no PR to `main` without it
