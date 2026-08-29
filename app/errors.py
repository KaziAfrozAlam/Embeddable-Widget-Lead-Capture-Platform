"""FastAPI exception handlers so bad input -> clean JSON 4xx, never a bare crash."""

import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        # Unparseable body is a malformed-request error (400), not a field
        # validation error (422).
        all_json = all("json" in (e.get("type") or "") for e in errors)
        if errors and all_json:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        out = []
        for err in errors:
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            out.append({"field": loc or "body", "message": err.get("msg", "invalid")})
        return JSONResponse(status_code=422, content={"detail": out})

    @app.exception_handler(json.JSONDecodeError)
    async def _bad_json(request: Request, exc: json.JSONDecodeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})