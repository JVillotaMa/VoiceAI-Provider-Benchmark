## Context

`src/voicebench/caller/` holds a complete agent that has never run. `run_caller(transport,
personality)` takes its transport as an argument and this repository supplies none — a deliberate
gap left by `add-caller-agent`, on the grounds that the first real conversation would happen over
the telephone anyway and a browser loop would prove nothing about it.

This change fills that gap with the smallest possible thing: one endpoint, one destination, one
call at a time. It is a test harness, not the run orchestrator — but it is the seed of one, so it
is shaped to grow into it rather than to be thrown away.

Two constraints frame everything below:

1. **Twilio is not a platform under test.** It is our instrument. Nothing here belongs in
   `providers/`, and nothing here may become platform-aware.
2. **This endpoint spends money and will be reachable from the internet.** A tunnel is required
   for Twilio to open the media socket, which means every route is exposed the moment the tunnel
   is up. The threat model is not hypothetical: an authenticated dialler is a toll-fraud machine,
   and an open media socket burns OpenAI, Deepgram and Cartesia credit per connection.

## Goals / Non-Goals

**Goals:**
- Place a real outbound call to a fixed number on an authenticated POST, and hold the scripted
  conversation over it.
- Close the seven behavioural checks deferred from `add-caller-agent`, over real telephony.
- Establish the transport of the instrument deliberately rather than by accident.
- Leave the caller agent untouched except for one constant that belongs to it anyway.

**Non-Goals:**
- Any latency number. This change produces a phone that rings.
- Two-channel recording.
- Dialling the platforms under test; run orchestration; offline analysis.
- Pinning the outbound-number country and the Twilio edge — named as open, not decided.
- Production hardening beyond the two authentication surfaces and the concurrency limit.

## Decisions

### 1. Twilio Media Streams, not Daily

Three architectures were on the table. The linked Pipecat example is the middle one.

| | Twilio Media Streams | Daily + Twilio SIP | Daily PSTN |
|---|---|---|---|
| Hops, phone network → our recording point | **2** | 4 | 2 |
| Public tunnel | required | no | no |
| Accounts | Twilio | Twilio **and** Daily | Daily |
| Manual setup | number, geo permissions | number, SIP domain, two IP ACLs, TwiML Bin | Daily number |
| Audio we receive | raw mu-law 8 kHz from Twilio | after Daily's SFU | after Daily's SFU |

Chosen for the hop count. Measured latency is the platform's latency plus whatever the instrument
adds; a constant offset is harmless because it lands on all five platforms equally, but *variance*
is not — it inflates the tail on every platform at once and makes P95/P99 less able to separate
them. An SFU between the phone network and the recording point is a jitter source that buys us
nothing.

The "no tunnel required" advantage of the SIP route is smaller than it looks: it is paid for with
a SIP domain, two IP access control lists and a TwiML Bin. `ngrok http` is less work, and it is
already installed.

### 2. Inline TwiML, not a `/twiml` callback

`calls.create(twiml="<Response>…")` rather than `calls.create(url="https://…/twiml")`.

TwiML tells Twilio what to do once the call is answered; without it, the call connects to nothing.
Ours says one thing: bridge this call's audio, both directions, to our websocket.

The Pipecat example uses the callback form because it parses `To`/`From` out of the form post
Twilio sends. Our destination is fixed and known before dialling, so the round-trip buys nothing
and costs a second public route to expose and defend. TwiML has a 4000-character limit; ours is
about 150.

*One thing to get right:* `<Connect><Stream>` is bidirectional. `<Start><Stream>` is a
listen-only fork. Confusing them yields an agent that hears and cannot answer, with no error
anywhere.

### 3. `<Hangup/>` after the stream, not `<Pause length="20"/>`

When the pipeline ends — the caller invoked `end_call` — the websocket closes and Twilio moves to
the next TwiML verb. The example pauses for twenty seconds, which on a measurement call means
twenty seconds of dead line and twenty seconds of billing on the end of every single call.
`<Hangup/>` drops it immediately.

The serializer may also offer an automatic hang-up; whichever mechanism is used, it is verified
against the resolved Pipecat version rather than recalled, and the call must not be left up if the
pipeline dies unexpectedly.

### 4. Two authentication surfaces, because there are two clients

```
  POST /test_call    ← called by us (Postman, cron)     X-API-Key header, constant-time compare
  WS   /ws/{token}   ← opened by TWILIO, never by us    single-use token, short TTL
```

The API key cannot protect the media socket: Twilio opens it and has no way to carry our header.
Twilio does not sign websocket connections either — `X-Twilio-Signature` covers HTTP webhooks, not
streams. So the socket is guarded by a token we mint ourselves, embedded in the stream URL we hand
Twilio. This is the mechanism Pipecat's own development runner uses.

**We generate the token; Twilio only carries it.** It is minted when an authenticated
`POST /test_call` arrives, written into the TwiML, and handed to Twilio over TLS. Twilio opens
exactly the URL string it was given, token included, and has no idea there is a secret in it. The
only way to know a valid token is to have been given one, and the only party ever given one is
Twilio.

What this does *not* do, stated so it is not mistaken for more: it does not prove the connecting
party is Twilio, and it is not a signature. Anyone holding the token could connect. What makes
that acceptable is the token's lifetime and the entropy behind it.

**Scope: one call, not one connection.** The token is bound to the call it was minted for, valid
while that call is alive with a five-minute ceiling, and invalidated the moment the call ends —
even if minutes of TTL remain. Since only one call may be in flight at a time, there is no
ambiguity about which call a connecting socket belongs to.

Deliberately not single-*use*: a strictly single-use token dies on the first TCP connection, so a
Twilio reconnect inside a live call would fail for no good reason. Binding to the call instead of
the connection lets a reconnect work while keeping the window tied to something meaningful.

The five minutes are sized for ringing, not for the request: between the POST and Twilio opening
the socket sits however long it takes to answer the phone. A ten-second TTL would fail calls purely
because someone was slow to pick up.

And the ceiling is not what defends against an attacker — entropy is. `token_urlsafe(32)` is 256
bits; guessing it is equally impossible at five minutes and at five hours. The TTL bounds the
exposure of a *leaked* token — from Twilio's console debugger, a proxy log, a traceback — which is
a real risk with a short window rather than an imaginary one with a long one.

An alternative was available: Twilio can carry custom `<Parameter>` tags inside `<Stream>`, which
arrive in the first websocket message. Rejected because it forces us to accept the socket before
we can judge it, while the token ends up written into the TwiML either way, so it is no less
exposed. The URL form lets us reject before accepting.

The key goes in a header rather than the body or the query string — query strings end up in access
logs and proxy logs. It is compared with a constant-time comparison, and it is generated rather
than chosen.

### 5. The destination is not a request parameter

It comes from the environment.

A key-authenticated endpoint that dials whatever number the body contains is a toll-fraud machine
the moment the key leaks, and this one is reachable from the internet whenever the tunnel is up.
Premium-rate numbers exist precisely to convert someone else's dialler into revenue.

The number is also a personal mobile and this repository is public, so it lives in `.env` with the
key documented in `.env.example` — never in source, never in a committed example body.

### 6. Return 202 immediately; one call at a time

A phone call lasts a minute or two. Holding the HTTP request open for it makes Postman look hung
and makes any cron client time out and retry — which would place a second call. So the endpoint
returns `202` with a call id and runs the conversation in a background task.

That makes a concurrency limit mandatory rather than nice: a second request while a call is in
flight gets `409`. A cron firing every minute over a two-minute call must not stack.

### 7. 8000 Hz belongs to the agent, not to the transport

The first instinct was to pass sample rates in with the transport, since telephony is what imposes
them. That would have been a leak: the pipeline's audio rate is not the transport's business, and
`caller/agent.py` is the module declared frozen.

The correct framing is the one the instrument already implies — **the instrument is always a phone
call**. 8000 Hz is therefore a property of the caller, and it sits in `agent.py` next to the LLM
snapshot and the voice id, as another constant that invalidates comparability if it changes.

```
  agent.py — frozen
  ├─ CALLER_LLM_MODEL   = "gpt-4.1-mini-2025-04-14"
  ├─ CALLER_VOICE_ID    = "9626c31c-…"
  ├─ AUDIO_SAMPLE_RATE  = 8000
  ├─ VAD_STOP_SECS      = 0.8
  └─ IDLE_TIMEOUT_SECS  = 20
```

Two consequences to handle rather than discover. Cartesia is told to render at 8 kHz rather than
letting the serializer resample down from 24 kHz — one resample fewer, and the stimulus is then
defined end to end. And Silero VAD is less accurate at 8 kHz than at 16 kHz, which is one more
reason `stop_secs` stays explicitly set instead of at the framework's aggressive 0.2 default.

The stimulus definition changes accordingly: not "that Cartesia voice" but **that voice through
mu-law 8 kHz**. That is what all five platforms will hear, which is what matters.

### 8. `telephony/`, not `providers/`

`providers/` is for the platforms under test. Twilio is how we reach them. Keeping it separate is
what stops the instrument from acquiring per-platform behaviour, which is the one thing that would
destroy the comparison.

## Risks / Trade-offs

**The ngrok URL changes on every restart** → the public base URL is read from the environment at
call time, not baked in. Forgetting to update it produces a call that connects and then sits in
silence, which looks like an agent bug and is not.

**Twilio trial plays a notice into the call** → fine for proving the path, unusable for
measurement: that audio lands in the conversation and the caller's STT will hear it. Leaving trial
is a prerequisite for any real run, not for this change.

**Geographic permissions for Spain are off by default** → `calls.create` fails with error 21215,
which does not say "enable Spain". Named here so it is recognised in ten seconds rather than
debugged for an hour.

**The process dies mid-call** → Twilio keeps the leg up and keeps billing. The hangup path cannot
depend solely on our pipeline ending cleanly.

**The caller does not speak first** → correct behaviour, and it will look broken. Answer the phone
and greet it as the shop, or it sits silent until the 20-second idle timeout ends the call.

**The endpoint grows into the run orchestrator by accident** → likely, and fine, provided the
growth is deliberate. The concurrency limit, the background execution and the fixed destination
are all shaped so that adding "which platform to dial" later is an addition rather than a rewrite.

## Migration Plan

Additive. Nothing published, nothing to migrate. The one edit to existing code is the 8 kHz
constant in `caller/agent.py`, and the one edit to an existing artifact is the matching
requirement in the still-open `add-caller-agent` spec.

Rollback is deleting the new modules and the constant.

## Open Questions

- **Country of the outbound number.** Today a US Twilio number. A European one is arguably more
  defensible for a project whose stated differentiator is measurement from Europe. Deliberately
  not decided here — this change publishes no numbers.
- **Twilio edge for the media stream** (`ashburn`, `dublin`, `frankfurt`, …). Together with the
  number's country, this defines what "measured from Europe" concretely means, and changing either
  later invalidates comparability exactly as changing the voice would. Must be pinned before the
  first published run; need not be pinned to make a phone ring.
- **Whether two-channel recording joins this change.** Deferred by decision. Noted because this is
  where it is cheapest — the same pipeline, one processor — and doing it later means re-testing
  telephony from scratch.
