# Design — Embeddable Widget & Lead-Capture Platform

One-page design document (capstone Phase 1 gate).

## Problem

Let a customer create an embeddable form widget, install it on any website with one
`<script>` tag, and receive validated, spam-filtered, geo-enriched leads in a dashboard —
while the whole flow survives the open internet (untrusted input, floods, dead upstreams).

## Data model

```
owners        id, email (unique), name, password_hash(scrypt), created_at
widgets       id, owner_id → owners (tenant), type[signup|contact|cta|popover],
              title, description, fields (JSON), button_text, styles (JSON), timestamps
submissions   id, widget_id → widgets, owner_id → owners (denormalized for fast
              tenant-scoped queries), client_token (idempotency key), data (JSON),
              ip, geo_country, geo_city, geo_provider, created_at
              UNIQUE(widget_id, client_token)
jobs          id, kind[email|webhook], payload (JSON), status[pending|processing|
              done|failed], attempts, max_attempts, next_run_at, last_error
```

Indexes: `owners(email)`, `widgets(owner_id)`, `submissions(widget_id)`,
`submissions(owner_id)`, `submissions(owner_id, created_at)`, `jobs(status, next_run_at)`.
Migrations via Alembic.

## The embed flow

1. Owner creates a widget → gets an id.
2. Owner copies the embed snippet: `<script src="{api}/embed/{version}/widget.js?id={id}" …>`
3. Any website loads it → the bundle reads (id, api origin) from its own URL →
   fetches `GET /widgets/{id}/config` (public, cached) → renders the form (or popover).
4. Visitor submits → `POST /submissions` → validation → rate limits → honeypot →
   geo enrichment (fallback chain) → store → queue side effects.

## API surface

| Path | Auth | Purpose |
|---|---|---|
| `POST /api/auth/register`, `/login`, `GET /me` | public | tenant accounts, JWT |
| `POST/GET/PATCH/DELETE /api/widgets[/:id]` | owner | widget CRUD (tenant-scoped) |
| `GET /api/widgets/:id/embed` | owner | returns the one-line snippet |
| `GET /widgets/:id/config` | public | small config payload, `Cache-Control`, ETag/304 |
| `GET /embed/:version/widget.js`, `/widget.js` | public | versioned immutable bundle |
| `POST /submissions` | public | hardened submission path (CORS + preflight) |
| `GET /api/dashboard/submissions`, `/stats` | owner | listings + totals / per-widget / country |

## Layer sketch

`app/api` (HTTP + auth + validation-on-the-edge) → `app/services`
(geo chain, mailer, webhook, worker queue, side-effect enqueueing) → `app/models`
(SQLAlchemy, tenant-id everywhere) → SQLite (dev/zero-config) or Postgres via `DATABASE_URL`.

## Explicit non-goal

No real CDN, no hosting, no domain, no form-builder UI, and no frontend beyond a
minimal renderer + test page. The grade lives in the backend hardening story.

## Hardening checklist

- Boundary validation (Pydantic + business rules) → clean 4xx, never 500.
- Rate limiting per IP and per widget (fixed window) → 429 under flood.
- Honeypot spam control → silent drop.
- Geo fallback chain (ip-api → ipapi.co → degrade) → store with or without geo.
- Idempotency via `client_token` → retried submissions stored once.
- Side effects (email/webhook) queued after commit, retried by a worker, failure = alert, never a failed main path.