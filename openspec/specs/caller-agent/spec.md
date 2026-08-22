# caller-agent Specification

## Purpose
TBD - created by archiving change add-caller-agent. Update Purpose after archive.
## Requirements
### Requirement: Composed system prompt

The caller's system prompt SHALL be composed of exactly two parts: a TASK constant describing the
purchase script, and a PERSONALITY string describing how the caller behaves. TASK is frozen — it
is the stimulus applied to every platform. PERSONALITY is the only parameter the caller accepts.

The composition function SHALL be pure, SHALL require no network or credentials, and SHALL be
callable in a test.

#### Scenario: Prompt contains both parts

- **WHEN** the system prompt is built with a given personality
- **THEN** the result contains the full TASK text
- **AND** the result contains the full personality text

#### Scenario: Personality is substitutable

- **WHEN** the system prompt is built twice with two different personality strings
- **THEN** both results contain identical TASK text
- **AND** the results differ only in the personality portion

#### Scenario: Default personality

- **WHEN** the caller is started without specifying a personality
- **THEN** the easy-going personality is used

### Requirement: Fixed purchase script

The TASK SHALL instruct the caller to pursue seven intents in this exact order:

1. Ask whether the shop stocks the product
2. Ask its price
3. Ask whether the shop ships to Canada
4. Ask the shipping price
5. Negotiate the price
6. Accept the price
7. Thank the employee and end the call

The caller SHALL pursue exactly one intent per turn and SHALL NOT combine two intents in a single
utterance. The caller SHALL NOT advance to the next intent until the current one has been
answered.

The product SHALL be named unambiguously — a concrete model name, not a product category.

#### Scenario: Intents appear in order in the prompt

- **WHEN** the composed system prompt is inspected
- **THEN** all seven intents are present
- **AND** they appear in the specified order

#### Scenario: One intent per turn

- **WHEN** the caller takes a turn
- **THEN** it asks about exactly one intent

#### Scenario: No advancing without an answer

- **WHEN** the shop replies without answering the current intent
- **THEN** the caller re-addresses the current intent rather than moving to the next one

### Requirement: Bounded negotiation

The caller SHALL accept the second counteroffer unconditionally, regardless of whether the offer
is favourable. The caller is not optimising for price; it is producing a conversation of
comparable shape on every platform.

#### Scenario: Second counteroffer accepted

- **WHEN** the shop makes a second counteroffer
- **THEN** the caller accepts it and moves to the closing intent

#### Scenario: Negotiation does not run long

- **WHEN** the shop keeps countering
- **THEN** the caller does not haggle beyond the second counteroffer

### Requirement: Deterministic call termination

The caller SHALL end the call itself by invoking an `end_call` function tool after thanking the
employee. Termination SHALL NOT depend on matching a goodbye phrase, on a heuristic, or on the
agent under test hanging up first.

#### Scenario: Caller hangs up after closing

- **WHEN** the caller has thanked the employee and said goodbye
- **THEN** it invokes `end_call`
- **AND** the pipeline terminates

#### Scenario: Termination is not delegated

- **WHEN** the agent under test says goodbye first
- **THEN** the caller still completes its own closing intent and invokes `end_call`

### Requirement: The caller never talks over the agent under test

The instrument SHALL NOT talk over the agent under test. This is governed by how patiently the
caller decides the other party's turn has ended: the VAD silence threshold and the turn-stop
timeout SHALL be set explicitly to conservative values, never left at framework defaults.

Caller-side turn detection lies outside the primary metric — the measurement starts at the
caller's own last audio frame with energy — so patience here costs the measurement nothing. It is
bounded only by the agent under test filling long silences with prompts of its own.

Conversely, when the agent under test talks over the caller, the caller SHALL yield and stop
speaking, as a human caller would. The resulting overlapping turn is an invalid latency sample
for the analysis layer to discard; it SHALL NOT be prevented by muting the other party.

#### Scenario: Agent under test pauses mid-sentence

- **WHEN** the agent under test pauses briefly in the middle of an utterance
- **THEN** the caller stays silent and does not treat the pause as the end of the turn

#### Scenario: Agent under test talks over the caller

- **WHEN** the agent under test starts speaking while the caller is speaking
- **THEN** the caller stops speaking and listens

#### Scenario: Thresholds are explicit

- **WHEN** the VAD and turn-stop configuration is inspected
- **THEN** the silence threshold and turn-stop timeout are set explicitly in code
- **AND** neither relies on the framework default

### Requirement: The caller never re-prompts on silence

The caller SHALL NOT re-ask, prompt, or emit filler audio while waiting for the agent under test
to respond. Waiting SHALL be bounded by an idle timeout of 20 seconds, after which the call ends.

This exists because a re-prompt truncates the latency sample of a slow agent, which would
systematically censor exactly the platforms the P99 metric is meant to expose. A turn that reaches
the timeout is a failed turn, to be recorded as censored by the analysis layer — never silently
discarded, never replaced by a retry.

#### Scenario: Agent under test is slow

- **WHEN** the agent under test has not responded for 10 seconds
- **THEN** the caller remains silent and continues waiting

#### Scenario: Agent under test never responds

- **WHEN** no audio arrives from the agent under test for 20 seconds
- **THEN** the call ends

### Requirement: The caller does not speak first

The caller SHALL wait for the other party to speak before taking its first turn, matching a real
outbound call where the shop answers the phone.

#### Scenario: Call connects

- **WHEN** the call connects and no audio has arrived from the other party
- **THEN** the caller remains silent

#### Scenario: Shop greets

- **WHEN** the other party greets the caller
- **THEN** the caller begins with the first intent

### Requirement: Pinned instrument

Every version-bearing component of the caller SHALL be pinned explicitly in code:

- The LLM SHALL be referenced by a dated snapshot identifier, never by a moving alias.
- The TTS voice SHALL be referenced by an explicit voice id, never by a name or by a provider
  default.
- The Pipecat version SHALL be constrained in `pyproject.toml`.

The TTS voice is part of the stimulus — how an utterance ends prosodically determines the agent
under test's endpointing — and SHALL NOT be exposed as a runtime parameter.

#### Scenario: LLM identifier is dated

- **WHEN** the LLM configuration is inspected
- **THEN** the model identifier includes a version date

#### Scenario: Voice is not a parameter

- **WHEN** the caller is started
- **THEN** no argument allows the TTS voice to be changed

### Requirement: Audio is 8 kHz

The caller's audio SHALL be 8000 Hz throughout the pipeline, frozen alongside the LLM snapshot and
the voice id. The instrument is always a phone call, so the rate is a property of the caller and
SHALL NOT be supplied by whichever transport is plugged in.

The text-to-speech service SHALL be told to render at 8 kHz directly rather than letting a
telephony serializer resample down from a higher rate.

This completes the definition of the stimulus: not "that voice", but **that voice through mu-law
8 kHz** — which is what every platform under test actually hears. Changing the rate invalidates
comparability exactly as changing the voice would.

#### Scenario: Pipeline rate

- **WHEN** the pipeline is started
- **THEN** both input and output audio rates are 8000 Hz

#### Scenario: Speech synthesis rate

- **WHEN** the text-to-speech service is configured
- **THEN** it is asked for 8000 Hz output

#### Scenario: Voice activity detection rate

- **WHEN** the voice activity detector is configured
- **THEN** it is given 8000 Hz explicitly rather than relying on a default

#### Scenario: Transport does not decide the rate

- **WHEN** a transport is supplied
- **THEN** it does not determine the pipeline's audio rate

### Requirement: Transport is injected

The caller pipeline SHALL receive its transport as an argument, so that switching between local
audio and telephony changes no prompt, no pipeline stage, and no configuration.

#### Scenario: Transport swapped

- **WHEN** a different transport is supplied
- **THEN** the prompt, the pipeline stages and the model configuration are unchanged

#### Scenario: No transport is hardcoded

- **WHEN** the caller module is inspected
- **THEN** it constructs no transport of its own
- **AND** it depends on no transport-specific package

### Requirement: Turn-by-turn transcript

The caller SHALL log what was said each turn, by both parties. A free-running LLM makes the
caller's own wording a variable, and an anomalous run must be attributable to the instrument
rather than blamed on the platform.

#### Scenario: Conversation is logged

- **WHEN** a turn completes
- **THEN** the caller's utterance and the other party's utterance are written to the log
