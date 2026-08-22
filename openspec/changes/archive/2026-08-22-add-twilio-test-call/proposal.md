## Why

The caller agent has never held a conversation. It imports, type-checks and its prompt is tested,
but no audio has ever passed through the pipeline. Until it places a real phone call and talks to
someone, every claim about it is unverified — including the seven behavioural checks left open in
`add-caller-agent`.

This change builds the smallest thing that proves it works: one endpoint that dials one number.

## What Changes

- New FastAPI app with two routes:
  - `POST /test_call` — places the call. Authenticated with an API key in the `X-API-Key`
    header, compared in constant time. Returns `202` with a call id immediately; the conversation
    runs in the background rather than holding the request open for the length of a phone call.
  - `WS /ws/{token}` — the Twilio Media Stream. Twilio opens it, not us, so the API key cannot
    protect it. Guarded instead by a single-use token minted when the call is placed, with a short
    TTL, consumed on connect.
- Outbound call placed through the Twilio REST API with **inline TwiML** (`twiml=`), not a
  `url=` callback. The destination is fixed and known before dialling, so the `/twiml` round-trip
  the Pipecat example needs buys nothing and would expose a second public route.
- The TwiML is `<Connect><Stream>` — bidirectional — followed by `<Hangup/>` so the line drops the
  moment the pipeline ends, instead of the example's `<Pause length="20"/>` leaving twenty seconds
  of dead air on the end of every call.
- **The destination number is not a request parameter.** It comes from the environment. A
  key-authenticated endpoint that dials arbitrary numbers is a toll-fraud machine the moment the
  key leaks, and this one will be reachable from the internet through a tunnel.
- One call at a time. A second request while a call is in flight gets `409`, so a cron firing over
  a running call cannot stack up calls.
- `+34633402260` and the endpoint's API key live in `.env`; `.env.example` documents both keys.
  The number is a personal mobile and this repository is public.
- **Audio is fixed at 8000 Hz in `caller/agent.py`**, alongside the LLM snapshot and the voice id.
  The instrument is always a phone call, so this is a property of the instrument rather than an
  override the transport supplies.

### Measurement design

This change **touches the measurement design** in three places.

1. **8000 Hz becomes part of the frozen instrument.** The stimulus is no longer "that Cartesia
   voice" but "that voice through mu-law 8 kHz" — which is what all five platforms will hear.
   Consequences to handle rather than discover: Cartesia is told to render at 8 kHz rather than
   letting the serializer resample, and Silero VAD is less accurate at 8 kHz than at 16 kHz, which
   is one more reason `stop_secs` stays explicitly set rather than at the framework default.

2. **Twilio Media Streams becomes the transport of record.** It was one of three candidates
   (against Daily PSTN, and Daily+Twilio SIP as in the linked example). Chosen for the shortest
   path between the phone network and the point where audio is recorded — every extra hop adds
   jitter that is not the platform's, and jitter inflates exactly the tail that P50/P95/P99 exist
   to read.

3. **The route is now a variable that must be pinned, and it is not pinned yet.** Two things
   define what "measured from Europe" concretely means, and changing either invalidates
   comparability the same way changing the voice would:
   - the country of the outbound number (today a US Twilio number)
   - the Twilio edge serving the media stream (`ashburn`, `dublin`, `frankfurt`, …)

   A European outbound number is arguably more defensible for the project's thesis. Deliberately
   left open here: this change proves the machinery works and does not publish a number.

**Comparability with previously published runs: not affected.** `results/` is empty.

## Capabilities

### New Capabilities
- `test-call-endpoint`: placing a real outbound phone call on demand — authentication on both the
  control route and the media socket, fixed destination, concurrency limit, call lifecycle and
  hangup.

### Modified Capabilities

None as a delta spec. `openspec/specs/` is empty — `caller-agent` still lives inside the
in-progress `add-caller-agent` change rather than in the synced specs. The 8 kHz requirement is
therefore added directly to that change's spec, which keeps every requirement about the caller in
one place. Once `add-caller-agent` is archived, later changes to the caller become ordinary
deltas.

## Impact

**New code**
- `src/voicebench/telephony/` — Twilio call placement and the transport construction (websocket
  transport plus the Twilio serializer). Not `providers/`: Twilio is our instrument, not a
  platform under test.
- The FastAPI app and its two routes.

**Modified code**
- `src/voicebench/caller/agent.py` — the 8 kHz constant. The one edit to the frozen module.

**Dependencies**
- `pipecat-ai[websocket]` extra (the Twilio Media Streams transport), `twilio`, `fastapi`,
  `uvicorn`
- Triggers rule 3: `npx autoskills -a claude-code`.

**Configuration**
- New keys: the destination number and the endpoint API key. Existing `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` are already populated.
- A public URL is required — Twilio must reach `/ws`. `ngrok` is installed.

**Operational prerequisites, outside the code**
- Twilio geographic permissions enabled for Spain (+34), or `calls.create` fails with 21215.
- The destination verified while the account is in trial, and a trial notice played into the call
  that makes trial unsuitable for measurement, only for proving the path.

**What this unblocks**
- The seven behavioural checks deferred from `add-caller-agent`, run over real telephony instead
  of a browser.

**Explicitly out of scope**
- Two-channel recording. Deferred by decision, though this is where it becomes cheap: the
  `AudioBufferProcessor` goes in the same pipeline, and adding it later means re-testing telephony.
- Dialling the platforms under test, run orchestration, offline analysis.
- Pinning the outbound-number country and Twilio edge.

**This change produces no latency numbers.** It produces a phone that rings.
