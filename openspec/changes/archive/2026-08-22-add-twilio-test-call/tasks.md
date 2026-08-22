## 1. Dependencies

- [x] 1.1 Add the `websocket` extra to the existing pipecat requirement and add `twilio`; confirm whether `fastapi` and `uvicorn` arrive with the extra or need adding explicitly — check against what `uv` resolves, do not assume
- [x] 1.2 Keep the `<2` bound on pipecat and bound the new direct dependencies the same way
- [x] 1.3 Run `npx autoskills -a claude-code` (rule 3); read any skill flagged with a security warning before trusting it

## 2. The instrument becomes 8 kHz

- [x] 2.1 Add `AUDIO_SAMPLE_RATE = 8000` to `caller/agent.py` beside the other frozen constants, with the reason: the instrument is always a phone call
- [x] 2.2 Pass it through to the pipeline so every processor sees it, and tell Cartesia to render at 8 kHz rather than letting the serializer resample down from 24 kHz — one resample fewer, and the stimulus is then defined end to end
- [x] 2.3 Add the matching requirement to `openspec/changes/add-caller-agent/specs/caller-agent/spec.md`: audio is 8 kHz, it is frozen, and the stimulus is the voice *through mu-law 8 kHz*
- [x] 2.4 Confirm Silero VAD runs at 8 kHz and that `VAD_STOP_SECS` is still explicitly set — accuracy drops at 8 kHz, which makes the framework's 0.2 default worse, not better

## 3. Telephony

- [x] 3.1 Create `src/voicebench/telephony/` — Twilio call placement and transport construction. Not `providers/`: Twilio is the instrument, not a platform under test
- [x] 3.2 Build the websocket transport with the Twilio serializer at 8 kHz; verify the processor and parameter names against the resolved pipecat version rather than from memory (its params objects drop unknown fields silently)
- [x] 3.3 Generate the TwiML inline: `<Connect><Stream url="wss://…/ws/{token}"/></Connect><Hangup/>`. `<Connect>`, never `<Start>` — a listen-only fork gives an agent that hears and cannot answer, with no error anywhere
- [x] 3.4 Place the call with `calls.create(to=…, from_=…, twiml=…)`, destination read from the environment
- [x] 3.5 Release the telephone leg when the pipeline ends, and also when it dies unexpectedly — an abandoned leg keeps billing and corrupts the next recording
- [x] 3.6 Read the public base URL from the environment at call time, never baked in; the tunnel URL changes on every restart

## 4. The endpoint

- [x] 4.1 FastAPI app with `POST /test_call` and `WS /ws/{token}` — no third public route
- [x] 4.2 `X-API-Key` header, read from the environment, compared with `secrets.compare_digest`; `401` otherwise, and never accepted from the query string
- [x] 4.3 Return `202` with a call id immediately; run the conversation in a background task
- [x] 4.4 One call in flight at a time; `409` on a second request. A cron firing over a running call must not stack
- [x] 4.5 Mint the token with `secrets.token_urlsafe(32)`, scoped to the call: valid while the call lives, invalidated when it ends, five-minute ceiling sized for ringing time. Accept a reconnect inside the same live call; close unknown, expired and finished-call connections without starting a pipeline
- [x] 4.6 Fail with a message naming the missing environment variable rather than a stack trace
- [x] 4.7 Add the destination number and the endpoint API key to `.env` and document both in `.env.example`. Neither appears in source, tests or committed examples — the repository is public and the number is a personal mobile
- [x] 4.8 Generate the API key rather than choosing one

## 5. Checks

Everything here runs without placing a call, using a fake Twilio client.

- [x] 5.1 `401` with no key and with a wrong key, and no call placed in either case
- [x] 5.2 A key supplied as a query parameter is treated as unauthenticated
- [x] 5.3 A destination in the request body is ignored; the configured number is dialled
- [x] 5.4 `202` and a call id returned without waiting for the conversation
- [x] 5.5 `409` on a second request during a call; a new call accepted once it has ended
- [x] 5.6 Token: valid accepted, reconnect during the live call accepted, finished-call rejected, unknown rejected, past-ceiling rejected — and no pipeline started in the rejecting cases
- [x] 5.7 The generated TwiML contains `<Connect><Stream>` and `<Hangup/>`, and does not contain `<Start>`
- [x] 5.8 `uv run ruff check --fix . && uv run ruff format .`
- [x] 5.9 `uv run mypy`
- [x] 5.10 `uv run deptry src`
- [x] 5.11 `uv run pytest`

## 6. The first real call

Prerequisites outside the code, all yours: Twilio geographic permissions enabled for Spain (+34)
or `calls.create` fails with an opaque 21215; the destination verified while the account is in
trial; and a trial notice played into the call, which is fine for proving the path and disqualifies
trial for measurement.

- [x] 6.1 `ngrok http` the app and put the URL in the environment
- [x] 6.2 POST from Postman with the key — the phone rings
- [x] 6.3 Answer and greet it as the shop. **It does not speak first**; stay silent and it dies at the 20-second idle timeout, which is correct behaviour and looks like a bug
- [x] 6.4 Close the seven behavioural checks deferred from `add-caller-agent`, now over real telephony: silent until greeted, seven intents in order one per turn, re-addresses an evaded intent, accepts the second counteroffer, never re-prompts through a 25-second silence, thanks and calls `end_call`, line drops
- [x] 6.5 Mark those checks done in `add-caller-agent/tasks.md` — that change stays open precisely for this
- [x] 6.6 Confirm audio quality at 8 kHz is good enough for the caller's STT to follow the conversation; if it is not, that is a finding about the instrument, not a bug to paper over

## 7. Documentation and landing

- [x] 7.1 Record in `CLAUDE.md` that the transport of the instrument is Twilio Media Streams at 8 kHz, and that the caller's audio rate is frozen alongside its LLM snapshot and voice id
- [x] 7.2 Note in `CLAUDE.md` that the outbound number's country and the Twilio edge are unpinned, define what "measured from Europe" concretely means, and must be fixed before any published run
- [x] 7.3 Document the run command and the tunnel step
- [x] 7.4 Conventional commits on `dev`, scoped small
- [x] 7.5 Ask before running `/code-review` (rule 2); no PR to `main` without it
