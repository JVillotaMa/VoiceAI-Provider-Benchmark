"""Placing an outbound call over Twilio and bridging its audio to the caller agent."""

import os

from fastapi import WebSocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from voicebench.caller.agent import AUDIO_SAMPLE_RATE

REQUEST_TIMEOUT_SECS = 15.0

REQUIRED_ENV_VARS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TEST_CALL_TO_NUMBER",
    "PUBLIC_BASE_URL",
)


def require_env() -> dict[str, str]:
    """Read telephony configuration, naming what is missing instead of failing mid-call."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            f"Copy .env.example to .env and fill them in."
        )
    return {name: os.environ[name] for name in REQUIRED_ENV_VARS}


def build_twiml(stream_url: str) -> str:
    """Instructions Twilio runs once the callee answers.

    `<Connect>` is bidirectional. `<Start>` is a listen-only fork and would give an agent that
    hears and cannot answer, with no error raised anywhere — so it is never used here.

    `<Hangup/>` follows the stream so the line drops the moment the pipeline ends. The Pipecat
    example pauses for twenty seconds instead, which on a measurement call is twenty seconds of
    dead air and billing on the end of every single call.
    """
    return f'<Response><Connect><Stream url="{stream_url}"/></Connect><Hangup/></Response>'


def place_call(env: dict[str, str], stream_url: str) -> str:
    """Dial the configured destination and return the Twilio call SID.

    The destination comes from configuration, never from a request: an authenticated endpoint
    that dials arbitrary numbers is a toll-fraud machine the moment its key leaks, and this one
    is reachable from the internet whenever the tunnel is up.

    TwiML is passed inline rather than fetched from a callback route — the destination is known
    before dialling, so a callback buys nothing and would expose a second public route.
    """
    # twilio-python has no default request timeout, so a hung request would otherwise hold the
    # worker thread until something else gave up first.
    client = Client(
        env["TWILIO_ACCOUNT_SID"],
        env["TWILIO_AUTH_TOKEN"],
        http_client=TwilioHttpClient(timeout=REQUEST_TIMEOUT_SECS),
    )
    call = client.calls.create(
        to=env["TEST_CALL_TO_NUMBER"],
        from_=env["TWILIO_FROM_NUMBER"],
        twiml=build_twiml(stream_url),
    )
    return str(call.sid)


def build_transport(
    websocket: WebSocket,
    env: dict[str, str],
    stream_id: str,
    call_id: str,
) -> FastAPIWebsocketTransport:
    """Bridge a live Twilio Media Stream to the caller agent.

    Credentials are handed to the serializer for `auto_hang_up`, which is on by default and fires
    on both EndFrame and CancelFrame — so the telephone leg is released whether the caller ended
    the call deliberately or the pipeline died. An abandoned leg keeps billing and would corrupt
    the recording of whatever call runs next.
    """
    serializer = TwilioFrameSerializer(
        stream_sid=stream_id,
        call_sid=call_id,
        account_sid=env["TWILIO_ACCOUNT_SID"],
        auth_token=env["TWILIO_AUTH_TOKEN"],
    )
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=AUDIO_SAMPLE_RATE,
            audio_out_sample_rate=AUDIO_SAMPLE_RATE,
            serializer=serializer,
        ),
    )
