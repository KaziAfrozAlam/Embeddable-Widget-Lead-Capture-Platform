# FlyRank Capstone — Embeddable Widget & Lead-Capture Platform

An embeddable widget platform, backend-first. Customers create form widgets, install
them on any website with a **single `<script>` tag**, and collect leads that are
**validated, spam-filtered, rate-limited, geo-enriched (with a fallback chain), stored,
and surfaced in a dashboard** — all on a $0 stack, no credit card.

Tested against 60 behavior-level tests. Deterministic proofs for every acceptance
probe live in [EVIDENCE.md](EVIDENCE.md).

---

## What the system does

Three actors, three request paths:

```
Widget Owner (authenticated)
   └─> Widget Management API  ──> Widget DB (tenant-isolated) ──> embed snippet

Customer Website (ANY origin)
   └─> <script src="…/embed/w<hash>/widget.js?id=123">
         └─> GET /widgets/:id/config   (public · cached · ETag/304)
               └─> widget renders + wires submission

Website Visitor
   └─> POST /submissions       (public · CORS · preflight handled)
         ├─ validation                    bad payload → 4xx JSON, never 500
         ├─ rate limiting (per IP + widget) flood  → 429, service stays up
         ├─ honeypot spam control          bot     → silently dropped
         ├─ geo enrichment: provider A ─fail→ provider B ─fail→ store anyway
         ├─ store submission (idempotent via client_token)
         └─ queue email/webhook side effect (failure never blocks success)

Widget Owner
   └─> Dashboard API          submissions list + totals / per-widget / country
```

Layering: `app/api` (HTTP, JWT auth, boundary validation) → `app/services`
(geo fallback chain, mailer, webhook, background worker) → `app/models`
(tenant-id on every query) → SQLite (zero-config) or Postgres (`DATABASE_URL`).

## Repository layout

```
app/
  main.py            FastAPI app, CORS, payload-size guard, exception handlers
  config.py          settings from env / .env
  db.py / models.py  SQLAlchemy engine + models (Owner, Widget, Submission, Job)
  security.py        scrypt password hashing + JWT
  schemas.py         Pydantic boundary schemas
  deps.py            auth + DB dependencies
  rate_limit.py      fixed-window per-IP / per-widget limiters
  api/               auth, widgets, public (config/submissions/bundle), dashboard
  services/          geo.py, mailer.py, webhook.py, worker.py, sideeffects.py
  renderer/widget.js the embeddable bundle (ships versioned + immutable)
  seed.py            demo tenant + widgets + sample leads
migrations/          Alembic schema migrations
website/             the second-origin "customer site" test page
tests/               60 pytest tests covering every acceptance probe
```

## Setup (validated on Windows; everything free)

```powershell
git clone <repo>
cd flyrank-capstone-widget-platform

# 1. venv + dependencies
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt

# 2. env config (copy the committed example)
Copy-Item .env.example .env
#    set SECRET_KEY to something long; change API_BASE_URL if your port differs

# 3. migrations
.\.venv\Scripts\python -m alembic upgrade head

# 4. seed demo data (demo@example.com / demo-pass-123)
.\.venv\Scripts\python -m app.seed

# 5. run the API  +  the background worker (two terminals).
#    --no-proxy-headers: client IPs come from the socket, so forged
#    X-Forwarded-For headers can't rewrite them (see "Limitations" below).
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
.\.venv\Scripts\python -m app.services.worker

# 6. the "customer site" on a DIFFERENT origin (second terminal/port)
.\.venv\Scripts\python -m http.server 5500 --directory website
#    → open http://localhost:5500/customer-site.html
```

Linux/macOS use `venv/bin/pip` / `venv/bin/python` and `source .venv/bin/activate`.

### Postgres (optional)

The app is SQLite-by-default precisely so a clean machine runs with zero
infrastructure. If you prefer Postgres, Docker Compose is included:

```
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/app
docker compose up -d db
.\.venv\Scripts\python -m alembic upgrade head
```

(`docker compose up --build` runs the whole stack — api + worker + db + migrations.)

## Using it

1. Register: `POST /api/auth/register` `{name, email, password}` → JWT.
2. Create a widget: `POST /api/widgets`
   `{type: "signup|contact|cta|popover", title, fields:[…], button_text, styles}`.
3. Copy the snippet from `GET /api/widgets/{id}/embed` and paste it into any page.
4. Watch leads arrive: `GET /api/dashboard/submissions` and `GET /api/dashboard/stats`.

### Example — create and embed (PowerShell / curl)

```powershell
$token = (Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login `
  -ContentType application/json -Body '{"email":"demo@example.com","password":"demo-pass-123"}').access_token

$widget = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/widgets `
  -Headers @{Authorization="Bearer $token"} -ContentType application/json -Body @'
  {"type":"signup","title":"Newsletter","fields":[
     {"name":"name","label":"Full name","type":"text","required":true},
     {"name":"email","label":"Email","type":"email","required":true}]}'@

$widget.id   # ← the id that goes into the embed snippet
```

## API reference (abridged)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/register` | – | 201 + JWT |
| POST | `/api/auth/login` | – | 200 + JWT |
| GET | `/api/auth/me` | owner | |
| POST | `/api/widgets` | owner | 201; validated fields |
| GET | `/api/widgets` | owner | own widgets only |
| GET | `/api/widgets/{id}` | owner | 404 if not yours |
| PATCH | `/api/widgets/{id}` | owner | partial update |
| DELETE | `/api/widgets/{id}` | owner | 204 |
| GET | `/api/widgets/{id}/embed` | owner | returns `snippet` |
| GET | `/widgets/{id}/config` | public | `Cache-Control: public, max-age=300`, ETag→304 |
| GET | `/embed/{version}/widget.js` | public | `max-age=31536000, immutable` |
| GET | `/widget.js` | public | unversioned alias, short cache |
| POST | `/submissions` | public | hardened path — see below |
| GET | `/api/dashboard/submissions` | owner | paginated, `?widget_id=` optional |
| GET | `/api/dashboard/stats` | owner | totals, daily 30d, per-widget, country |
| GET | `/healthz` | – | |

### `POST /submissions` behavior

```jsonc
// request
{ "widget_id": "…", "client_token": "visitor-session-id", "data": { "name": "Ada", "email": "ada@x.dev" } }
```
- **422** unknown/missing/invalid fields (JSON error list), **400** unparseable body,
  **413** body over 16 384 bytes (enforced on the ASGI receive stream — applies to
  chunked bodies without a `Content-Length` too),
  **404** unknown widget, **429** flood (with `Retry-After`).
- Honeypot filled ⇒ `200 {"accepted": true, "stored": false}` — silently dropped.
- Same `client_token` replayed ⇒ `200` with the original row (`idempotent: true`) — stored once.
- Valid ⇒ `201 {"id", "accepted": true, "stored": true, "created": true}` with geo
  enrichment attached (`ip-api.com` → `ipapi.co` → none), email/webhook jobs queued.

## Configuration (`.env`)

Everything needed is documented in [.env.example](.env.example): secret key, `DATABASE_URL`,
rate-limit windows/budgets, payload cap, geo mode + provider toggles (mock mode makes the
fallback proof deterministic), mail mode (console / stderr / fail / smtp) and worker settings.

## Tests

```
python -m pytest -q          # 60 tests, covers every Section-6 requirement
```

The suite includes: CORS preflight, config caching + 304, boundary validation,
oversized payloads, per-IP and per-widget 429s with a surviving service, honeypot drops,
idempotent replays, geo fallback A→B→none (mock mode), failing side-effects that don't
block success, worker retry + failure alert, tenant isolation, and dashboard aggregates.
See [EVIDENCE.md](EVIDENCE.md) for the mapped proofs.

## Limitations (honest)

- Rate limiting and payload-size guards are process-local (in-memory), so horizontal
  scaling would need a shared store (Redis); fine for single-instance operation.
- Client IPs behind a direct deployment ignore `X-Forwarded-For` (spoof-proof); set
  `TRUST_PROXY_COUNT` to the number of reverse proxies in front when you run behind one.
- The renderer is intentionally minimal (no bundler/minifier); a production bundle via
  esbuild/terser is the first stretch goal.
- `client_token` idempotency is scoped per widget; tokens are generated client-side.
- geo `live` mode depends on free provider rate limits (~45 req/min ip-api); mock mode
  is the deterministic path used by tests and this repo's EVIDENCE.

## License

MIT — see [LICENSE](LICENSE).

