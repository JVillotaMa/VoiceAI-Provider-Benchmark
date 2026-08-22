"""The endpoint spends money and faces the internet. These run without placing a call."""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from voicebench import api
from voicebench.telephony.twilio import build_twiml

API_KEY = "test-key-not-a-real-one"
CONFIGURED_NUMBER = "+34600000000"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CALL_API_KEY", API_KEY)
    monkeypatch.setenv("TEST_CALL_TO_NUMBER", CONFIGURED_NUMBER)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC-fake")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")


@pytest.fixture
def placed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record calls that would have been placed, and place none."""
    calls: list[dict[str, Any]] = []

    def fake_place_call(env: dict[str, str], stream_url: str) -> str:
        calls.append({"to": env["TEST_CALL_TO_NUMBER"], "stream_url": stream_url})
        return f"CA-fake-{len(calls)}"

    monkeypatch.setattr(api, "place_call", fake_place_call)
    return calls


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    api._current = None
    yield
    api._current = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def test_no_key_is_rejected_and_places_no_call(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    assert client.post("/test_call").status_code == 401
    assert placed == []


def test_wrong_key_is_rejected_and_places_no_call(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    r = client.post("/test_call", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert placed == []


def test_key_in_query_string_is_not_authentication(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    # Query strings reach access logs and proxy logs.
    r = client.post(f"/test_call?x_api_key={API_KEY}&api_key={API_KEY}")
    assert r.status_code == 401
    assert placed == []


def test_body_cannot_choose_the_destination(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    # A key-authenticated endpoint that dials arbitrary numbers is a toll-fraud machine.
    r = client.post(
        "/test_call",
        headers={"X-API-Key": API_KEY},
        json={"to": "+900123456789", "to_number": "+900123456789"},
    )
    assert r.status_code == 202
    assert [c["to"] for c in placed] == [CONFIGURED_NUMBER]


def test_returns_202_with_a_call_id(client: TestClient, placed: list[dict[str, Any]]) -> None:
    r = client.post("/test_call", headers={"X-API-Key": API_KEY})
    assert r.status_code == 202
    assert r.json()["call_sid"] == "CA-fake-1"
    assert len(placed) == 1


def test_second_call_while_one_is_live_is_refused(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    assert client.post("/test_call", headers={"X-API-Key": API_KEY}).status_code == 202
    assert client.post("/test_call", headers={"X-API-Key": API_KEY}).status_code == 409
    assert len(placed) == 1


def test_new_call_accepted_once_the_previous_finished(
    client: TestClient, placed: list[dict[str, Any]]
) -> None:
    client.post("/test_call", headers={"X-API-Key": API_KEY})
    assert api._current is not None
    api._current.finished = True
    assert client.post("/test_call", headers={"X-API-Key": API_KEY}).status_code == 202
    assert len(placed) == 2


def test_missing_config_names_the_variable(
    client: TestClient, placed: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PUBLIC_BASE_URL")
    r = client.post("/test_call", headers={"X-API-Key": API_KEY})
    assert r.status_code == 500
    assert "PUBLIC_BASE_URL" in r.json()["detail"]
    assert placed == []


# --- The media socket token ---------------------------------------------------------------------


def _live_call() -> api.Call:
    call = api.Call(token="good-token", sid="CA-x", started_at=time.monotonic())
    api._current = call
    return call


def test_token_accepts_the_live_call() -> None:
    assert _live_call().accepts("good-token")


def test_token_accepts_a_reconnect_during_the_same_call() -> None:
    # Twilio may reconnect mid-call; a single-use token would kill the retry for no good reason.
    call = _live_call()
    assert call.accepts("good-token")
    assert call.accepts("good-token")


def test_token_rejected_once_the_call_finished() -> None:
    call = _live_call()
    call.finished = True
    assert not call.accepts("good-token")


def test_token_rejected_past_the_ceiling() -> None:
    call = _live_call()
    call.started_at = time.monotonic() - api.TOKEN_CEILING_SECS - 1
    assert not call.accepts("good-token")


def test_unknown_token_rejected() -> None:
    assert not _live_call().accepts("some-other-token")


def test_unknown_token_closes_the_socket_without_running_a_pipeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a pipeline must not start for an unrecognised token")

    monkeypatch.setattr(api, "run_caller", explode)
    _live_call()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/some-other-token"):
        pass


# --- TwiML ---------------------------------------------------------------------------------------


def test_twiml_is_a_bidirectional_bridge_that_hangs_up() -> None:
    twiml = build_twiml("wss://example.invalid/ws/abc")
    assert "<Connect>" in twiml
    assert '<Stream url="wss://example.invalid/ws/abc"/>' in twiml
    assert "<Hangup/>" in twiml


def test_twiml_never_uses_a_listen_only_fork() -> None:
    # <Start><Stream> is one-way: the agent would hear and never be able to answer, with no error
    # raised anywhere.
    assert "<Start>" not in build_twiml("wss://example.invalid/ws/abc")


def test_twiml_does_not_leave_the_line_open_after_the_stream() -> None:
    # The Pipecat example uses <Pause length="20"/>, which is twenty seconds of dead air and
    # billing at the end of every measurement call.
    assert "<Pause" not in build_twiml("wss://example.invalid/ws/abc")
