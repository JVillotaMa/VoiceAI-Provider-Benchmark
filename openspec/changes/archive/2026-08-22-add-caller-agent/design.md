## Context

The repository is a scaffold: `src/voicebench/` holds only empty `__init__.py` files and
`pyproject.toml` declares no runtime dependencies. Nothing has been measured, nothing published.

The caller agent is the instrument. Every number this project will publish is produced by
applying one stimulus to five platforms and timing the response. If the stimulus differs between
platforms, the comparison is worthless; if it differs between runs, the time series is worthless.
So the design pressure here is not flexibility — it is *frozen-ness plus traceability*.

Two constraints shape everything below:

1. **The caller must be identical across platforms.** It does not know which platform it is
   talking to. Anything platform-aware belongs in `providers/`.
2. **The primary metric is measured offline from audio**, last caller frame with energy → first
   agent frame with energy. That decides which parts of the caller matter and which do not — see
   the first decision.

## Goals / Non-Goals

**Goals:**
- A Pipecat caller that runs on the author's own machine or server, follows the purchase script,
  and ends the call itself.
- A system prompt split into TASK (frozen stimulus) and PERSONALITY (the one parameter).
- A development loop that does not require telephony, a public URL, or paid calls.
- Every version-bearing choice pinned: LLM snapshot with date, TTS voice by id, Pipecat version.

**Non-Goals:**
- Producing any latency number. This change measures nothing.
- Two-channel recording, Twilio, tunnels, phone numbers.
- Creating or configuring agents on the five platforms under test.
- Offline analysis, VAD, percentiles.
- An HTTP interface to trigger runs. That arrives when runs need orchestrating; today the
  entry point is `python -m voicebench.caller`.
- Multiple personalities or model comparison. One personality ships. The seam exists because the
  prompt is composed, not because a second one is planned.

## Decisions

### 1. What is frozen and what is a parameter — derived from the metric

The metric starts at the *last caller audio frame with energy*. That single fact partitions the
caller's stack:

| Component | In the metric? | Consequence |
|---|---|---|
| Caller LLM | No — it runs before the caller speaks | Its speed is irrelevant. Chosen for script-following and cost. |
| Caller STT | No — only decides when the caller starts thinking | Frozen for simplicity, not for correctness. |
| Caller TTS voice | **Yes — it *is* the stimulus** | Frozen by voice id. How an utterance ends prosodically is exactly what triggers the DUT's endpointing. |
| Personality | Shapes utterance length and shape | Parameter, and it must be recorded alongside every published result. |

`gpt-4.1-mini-2025-04-14`, dated. `gpt-4.1-mini` is a moving alias; a repointed alias silently
invalidates a time series, which reproducibility rules out.

*Alternative considered:* a `ModelSpec` dataclass covering the whole stack (LLM + STT + TTS +
voice) as a parameter. Rejected — it makes the voice swappable, and swapping the voice moves the
instrument. Making a footgun ergonomic is not a feature.

### 2. No factory, no interface — one module, one function

`run_caller(transport, personality=PERSONALITY_EASY)`. No abstract base class, no registry, no
plugin lookup. There is one caller and there will be one caller; what varies in this benchmark is
the platform being dialled, and from the caller's side that is a phone number — a string it never
sees.

The interface, when it comes, belongs at the run-orchestration layer (which platform, how many
calls, where the audio lands), not at the agent layer.

*Alternative considered:* `build_caller(model, personality)` factory. Rejected — a factory for one
product, and worse, it advertises that varying the caller is supported when varying the caller
breaks comparability.

### 3. Prompt as Python constants, not YAML

`prompt.py` holds `TASK` and `PERSONALITY_EASY` as module-level strings plus a
`build_system_prompt(personality)` that concatenates them.

No YAML, no config loader, no parser dependency. The prompt is read by developers and by third
parties reproducing the experiment; a Python file with two triple-quoted strings is as readable on
GitHub as a YAML file and costs zero machinery. Only when a non-developer needs to edit it, or
when it must be hashed into result rows, does externalising it pay for itself — and result rows
do not exist yet.

### 4. Free-running LLM, non-determinism absorbed by volume

The caller's LLM writes its own words each turn. It is not a state machine and not pre-rendered
audio.

*Alternatives considered:*

| Option | Stimulus identity | Robustness |
|---|---|---|
| Pre-rendered audio clips | Identical bit-for-bit | Zero — one unexpected clarification and the call derails |
| Intent state machine | High | Good, but needs advance-conditions and a second source of bugs |
| **Free-running LLM** (chosen) | Varies per call | High — handles anything the DUT says |

Chosen deliberately: wording variance is noise, and noise is beaten with sample size, which this
benchmark needs anyway to make P99 meaningful. Structural variance (derailed calls, skipped
intents) is *not* noise and is what the script's hard rules below exist to prevent.

The trade is accepted with one guard: the per-turn transcript is logged, so a weird run can be
attributed to the caller rather than blamed on the platform.

### 5. Negotiation bounded by "accept the second counteroffer"

Negotiation is the only intent whose turn count the caller does not control — the shop can
counter three times. Left free, calls against one platform would run 7 turns and against another
11, and the samples would not be drawn from the same distribution.

So the TASK carries an unconditional rule: accept the second counteroffer, good deal or not. The
caller is not trying to win; it is trying to produce a comparable conversation.

Negotiation turns are kept — not trimmed — precisely because they carry the longest context and
the most reasoning, which is where the tail lives.

### 6. Caller never barges in, and never re-prompts on silence

**Corrected during implementation.** The original plan here was `allow_interruptions=False`. That
is wrong in two independent ways, and both were found only by reading the installed package and
the 1.0 migration guide.

*Wrong direction.* In Pipecat, "user" is the remote party — the agent under test — and "bot" is
our caller. `allow_interruptions`, and its 1.x replacement `user_mute_strategies`, govern whether
**the user may interrupt the bot**. Our requirement is the opposite: our caller must not talk over
the agent under test. Mute strategies do not address it at all.

What actually governs it is when the caller decides the other party's turn has ended:
`SileroVADAnalyzer`'s `stop_secs` and `LLMUserAggregatorParams.user_turn_stop_timeout`. Both are
conservative here, because **caller-side turn detection sits outside the metric** — the stopwatch
starts at the caller's own last audio frame with energy, so waiting longer before speaking costs
the measurement nothing.

Not literally nothing, though: wait too long and some platforms fill the silence with "are you
still there?", which pollutes the conversation. So the setting is deliberate and moderate, not
maximal. Note that **1.x lowered the `stop_secs` default from 0.8 to 0.2** — aggressive enough
that any mid-sentence pause by the agent under test would make our caller talk over it. It is set
explicitly, never left at the default.

*Wrong API.* `allow_interruptions` no longer exists, and `TransportParams` / `PipelineParams` are
Pydantic models that **silently drop unknown fields — no error, no warning**. The same applies to
`vad_analyzer` and `turn_analyzer`, which moved to `LLMUserAggregatorParams`. A pipeline written
from 0.0.x memory starts up clean and is simply not configured. Under rule 7 that is a bug, and
it is the reason every processor and parameter name in this change is verified against the
resolved version rather than recalled.

*The other direction, decided separately:* when the agent under test barges in on our caller, the
caller **yields and stops talking** — no mute strategies, Pipecat's natural behaviour. That turn
yields an overlapping and therefore unusable latency sample, which the analysis layer discards.
The alternative, `MuteDuringBotSpeechStrategy`, would guarantee all seven intents complete but
would make our caller talk over the other party — behaviour no human caller exhibits, which would
push the agent under test into a situation it never meets in production.

The re-prompt half of this decision matters more than it looks: **if the caller re-prompts a slow
agent after N
seconds, it truncates that agent's latency sample.** The platforms with the worst tails — the
exact thing P99 is for — would be the ones systematically censored. So the caller waits. If the
agent never answers, the call ends on an idle timeout and the turn is recorded as censored by the
analysis layer later; it is never quietly dropped and never replaced by a re-prompt.

The idle timeout is **20 seconds**. Generous by design: seconds of dead air are cheap, a biased
P99 is not. No usable voice agent answers at 20 s, so anything reaching the ceiling is a failed
turn rather than a slow one — which is exactly how the analysis layer should treat it.

### 7. `end_call` function tool

With a free-running LLM, the end of the conversation is the one thing that can be made
deterministic, so it is. The caller calls `end_call` after thanking the shop; the pipeline ends.
No hangup heuristics, no "goodbye" string matching, no reliance on the DUT hanging up first.

### 8. No transport in this change

`run_caller` takes the transport as an argument and this change ships none.

The original plan was a local microphone loop for fast prompt iteration, then a WebRTC browser
loop when pyaudio would not build. Both were dropped: the first real conversation will happen over
the telephone anyway, in the telephony change, and a browser at 16 kHz proves nothing about 8 kHz
mu-law over PSTN. Building a second validation harness that cannot answer the question is work
with a known-zero payoff, so this change stops at the agent and carries no transport dependency.

The consequence is stated plainly, because it is the honest status of this change: **the caller
has never held a conversation.** It imports, type-checks, and its prompt is tested; the pipeline
itself is unexercised until a transport arrives.

The caller does **not** speak first, whatever the transport. On a real outbound call the shop
answers the phone.

### 9. No filler audio on the agent under test

Not caller code, but decided here because it constrains the whole instrument: several platforms
can emit a pre-recorded phrase while the LLM is still generating. Under a metric defined as *first
agent frame with energy*, such a platform wins by playing a wav file. Fillers are disabled on
every platform; where a platform cannot disable them, its results carry an asterisk.

Recorded in this design so `providers/` inherits it as a requirement rather than rediscovering it.

### 10. Language is English

Canadian buyer, Texan shop. Fixed in the TASK, and it fixes the STT and TTS language settings too.

## Risks / Trade-offs

**Pipecat's API moves fast between minor versions** → pin the version in `pyproject.toml` and
verify processor/params names against the resolved version rather than against memory. A caller
that stops importing after `uv sync` is a reproducibility bug for anyone cloning the repo.

**pyaudio needs `libportaudio2` on Linux** → if the native dependency fights back, switch to
Pipecat's WebRTC transport and talk to the caller from a browser. Same pipeline, one argument
different. Not a redesign.

**The LLM drifts off script** — asks two things in one turn, skips shipping, haggles forever →
hard rules in TASK (one intent per turn, do not advance without an answer, accept the second
counteroffer), plus transcript logging so drift is visible, plus a test asserting the seven steps
survive in order in the composed prompt.

**Personality silently changes the measurement** — a chattier caller with trailing tags is harder
to endpoint, so it measures worse latency on every platform equally → this is real and is why
personality must appear as a column in published results, not as an implicit default. Comparing
across personalities is a feature; comparing *between* them by accident is a bug.

**Wording variance is instrument noise** → beaten by sample size, and by interleaving platforms
within a measurement session rather than running all of one platform then all of another, so
drift in network conditions or provider load does not align with the platform variable. Belongs
to the run-orchestration change; noted here so it is not forgotten.

**A microphone loop proves nothing about telephony** → true. 8 kHz μ-law over PSTN behaves
differently from a laptop mic at 16 kHz, and endpointing on a real line is a different problem.
The local transport validates *script behaviour only*. Nothing about latency, audio quality, or
turn-taking over the phone can be concluded from it, and this change claims nothing about them.

## Migration Plan

Nothing to migrate — additive, no published state. The rollout is: add the dependency, run
`npx autoskills -a claude-code`, write the two modules and the test, iterate the prompt at the
microphone until the script holds, commit on `dev`. Rollback is deleting the module.

The one non-additive edit is `CLAUDE.md`: caller description from "6 turns" to "7 intents,
variable turns", plus the no-filler constraint. Cheap now, expensive after 300 recorded calls.

## Open Questions

- ~~**Which Cartesia voice id?**~~ **Resolved**: `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`. Pinned
  as an explicit constant, never a name and never a provider default. Frozen from here — it is
  part of the stimulus, and changing it invalidates comparability with runs already recorded.
- ~~**Which product?**~~ **Resolved**: a Weber Spirit II E-310 gas grill. A real, widely known
  model, plausible stock for an Austin shop, and specific enough that the agent under test cannot
  wander about what is being bought.
- **Does the caller need a target price?** Currently no — it asks, negotiates once, accepts the
  second counteroffer. Adding a target would mean the caller carries facts about the product,
  which is the callee's job.
