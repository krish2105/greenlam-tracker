# Greenlam Maintenance & Production Intelligence System
## Build Specification v1.0

**Prepared by:** Krishna Mathur
**Date:** 24 August 2026
**Status:** Draft for stakeholder review — open decisions listed in Section 12

---

## 0. Read this first — the three things that will decide the project

Before any code, three constraints from your brief interact badly with each other. Resolving them early saves weeks.

| # | Constraint you gave | The problem | Recommended resolution |
|---|---|---|---|
| 1 | "Backend on Render free" | Render's **free PostgreSQL is deleted after 30 days** (1 GB, 14-day grace period, then gone). A 30-day pilot would lose all its data right when leadership reviews it. | Keep Render free for the **API compute**, but put the **database on Neon's free tier** (0.5 GB, permanent, no card, scale-to-zero). Free Render web services also spin down after 15 min idle with a 30–60 s cold start, and you get 750 instance-hours/month. |
| 2 | "Export to Excel daily, no manual intervention" | Render's **Cron Jobs are a paid feature**. There is no free scheduler on Render. | Trigger the export from a **GitHub Actions scheduled workflow** (free, and it fails loudly in your inbox if the export breaks — which matters more than the scheduling itself). Backup option: cron-job.org free tier. |
| 3 | "Offline requirement" + "iOS and Android app" | A shop floor with patchy Wi-Fi *plus* a backend that cold-starts for 30–60 s means the app must never wait on the network. Also, publishing to the App Store needs a **paid Apple Developer account (₹8,900/yr) registered to Greenlam**, not to you. | Build **offline-first from day one** (local SQLite is the source of truth, background sync). And strongly consider shipping the pilot as an **installable PWA** — see Section 4.1. |

**The one architectural rule that matters most for scaling:** put `plant_id` and `unit_id` columns on every single table from the very first migration, even though the pilot is one unit. Retrofitting multi-tenancy after the plant-wide rollout is the single most expensive mistake you can make on this project.

---

## 1. Objective and scope

### 1.1 What the system does

Replace the current manual Excel breakdown/production register with a system that:

1. Lets shop-floor operators raise a machine breakdown in under 30 seconds, from a phone, with or without a network connection
2. Walks the maintenance team through a structured resolution workflow that captures root cause and preventive action — not just "fixed it"
3. Records daily production output and rejections against size, texture, shift, and machine
4. Surfaces live KPIs and trend graphs to plant leadership on a dashboard
5. Regenerates the complete master Excel workbook every night and delivers it to leadership automatically

### 1.2 Rollout stages

| Stage | Scope | Duration | Infrastructure |
|-------|-------|----------|----------------|
| **Pilot** | 1 unit (target: Press or Sanding section) | 4–6 weeks | Free tier (Render + Neon) |
| **Plant-wide** | All sections of the pilot plant | 8–12 weeks | Paid, ~₹2,500–4,000/month |
| **Multi-plant** | Other Greenlam plants across India | 6+ months | Paid, multi-tenant, ~₹12,000–25,000/month |

### 1.3 Explicitly out of scope for the pilot

Spare-parts inventory management, vendor/purchase-order workflow, ERP/SAP integration, PLC or machine-sensor data ingestion, energy monitoring, labour/attendance. Each is a valid Phase-2 conversation. Trying to do them in the pilot will sink it.

---

## 2. What already exists, and what it is missing

Your current prototype (`greenlam-maintenance-tracker.jsx`) is a genuinely good functional spec. Keep it — it is the clickable requirements document. But understand what it is not:

**What it gets right and should carry forward:**
- The 7-stage ticket lifecycle (Raised → Acknowledged → Material check → Repair → Resolved → Root cause → Verified & closed)
- Separating *immediate correction* from *root cause* from *preventive action* — this is proper why-why discipline and most trackers skip it
- Auto-flagging repeat failures on the same machine + category
- Auto-flagging preventive-maintenance candidates at 3+ breakdowns
- The Excel column headers, which appear to be copied from the plant's real register — **preserve these exactly**, including quirks, so leadership doesn't have to change how they read the file
- Section and machine master lists (Press-1..5, IMP-1..12, Sanding-1..4, etc.)

**What blocks it from being a real system:**

| Gap | Why it matters |
|-----|----------------|
| `window.storage` is Claude-artifact-only | Data does not exist outside claude.ai. There is no database. |
| Hardcoded passcode `PLANTHEAD` in the source | Anyone who views source has leadership access. Not defensible to an IT audit. |
| No user accounts | You cannot tell who acknowledged, who repaired, who verified. Accountability is the whole point of a maintenance system. |
| No offline capability | Dead in a press hall with no signal. |
| No shift dimension | A plant running 3 shifts cannot analyse anything meaningfully without it. |
| Numbers only, no charts | "Performance graphs" was an explicit requirement. |
| Export is a manual button press | "No manual intervention" was an explicit requirement. |
| No downtime-cost model | Leadership approves budget in rupees, not minutes. |
| No planned-vs-breakdown distinction | Planned maintenance downtime is not a failure and must not pollute MTBF. |

---

## 3. Architecture

### 3.1 System diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         SHOP FLOOR                               │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐      │
│  │ Operator phone │  │ Technician     │  │ Shared tablet  │      │
│  │ (raise ticket) │  │ phone (close)  │  │ (kiosk mode)   │      │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘      │
│          │ writes to LOCAL SQLite first, always  │               │
│          └───────────────────┴───────────────────┘               │
│                              │ sync queue (outbox)               │
└──────────────────────────────┼───────────────────────────────────┘
                               │ HTTPS, batched, retry w/ backoff
                               ▼
              ┌────────────────────────────────────┐
              │   API — FastAPI on Render (free)   │
              │   /auth  /sync  /kpi  /export      │
              │   Cold start 30–60s → never on     │
              │   the operator's critical path     │
              └──────┬──────────────────┬──────────┘
                     │                  │
         ┌───────────▼──────┐   ┌───────▼─────────────────┐
         │ Neon PostgreSQL  │   │ Object storage (R2 /    │
         │ (free, permanent)│   │ Supabase) — photos +    │
         │ event-sourced    │   │ nightly .xlsx archive   │
         └───────────┬──────┘   └───────┬─────────────────┘
                     │                  │
   ┌─────────────────▼──────┐   ┌───────▼──────────────────┐
   │ Web dashboard          │   │ Nightly job (GitHub      │
   │ React + Vite + Recharts│   │ Actions cron, 00:15 IST) │
   │ Render static (free)   │   │ → builds workbook        │
   │ Leadership, desktop    │   │ → emails leadership      │
   └────────────────────────┘   │ → alerts on failure      │
                                └──────────────────────────┘
```

### 3.2 Why offline-first changes everything

This is not a feature you bolt on. It dictates the data model.

**The rule:** the phone writes to its own SQLite database and returns to the user immediately. Sync happens in the background. The operator never sees a spinner waiting for Render to wake up.

**The mechanism — event sourcing.** Instead of the app sending "set ticket X to stage 3", it sends immutable events:

```
{ event_id: <uuid-v7>, ticket_id: <uuid-v7>, type: "ACKNOWLEDGED",
  actor_id: 42, device_id: "tab-press-01",
  client_ts: "2026-08-24T09:14:03+05:30", payload: {...} }
```

The server stores every event append-only and derives current ticket state by replaying them. This buys you four things at once:

1. **Conflict-free sync.** Two devices acting on the same ticket offline produce two events, not two conflicting writes. Both survive.
2. **Idempotency.** `event_id` is unique-constrained, so a retried upload is a no-op. Flaky networks stop being a correctness problem.
3. **A real audit trail.** "Who acknowledged this at 2 AM and why did it take 40 minutes?" is answerable. This is what turns the tool from a logbook into a management system.
4. **Accurate KPIs for free.** MTTR, MTTA, and downtime all fall directly out of event timestamps.

**Clock skew:** phones on the floor will have wrong clocks. Store both `client_ts` (what the user experienced) and `server_received_at` (authoritative ordering). Use `client_ts` for display, server order for state resolution. Reject client timestamps more than 24 h in the future.

**Sync protocol:**

```
POST /sync
  { device_id, last_pulled_at, events: [ ...unsynced local events ] }
→ { accepted: [event_ids], rejected: [{id, reason}],
    changes: { tickets: [...], production: [...], masters: [...] },
    server_time }
```

Triggers: app foreground, network regained, every 5 min while active, manual pull-to-refresh, and immediately after any write attempt.

**Conflict rules (deterministic, server-side):**
- Stage can only move forward, except an explicit `REOPENED` event
- Duplicate stage transitions: first-by-server-order wins, second is recorded as a no-op event (still visible in the audit trail)
- Text fields (root cause, etc.): last-write-wins by `server_received_at`, with prior value retained in event history

### 3.3 Handling Render's cold start

Free Render services sleep after 15 minutes idle. Three mitigations, used together:

1. **Offline-first means it doesn't block anyone.** This is the real answer.
2. **Keep-alive ping** from the same GitHub Actions workflow (or cron-job.org) every 10 min *during plant operating hours only*. If the plant runs 24/7 you will consume ~744 of your 750 monthly instance-hours — cutting too close. Ping during 06:00–23:00 IST only (~510 hrs/month) and let it sleep overnight; the nightly export tolerates a cold start.
3. **Client-side timeout of 90 s** with exponential backoff, so a cold start never surfaces as an error.

---

## 4. Tech stack

### 4.1 The PWA-vs-native decision (please read before choosing)

You asked for iOS and Android apps. Consider shipping the **pilot** as an installable PWA instead, then going native for the plant-wide rollout.

| | PWA | Native (Expo / React Native) |
|---|---|---|
| Cost to distribute | ₹0 | Apple Developer ₹8,900/yr **registered to Greenlam** + Google Play ₹2,100 one-time |
| Time to first install | Same day — send a URL, "Add to Home Screen" | 2–4 weeks including account setup, review, MDM |
| Updates | Instant, everyone on latest | Store review, or Expo OTA for JS-only changes |
| Offline | Service worker + IndexedDB — genuinely good in 2026 | SQLite — better |
| Camera / QR scan | Works | Better |
| Push notifications | Works on Android; works on iOS 16.4+ **only after Add-to-Home-Screen** | Reliable everywhere |
| Company IT approval | Just a website | Needs MDM policy, device enrolment discussion |
| Codebase | Shared with dashboard | Separate app, shared API |

**DECIDED: PWA for the pilot, Expo native from plant-wide rollout.** The pilot's job is to prove the *process change* works, not to prove you can ship to the App Store. Getting an Apple Developer account approved under a company legal entity routinely takes 2–4 weeks and needs a D-U-N-S number — that alone would eat a third of the pilot window.

This choice also hedges the open IT-hosting question (Section 12.1 Q12). A PWA is just a website: if Greenlam IT refuses external cloud hosting, the same build is served from a plant intranet server with no code changes. A native app pointed at a blocked API is dead.

**PWA implementation notes — the parts that bite:**

- **Stack:** Vite + React + TypeScript + Tailwind, `vite-plugin-pwa` (Workbox) for the service worker, **Dexie.js** over IndexedDB for local storage.
- **One codebase, two surfaces.** Floor app and dashboard ship as the same PWA with role-based routes (`/floor/*`, `/board/*`). This collapses what was two phases into one and means the KPI logic exists in exactly one place.
- **iOS storage eviction — the critical gotcha.** Safari evicts script-writable storage (IndexedDB included) after ~7 days of no use for *non-installed* sites. Installed home-screen PWAs are exempt. So "Add to Home Screen" is not a nice-to-have on iPhone — it is a **mandatory install step in training**, or an operator who's off for a week loses their unsynced queue. Build a first-run screen that detects iOS Safari and won't let the user past it until the app is installed.
- **No Background Sync API on iOS.** Sync fires on app foreground, on `online` event, and on a timer while open. Never assume it runs in the background.
- **Push on iOS** works only on iOS 16.4+ and only once installed to the home screen. Treat Telegram/WhatsApp group alerts as the primary channel for the pilot (Section 4.3) and push as a bonus.
- **Service worker caching:** app shell precached, API calls network-first with a short timeout falling back to local Dexie data. Never let a sleeping Render service produce a blank screen.
- **Port path to Expo later:** keep all business logic (state machine, KPI calculations, sync reducer, validation) in a framework-free `packages/core` directory with zero DOM dependencies. The Expo port then reuses it verbatim and only re-implements the UI layer.

### 4.2 Stack table

| Layer | Choice | Why |
|-------|--------|-----|
| Floor app + dashboard | **One PWA: Vite + React + TypeScript + Tailwind + `vite-plugin-pwa`**, role-based routes. Expo + NativeWind from plant-wide rollout. | Decided — see 4.1. Installs from a URL on both iOS and Android, ₹0 to distribute, survives an on-prem IT mandate, and shares KPI logic with the dashboard. |
| Shared logic | `packages/core` — pure TypeScript, no DOM, no React | The state machine, sync reducer, and KPI math live here so the later Expo port reuses them untouched |
| Local DB | **Dexie.js over IndexedDB** (PWA) → `expo-sqlite` (native later) | Real indexed queries offline. Dexie's schema-versioned migrations matter once you're shipping updates to live devices. |
| Client state / sync | TanStack Query + a hand-rolled outbox table | Full control over the sync semantics; sync libraries hide the conflict behaviour you need to reason about |
| API | **Python 3.12 + FastAPI + SQLModel + Alembic** | Excel generation with `pandas`/`openpyxl` is far better in Python than in JS, KPI aggregation is natural there, and it matches your own strongest language. *Alternative:* Node + Fastify + Drizzle if you'd rather have one language across the whole stack. |
| Database | **Neon PostgreSQL free tier** | Permanent, no card, scale-to-zero, no 30-day deletion. Render's free Postgres is disqualified. |
| API hosting | **Render free web service** | Per your constraint. 512 MB RAM / 0.1 CPU is enough for a single-unit pilot. |
| Dashboard | React + Vite + **Recharts** + Tailwind, on Render Static Sites (free, unlimited) | Recharts for line/bar/Pareto; it's the least fussy option for this kind of KPI board |
| Object storage | Cloudflare R2 free (10 GB) or Supabase Storage free (1 GB) | Photos + nightly workbook archive. Render free has no persistent disk. |
| Scheduler | **GitHub Actions cron** | Free, versioned, and it emails you when it fails |
| Email delivery | Resend free tier (3,000/month) | Nightly workbook to the leadership distribution list |
| Auth | Employee ID + 6-digit PIN → JWT (30-day refresh) | Operators may not have work email addresses. Long refresh window is required for offline operation. |
| Error tracking | Sentry free tier | You will not be standing on the floor when it breaks |

### 4.3 Notifications — a note on Indian plant reality

Push notifications are technically correct and frequently ignored. In most Indian manufacturing units, the maintenance team already lives in a WhatsApp group.

- **Free path:** a Telegram bot posting to a maintenance group. Zero cost, zero approval, works immediately.
- **Correct path:** WhatsApp Business API via MSG91 or Gupshup — paid per conversation, needs template approval, but it lands where people actually look.
- **Pilot recommendation:** in-app push (free via Expo) **plus** a Telegram or WhatsApp group post for Critical/High priority tickets only. Do not notify on everything or people will mute it in week one.

---

## 5. Data model

### 5.1 Core tables

```sql
-- ============ ORGANISATION (multi-tenant from day one) ============
plants          (id, name, city, state, timezone, created_at)
units           (id, plant_id, name, description)          -- the pilot is ONE row here
sections        (id, plant_id, unit_id, name, sort_order)  -- Press, Impregnation, Sanding...
machines        (id, plant_id, unit_id, section_id, code, name,
                 make, model, install_date, criticality,   -- A/B/C
                 hourly_downtime_cost, qr_token, is_active)
shifts          (id, plant_id, name, start_time, end_time) -- A / B / C

-- ============ PEOPLE ============
users           (id, plant_id, employee_id, name, phone, pin_hash,
                 role, section_id, is_active, created_at)
                 -- role: operator | technician | supervisor | plant_head | admin
devices         (id, user_id, device_uid, platform, last_sync_at, push_token)

-- ============ MAINTENANCE ============
tickets         (id UUID, plant_id, unit_id, section_id, machine_id,
                 raised_by, category, priority, description, location,
                 downtime_type,           -- breakdown | planned | changeover | no_downtime
                 current_stage, shift_id,
                 raised_at, acked_at, material_at, repair_at,
                 resolved_at, diagnosis_at, closed_at,
                 immediate_correction, root_cause, preventive_action,
                 sheets_after_sanding, rating, reopen_count,
                 created_at, updated_at)

ticket_events   (event_id UUID PK, ticket_id, plant_id, type, actor_id,
                 device_id, payload JSONB,
                 client_ts, server_received_at)            -- APPEND ONLY. Never update.

ticket_materials(id, ticket_id, source,                    -- store | purchase
                 name, qty, unit, cost, bin_location, vendor, po_number)

attachments     (id, ticket_id, event_id, storage_key,
                 mime_type, size_bytes, uploaded_at)

-- ============ PRODUCTION ============
production_logs (id UUID, plant_id, unit_id, section_id, machine_id,
                 log_date, shift_id, size, texture, thickness,
                 produced_qty, rejected_qty, reject_reason,
                 target_qty, logged_by, created_at, updated_at)

-- ============ PREVENTIVE MAINTENANCE (Phase 6) ============
pm_schedules    (id, machine_id, frequency_days, task_description,
                 last_done_at, next_due_at, assigned_to, is_active)
pm_completions  (id, pm_schedule_id, completed_by, completed_at, notes)

-- ============ OPS ============
export_runs     (id, run_date, status, row_counts JSONB,
                 storage_key, email_sent_at, error_message, duration_ms)
audit_log       (id, plant_id, actor_id, action, entity, entity_id,
                 before JSONB, after JSONB, created_at)
```

### 5.2 Design notes

- **`downtime_type` is not optional.** Planned maintenance and changeovers are downtime but not failures. Mixing them into MTBF makes the metric meaningless, and a plant head will spot that within a week.
- **`hourly_downtime_cost` on the machine** is what converts "47 hours of downtime" into "₹X lakh". Get this number from the finance or production head even if it's rough — a defensible estimate beats no number.
- **`criticality` (A/B/C)** lets the dashboard sort attention properly. A 3-hour stop on Press-2 is not equivalent to 3 hours on a spare compressor.
- **UUIDv7 for all client-created IDs.** Time-sortable, generated offline, no server round-trip needed. The current prototype's `MT-` + random 5 chars will collide.
- **Keep the human-readable ticket number too** — `PR-2608-0142` (section–yearmonth–sequence). Nobody says a UUID out loud on a factory floor. Generate it server-side on first sync.
- **`sheets_after_sanding`** from your prototype is clearly a Greenlam-specific quality field. Confirm exactly which sections it applies to and whether other sections have equivalent fields.

---

## 6. KPIs and the dashboard

### 6.1 Metrics to compute

Your prototype has four. A plant head expects these:

**Maintenance — reliability**

| Metric | Formula | Why it matters |
|--------|---------|----------------|
| **MTTR** — Mean Time To Repair | Σ(resolved − raised) / count | The headline maintenance-efficiency number |
| **MTTA** — Mean Time To Acknowledge | Σ(acked − raised) / count | Isolates *response* delay from *repair* delay. Usually where the easy wins are. |
| **MTBF** — Mean Time Between Failures | Operating hours / failure count, per machine | Reliability trend. Excludes planned downtime. |
| **Availability %** | (Scheduled − Downtime) / Scheduled × 100 | The number that goes into OEE |
| **Downtime hours** | By machine / section / category / shift | The raw currency of the whole system |
| **Downtime cost** | Downtime hrs × machine hourly cost | The number that gets budget approved |
| **First-time-fix rate** | Tickets closed without reopen / total closed | Repair quality |
| **Reopen rate** | Reopened / total closed | The honest counter-metric to a good MTTR |
| **Repeat-failure count** | Same machine + category within 30 days | Already in your prototype — keep it |
| **PM compliance %** | PM tasks done on time / scheduled | Phase 6 |
| **Backlog ageing** | Open tickets bucketed <24h / 1–3d / 3–7d / >7d | Stops old tickets quietly disappearing |

**Production — quality and output**

| Metric | Formula |
|--------|---------|
| Output vs target | Σ produced / Σ target, by day/shift/machine |
| Reject rate % | rejected / (produced + rejected) × 100 |
| Rejection Pareto | rejected qty by reason, descending, with cumulative % |
| Reject rate by texture / size / shift / machine | Segmented — this is where root causes hide |
| Cost of rejection | rejected qty × cost per sheet |
| Downtime-adjusted throughput | produced per available hour |

**The one derived metric worth building:** correlate breakdown events against reject-rate spikes on the same machine within ±48 h. If Sanding-2's reject rate climbs before it fails, you have a leading indicator — and that finding alone will justify the entire project to leadership.

### 6.2 Dashboard structure

Design brief for the dashboard: **glanceable in 10 seconds from across a room, drillable in 3 clicks.** A plant head opens this on a desktop between meetings, or it runs permanently on a wall-mounted screen in the maintenance office.

```
┌────────────────────────────────────────────────────────────────┐
│  GREENLAM · [Unit ▾]  [Aug 2026 ▾]  [All sections ▾]  ⬇ Excel  │
├────────────────────────────────────────────────────────────────┤
│  ROW 1 — HEADLINE (4 tiles, each with sparkline + Δ vs last mo) │
│  ┌──────────┬──────────┬──────────┬──────────┐                 │
│  │ Downtime │  MTTR    │ Reject % │ Open     │                 │
│  │ 47.2 hrs │ 2h 14m   │  3.4%    │ tickets  │                 │
│  │ ▼12% ✓   │ ▲8%  ✗   │ ▼0.6% ✓  │   7      │                 │
│  └──────────┴──────────┴──────────┴──────────┘                 │
│  Sub-line: estimated downtime cost this month — ₹X.XX lakh     │
├────────────────────────────────────────────────────────────────┤
│  ROW 2                                                         │
│  ┌────────────────────────┬─────────────────────────────┐      │
│  │ Downtime trend         │ Downtime Pareto by cause    │      │
│  │ (stacked area, daily,  │ (bars desc + cumulative %   │      │
│  │  by category, 90 days) │  line, 80% cutoff marked)   │      │
│  └────────────────────────┴─────────────────────────────┘      │
├────────────────────────────────────────────────────────────────┤
│  ROW 3                                                         │
│  ┌────────────────────────┬─────────────────────────────┐      │
│  │ Machine leaderboard    │ Reject rate trend + Pareto  │      │
│  │ (worst 10 by downtime, │  by reason                  │      │
│  │  hrs / count / MTBF)   │                             │      │
│  └────────────────────────┴─────────────────────────────┘      │
├────────────────────────────────────────────────────────────────┤
│  ROW 4 — ACTION QUEUE (this is what makes it a tool, not a     │
│  report). Each row is clickable and assignable.                │
│  ⚠ PM overdue: Press-4, 5 breakdowns, last 21 Aug              │
│  ⚠ Ageing: MT-8823 open 6 days, no acknowledgement             │
│  ⚠ Reopened twice: IMP-7, electrical                           │
└────────────────────────────────────────────────────────────────┘
```

**Design direction:** Greenlam's identity is a deep forest green with a spectrum-fan peacock. Use the deep green (`#1F5F3F` in your prototype is close) as the single structural colour and let the **status spectrum** carry the peacock reference — a controlled 4-step scale from green through amber to rust for healthy → critical. Do not scatter the full rainbow across charts; one restrained echo of the logo reads as intentional, seven colours read as clip-art. Keep the paper-white background from your prototype; it photographs and projects well in a lit office. Set numerals in a tabular-figure face so columns align — on a metrics board that single choice does more for legibility than any chart styling.

**Colour rule for KPIs:** green means *improving*, not *high*. A rising MTTR is bad. Get the direction-of-good right per metric or the board will actively mislead.

---

## 7. The daily Excel automation

This was an explicit requirement and it is the piece most likely to fail silently. Design it defensively.

### 7.1 Flow

```
GitHub Actions  cron: "45 18 * * *"   (= 00:15 IST next day)
   │
   ├─ 1. Wake ping to Render, wait for 200 (retry 5× / 30 s apart)
   ├─ 2. POST /internal/exports/daily   header: X-Export-Token
   │      │
   │      ├─ Query all tickets, events, production, masters
   │      ├─ Build workbook with openpyxl/pandas
   │      ├─ Upload .xlsx to R2 → greenlam/exports/2026-08-24.xlsx
   │      ├─ Email to leadership DL via Resend (attach if <10 MB, else link)
   │      ├─ INSERT into export_runs (status, row_counts, duration)
   │      └─ Return 200 + summary JSON
   │
   ├─ 3. Assert row counts > 0 and status == success
   └─ 4. On any failure → workflow fails → GitHub emails you
         + Telegram/Slack alert to the maintenance group
```

### 7.2 Workbook structure

Sheet order matters — leadership opens sheet 1 and often stops there.

| # | Sheet | Contents |
|---|-------|----------|
| 1 | **KPI Summary** | Current month vs previous: downtime hrs, MTTR, MTTA, MTBF, availability, reject %, downtime cost. Section-wise block below. |
| 2 | **BD Tracker** | **Exact column headers from the existing plant register**, including the current quirks. Do not "clean up" these headers — leadership's own downstream sheets and pivot tables may reference them. |
| 3 | **Production** | Date, shift, size, texture, produced, rejected, reject reason, logged by |
| 4 | **Machine-wise Summary** | Per machine: breakdowns, downtime hrs, MTTR, MTBF, last failure, PM flag |
| 5 | **Section-wise Summary** | Rolled up per section, month over month |
| 6 | **Open Tickets** | Live snapshot with ageing buckets |
| 7 | **Event Log** | Full append-only audit trail (technical, but this is the evidence layer) |

**Naming:** `Greenlam_<Unit>_Tracker_YYYY-MM-DD.xlsx`, plus a stable `Greenlam_<Unit>_Tracker_LATEST.xlsx` overwritten daily — so anyone with a Power Query or pivot pointed at that path never has to update their link.

### 7.3 Non-negotiables

1. **Idempotent.** Re-running for the same date produces the same file. No duplicate rows.
2. **Full history every night, not a delta.** The file is a complete snapshot, so a missed night is self-healing.
3. **Alert on failure, always.** A daily export that silently stopped three weeks ago is worse than no export — people trust it and act on stale data.
4. **Manual "Export now" button** on the dashboard, using the same code path. If the two paths differ, they will drift.
5. **Retention:** keep 90 days of dated files in object storage, then monthly snapshots only.

### 7.4 Worth asking about

If Greenlam runs Microsoft 365, writing the nightly file into a **SharePoint / OneDrive folder** (via Microsoft Graph) is dramatically better than email — leadership just opens the file where they already keep everything, and it version-histories automatically. Same for Google Drive if they're on Workspace. Confirm which the company uses before building the email path.

---

## 8. Phased plan

**Baseline: solo, full-time, PWA-first, working with Claude Code.** Single codebase for floor app and dashboard, which removes roughly two weeks versus the native plan.

| Phase | Weeks | Cumulative | Deliverable | Definition of done |
|-------|-------|-----------|-------------|--------------------|
| **0 — Discovery** | 1 | W1 | Filled Section 12 questionnaire, verified machine master list, confirmed Excel column headers, downtime cost per machine, pilot unit chosen, 2 named champion users, IT hosting answer | Signed off by plant head. **Do not skip this phase.** |
| **1 — Foundation** | 1 | W2 | Postgres schema + migrations, FastAPI on Render, auth + roles, masters CRUD, seeded machine list, Docker Compose | You can log in as each role and see the right things |
| **2 — Sync engine** | 1.5 | W3.5 | `/sync` endpoint, event sourcing, idempotency, conflict rules, `packages/core` state machine, integration tests | Test suite passes with 3 simulated devices going offline, conflicting, and reconciling |
| **3 — Floor PWA: tickets** | 1.5 | W5 | Installable PWA, service worker, Dexie outbox, raise ticket, 7-stage workflow, photo attach, QR scan | An operator raises and a technician closes a ticket in airplane mode; both reconcile on reconnect. Installs to home screen on a real iPhone and a real Android. |
| **4 — Production logging** | 0.5 | W5.5 | Production entry with shift + target, offline-capable | Same offline test passes |
| **5 — Dashboard** | 1.5 | W7 | Same PWA, `/board/*` routes. All KPIs from §6.1, all charts from §6.2, filters, drill-through | Plant head answers "which machine cost us the most last month" in under 30 s |
| **6 — Excel automation** | 1 | W8 | Nightly GitHub Actions job, all 7 sheets, R2 upload, email, failure alerting, manual trigger | Runs unattended 7 consecutive nights including one deliberately induced failure that alerts correctly |
| **7 — Hardening** | 1 | W9 | Alerts, PM scheduler, backlog ageing, Sentry, nightly `pg_dump`, Hindi/Hinglish labels, training material | A colleague can deploy it from your README without asking you anything |
| **8 — Pilot** | 4–6 | W13–15 | Live in one unit. Daily standup week 1, weekly after | ≥80% of that unit's breakdowns logged in-system vs the paper register — measure this weekly, it is your real KPI |
| **9 — Plant-wide** | 4–6 | — | All sections, migrate to paid infra, Expo native build, RBAC hardening | — |
| **10 — Multi-plant** | 8+ | — | Tenant isolation testing, per-plant config, cross-plant benchmarking | — |

**~9 weeks from start to a pilot-ready system, ~15 weeks to pilot results.** Protect two things: don't compress Phase 0 (it has no code and decides everything), and don't let Phase 8 start before Phase 7's training material exists.

Being solo full-time is an advantage on build speed and a liability on bus factor and on blind spots. Two habits that pay for themselves: demo to a floor person at the end of every phase, not at the end of the project; and write the runbook as you go, because the person who inherits this will not be you.

**Critical-path warning:** Phase 0 and Phase 8 are the ones that decide whether this project succeeds, and they are the two with no code in them. A technically perfect system that operators route around — because raising a ticket takes 90 seconds and shouting across the floor takes 5 — has failed. Sit on the floor for a full shift in Phase 0.

---

## 9. Scaling and cost

| Stage | Infrastructure | Monthly cost |
|-------|---------------|--------------|
| Pilot (1 unit, ~20 users) | Render free + Neon free + R2 free + GitHub Actions + Resend free | **₹0** |
| Plant-wide (~150 users) | Render Starter $7 + Neon Launch $19 + R2 + Sentry | **~₹2,500–3,500** |
| Multi-plant (5 plants) | Render Pro $25 flat + Neon Scale + R2 + WhatsApp API + monitoring | **~₹12,000–25,000** |

**Migration triggers — move off free tier when any of these hit:**
- Neon free storage passes 400 MB (of 0.5 GB)
- Render instance-hours pass 700/month (of 750)
- More than ~30 concurrent users
- The moment leadership makes a real operational decision from this data — at that point the 30–60 s cold start and the absent backups stop being acceptable trade-offs

**What multi-tenancy requires beyond `plant_id` columns:**
- Row-level security policies, or a mandatory `plant_id` filter enforced in a single query layer that every endpoint goes through
- Per-plant machine masters, sections, shifts, and reject reasons — none of these are the same across Greenlam plants
- A cross-plant benchmarking dashboard for corporate (this becomes the real selling point at national rollout)
- Data residency confirmation with Greenlam IT — some manufacturers require India-region hosting

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Operators don't adopt; keep using paper | **High** | Fatal | ≤30 s to raise a ticket. QR sticker on every machine. Hindi/Hinglish UI. Pick 2 respected floor champions in Phase 0. Track adoption % weekly as a first-class KPI. |
| Free-tier data loss | Medium | Severe | Neon over Render Postgres. Nightly `pg_dump` to R2 as a second job. The daily Excel is itself a third backup. |
| No Wi-Fi in press hall | High | High | Offline-first (already core). Test in the actual physical location during Phase 0, not from the office. |
| Apple Developer account delays | High | Medium | PWA for pilot. Start company account paperwork in week 1 regardless. |
| Machine master list is wrong or incomplete | High | Medium | Verify physically in Phase 0. Allow free-text machine entry with an admin "promote to master" flow. |
| Garbage root-cause entries ("machine stopped") | High | High | Guided why-why with 3 prompted levels, not one free-text box. Supervisor must verify before close. Show the technician their own past entries for the same machine. |
| Leadership wants a feature mid-pilot | Certain | Medium | Written scope freeze after Phase 0. Maintain a visible Phase-2 backlog so ideas are captured, not argued about. |
| You are the only person who understands it | High | High for Greenlam | Write the README and a runbook as you go. Add `/health` and `/metrics`. Assume handover. |
| IT rejects external cloud hosting | Medium | High | **Ask in Phase 0.** Many Indian manufacturers require on-prem. Docker Compose everything from day one so an on-prem move is a deployment change, not a rewrite. |

---

## 11. Claude Code starter prompt

Save as `PROJECT_BRIEF.md` in an empty repo, open Claude Code there, and paste the block below as your first message.

````markdown
# Project: Greenlam Maintenance & Production Intelligence System

Read `PROJECT_BRIEF.md` (this build spec) fully before writing any code.

## What we're building
An offline-first maintenance breakdown and production tracking system for a
Greenlam Laminates plant. Piloting in one unit, scaling to the full plant,
then to other plants in India.

Three surfaces:
1. A floor app (phones/tablets) — operators raise breakdowns, technicians
   work them through a 7-stage lifecycle, everyone logs production
2. A web dashboard — plant leadership sees KPIs and trend graphs
3. A nightly automated job that regenerates the complete master Excel
   workbook and emails it to leadership

## Hard constraints — do not design around these, design WITH them
- Backend API runs on Render's FREE tier: 512 MB RAM, 0.1 CPU, sleeps after
  15 min idle with a 30–60 s cold start, 750 instance-hours/month
- Database is Neon free Postgres (0.5 GB). NOT Render Postgres — Render's
  free database is deleted after 30 days
- Render free tier has NO cron. The nightly job is triggered by GitHub Actions
- Shop floor Wi-Fi is unreliable. The app MUST work fully offline and sync in
  the background. The user never waits on the network for any write
- The daily Excel export must run with zero manual intervention AND alert
  loudly on failure
- Users are Indian factory-floor staff. Some have limited English. UI must be
  simple, large-touch-target, and support Hindi/Hinglish labels

## Architecture decisions already made — follow these
- **Event sourcing** for tickets. Clients emit immutable events with
  client-generated UUIDv7 event_ids. Server stores append-only in
  `ticket_events` and derives ticket state by replay. This gives us
  conflict-free offline sync, idempotent retries, and a real audit trail.
- **`plant_id` and `unit_id` on EVERY table** from the first migration, even
  though the pilot is a single unit. Non-negotiable — this is the scaling path.
- Stack: FastAPI + SQLModel + Alembic + Neon Postgres on the backend.
  React + Vite + Tailwind + Recharts for the dashboard. Expo + React Native +
  NativeWind + expo-sqlite for the floor app (Phase 3 — confirm PWA-vs-native
  with me before starting it).
- Auth: employee ID + 6-digit PIN → JWT with a 30-day refresh window.
  Operators do not reliably have work email addresses.
- Roles: operator, technician, supervisor, plant_head, admin.

## Reference implementation
`reference/greenlam-maintenance-tracker.jsx` is a working prototype built as a
Claude artifact. Treat it as the functional spec — the 7-stage lifecycle, field
names, section/machine master lists, and especially the Excel column headers
are all taken from the plant's real process. Preserve the Excel headers exactly,
including their existing quirks. Do NOT carry over its `window.storage`
persistence or its hardcoded `PLANTHEAD` passcode.

## How I want you to work
- Follow `/mnt/skills/user/karpathy-guidelines` if available: smallest change
  that works, no speculative abstraction, surface assumptions explicitly
- Build in the phase order in the spec. Stop at the end of each phase, show me
  what runs, and wait for my go-ahead
- Write tests for the sync engine specifically — simulate 3 devices going
  offline, generating conflicting events, and reconciling. That's where the
  bugs will be
- Every endpoint gets an OpenAPI docstring. Keep the README deployable-by-
  someone-else from day one
- When you hit a decision the spec doesn't cover, ask me. Don't guess and
  don't invent plant-specific values (machine names, costs, thresholds) —
  those come from me

## Start here — Phase 1 only
1. Scaffold the repo: `api/`, `dashboard/`, `app/`, `docs/`, `.github/workflows/`
2. Write the complete Postgres schema and first Alembic migration from
   Section 5 of the spec
3. FastAPI skeleton: health check, auth (PIN login, JWT issue/refresh),
   role middleware, masters CRUD (plants, units, sections, machines, shifts,
   users)
4. A seed script that loads the machine master list from the reference file
5. `render.yaml` + `Dockerfile` + `docker-compose.yml` (compose matters —
   the company may require on-prem later)
6. README with local setup

Then stop and show me. Do not start Phase 2 until I say so.
````

---

## 12. Open questions

### 12.1 For Greenlam (take these to your Phase 0 meeting)

**Scope and pilot**
1. Which unit and section is the pilot? How many machines and how many people?
2. Does the plant run 1, 2, or 3 shifts? What are the shift timings?
3. Roughly how many breakdowns per week does that unit currently log?
4. Who is the executive sponsor, and what specific number do they want to see improve? (This defines success.)

**Data and process**
5. Can I get the actual Excel register currently in use, so column headers match exactly?
6. Is the machine list in the prototype complete and correct? Do machines have asset codes/tags already?
7. What is the approximate cost of one hour of downtime, per machine or per section?
8. Do they distinguish planned maintenance downtime from breakdown downtime today? If not, they will need to start.
9. What is `sheets_after_sanding` used for, and which sections does it apply to?
10. What is the production target per shift, and is it per machine or per line?
11. Are there existing PM schedules on paper that should be digitised?

**IT and infrastructure**
12. **Does Greenlam IT permit external cloud hosting, or is on-prem/India-region required?** This is the highest-impact question on the list.
13. Is the company on Microsoft 365 or Google Workspace? (Decides where the nightly Excel lands.)
14. Is there usable Wi-Fi in the production halls? Any dead zones?
15. Company-issued phones or personal devices? Is there an MDM in place?
16. Does the company have an Apple Developer account, or would one need to be created?

**People**
17. Who are the two floor people most likely to champion this? Get them into Phase 0.
18. What language do maintenance entries get written in today — English, Hindi, or mixed?
19. Who currently maintains the Excel register, and how do they feel about being replaced by this? (Handle this one carefully. That person is either your best ally or your biggest obstacle.)

### 12.2 For you, before I write any more

I've listed the three blocking ones as buttons below. The rest, when you have a moment:

- Is this a college/internship project with an academic deliverable attached, or purely a company assignment? (Changes how much documentation the spec needs.)
- What's your realistic time budget per week, and is there a hard deadline?
- Are you building alone, or is there a dev team or other interns?
- Is there any budget at all, or is ₹0 a genuine hard limit through the pilot?
- Do you have physical access to the plant floor, and can you get a shift's worth of observation time?
