# Greenlam Maintenance & Production Intelligence System

## Specs — read these before writing code
- `docs/GREENLAM-TRACKER-BUILD-SPEC.md` — architecture, schema, KPIs, phases
- `docs/MODULE-ADDENDUM-v1.1.md` — QR, bilingual, Excel partitioning, reviews. **Supersedes the base spec where they disagree.**
- `docs/reference/greenlam-maintenance-tracker.jsx` — working prototype. This is the functional spec: lifecycle, field names, machine master, Excel headers. Do not copy its `window.storage` persistence or its hardcoded passcode.

## What this is
Offline-first maintenance breakdown + production tracking for a Greenlam Laminates plant. Pilot in one unit → full plant → other plants in India. Three surfaces: a floor PWA (operators + technicians), a dashboard (leadership), and a nightly job that rebuilds the master Excel workbook.

## Stack
- **API:** Python 3.12, FastAPI, SQLModel, Alembic
- **DB:** Neon PostgreSQL (plain Postgres only — no vendor-specific features)
- **Frontend:** one PWA. Vite + React + TypeScript + Tailwind + `vite-plugin-pwa`. Routes `/floor/*` and `/board/*`, role-gated.
- **Local storage:** Dexie over IndexedDB
- **Shared logic:** `packages/core` — pure TypeScript, no DOM, no React
- **Nightly job:** GitHub Actions runner, `pandas` + `openpyxl`, direct Neon connection
- **Hosting:** Render free (API), Render Static (PWA), Neon free (DB), Cloudflare R2 (files)

## Non-negotiable constraints
- Render free = 512 MB / 0.1 CPU / sleeps after 15 min. **Excel generation never runs on Render** — it runs on the GitHub Actions runner via a read-only `export_reader` Postgres role.
- Render free has **no cron**. GitHub Actions is the scheduler.
- **Offline-first.** Local Dexie is the source of truth for the user. No write ever blocks on the network.
- **`plant_id` and `unit_id` on every table** from the first migration, even though the pilot is one unit.
- **Event sourcing for tickets.** Client-generated UUIDv7 event ids, append-only `ticket_events`, state derived by replay.
- **`docker-compose.yml` from day one.** Plant IT may mandate on-prem; hosting must stay a deployment choice, not an architecture change.
- **Synthetic data only** until cloud hosting is approved in writing. No real machine names, downtime figures, or employee names leave the machine.

## Domain rules
- Ticket lifecycle: Raised → Acknowledged → Material check → Repair → Resolved → Root cause → Verified & closed. Stages move forward only, except an explicit `REOPENED` event.
- `downtime_type` (breakdown / planned / changeover / no_downtime) must be set. Planned downtime never counts toward MTBF.
- Every user-visible string goes through `t()` from the first component. Locales: `en`, `hi`, `hi-Latn`.
- Free-text root-cause entries are stored and displayed exactly as typed. Never auto-translate them.
- QR encodes `{BASE_URL}/s/{qr_token}` — a random 22-char token on the machine row, never `machine_id`. Scan resolution works offline against the local machine master.
- Individual technician performance metrics are visible to that person and their supervisor only. Never on the main dashboard, never in an emailed workbook, never as a peer-visible ranking. Ask before exposing any individual-level metric anywhere new.

## How to work
- Follow the phase order in the spec. **Stop at the end of each phase**, show what runs, wait for my go-ahead. Don't run ahead.
- Smallest change that works. No speculative abstraction, no config for things that have one value.
- Ask when the spec doesn't cover something. Never invent plant-specific values — machine names, costs, thresholds, targets all come from me.
- The sync engine is the risky part. It needs tests simulating three devices going offline, generating conflicting events, and reconciling.

## Commands
```bash
docker compose up              # api + postgres + frontend, local
alembic upgrade head           # migrations
pytest                         # api tests
npm run dev                    # frontend
npm run test                   # frontend + core tests
```
