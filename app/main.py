"""FastAPI application factory + middleware (CORS, payload-size guard)."""

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import auth, dashboard, public, widgets
from .config import get_settings
from .errors import register_exception_handlers

settings = get_settings()


class _PayloadTooLarge(Exception):
    """Raised by the receive-guard when a streamed body exceeds the limit."""


class PayloadSizeLimitMiddleware:
    """Reject oversized request bodies even when the client skips
    Content-Length (chunked transfer). The ASGI receive stream is counted, so
    the cap holds regardless of how the bytes arrive; a Content-Length fast
    path exists for the cheap reject."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        content_length = None
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                content_length = value
                break
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        def _has_cors_header(headers: list[tuple[bytes, bytes]]) -> bool:
            return any(k.lower() == b"access-control-allow-origin" for k, v in headers)

        received = 0

        async def guarded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raise so the upstream body read aborts. When FastAPI is
                    # consuming the body it swallows this into a 400 and sends
                    # a response itself; guarded_send rewrites that to 413.
                    raise _PayloadTooLarge()
            return message

        sent_413 = False

        async def guarded_send(message):
            nonlocal sent_413
            if message["type"] == "http.response.start" and received > self.max_bytes and not sent_413:
                # The guarded receive tripped but the app already replied
                # (e.g. FastAPI's generic 400 for a failed body read) — send
                # the documented 413 instead of that mask.
                body = json.dumps(
                    {"detail": f"Payload too large; limit is {self.max_bytes} bytes"}
                ).encode("utf-8")
                headers = [
                    (k, v)
                    for k, v in message["headers"]
                    if k.lower() not in {b"content-length", b"content-type", b"content-encoding"}
                ]
                if not _has_cors_header(headers):
                    headers.append((b"access-control-allow-origin", b"*"))
                headers.append((b"content-type", b"application/json; charset=utf-8"))
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                await send({"type": "http.response.start", "status": 413, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                sent_413 = True
                return
            if message["type"] == "http.response.body" and sent_413:
                # The superseded response's own body must not be written.
                return
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _PayloadTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send) -> None:
        # This middleware sits *outside* CORSMiddleware (add_middleware puts the
        # last-registered middleware first), so its 413 would leave the server
        # without CORS headers. Match the app's wide-open policy explicitly.
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Payload too large; limit is {self.max_bytes} bytes"},
            headers={"Access-Control-Allow-Origin": "*"},
        )
        await response(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Embeddable Widget & Lead-Capture Platform",
        version=__version__,
        description="Capstone: embeddable widgets, hardened public submission API, "
        "geo enrichment with fallback, safe side effects, owner dashboard.",
    )

    # The public endpoints are called from *any* website, so CORS is wide open.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=settings.max_payload_bytes)

    register_exception_handlers(app)

    app.include_router(auth.router)
    app.include_router(widgets.router)
    app.include_router(public.router)
    app.include_router(dashboard.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()