# BUILDLOG — AI-assisted building, kept honest

This capstone was built with heavy AI assistance. Here is what the AI did, where it
got things wrong, and what I changed as a result. Per the ground rules: "The AI wrote
it" is not an answer — I can explain the code. This log is the honest record.

## How I used AI

- **Design**: I first wrote the one-page design (DESIGN.md) myself from the brief;
  the AI helped stress-test the data model and the three request paths.
- **Implementation**: I had the AI scaffold the FastAPI app, models, migrations,
  service layer, renderer bundle, seed, and the pytest suite. I reviewed every file
  after it was generated and fixed or rewrote the parts below.
- **Debugging**: I drove the verification (live server probes + tests) and had the AI
  explain failures when I couldn't see the cause.

## Where AI was wrong (and what I changed)

1. **Malformed JSON returned 422, not 400.** The brief requires "malformed and oversized
   payloads rejected with appropriate 4xx". FastAPI wraps JSON decode failures as
   `RequestValidationError`; my first `JSONDecodeError` handler never fired. Fix:
   detect `json_invalid` errors inside the RequestValidationError handler and map them
   to a clean `400 {"detail": "Invalid JSON body"}`. Now covered by
   `tests/test_public_submissions.py::test_malformed_json_returns_400`.

2. **Rate-limit exception handler on a router doesn't fire.** I initially registered a
   `@router.exception_handler(RateLimitError)` — Starlette handles exceptions at the
   app level, not per-router. Replaced with a plain `HTTPException(429)` carrying the
   `Retry-After` header. Simpler, and it works.

3. **Worker test flakiness from the retry backoff.** The worker correctly sets
   `next_run_at = now + backoff(attempts)` on failure; my tests polled back-to-back and
   immediately observed only the first retry. I changed the tests to a zeroed backoff
   (monkeypatch) so the retry/alert behavior is deterministic.

4. **Hidden test-pollution bug.** The test "cleanup" deleted all rows after each test,
   but never committed (SQLAlchemy sessions default to rollback-on-close) — old jobs
   leaked into later tests and even produced a bogus "done" mailer result. Fixed by
   committing in the fixture teardown.

5. **Renderer JS double-assignment / dead strings.** The generated renderer had a dead
   `label` assignment and a duplicated `.textContent` line; I cleaned both and kept the
   bundle free of a build step (versioned by content hash instead).

6. **Config map lacked explicit locale/mode keys.** Early on, `/widgets/{id}/config`
   carried type/styling but no `locale`/`mode`, which weakened the "config map" claim.
   These are now derived and served on every config (`mode: inline|popover`, `locale`
   defaulting to `en`), and the renderer consumes them (with legacy type-based
   fallback). Pinned by `test_config_map_exposes_mode_locale_theme`. Because the bundle
   changed, its content-hash URL bumped automatically (`w9c088d012f` → `wb6045a1267`).

7. **Demo harness reached admin API cross-origin.** The first `customer-site.html`
   auto-picked its widget via a cross-origin `/api/auth/login` — which a real customer
   page can't do. I reworked the page to load the seeded widget id from a same-origin
   marker (`website/_widgets.json`, emitted by `seed.py`) and made the API base
   overridable (`?api=`), so the second-origin demo works without weakening CORS.

8. **Immutable bundle URL wasn't enforced.** `/embed/{version}/widget.js` served the
   script for *any* version string, which undermined the "one immutable URL per
   release" guarantee. Unknown versions now return **404**; the alias `/widget.js`
   remains as a convenience with a short cache. Pinned by
   `test_unknown_version_returns_404`.

9. **Line endings bit the content-hash release URL.** The renderer URL is derived from
   the file's bytes; Windows Git's `core.autocrlf` rewrote line endings on checkout,
   so the same commit produced a different version hash (`w081cd0dd7e`) on a fresh
   machine than the one reviewed (`wb6045a1267`). Fixed with `.gitattributes`
   (`* text=auto eol=lf`) + `git add --renormalize`; verified a fresh clone now yields
   byte-identical output (`wb6045a1267`).

## What the AI got right (and I kept, with explanation)

- Layered layout `api → services → models` with tenant-id scoping on every query.
- Boundary validation split: Pydantic schemas (shape) + a business-rule validator for
  dynamic widget fields (unknown field / missing required / bad email / bad option).
- The geo fallback chain design: provider A → B → `None` (degrade, never fail), with a
  deterministic mock mode toggled by env.
- Idempotency via `UNIQUE(widget_id, client_token)` and a same-token → same-row reply.
- The versioned bundle: renderer content hash becomes the URL path, `immutable`.

## Anything I still don't fully understand?

- FastAPI/Starlette middleware ordering (which middleware wraps which) — I confirmed by
  reading Starlette's `build_middleware_stack`, but it took a while.
- Why a long-lived `uvicorn` kept a stale state in one dev run; restarting fixed it.

## Cost tracking (shared requirement #7)

AI usage here was billed per-call through my own provider. I tracked every AI session
against a budget of **$10 per day**; this capstone stayed under it. No commit includes
any API key, token, or credential — everything is env-based (see `.env.example`).