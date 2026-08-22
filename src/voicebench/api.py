"""Test endpoint: place one real phone call and hold the scripted conversation over it.

Proves the caller agent works end to end. Not a measurement — no timing is taken here, and none
could be trusted if it were: latency comes offline from recorded audio.

This endpoint spends money and is reachable from the internet whenever the tunnel is up, so the
two authentication surfaces and the concurrency limit are load-bearing, not decoration.
"""

import asyncio
import os
import secrets
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket
from loguru import logger
from pipecat.runner.utils import parse_telephony_websocket

from voicebench.caller.agent import require_env as require_caller_env
from voicebench.caller.agent import run_caller, setup_logging
from voicebench.telephony.twilio import build_transport, place_call
from voicebench.telephony.twilio import require_env as require_telephony_env

# Sized for ringing, not for the request: between placing the call and Twilio opening the socket
# sits however long the callee takes to answer. This is a ceiling, not the usual lifetime — the
# token dies with its call. And it is not what defends against an attacker; 32 random bytes are.
# It bounds the exposure of a *leaked* token, which is the realistic risk.
TOKEN_CEILING_SECS = 300.0

# At import, not in main(): the app is also started by `uvicorn voicebench.api:app`, which never
# calls main() — and then every credential would silently be missing.
load_dotenv()


@dataclass
class Call:
    """One in-flight call. At most one exists at a time."""

    token: str
    sid: str | None = None
    started_at: float = 0.0
    finished: bool = False

    def is_live(self) -> bool:
        """Whether this call still occupies the single slot.

        The ceiling is what stops an unanswered call from wedging the endpoint: without it a call
        nobody picks up never sets `finished`, and every later request gets 409 until the process
        is restarted.
        """
        return not self.finished and (time.monotonic() - self.started_at) < TOKEN_CEILING_SECS

    def accepts(self, token: str) -> bool:
        """Whether a websocket presenting this token may join."""
        return self.is_live() and _same_secret(token, self.token)


app = FastAPI(title="voicebench test call")

_current: Call | None = None
_lock = asyncio.Lock()


def _same_secret(given: str, expected: str) -> bool:
    """Constant-time comparison that survives non-ASCII input.

    `secrets.compare_digest` raises TypeError on str containing non-ASCII, which would turn a
    junk credential into a 500 and a junk URL token into an unhandled exception. Comparing the
    UTF-8 bytes keeps the timing property and makes every input answerable.
    """
    return secrets.compare_digest(given.encode(), expected.encode())


def _require_api_key(x_api_key: str | None) -> None:
    """Check the caller's key.

    Header only. Query strings reach access logs and proxy logs, so a key supplied that way is
    simply not looked at and the request is unauthenticated.
    """
    expected = os.environ.get("TEST_CALL_API_KEY")
    if not expected:
        raise HTTPException(500, "TEST_CALL_API_KEY is not configured")
    if not x_api_key or not _same_secret(x_api_key, expected):
        raise HTTPException(401, "invalid or missing API key")


def _stream_url(public_base_url: str, token: str) -> str:
    """Build the wss:// URL Twilio will open.

    Twilio Media Streams require TLS, so anything but an https base is rejected here rather than
    producing TwiML that Twilio silently refuses — which would return 202, ring the phone, bill
    the call, and deliver no audio.
    """
    base = public_base_url.rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError(
            f"PUBLIC_BASE_URL must start with https:// (Twilio Media Streams require TLS); "
            f"got {base!r}"
        )
    return f"wss://{base.removeprefix('https://')}/ws/{token}"


@app.post("/test_call", status_code=202)
async def test_call(x_api_key: str | None = Header(default=None)) -> dict[str, str]:
    """Place the call and return immediately.

    Takes no parameters at all — in particular, no destination. The body is ignored.

    Returns 202 rather than waiting: a phone call lasts minutes, and a client that times out and
    retries would place a second call.
    """
    _require_api_key(x_api_key)

    try:
        env = require_telephony_env()
        # Checked before dialling, not when the socket opens: a missing speech or language
        # credential would otherwise place a real, billed call, ring the phone, and only fail
        # once the callee had already answered.
        require_caller_env()
        token = secrets.token_urlsafe(32)
        stream_url = _stream_url(env["PUBLIC_BASE_URL"], token)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    global _current
    async with _lock:
        if _current is not None and _current.is_live():
            raise HTTPException(409, "a call is already in progress")

        call = Call(token=token, started_at=time.monotonic())
        _current = call

        try:
            # Off the event loop: the Twilio SDK is synchronous, and a slow request would
            # otherwise freeze every other route, the media socket included.
            call.sid = await asyncio.to_thread(place_call, env, stream_url)
        except Exception as exc:
            call.finished = True
            logger.error(f"could not place call: {exc}")
            raise HTTPException(502, f"could not place call: {exc}") from exc

    logger.info(f"call placed: {call.sid}")
    return {"call_sid": call.sid or "", "status": "ringing"}


@app.websocket("/ws/{token}")
async def media_stream(websocket: WebSocket, token: str) -> None:
    """The Twilio Media Stream. Twilio opens this, never us.

    Every accepted connection spends money on speech, language and voice services, so an
    unrecognised one is closed before any pipeline starts.
    """
    call = _current
    if call is None or not call.accepts(token):
        logger.warning("rejected media stream: token not valid for any live call")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        _, call_data = await parse_telephony_websocket(websocket)
        env = require_telephony_env()
        transport = build_transport(
            websocket,
            env,
            stream_id=call_data["stream_id"],
            call_id=call_data["call_id"],
        )
        await run_caller(transport)
    finally:
        # Frees the token and releases the slot, whether the conversation ended cleanly or blew
        # up. Correct on both counts for `<Connect><Stream>`: Twilio never reopens a media stream
        # it has lost — closing the socket ends the stream and resumes the remaining TwiML — and
        # a fresh socket could not resume this conversation anyway, since the pipeline's context
        # died with it.
        call.finished = True
        logger.info(f"call finished: {call.sid}")


def main() -> None:
    """Run the app. Twilio must be able to reach it, so put a tunnel in front."""
    import uvicorn

    setup_logging()
    # Localhost only. The tunnel is what exposes this to Twilio, and it connects from the same
    # machine — binding every interface would hand a dialler to the local network for free.
    uvicorn.run(app, host="127.0.0.1", port=8000)
