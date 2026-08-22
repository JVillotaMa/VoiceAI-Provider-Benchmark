## Why

The benchmark has no instrument yet. Every latency figure the project will ever publish comes
from one identical stimulus applied to five platforms, and that stimulus is the caller agent —
without it there is nothing to measure with. This change builds it and nothing else: a Pipecat
caller that runs on our own machine, follows a fixed purchase script, and can be iterated
against a microphone before a single paid phone call is placed.

## What Changes

- New `voicebench.caller` module: a Pipecat pipeline (Deepgram STT → OpenAI LLM → Cartesia TTS)
  that plays a Canadian buyer calling a shop in Austin, Texas about a product.
- The system prompt is composed of two constants: **TASK** (the purchase script, frozen — it is
  the stimulus) and **PERSONALITY** (how the caller behaves, the one parameter the agent takes).
  A single personality ships: easy-going, brief, cooperative.
- The script is 7 intents in fixed order: product availability → price → ships to Canada? →
  shipping price → negotiate → accept → thank and hang up.
- The caller terminates the call itself through an `end_call` function tool. With a free-running
  LLM this is the only deterministic thing about the end of a conversation.
- Barge-in disabled on the caller (`allow_interruptions=False`): the instrument must never talk
  over the agent under test.
- No transport ships with this change. `run_caller` takes one as an argument; the telephony
  change supplies it. A local microphone loop and then a browser WebRTC loop were both built and
  then dropped — the first real conversation will happen over the phone regardless, and a
  browser at 16 kHz proves nothing about 8 kHz mu-law over PSTN.
- Caller LLM pinned to a dated snapshot (`gpt-4.1-mini-2025-04-14`); caller TTS voice pinned by
  id. Turn-by-turn transcript logged to stdout.
- **BREAKING (documentation only)**: `CLAUDE.md` currently specifies the caller as *"6 turns,
  fixed intents in fixed order"*. This change makes it 7 intents with a variable turn count —
  negotiation can take more than one exchange. `CLAUDE.md` is updated to match.

### Measurement design

This change **touches the measurement design** in two places:

1. **Turn count.** 6 fixed turns → 7 intents, variable turns. Non-determinism is accepted
   deliberately and will be handled by running many calls per platform, not by constraining the
   caller's wording. To bound the variance, the script instructs the caller to accept the second
   counteroffer unconditionally — otherwise negotiation length would differ per platform and the
   samples would not be drawn from the same distribution.
2. **No filler audio.** The agent under test is configured with filler/thinking audio disabled on
   every platform. Some platforms emit a pre-recorded phrase while the LLM is still generating,
   which would win the primary metric without being faster. This is recorded here as a standing
   constraint on provider setup.

**Comparability with previously published runs: not affected.** `results/` is empty; no run has
been published. This is the moment to change the specification for free.

Explicitly unchanged: recording is still bidirectional two-channel captured from our end,
timestamps still come offline from audio energy, the primary metric is still last-caller-frame
to first-agent-frame, reporting is still P50/P95/P99.

## Capabilities

### New Capabilities
- `caller-agent`: the calling instrument — script, personality, LLM/STT/TTS stack, turn-taking
  rules, call termination, and the pinning guarantees that make a run reproducible by a third
  party.

### Modified Capabilities

None. `openspec/specs/` is empty; there are no existing requirements to modify.

## Impact

**New code**
- `src/voicebench/caller/prompt.py` — TASK, PERSONALITY_EASY, `build_system_prompt()`
- `src/voicebench/caller/agent.py` — pipeline assembly, `end_call` tool, `run_caller()`, `__main__`
- `tests/test_caller_prompt.py` — prompt composition check, no network

**Dependencies**
- `pipecat-ai[openai,deepgram,cartesia,silero]>=1.7.0,<2`, `python-dotenv`, `loguru`
- No transport extra: the telephony change adds `websocket`, which is what Twilio uses.
- Upper bounds are deliberate: Pipecat's params objects are Pydantic models that drop unknown
  fields silently, so a major bump reconfigures the instrument without failing.
- Triggers rule 3: `npx autoskills -a claude-code` after the dependency is added.

**Configuration**
- Consumes `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, already documented in
  `.env.example`. No new keys.

**Documentation**
- `CLAUDE.md`: caller description updated from "6 turns" to "7 intents, variable turns"; the
  no-filler constraint on agents under test added to the measurement design section.

**Explicitly out of scope** — each is its own later change:

| Out | Why it waits |
|---|---|
| Two-channel recording (`AudioBufferProcessor`) | needs the telephony transport to be worth wiring |
| Twilio outbound, public URL / tunnel | infrastructure, separable from the agent itself |
| `providers/` — creating the agent under test on the five platforms | different capability |
| `analysis/` — offline VAD, latency extraction, percentiles | different capability |
| HTTP endpoint to trigger runs | only needed once runs are orchestrated |

**This change produces no latency numbers.** It produces a caller that can buy a product over the
phone. Numbers arrive when recording and analysis land.
