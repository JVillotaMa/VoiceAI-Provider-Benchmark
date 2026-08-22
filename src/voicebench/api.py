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

from voicebench.caller.agent import run_caller
from voicebench.telephony.twilio import build_transport, place_call, require_env

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

    def accepts(self, token: str) -> bool:
        """Whether a websocket presenting this token may join.

        Scoped to the call, not to a single connection: a Twilio reconnect inside a live call is
        legitimate and a single-use token would kill it for no good reason.
        """
        return (
            not self.finished
            and secrets.compare_digest(token, self.token)
            and (time.monotonic() - self.started_at) < TOKEN_CEILING_SECS
        )


app = FastAPI(title="voicebench test call")

_current: Call | None = None
_lock = asyncio.Lock()


def _require_api_key(x_api_key: str | None) -> None:
    """Constant-time check against the configured key.

    Header only. Query strings reach access logs and proxy logs, so a key supplied that way is
    simply not looked at and the request is unauthenticated.
    """
    expected = os.environ.get("TEST_CALL_API_KEY")
    if not expected:
        raise HTTPException(500, "TEST_CALL_API_KEY is not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "invalid or missing API key")


@app.post("/test_call", status_code=202)
async def test_call(x_api_key: str | None = Header(default=None)) -> dict[str, str]:
    """Place the call and return immediately.

    Takes no parameters at all — in particular, no destination. The body is ignored.

    Returns 202 rather than waiting: a phone call lasts minutes, and a client that times out and
    retries would place a second call.
    """
    _require_api_key(x_api_key)

    try:
        env = require_env()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    global _current
    async with _lock:
        if _current is not None and not _current.finished:
            raise HTTPException(409, "a call is already in progress")

        token = secrets.token_urlsafe(32)
        call = Call(token=token, started_at=time.monotonic())
        _current = call

        stream_url = (
            f"{env['PUBLIC_BASE_URL'].rstrip('/').replace('https://', 'wss://')}/ws/{token}"
        )
        try:
            call.sid = place_call(env, stream_url)
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
        env = require_env()
        transport = build_transport(
            websocket,
            env,
            stream_id=call_data["stream_id"],
            call_id=call_data["call_id"],
        )
        await run_caller(transport)
    finally:
        # Frees the token and releases the concurrency slot, whether the conversation ended
        # cleanly or blew up.
        call.finished = True
        logger.info(f"call finished: {call.sid}")


def main() -> None:
    """Run the app. Twilio must be able to reach it, so put a tunnel in front."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
