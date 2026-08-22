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

- **Caller agent**: a Pipecat agent with an LLM but a *closed script* — 6 turns, fixed intents in
  fixed order. Natural conversation, equivalent stimulus on every platform.
- **Agent under test**: created by us on each platform with the **same prompt, same voice, same
  LLM**. The platform is the only variable.
- **Transport**: real phone call. Not WebRTC-only shortcuts.
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
  caller/      Pipecat calling agent (closed 6-turn script)
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
