# VoiceAI Provider Benchmark

Open source, independent, reproducible latency benchmark for voice AI agent platforms.

## Why this exists

Commercial benchmarks (Cekura, Coval) run on proprietary platforms, are not reproducible by
third parties, and measure from US-East. The gap this repo fills: **independence,
reproducibility, and measurement from Europe**. Anyone must be able to clone this repo, plug in
their own API keys, and re-run the exact same experiment.

Platforms under test: **Vapi, Retell, ElevenLabs, Pipecat, LiveKit**.

## Measurement design (do not silently change this)

The whole value of the project is that the instrument is identical across platforms. Any change
to the points below invalidates comparability with previously published runs.

- **Caller agent**: a Pipecat agent with a free-running LLM on a *closed script* — **7 intents in
  fixed order**, one intent per turn. Turn count varies (negotiation can take more than one
  exchange); wording varies too. That non-determinism is absorbed by running many calls per
  platform, not by constraining the caller. Bounded by one rule in the script: **accept the second
  counteroffer**, so negotiation length does not differ per platform.
- **The caller is frozen.** Its LLM snapshot (`gpt-4.1-mini-2025-04-14`, dated on purpose) and its
  Cartesia voice id are constants in `caller/agent.py`, never parameters. The voice especially:
  how an utterance ends prosodically is what triggers the agent under test's endpointing, so it
  *is* the stimulus. Personality is the only parameter, and it belongs in the result rows next to
  the platform — a chattier caller measures differently on every platform at once.
- **Agent under test**: created by us on each platform with the **same prompt, same voice, same
  LLM**. The platform is the only variable.
- **No filler audio on the agent under test.** Several platforms can play a pre-recorded phrase
  while the LLM is still generating. Under a metric defined as *first agent frame with energy*,
  such a platform wins by playing a wav file. Disabled everywhere; a platform that cannot disable
  it gets an asterisk in the report.
- **The caller never re-prompts a slow agent.** A re-prompt truncates that agent's latency sample
  and would systematically censor exactly the platforms P99 exists to expose. It waits up to 20 s;
  reaching that ceiling is a *failed* turn, recorded as censored — never dropped.
- **Transport**: real phone call over **Twilio Media Streams**, dialled out from our own machine.
  Chosen over Daily PSTN and Daily+Twilio SIP for hop count: every hop between the phone network
  and the point where we record adds jitter that is not the platform's. A constant offset is
  harmless — it lands on all five equally — but variance inflates the tail on every platform at
  once and makes P95/P99 worse at telling them apart.
- **Audio is 8 kHz everywhere**, frozen in `caller/agent.py` beside the LLM snapshot and the voice
  id. The instrument is always a phone call, so the rate belongs to the caller, not to whichever
  transport is plugged in. The stimulus is therefore not "that voice" but *that voice through
  mu-law 8 kHz* — which is what every platform actually hears.
- **Not yet pinned, and must be before any published run**: the country of the outbound number
  (today a US Twilio number) and the Twilio edge serving the media stream. Together they are what
  "measured from Europe" concretely means. Changing either later invalidates comparability exactly
  as changing the voice would. A European outbound number is arguably more defensible for the
  project's thesis.
- **Recording**: bidirectional, **two separate channels** (caller audio / agent audio), captured
  **from our end** so the instrument is identical everywhere.
- **Timestamps**: extracted **offline from the audio files** via energy detection (windowed RMS /
  Silero VAD). **Never** from platform-internal pipeline events — those are not comparable and
  are not independently verifiable.
- **Primary metric**: `response latency` = time from the last caller audio frame with energy to
  the first agent audio frame with energy.
- **Reporting**: **P50, P95, P99. Never means.** In voice, the tail is what breaks the
  conversation. If you find yourself writing `mean()` or `avg`, stop and reconsider.

## Repo layout

```
src/voicebench/
  caller/      Pipecat calling agent (closed script, 7 intents in fixed order)
  telephony/   Twilio: placing the call, bridging its audio. Our instrument, not a platform
  api.py       Test endpoint: dials one fixed number to prove the agent works
  providers/   Per-platform agent setup + call placement (vapi, retell, elevenlabs, pipecat, livekit)
  analysis/    Offline audio analysis: VAD/RMS, latency extraction, percentiles
tests/         pytest
data/recordings/  Raw call audio — gitignored, regenerable
results/       Committed measurement outputs (CSV/JSON) — the published evidence
openspec/      Change proposals and specs (OpenSpec workflow)
docs/          Methodology writeups
```

## Tooling

`uv` manages everything. There is no `pip`, no `requirements.txt`, no manual venv.

| Task | Command |
|---|---|
| Install / sync | `uv sync` |
| Add a runtime dep | `uv add <pkg>` |
| Add a dev dep | `uv add --dev <pkg>` |
| Run anything | `uv run <cmd>` |
| Lint + autofix | `uv run ruff check --fix .` |
| Format | `uv run ruff format .` |
| Types | `uv run mypy` |
| Unused / missing deps | `uv run deptry src` |
| Tests | `uv run pytest` |
| Commit (guided) | `uv run cz commit` |
| Test call API | `uv run python -c "from voicebench.api import main; main()"` (port 8000) |
| Expose it to Twilio | `ngrok http 8000` → put the https URL in `PUBLIC_BASE_URL` |
| Place a call | `POST /test_call` with header `X-API-Key`. No body, no parameters. |

The test endpoint dials one number, fixed in `.env`. The destination is never a request parameter:
an authenticated endpoint that dials arbitrary numbers becomes a toll-fraud machine the moment its
key leaks, and this one faces the internet whenever the tunnel is up.

When you answer, **greet it first** — the caller never speaks first. Stay silent and it ends on the
20-second idle timeout, which is correct behaviour and looks exactly like a bug.

`pre-commit` runs ruff, mypy, deptry and the commit-message check on every commit.
Install the hooks once with `uv run pre-commit install --install-hooks -t pre-commit -t commit-msg`.

## Rules

1. **Branches: work on `dev`, `main` is the published state.** Feature branches off `dev`,
   `dev` reaches `main` through a PR. Never commit straight to `main`.
2. **Code review before any PR.** Never open a PR without running `/code-review` first — and
   **always ask me before running it**. Do not launch it on your own initiative.
3. **New library ⇒ run autoskills.** Whenever a new dependency is added (`uv add ...`), run
   `npx autoskills -a claude-code` so the skill set matches the stack. Skills flagged with a
   security warning get read before they are trusted.
4. **OpenSpec for anything non-trivial.** Behaviour changes, new providers, new metrics: start
   with `/opsx:propose`, then implement against the change. Bug fixes and chores can go direct.
5. **Conventional commits**, enforced by commitizen. Small, scoped commits.
6. **Never commit secrets or audio.** API keys live in `.env` (gitignored); `.env.example`
   documents every key. Recordings stay in `data/recordings/`, gitignored.
7. **Reproducibility beats convenience.** Anything that makes a run non-reproducible by a third
   party (hidden config, unpinned model versions, platform-internal telemetry) is a bug.
8. **Don't invent numbers.** Latency figures come from committed runs in `results/` or they don't
   get stated. Ever. This is a benchmark; a fabricated number destroys the project's only asset.

## Context notes

- OpenSpec 1.2 no longer generates `openspec/project.md` — **this file is the project context**.
  Keep it current when the design changes.
- Author is a voice AI engineer who built and sold a telephone-survey voice agent product.
  Assume domain fluency: no explanations of what STT/TTS/barge-in/endpointing are.
