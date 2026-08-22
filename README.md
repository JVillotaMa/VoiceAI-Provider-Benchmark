# VoiceAI Provider Benchmark

An independent, open source, **reproducible** latency benchmark for voice AI agent platforms —
measured over real phone calls, from Europe.

Platforms under test: **Vapi · Retell · ElevenLabs · Pipecat · LiveKit**

## What makes it different

Existing benchmarks run on proprietary platforms and can't be re-executed by anyone else. This
one ships the whole harness: clone it, add your own API keys, run it, get your own numbers.

- **Same stimulus everywhere.** A Pipecat caller agent with an LLM but a closed script (6 turns,
  fixed intents, fixed order) calls an agent we create on each platform with the *same prompt,
  same voice, same LLM*. The platform is the only variable.
- **Same instrument everywhere.** Bidirectional recording in two separate channels, captured from
  the caller's end. No platform-internal telemetry.
- **Timestamps from the audio, offline.** Windowed RMS / Silero VAD over the recordings, not
  pipeline events.
- **Measured from Europe**, where most published numbers are US-East.

## The metric

`response latency` = time between the last caller audio frame with energy and the first agent
audio frame with energy.

Reported as **P50 / P95 / P99** — never as a mean. In a voice conversation it's the tail that
breaks the interaction.

## Quickstart

```bash
uv sync
uv run pre-commit install --install-hooks -t pre-commit -t commit-msg
cp .env.example .env   # fill in your keys
```

## Status

Early. Harness under construction; no results published yet.

## License

MIT
