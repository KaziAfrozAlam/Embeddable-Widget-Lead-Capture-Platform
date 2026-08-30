"""Payload-size guard: the cap must hold even when the client sends no
Content-Length (chunked transfer). Starlette's TestClient materialises
generator bodies on the request side, so it cannot exercise the streaming
receive path faithfully -- these tests drive the middleware with spec-shaped
ASGI messages instead."""

import asyncio

from app.main import PayloadSizeLimitMiddleware


async def _inner_app(scope, receive, send):
    body = bytearray()
    while True:
        message = await receive()
        assert message["type"] == "http.request"
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": bytes(body)})


def _run(scope_headers, messages, max_bytes=100):
    sent = []

    async def _receive():
        return messages.pop(0)

    async def _send(message):
        sent.append(message)

    async def _run_coro():
        inner_called = {"v": False}

        async def _inner(scope, receive, send):
            inner_called["v"] = True
            await _inner_app(scope, receive, send)

        await PayloadSizeLimitMiddleware(_inner, max_bytes=max_bytes)(
            {"type": "http", "method": "POST", "headers": scope_headers},
            _receive,
            _send,
        )
        return inner_called["v"]

    return asyncio.run(_run_coro()), sent


def _status(sent, default=200):
    for message in sent:
        if message["type"] == "http.response.start":
            return message["status"]
    return default


def _responder_headers(sent):
    for message in sent:
        if message["type"] == "http.response.start":
            return dict(message["headers"])
    return {}


def _assert_413_is_cross_origin_readable(sent):
    """The middleware sits outside CORS; its 413 must still carry
    Access-Control-Allow-Origin or a browser treats it as an opaque failure."""
    assert _status(sent) == 413
    assert _responder_headers(sent)[b"access-control-allow-origin"] == b"*"


def test_content_length_fast_path_rejects_before_app():
    # Content-Length alone is enough to reject; the app never runs.
    inner_called, sent = _run(
        scope_headers=[(b"content-length", b"500")],
        messages=[{"type": "http.request", "body": b"x" * 500, "more_body": False}],
    )
    assert inner_called is False
    _assert_413_is_cross_origin_readable(sent)


def test_chunked_body_without_content_length_is_capped():
    # Two chunks, no content-length: the guard trips as soon as the total
    # exceeds the limit, mid-stream.
    _, sent = _run(
        scope_headers=[],
        messages=[
            {"type": "http.request", "body": b"a" * 60, "more_body": True},
            {"type": "http.request", "body": b"b" * 60, "more_body": False},
        ],
    )
    _assert_413_is_cross_origin_readable(sent)


def test_body_at_limit_passes_through_unchanged():
    inner_called, sent = _run(
        scope_headers=[],
        messages=[{"type": "http.request", "body": b"a" * 60, "more_body": False}],
    )
    assert inner_called is True
    assert _status(sent) == 200


def test_non_post_methods_are_not_guarded():
    sent = []
    inner_called = {"v": False}

    async def _receive():
        return {"type": "http.request", "body": b"x" * 500, "more_body": False}

    async def _send(message):
        sent.append(message)

    async def _run_coro():
        async def _inner(scope, receive, send):
            inner_called["v"] = True
            await _inner_app(scope, receive, send)

        await PayloadSizeLimitMiddleware(_inner, max_bytes=100)(
            {
                "type": "http",
                "method": "GET",
                "headers": [(b"content-length", b"500")],
            },
            _receive,
            _send,
        )

    asyncio.run(_run_coro())
    assert inner_called["v"] is True
    assert _status(sent) == 200