# test-call-endpoint Specification

## Purpose
TBD - created by archiving change add-twilio-test-call. Update Purpose after archive.
## Requirements
### Requirement: Authenticated call placement

The system SHALL expose `POST /test_call`, which places one outbound phone call.

The request SHALL carry a secret in the `X-API-Key` header. The secret SHALL be compared in
constant time, SHALL be read from the environment, and SHALL NOT be accepted from the query string
— query strings reach access logs and proxy logs.

A request without a valid secret SHALL be rejected and SHALL NOT place a call.

#### Scenario: Valid key

- **WHEN** a request arrives with the correct `X-API-Key`
- **THEN** a call is placed to the configured destination

#### Scenario: Missing or wrong key

- **WHEN** a request arrives with no key, or with an incorrect one
- **THEN** the request is rejected with `401`
- **AND** no call is placed

#### Scenario: Key in the query string

- **WHEN** a request supplies the secret as a query parameter instead of a header
- **THEN** it is treated as unauthenticated

### Requirement: The destination is not a request parameter

The destination number SHALL come from configuration, never from the request. The endpoint SHALL
NOT accept a destination, an override, or any parameter that changes which number is dialled.

An authenticated endpoint that dials arbitrary numbers becomes a toll-fraud machine the moment its
key leaks, and this endpoint is reachable from the internet whenever the tunnel is up.

The destination number and the API key SHALL live in the environment and SHALL NOT appear in
source, in tests, or in committed examples. The repository is public and the number is a personal
mobile.

#### Scenario: Request tries to choose the destination

- **WHEN** an authenticated request includes a destination number in its body
- **THEN** the value is ignored and the configured destination is dialled

#### Scenario: Destination not configured

- **WHEN** the destination is missing from the environment
- **THEN** the endpoint fails with a message naming the missing variable
- **AND** no call is placed

### Requirement: The request does not wait for the call

The endpoint SHALL respond as soon as the call has been placed, returning an identifier for it,
and SHALL run the conversation independently of the request.

A phone call lasts minutes. Holding the request open makes any client time out and retry, and a
retry would place a second call.

#### Scenario: Call placed

- **WHEN** an authenticated request is accepted
- **THEN** the response is returned immediately with `202` and a call identifier
- **AND** the conversation proceeds after the response has been sent

### Requirement: One call at a time

The system SHALL allow at most one call in flight. A request arriving while a call is running
SHALL be refused rather than queued or run concurrently.

#### Scenario: Second request during a call

- **WHEN** an authenticated request arrives while a call is in progress
- **THEN** it is refused with `409`
- **AND** no second call is placed

#### Scenario: Request after the previous call ended

- **WHEN** an authenticated request arrives after the previous call has finished
- **THEN** a new call is placed

### Requirement: The media socket is authorized by a call-scoped token

The media websocket SHALL be protected by a token that the system itself generates when the call
is placed and embeds in the stream URL handed to the telephony provider. The provider only carries
the token; it neither generates nor interprets it.

The token SHALL be scoped to **one call, not one connection**: valid while that call is alive,
invalidated as soon as the call ends even if its lifetime has not expired, and subject to a ceiling
of five minutes. A reconnect within the same live call SHALL be accepted.

The ceiling SHALL cover ringing time, not merely request time — the socket opens only once the
callee answers.

A connection presenting an unknown, expired, or already-finished call's token SHALL be closed
without starting a pipeline. This matters because every accepted connection spends money on
speech, language and voice services.

#### Scenario: Provider connects with a valid token

- **WHEN** the media socket is opened with the token minted for the live call
- **THEN** the connection is accepted and the caller agent runs on it

#### Scenario: Reconnect during the same call

- **WHEN** the media socket reconnects with the same token while the call is still alive
- **THEN** the connection is accepted

#### Scenario: Token after the call ended

- **WHEN** a connection presents a token whose call has finished
- **THEN** the connection is closed without starting a pipeline

#### Scenario: Unknown token

- **WHEN** a connection presents a token that was never issued, or one past its ceiling
- **THEN** the connection is closed without starting a pipeline

### Requirement: Bidirectional media bridge

The call SHALL bridge its audio to the caller agent in both directions. A listen-only media fork
SHALL NOT be used — it yields an agent that hears and cannot answer, with no error raised
anywhere.

The telephony instructions SHALL be supplied inline when the call is created rather than fetched
from a callback route. The destination is known before dialling, so a callback buys nothing and
would expose a second public route.

#### Scenario: Callee answers

- **WHEN** the callee answers the phone
- **THEN** the callee's audio reaches the caller agent
- **AND** the caller agent's audio reaches the callee

#### Scenario: No callback route

- **WHEN** the running application's routes are inspected
- **THEN** there is no publicly reachable route serving telephony instructions

### Requirement: The line drops when the conversation ends

The telephone leg SHALL be released as soon as the conversation ends, with no trailing dead air.

The leg SHALL NOT be left up if the pipeline terminates unexpectedly. An abandoned leg keeps
billing and, on a measurement run, silently corrupts the recording that follows it.

#### Scenario: Caller ends the call

- **WHEN** the caller agent invokes `end_call`
- **THEN** the telephone leg is released immediately

#### Scenario: Pipeline dies unexpectedly

- **WHEN** the pipeline terminates without the caller having ended the call
- **THEN** the telephone leg is still released

### Requirement: The telephony layer is not platform-aware

The telephony code SHALL contain no knowledge of the platforms under test. It reaches them; it
does not know them. Anything platform-specific belongs in the provider layer.

The caller agent SHALL remain unchanged by this capability except for audio sample rate, which is a
property of the instrument rather than of the transport.

#### Scenario: Telephony module inspected

- **WHEN** the telephony code is inspected
- **THEN** it contains no branch, constant, or configuration naming a platform under test
