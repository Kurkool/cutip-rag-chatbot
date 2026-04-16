"""LINE Messaging API helpers — signature verification, event parsing, text splitting."""

import base64
import hashlib
import hmac as _hmac

import pytest


def _sign(body: bytes, secret: str) -> str:
    digest = _hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_verify_signature_valid():
    from chat.services.line import verify_signature
    body = b'{"hello":"world"}'
    secret = "channel-secret-1"
    assert verify_signature(body, _sign(body, secret), secret) is True


def test_verify_signature_tampered_body():
    from chat.services.line import verify_signature
    secret = "channel-secret-1"
    sig = _sign(b'{"hello":"world"}', secret)
    assert verify_signature(b'{"hello":"tampered"}', sig, secret) is False


def test_verify_signature_wrong_secret():
    from chat.services.line import verify_signature
    body = b"{}"
    assert verify_signature(body, _sign(body, "secret-A"), "secret-B") is False


def test_verify_signature_empty():
    from chat.services.line import verify_signature
    assert verify_signature(b"{}", "", "secret") is False


def test_parse_text_events_extracts_message():
    from chat.services.line import parse_text_events
    payload = {
        "events": [{
            "type": "message",
            "message": {"type": "text", "text": "hello"},
            "replyToken": "rt-1",
            "source": {"userId": "u-1"},
            "webhookEventId": "evt-1",
            "timestamp": 1700000000,
        }],
    }
    events = parse_text_events(payload)
    assert len(events) == 1
    assert events[0]["text"] == "hello"
    assert events[0]["user_id"] == "u-1"
    assert events[0]["webhook_event_id"] == "evt-1"


def test_parse_text_events_ignores_non_text():
    from chat.services.line import parse_text_events
    payload = {
        "events": [
            {"type": "postback", "postback": {"data": "ignored"}},
            {"type": "message", "message": {"type": "sticker"}},
        ],
    }
    assert parse_text_events(payload) == []


def test_split_text_messages_short_returns_single():
    from chat.services.line import _split_text_messages
    msgs = _split_text_messages("short message")
    assert msgs == [{"type": "text", "text": "short message"}]


def test_split_text_messages_empty_returns_none():
    from chat.services.line import _split_text_messages
    assert _split_text_messages("") == []
    assert _split_text_messages("   ") == []


def test_split_text_messages_splits_long_at_newline():
    from chat.services.line import _LINE_TEXT_LIMIT, _split_text_messages
    long = ("a" * (_LINE_TEXT_LIMIT - 100)) + "\n\n" + ("b" * 500)
    msgs = _split_text_messages(long, max_parts=4)
    assert len(msgs) >= 2
    assert all(len(m["text"]) <= _LINE_TEXT_LIMIT for m in msgs)
