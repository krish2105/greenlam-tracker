# Greenlam Tracker

Maintenance breakdowns and HPL production for a laminates plant, in one
offline-first PWA — a floor app for operators and technicians, a dashboard for
leadership, and a nightly Excel job. FastAPI and plain PostgreSQL behind it.

Built for a real plant, against a specification written on their side. It is in
trial, not in production.

```
Raised → Acknowledged → Material check → Repair → Resolved → Root cause → Closed
```

---

## What makes it more than a CRUD app

**A repair's severity is measured, not chosen.** Nobody picks "High" from a
dropdown. Criticality is banded on Solve Time —
`(correction complete − correction started) − time spent waiting` — so a
twenty-minute fix that sat three hours for a bearing is a twenty-minute repair.
Recording that waiting is the whole reason the material and hold screens exist.

**One filter bar instead of nine reports.** Machine, machine type, shift,
time-of-day, Load No. and module combine freely across three dashboard views.
The time-of-day window converts to plant-local time and wraps, because a night
shift is 22:00–06:00 and in UTC an Indian plant's night lands five and a half
hours off.

**Trilingual, and the third one is the point.** `en`, `hi` (Devanagari) and
`hi-Latn` — Hinglish, which is how a plant floor actually types. CI fails the
build on a missing key, an extra key, or a translated string that dropped its
`{{count}}` and still reads fluently.

**Offline-first for real.** Local Dexie is the source of truth for the user; no
write blocks on the network. Tickets are event-sourced with client-generated
UUIDv7 ids on an append-only log, so a retry is already a no-op.

**Individual metrics do not travel upward.** A person sees their own figures; a
supervisor sees the team against the team average, never ranked, never on the
main dashboard and never in an emailed workbook. `test_a_peer_gets_404_not_403`
asserts it against two distinct accounts.

**A 250-line xlsx writer with no dependency.** The CSP is `script-src 'self'`
and the bundle also serves cheap Android phones, so SheetJS was 900 KB too many.
An `.xlsx` is a ZIP of XML and ZIP entries may be *stored*, which removes the
part that would have needed a compressor.

The reasoning behind these and about thirty others is in
**[docs/DECISIONS.md](docs/DECISIONS.md)** — including the ones that were later
replaced, and why.

---

## Status

Working end to end and deployed: the full ticket lifecycle with two-stage
close, guided why-why with quality scoring, production logging for five machine
forms, Load No. traceability, photos, corrections with audit, six combinable
access areas with a signup and approval queue, Web Push, three dashboard views
with shared filters, Excel and PDF export, ad-hoc spreadsheet analysis, and the
nightly workbook.

| | |
|---|---|
| API tests | 321 |
| Core tests | 93 |
| Migrations | 17 |
| Locales | 3, at parity, CI-enforced |

**Not built, and blocked on someone else:** the Microsoft Graph Excel sync and
the Outlook share (§8, §11.2) need an app registration and tenant admin consent
that have not been issued — there is nothing to authenticate against and
nothing to test. The company-device restriction (§3) needs a decision on what
identifies a company device.

**Synthetic data only.** No real machine names, downtime figures or employee
names have gone into this system, and `app/seed.py` refuses to touch a
non-local database unless explicitly allowed.

---

## Run it

### Docker

```bash
cp .env.example .env
docker compose up
docker compose exec api python -m app.seed
```

<http://localhost:5173> — the API is proxied at `/api` on the same origin, docs
at `/api/docs`.

### Without Docker

Needs Python 3.12+, Node 20+ and PostgreSQL.

```bash
createdb greenlam && createdb greenlam_test

cd api
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://$USER@localhost:5432/greenlam"
export JWT_SECRET="$(openssl rand -base64 48)"
export PIN_PEPPER="$(openssl rand -base64 48)"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --reload

# second terminal, from the repo root
npm install && npm run dev
```

`python -m app.seed` generates 90 days of shaped synthetic history, because
charts drawn from ten tickets are noise. The distributions are deliberate, not
random — a Pareto where three causes carry 80% of downtime, bad-actor machines,
a night shift that runs worse on both MTTR and reject rate, and a reject-rate
lift in the 48 hours around a breakdown. `app/demo_data.py` documents exactly
which patterns were planted; whether any of them exist at the plant is what the
trial is for. `--thin` skips the history, `--reset` wipes it.

---

## Commands

```bash
npm run dev            # PWA (proxies /api to :8000)
npm run build          # typecheck + production build
npm test               # packages/core tests
npm run typecheck      # all workspaces
node scripts/check-locales.mjs   # locale parity + placeholder drift

cd api
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m pytest              # needs greenlam_test
.venv/bin/python -m ruff check app tests
```

---

## Layout

```
api/                      FastAPI + SQLModel + Alembic — 15 routers, 17 migrations
  app/models/             one module per domain; every table carries plant_id + unit_id
  app/roles.py            six access areas, union semantics — the ENFORCING copy
  app/lifecycle.py        escalation, Solve Time, why-why scoring
  app/classify.py         measuring a finished repair and banding it (V5 §5.8)
  app/tenancy.py          the one query layer — scope() and the resolution gate
  app/security.py         PIN peppering, argon2id, graduated lockout, JWT
  tests/                  24 files; the access and redaction rules are tests, not comments

dashboard/                the PWA — /floor/* and /board/*, area-routed
  src/components/floor/   answer-first: raise, work, hold, resume, why-why, production
  src/components/board/   control-room: three views, shared filters, export
  src/components/charts/  SVG, keyboard-navigable, with sr-only data tables
  src/lib/                api client, offline outbox, xlsx reader
  src/i18n/locales/       en / hi / hi-Latn, 724 keys each

packages/core/            pure TypeScript — no DOM, no React
  src/roles.ts            mirrors app/roles.py; a test asserts they stay in step
  src/tickets.ts          escalation, Solve Time, quality scoring
  src/xlsx.ts             the dependency-free workbook writer

export/                   nightly workbook — runs on the GitHub Actions runner,
                          never on the app host
docs/                     specs, decision log, hosting analysis
```

---

## Constraints that shaped it

- **Render free tier**: 512 MB, 0.1 CPU, sleeps after 15 minutes. Excel
  generation never runs there — it runs on the GitHub Actions runner against a
  read-only Postgres role.
- **No cron.** GitHub Actions is the scheduler.
- **`plant_id` and `unit_id` on every table** from the first migration, though
  the pilot is one unit. That is the part that would be expensive to retrofit.
- **`docker-compose.yml` from day one**, because plant IT may mandate on-prem
  and hosting should stay a deployment choice, not an architecture change.
- **Free-text root causes are stored and displayed exactly as typed.** Never
  auto-translated, never normalised.

---

## Documents

| | |
|---|---|
| [docs/DECISIONS.md](docs/DECISIONS.md) | Why the system is shaped this way, including what was replaced |
| [docs/HOSTING.md](docs/HOSTING.md) | Measured options and the free-tier expiry deadline |
| [CLAUDE.md](CLAUDE.md) | The short version of the constraints |

The specification documents in `docs/` and at the repository root were written
on the Greenlam side and are reproduced here as the brief this was built
against.
