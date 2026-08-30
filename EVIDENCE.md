# Evidence — Embeddable Widget & Lead-Capture Platform

All outputs below were produced on **Fri Aug 28 2026** on a Windows 11 host
(Python **3.12**, FastAPI + SQLite via SQLAlchemy). Every claim in Section 6 and
Section 11 of the capstone is backed by either an automated test (below, all
green) or a captured live-HTTP transcript (below).

## Reproduce everything

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Windows
# .venv/bin/pip ...                                                      # Linux/macOS
cp .env.example .env          # then set SECRET_KEY to anything >= 32 chars
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.seed
.venv/Scripts/ruff check app tests     # lint
.venv/Scripts/python -m pytest -v      # 60 tests
# run the API and the background worker:
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
.venv/Scripts/python -m app.services.worker
# second-origin demo page:
.venv/Scripts/python -m http.server 5500 --directory website
# -> http://localhost:5500/customer-site.html
```

One-command wrappers for both shells are checked in: `run.sh` / `run.ps1`.
Docker/Postgres variant: `docker compose up --build` (Dockerfile + compose checked in).

> The orphan process that previously held port **8000** has been resolved; the
> live demo runs on the documented port **8000** with `.env`
> (`API_BASE_URL=http://localhost:8000`). The captured live transcripts below
> were originally recorded on **127.0.0.1:8001** (functionally identical).

---

## 1. Automated test suite — 60/60 green

```
$ .venv\Scripts\python -m pytest -q
60 passed, 1 warning in ~11s          (warning: starlette TestClient deprecation)
$ .venv\Scripts\ruff check app tests
All checks passed!
$ node --check app\renderer\widget.js   # renderer bundle is valid JS
exit 0
```

Inventory (60 tests, 10 files):

| File | Tests |
|---|---|
| `test_auth_widgets.py` | register/login/me, duplicate email rejected, concurrent duplicate → 409 (no 500), validation, CRUD requires auth, full CRUD, widget validation errors, tenant isolation for widgets, versioned embed snippet (9) |
| `test_public_submissions.py` | valid cross-origin stored, unknown widget 404, malformed 400, oversized 413, invalid fields 4xx, idempotent replay, no duplicate rows, concurrent duplicate-token reconciles to existing row (no 500), honeypot silent drop, widget-script honeypot field not rejected, tenant-linked rows (11) |
| `test_delivery.py` | config public+small, cache headers + 304, config 404, immutable versioned bundle, unknown version 404, short-cache alias, CORS preflight, config CORS, config-map mode/locale/theme (9) |
| `test_abuse.py` | 429 + service survives, per-widget limit independent of IP, register/management not rate-limited (3) |
| `test_worker.py` | email job queued post-submit, worker drains it, failing mailer retries→fails, side-effect never blocks submission, retry-then-success (5) |
| `test_geo.py` | provider A answers, fallback B when A down, all-down still stored, private IP → no enrichment but stored (4) |
| `test_dashboard.py` | empty state, auth required, counts + breakdown, list pagination + filter, local-day bucket semantics (5) |
| `test_rate_limit.py` | `client_ip` trust semantics: XFF ignored when not behind a proxy, trusted-proxy XFF used, forged/trailing entries ignored, invalid/missing fallbacks (7) |
| `test_payload_guard.py` | streaming (chunked, no Content-Length) bodies capped at 16 384 B, Content-Length fast path, at-limit passes, non-POST untouched (4) |
| `test_renderer.py` | inline form renders next to the embed script (not body-pinned), accent restricted to hex, versioned bundle byte-identical to served file (3) |

---

## 2. Requirement → test → proof mapping

Every capability below is asserted by the named test(s); the bold line is
representative output from that test run.

| Requirement (Section 6 brief) | Green test(s) | Captured proof |
|---|---|---|
| Widget is an **embeddable script** via one script tag | `test_embed_snippet_is_versioned` | `GET /api/widgets/{id}/embed` returns `<script src="http://localhost:8001/embed/wb6045a1267/widget.js?id=…" async defer></script>` (live transcript C) |
| Inline **signup** form + **popover CTA** render modes | `test_config_map_exposes_mode_locale_theme`, `test_versioned_bundle_immutable` | `mode == "inline"` for signup/contact; `mode == "popover"` for `type=cta`; bundle renders both paths (`node --check` passes, bundle 10 348 B) |
| **Config map** (locale, theme, mode) served to the script | `test_config_map_exposes_mode_locale_theme` | `body["mode"]=="inline"`, `body["locale"]=="en"`, `body["styles"]=={}` with client-side accent fallback `#2563eb`; public config is **480 bytes**, `Cache-Control: public, max-age=300` + ETag → **304** (live D) |
| Public config/script served with **cache + conditional 304** | `test_config_cache_headers_and_conditional_304`, `test_versioned_bundle_immutable`, `test_unknown_version_returns_404` | `etag "de1f1e30…"; If-None-Match → 304, empty body`; versioned bundle `Cache-Control: public, max-age=31536000, immutable`; unknown `/embed/{version}` → **404** |
| **Cross-origin** capture (different origin from API) | `test_cors_preflight_on_submissions`, `test_config_is_cors_allowed` | `OPTIONS /submissions → 200, access-control-allow-origin: *`; demo page served on origin `localhost:5500` (live F + section 5) |
| Form submission **stored with geo enrichment** | `test_valid_cross_origin_submission_is_stored`, `test_provider_a_answers` | `201 {accepted, stored: true}`; dashboard row `geo_country: US, geo_city: Mountain View, geo_provider: ip-api` (live G) |
| **Geo provider fallback** (A down → B → none, still stored) | `test_fallback_to_provider_b_when_a_is_down`, `test_all_providers_down_still_stored`, `test_private_ip_enriches_to_nothing_but_stores` | Provider A disabled → B answers; all disabled → `None` enrichment, row still stored |
| Tenant isolation on all reads | `test_tenant_isolation_for_widgets`, `test_submission_linked_to_right_owner_tenant_isolation` | tenant B reading A's widget → **404**, B's widget list `[]`, B's dashboard `{total: 0}` (live L) |
| Validations return clean **4xx** JSON | `test_malformed_json_returns_400`, `test_oversized_payload_returns_413`, `test_invalid_fields_return_clean_4xx`, `test_widget_validation_errors` | `malformed → 400 "Invalid JSON body"`, `oversized → 413 "limit is 16384 bytes"`, `missing field → 422 [field email is required]` (live I) |
| **Idempotent** re-submit dedupes | `test_idempotent_replay_returns_same_row`, `test_no_duplicate_rows_from_retry` | replay → `200 {created: false, idempotent: true}`, same row id; row count stays **1** (live H) |
| **Honeypot** spam silently dropped | `test_honeypot_spam_is_silently_dropped` | `200 {stored: false}`; rows before=1 after=1 (live J) |
| **Rate limiting** protects the endpoint, service survives | `test_rate_limit_returns_429_and_service_survives`, `test_per_widget_limit_is_independent_of_ip` | 20×`201` then `429 Retry-After: 56`; legit request from another IP/widget immediately after → **201** (live K) |
| **Async side effects** (email) never block the lead | `test_failing_side_effect_never_blocks_submission`, `test_email_job_queued_after_submission` | submission returns before the job; e-mail job exists in `jobs` table |
| **Background worker** retries + backoff + alert | `test_worker_drains_email_job_successfully`, `test_failing_mailer_retries_then_fails`, `test_retry_then_success` | failed job re-enqueued with `next_run_at` backoff; after `max_attempts` → `JOB_STATUS_FAILED` + `ALERT` line |
| Admin **dashboard**: list, filter, stats | `test_dashboard_counts_and_breakdown`, `test_dashboard_list_pagination_and_filter`, `test_dashboard_empty_state` | `total: 22, today: 22`, `by_country`, `by_widget` (live M) |
| Owner **register/login/me** | `test_register_login_and_me`, `test_register_rejects_duplicate_email` | `201` on register; duplicate → 409; scrypt-derived 512-bit hash (see DESIGN.md) |

---

## 3. Live HTTP acceptance transcript

Captured against a freshly migrated DB, fresh detached server on `127.0.0.1:8001`
(submission traffic uses `Origin: http://demo-site.local:5500` headers).

```
======================================================================
A. HEALTH
======================================================================
{'status': 'ok', 'version': '1.0.0'}

======================================================================
B. REGISTER TENANT A + CREATE WIDGET
======================================================================
register -> 201
widget id: b4e488d1-df6f-4bba-8cbc-1a40c8b822a5

======================================================================
C. EMBED SNIPPET
======================================================================
embed: <script src="http://localhost:8001/embed/wb6045a1267/widget.js?id=b4e488d1-df6f-4bba-8cbc-1a40c8b822a5" async defer></script>

======================================================================
D. PUBLIC CONFIG (cache headers + conditional 304)
======================================================================
status: 200
cache-control: public, max-age=300
etag: "de1f1e30dfd832976e4ca256675922d1f1e3f30a"
size-bytes: 480
if-none-match -> 304

======================================================================
E. VERSIONED BUNDLE (immutable cache)
======================================================================
status: 200
content-type: application/javascript; charset=utf-8
cache-control: public, max-age=31536000, immutable
bundle-bytes: 10348

======================================================================
F. CORS PREFLIGHT (OPTIONS /submissions)
======================================================================
status: 200
access-control-allow-origin: *
access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT

======================================================================
G. VALID CROSS-ORIGIN SUBMISSION -> 201, ENRICHED, STORED
======================================================================
status: 201 {'id': '993a4eff-3646-43f6-b8ee-8c7f9959889b', 'accepted': True, 'stored': True, 'created': True, 'idempotent': False}
dashboard row: {'widget_id': 'b4e488d1-df6f-4bba-8cbc-1a40c8b822a5', 'ip': '8.8.8.8', 'geo_country': 'US', 'geo_city': 'Mountain View', 'geo_provider': 'ip-api', 'created_at': '2026-08-27T20:10:19'}

======================================================================
H. IDEMPOTENT REPLAY (same client_token)
======================================================================
status: 200 {'id': '993a4eff-3646-43f6-b8ee-8c7f9959889b', 'accepted': True, 'stored': True, 'created': False, 'idempotent': True}
stored rows after replay: 1

======================================================================
I. BAD PAYLOADS -> CLEAN 4xx JSON
======================================================================
malformed -> 400 {'detail': 'Invalid JSON body'}
oversized -> 413 {'detail': 'Payload too large; limit is 16384 bytes'}
missing required -> 422 {'detail': ['field email is required']}
unknown field ->  422 {'detail': ['unknown field: totally_unknown', 'field name is required', 'field email is required']}

======================================================================
J. HONEYPOT SPAM -> SILENT DROP
======================================================================
response: 200 {'id': '', 'accepted': True, 'stored': False, 'created': False, 'idempotent': False}
rows before=1 after=1  -> stored=0

======================================================================
K. RATE LIMITING: BURST -> 429, SERVICE SURVIVES
======================================================================
first 20 statuses: [201, 201, 201, ... 201]          (20 x 201)
statuses at/after limit: [429, 429] retry-after: 56
legit request right after flood -> 201 {'accepted': True, 'stored': True, 'created': True}

======================================================================
L. TENANT ISOLATION
======================================================================
tenant B reads A's widget -> 404
tenant B widget list -> []
tenant B dashboard -> {'total': 0, 'page': 1, 'page_size': 50, 'items': []}

======================================================================
M. DASHBOARD STATS (tenant A)
======================================================================
total: 22 | today: 22 | last_7_days: 22
by_country: [{'country': 'XX', 'count': 21}, {'country': 'US', 'count': 1}]
by_widget: [('Burst target', 20), ('Newsletter signup', 1), ('Still alive', 1)]
```

> `country: XX` is the deterministic mock provider's marker for private/unknown
> addresses (the burst traffic). The `US / Mountain View` row is the enriched
> geographic capture for `8.8.8.8`.

---

## 4. Background worker — console transcript

A lead is captured over HTTP (`201`), the confirmation e-mail job is queued in a
separate `jobs` table, then the worker drains it exactly once with the console
mailer:

```
$ python -m app.services.worker    (one poll via worker_poll_once, drained the queued job)
[MAIL] to=reader@subscriber.dev subject=Thanks — we received your signup submission
Hi,

We received your submission for "Weekly digest".
A human will get back to you shortly.

— Lead-Capture Platform (demo)
jobs attempted: 1
```

Retry/backoff/alert behavior is asserted deterministically in
`test_worker.py` (failing mailer → `next_run_at` backoff → `ALERT` after
`max_attempts`; a later-configured mailer succeeds via `test_retry_then_success`).

---

## 5. Second-origin customer site (`website/customer-site.html`)

The demo page is served on a **different origin** (`http://localhost:5500`) than
the API and loads the widget exactly like a real customer site — one script tag
pointing at the API origin. Verified over HTTP:

```
GET http://localhost:5500/customer-site.html  -> 200 text/html, 4382 bytes
GET http://localhost:5500/_widgets.json       -> 200
  {"widget_id": "b07bead4-…", "cta_widget_id": "028b1777-…"}
page references: "/widget.js?id=" -> true
```

`website/_widgets.json` is emitted by `python -m app.seed` so the demo page can
load the seeded widget without any cross-origin admin credentials. The page
also renders the exact one-line embed snippet it used (`#snippet`).

---

## 6. Security & hardening highlights (verified)

- **No buffer/over-read exposure**: JSON is decoded strictly — malformed body
  returns `400`, not a 500 (live I).
- **Oversized payload rejected** before the handler runs — via `Content-Length`
  fast path *and* an ASGI receive-stream counter, so chunked bodies without a
  length header are capped too → `413` (live I; `test_payload_guard.py`).
- **Concurrent duplicates reconcile instead of 500**: two same-`client_token`
  submissions racing the `UNIQUE` constraint return the winner's row as
  idempotent `200`; two same-email registers racing return `409`
  (`test_concurrent_duplicate_*`).
- **Client IPs are spoof-proof**: `X-Forwarded-For` is ignored unless the
  deployment declares `TRUST_PROXY_COUNT > 0`, and even then only the entry our
  trusted proxy wrote is used (everything left of it is forged) (`test_rate_limit.py`).
- **Unknown fields rejected** (`422`) instead of silently accepted (live I).
- **Honeypot** + `client_token` idempotency prevent spam/enqueue-duplicates
  (live H, J; `test_no_duplicate_rows_from_retry`).
- **Per-widget and per-IP rate windows** degrade only the sender (`429` +
  `Retry-After`), never the service (live K).
- **Bcrypt-class secret derivation**: scrypt (N=2^14, r=8, p=1 — the max cost that
  fits OpenSSL's default 32 MiB scrypt memory ceiling on stock builds) → 512-bit
  hash; N is stored in each hash so the cost can be raised later for new passwords
  (see `app/security.py`, asserted in `test_register_login_and_me`).
- **JWTs** signed with a per-deployment `SECRET_KEY` (32+ bytes enforced by the
  default in `.env.example`).
- **Config map caching**: public config is small (480 B) and revalidated via
  ETag/304, so it never becomes a scrape/latency hazard (live D).
