# Greenlam Maintenance & Production Intelligence System

Offline-first maintenance breakdown and production tracking for a Greenlam
Laminates plant. One PWA serves two surfaces — a floor app for operators and
technicians, and a dashboard for plant leadership — against a FastAPI backend
and plain PostgreSQL.

**Status: the maintenance and production system is working end to end.**

Schema and migrations, PIN auth, a ten-role capability model with explicit
scopes, masters CRUD, the full ticket lifecycle, an exception feed, shift
handover, guided why-why with quality scoring, derived escalation, the complete
§6.1 KPI set, four charts, individual performance under the §4.1 guardrails,
production logging with reject Pareto and segment analysis, and 90 days of
synthetic history so all of it has something to show.

Still ahead: offline sync (Phase 2), QR scanning (Phase 3), the nightly Excel
job (Phase 6), and Hindi strings (Phase 7).

Specs live in `docs/`. Read `CLAUDE.md` first — it is the short version of the
constraints, and `docs/MODULE-ADDENDUM-v1.1.md` supersedes the base spec where
they disagree.

---

## Run it locally

Two ways. Docker needs nothing installed; the native path is faster if you
already have Postgres.

### With Docker

```bash
cp .env.example .env
docker compose up
```

Then open <http://localhost:5173>. The API is proxied at `/api` on the same
origin, and its docs are at <http://localhost:5173/api/docs>.

Seed the masters once the stack is up:

```bash
docker compose exec api python -m app.seed
```

### Without Docker

Needs Python 3.12+, Node 20+, and a running PostgreSQL.

```bash
# 1. Database
createdb greenlam && createdb greenlam_test

# 2. API
cd api
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://$USER@localhost:5432/greenlam"
export JWT_SECRET="$(openssl rand -base64 48)"
export PIN_PEPPER="$(openssl rand -base64 48)"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --port 8000

# 3. PWA, in a second terminal, from the repo root
npm install
npm run dev
```

> **`PIN_PEPPER` must be identical between seeding and serving.** It is mixed
> into every PIN hash, so changing it invalidates every PIN in the database.
> Treat it as permanent once real users exist. (If sign-in fails right after a
> reseed, this is almost always why.)

### Sign in

Development PINs only, one per tier of Greenlam's chain, so you can see each boundary for yourself.

| Employee ID | PIN    | Level     | Sees |
| ----------- | ------ | --------- | ---- |
| `EMP002`    | 573014 | dashboard | Everything — **start here** |
| `EMP001`    | 481920 | dashboard | Everything |
| `EMP003`    | 628351 | dashboard | Everything |
| `EMP004`    | 746092 | app       | Floor only — no dashboard tab |
| `EMP005`    | 819473 | app       | Floor only |
| `EMP006`    | 354871 | app       | Floor only |
| `EMP007`    | 913460 | app       | Floor only |

Worth doing once: sign in as `EMP004` and look at what is **missing**. No
Dashboard tab, no Import tab — access is not a setting somebody forgot to
switch on, the tabs are not there.

---

## Commands

```bash
docker compose up                  # api + postgres + PWA
npm run dev                        # PWA only (proxies /api to :8000)
npm run build                      # typecheck + production build
npm test                           # packages/core tests
npm run typecheck                  # all workspaces
npm run csp:hash                   # regenerate the CSP hash after editing index.html

cd api
.venv/bin/python -m alembic upgrade head    # migrate
.venv/bin/python -m app.seed --reset        # reseed from scratch
.venv/bin/python -m pytest                  # API tests (needs greenlam_test)
.venv/bin/python -m ruff check app tests    # lint
```

---

## Layout

```
api/                  FastAPI + SQLModel + Alembic
  app/models/         one module per domain area; every table has plant_id + unit_id
  app/routers/        health, auth, masters, tickets
  app/roles.py        capability model — the ENFORCING copy
  app/lifecycle.py    escalation, why-why scoring (mirrors core/tickets.ts)
  app/security.py     PIN peppering, argon2id, graduated lockout, JWT
  app/tenancy.py      the one query layer; scope grants, resolution gate
  alembic/versions/   0001 schema, 0002 hierarchy + scopes + why-why
dashboard/            the PWA — /floor/* and /board/*, role-routed
  src/components/floor/   answer-first: raise, work, why-why
  src/components/board/   control-room: tiles, section bars, exceptions
  src/theme/          three-way theme, persistence, DOM application
  src/i18n/           i18next; en.json only so far
packages/core/        pure TypeScript, shared with the later Expo port
  src/roles.ts        capability model — mirrors app/roles.py
  src/tickets.ts      escalation + quality scoring, used by both sides
  src/brand.ts        palette taken from the mark, with the contrast notes
docs/                 build spec, v1.1 addendum, Phase 0 pack, reference prototype
.github/workflows/    CI
```

---

## The decisions worth knowing about

### Everything is one origin

The static site rewrites `/api/*` to the API service (`render.yaml`), and Vite
proxies the same path in development. This is not cosmetic: it lets the refresh
token live in a **first-party httpOnly cookie**. Cross-site cookies are
effectively dead on iOS Safari, and a meaningful share of the floor is on
iPhone, so a split-origin deployment would have sessions dying silently on
exactly the devices hardest to debug.

Consequences:

- The refresh token is unreadable from JavaScript. An XSS bug can steal at most
  a 30-minute access token from the current tab, not a 30-day session.
- The access token is held in a module-scoped variable in `lib/api.ts` — never
  `localStorage`, so it does not survive a reload and cannot be read by another
  script.
- `SameSite=Lax` plus same-origin covers CSRF. The cookie is scoped to
  `/api/auth`, so it is not attached to ordinary API calls at all.

### A 6-digit PIN is only a million combinations

Operators do not reliably have work email, so the spec chose employee ID + PIN.
That puts the whole burden on three things (`app/security.py`):

1. **Pepper.** The PIN is HMAC'd with a server-side secret before hashing, so a
   stolen database cannot be cracked offline — the attacker is missing an input
   that never touches the database.
2. **argon2id**, memory-hard, tuned to fit Render's 512 MB.
3. **Graduated lockout.** Free for three attempts, then the delay doubles
   (1s, 2s, 4s…), hard lock at ten which a **supervisor clears in-app**.

The lockout is graduated rather than a flat "5 tries, 15 minutes" deliberately.
An operator locked out during a live breakdown goes back to shouting across the
floor, which is the adoption failure `docs/GREENLAM-TRACKER-BUILD-SPEC.md` §10
warns about. A supervisor is standing right there; a lockout that needs a
developer will be worked around within a week.

Login also runs a dummy hash for unknown employee IDs so response timing does
not reveal which IDs are real, and returns identical text for "no such user" and
"wrong PIN".

### Two access levels, and why the third axis is gone

`app` is everyone on the floor — report a breakdown, log production, log a
paper roll. `dashboard` is a named few who also get the board, the Excel
import, the master lists and user management.

This replaced a ten-role, three-axis model (capability × scope × resolution)
that let a shareholder sit at the top of the org chart and see the *least*
operational detail, and scoped a manager to one section. That was a good model
for a group with five plants and a board. It is the wrong shape for one plant
running one pilot, where the real question is only "does this person need the
dashboard, or just the app".

Three things worth knowing about how it was removed:

- **The scoping and redaction code is deleted, not disabled.** Access control
  that is half-removed is worse than none — the next person writes code
  believing a guard still guards.
- **`plant_id` on every row survived**, and so did `scope()`. That is the part
  that would have been expensive to retrofit; the day a second plant arrives,
  the filter is already in the right place and fails closed.
- **The individual-metrics rule did not relax.** A person sees their own
  figures; a dashboard holder sees the team, alphabetically, against the team
  average, never ranked. Two floor users still cannot see each other's numbers
  — `test_a_peer_gets_404_not_403` asserts it against two distinct accounts.

### The old org hierarchy — three axes, not one (superseded)

Greenlam's chain runs Shareholders → Board → MD & CEO → Whole-time Director and
CXO/SVP → Business heads → Plant/regional heads → Managers → Employees. A single
rank ordering cannot express it, because **a shareholder sits at the top of the
org chart and sees the least operational detail**. Seniority is not access.

So `packages/core/src/roles.ts` and `api/app/roles.py` model three things:

- **Capability** — what you may do. A plant head may close a ticket; a CXO may
  not, and does not want to.
- **Scope** — which rows you may see. Held in `user_scopes` (migration 0002),
  one grant per row, narrowing left to right: plant → unit → section. A business
  head holds one grant per plant; a manager holds one for their section. The old
  single `plant_id` on the user row could express neither.
- **Resolution** — how deep you may drill. `portfolio` (totals only),
  `summary` (sections and named machines), `operational` (tickets and events).

The two copies must agree; the Python one is the enforcing copy, and the
TypeScript one only hides controls a person cannot use.

**The rule that matters most**: individual technician metrics never travel
upward. `directReportMetrics` is false for every corporate tier, root-cause
quality is reported at team level, and the exception feed strips the ticket id,
the priority and all free text for anyone above the floor.
`api/tests/test_hierarchy.py` is that rule written as failing tests rather than
as a comment.

### Two surfaces, two designs

The floor and the board are different problems and the first version of this UI
treated them as one, which is why it read as a phone list stretched to desktop.

- **`/floor`** — answer-first. "What needs you" is the top of the screen and
  nothing competes with it. One large lime action fixed in the thumb zone.
  Raising is a searchable flat machine list (type `p4`, get Press-4), a
  priority, and a sentence — not the seven fields and section-then-machine
  drill-down of the prototype.
- **`/board`** — control-room density. Four tabular-figure tiles readable across
  a room, downtime by section, and the action queue. `homeRouteFor(role)` sends
  you to the right one; a corporate role never lands on the floor at all.

### The brand, taken from the mark

The logo is a lime arch containing a spectrum peacock over a forest wordmark.
Three decisions follow, all contrast-verified (see `scripts/` and the tokens in
`dashboard/src/index.css`):

- **Lime `#A6CE39` is the action colour** — 8.5:1 as a fill under dark ink,
  10:1 as text on the night ground. It is what makes this recognisably Greenlam.
- **Forest `#1F5F3F` is structure** — 7.0:1 on paper. In dark mode the brand
  green lifts to `#6FBF8F`, because `#1F5F3F` on a dark ground is unreadable.
- **The spectrum is section identity and nothing else.** Eight sections, eight
  tail feathers — the fan is literally a plant fanning out into its sections.
  Fill and rule only, never text (yellow is 1.1:1 on paper), and always beside
  the section's name so colour is never the only cue. It never encodes a
  measurement; a rainbow scattered across charts reads as clip-art.

The **arch** is the app's structural motif — a corner-radius proportion on
anything that frames content. `ArchMark` is a geometric echo, not a
reproduction: swap it for the official SVG when brand assets arrive.

### Escalation without a scheduler

Render's free tier has no cron. A background job that *sets* escalation would be
a moving part that can silently stop, and a stalled escalator is worse than
none — the board looks calm while a press sits dead. So escalation is **derived
from timestamps on every read**: a Critical unacknowledged past ten minutes *is*
escalated, and doubling the SLA reaches the plant head. Nothing to drift.

`tickets.escalation_notified_at` exists only so a future notifier job cannot
page the same person twice.

### Root-cause quality

Three prompted why-levels replace the single free-text box, and the score is
shown to the technician **while they type**, before they submit — the cheapest
possible intervention against the decay the addendum warns about. "belt issue"
scores 15/100 and is marked unusable.

The team-level percentage is on the board on purpose: when it starts falling,
the analytics are about three weeks from worthless, and that warning is the
whole reason the metric exists. No individual is named and the API returns no
name to attach.

### Tenant isolation from commit one

`plant_id` and `unit_id` are on every table in migration 0001, and every read
goes through `tenancy.scope()`, which **refuses to compile** a query for a table
without `plant_id`. Anything fetched by primary key goes through
`assert_same_plant()`, which returns 404 rather than 403 — a cross-tenant probe
should not be able to distinguish "exists elsewhere" from "does not exist".

`tests/test_masters.py::TestTenantIsolation` creates a second plant and proves
its rows never appear. Written now, while there is one plant, because that is
when the test is cheap and still catches the leak.

### The theme toggle

Three-way (light / dark / **match device**), and more careful than it looks:

- **No flash.** An inline script in `index.html` applies the theme before first
  paint. That needs inline script, which normally means weakening the CSP — so
  instead the exact script is allowlisted **by SHA-256 hash**. `npm run csp:hash`
  regenerates it and CI fails if it drifts. No `'unsafe-inline'` anywhere.
- **Storage is untrusted input.** `localStorage` is writable by any script on
  the origin, so a stored value never reaches the DOM. It is mapped through
  `coerceThemePreference()` first, and anything unrecognised collapses to
  `system`. Only the literals `'light'` and `'dark'` are ever assigned.
  `packages/core/src/theme.test.ts` fires markup, CSS-injection and wrong-type
  payloads at it.
- **Shared tablets.** The preference is saved on the user row, so it follows a
  technician to whichever tablet they pick up — but it is applied on sign-in
  **only if that device has no choice of its own**, so tapping the toggle on the
  sign-in screen is not overridden a second later. Storage is cleared on
  sign-out so the next person does not inherit the last one's setting.
- Also: cross-tab sync via the `storage` event, live response to the OS theme
  changing while set to `system`, `color-scheme` set so native scrollbars and
  form controls match, and `<meta name="theme-color">` kept in step for
  Android's address bar.

Accessibility: it is a `radiogroup` of three real radios, not a cycling button,
so a screen reader announces all three options and the current one in a single
pass, and arrow keys work.

### Tint the accents, not the neutrals

The rule the dark palette is built on, stated because it took three passes to
actually follow it. Greenlam's colour belongs on the button, not smeared across
every background — and "smeared" is easy to do by accident in three ways, all
of which happened here:

1. **Green-biased neutrals.** `--surface` was `rgb(28,34,30)`, `--surface-muted`
   `rgb(38,45,40)`, `--line-strong` `rgb(71,82,74)` — green highest in every
   one, by 4 to 8 points. Invisible on a hairline, unmistakably **olive** the
   moment one fills a large card. They now carry a faint *blue* bias instead,
   rebuilt at identical luminance (ΔL < 0.003) so every contrast ratio already
   verified still holds.
2. **A brand-coloured "spotlight".** The KPI tiles' pointer highlight was 14%
   lime — and because the pointer position defaults to the centre of the card,
   it never turned off. A spotlight simulates *light*, and light is white. It
   is now neutral, hover-only, and fully transparent in light mode.
3. **An ambient lime glow.** A 40vw blurred lime blob at 0.4 opacity behind the
   whole board cast the entire light theme green. Dark keeps a restrained
   forest-and-cool pair for depth; light paints nothing behind the content.

The test for all three is the same: if a neutral surface reads as *coloured*,
the accent has escaped. Light mode is paper and white cards; dark mode is
cool grey. The green lives on the buttons, the feathers and the data ramps.

### Trilingual, end to end

Three locales ship and stay in step: **`en`**, **`hi`** (Devanagari) and
**`hi-Latn`** (Hinglish — Hindi in Latin script with the technical vocabulary
left in English, e.g. *"Hydraulic pressure gir raha hai"*).

`hi-Latn` is not a novelty. It is how an Indian plant floor actually talks and
types, and many operators read Latin script faster than Devanagari even when
Hindi is their first language, because that is the script their phone keyboard
trained them on. Shipping only `en` and `hi` would push those people back into
English — the outcome i18n exists to prevent.

Four decisions worth knowing:

- **All three bundles load eagerly.** Measured: 14.5 KB gzipped for both Hindi
  files on a 158 KB entry, about 9%. Lazy-loading would save that and buy an
  outage — an operator switching language while offline would fire a request
  that cannot be served and fall back to English, silently, on the screen they
  just told us they cannot read. Revisit at five locales.
- **Base `line-height` is 1.65**, not 1.4. Devanagari matras clip at tighter
  leading — the single most common Hindi rendering bug.
- **IBM Plex Sans Devanagari is self-hosted**, subset to the Devanagari block
  only. Without it Hindi falls back to whatever the device has, which on cheap
  Androids means inconsistent matra placement and, on some ROMs, no Devanagari
  at all. A translated app that renders as boxes is worse than an untranslated
  one.
- **The exception feed is localised client-side.** The server decides *which*
  message applies and computes the numbers; it returns `kind` plus `params`,
  and the client renders the sentence. `headline`/`detail` stay populated as a
  fallback and for the English workbook. Adding a fourth language never needs a
  backend deploy.

`node scripts/check-locales.mjs` (wired into CI) fails the build on a missing
key, an extra key, or **placeholder drift** — a translated string that dropped
its `{{count}}` still reads fluently and silently stops saying how many.

Admin-editable names (`sections`, `machines`, `categories`, `reject_reasons`)
have `name_hi` / `name_hi_latn` **columns**, not JSON entries, because a
supervisor renames them without a redeploy. Sections and categories are seeded
in all three; machine names are not yet.

### Impregnation is where the defect is created

The most valuable table in the system, and the last one added.

Everything else here records what already went wrong. `impregnation_logs`
records the thing that causes it. In short-cycle pressing, **blistering mostly
originates upstream at impregnation, not at the press** — residual volatiles in
the treated paper flash to vapour under the hot platen and lift the layers. So
the defect is *observed* at Press-4 and was *created* at IMP-7, hours earlier,
on a different machine owned by a different supervisor.

One roll per row: GSM, thickness and grade going in; cut size, thickness, resin
content and volatile content coming out.

Four decisions:

- **A separate table from `production_logs`.** A roll is metres and kilograms;
  a sheet is a count. One combined form would show a press operator eight paper
  fields he can never fill, and a form full of permanently blank boxes teaches
  people that skipping fields is normal.
- **The spec window lives on the paper GRADE**, not in a global setting. An
  80 gsm décor and a 150 gsm kraft do not share an acceptable resin content,
  and a range that is wrong for both trains people to ignore the warning.
- **`out_of_spec` is decided at write time and stored**, never recomputed on
  read. Editing a grade's limits later must not silently rewrite what an
  operator was told at the time.
- **It warns; it never blocks.** An out-of-spec roll saves. Force somebody to
  choose between an honest reading and finishing their shift and they stop
  entering honest readings — at which point the data this rests on quietly
  becomes fiction.

`roll_no` is the join key. Naming it at the press is what lets a reject be
traced back to the paper, and the dashboard reports the comparison rather than
asserting it: on the seeded data, sheets from out-of-spec paper reject at
**5.41%** against **3.75%** in-spec.

### Free text is fine for a description and wrong for a GROUP BY

`size`, `texture` and `thickness` used to be free text on the production row.
That is how one texture splits itself across three spellings and quietly
understates every line of a reject breakdown. Adding `design` as free text
would have made it worse, because design has the most distinct values.

All four are masters now, with the same trilingual shape as sections and
categories. The old string columns are kept so the Excel import still
round-trips; the `*_id` columns are what anything analytical groups by.

### Charts are instruments, not pictures

Hand-rolled SVG — Recharts is ~95 KB gzipped to draw bars and a cumulative
line. Three properties the first version lacked:

- **Responsive means reflow, not scale.** The old charts drew into a fixed
  `viewBox` and let CSS shrink it, so on a 375px phone `font-size="11"` rendered
  at about 5 physical pixels. `useChartWidth` measures the container and draws
  at true pixel scale; below 520px the charts shed bars, drop value labels and
  ellipsise names rather than shrinking.
- **One interaction model, three input devices.** Hover, tap and arrow keys all
  drive the same focus index, with full-height hit bands (so you point anywhere
  in a column, not at a 12px bar) and an `aria-live` region that speaks the
  focused datum. Clicking a machine or cause opens a focus strip that joins
  every dataset already in memory — no extra request, and nothing that can 403
  for a corporate reader whose `ticket_id` is redacted by design.
- **Data marks do not use brand colours.** Brand colours are chosen to be loud;
  data marks need the opposite. `--viz-1..5` (categorical), `--seq-1..5` and
  `--clay-1..5` (sequential) are measured to clear 3:1 on both canvas and
  surface in both themes. The categorical five are also a deliberate *luminance*
  staircase — five hues dark enough for paper cannot stay separable under
  deuteranopia, so lightness carries the distinction and hue is the third cue.
  The peacock feathers stay where they were designed to work: a 4px rule down
  the edge of a card, never a fill.

### An installable app, not an app store

`vite-plugin-pwa` with a generated service worker. Four decisions:

- **`autoUpdate`, not a prompt.** Nobody on a plant floor acts on "a new
  version is available", and a stale client talking to a moved API is a support
  call. The new worker takes over on the next launch.
- **`navigateFallback` to index.html**, with `/api/` on the denylist. Without
  the fallback, `/board` on a cold offline start is a 404 from the cache; with
  the API cached, a stale KPI would be presented with total confidence — and
  the outbox already owns offline writes.
- **A 6 MB cache ceiling.** The Devanagari font cut alone is ~80 KB and the
  default 2 MB cap would drop the fonts, so Hindi would render as boxes exactly
  when there is no network to fetch them.
- **Apple meta tags in `index.html` as well as the manifest.** iOS ignores the
  web manifest for the home-screen icon and title; without them an installed
  app on an iPhone gets a screenshot of the page as its icon.

### Getting the workbook out

Three routes to the same file, and the API never builds it.

`GET /exports/latest` streams a workbook a scheduled job already wrote.
Generation stays on the GitHub Actions runner because Render free is 512 MB and
0.1 CPU — openpyxl assembling a few thousand rows would take the instance down,
and it would do it at the moment somebody senior clicked a button. So the worst
case here is a 404 that says the workbook has not been built yet and how to
build one, which is true and actionable, unlike a timeout.

`GET /exports/status` exists separately so the button can state the file's age
*before* anyone clicks. "No workbook yet" and "a workbook from nine days ago"
are different problems needing different sentences; conflating them is how
somebody carries last week's numbers into a meeting.

The staging dotfile the export writes during its atomic move is explicitly
skipped — mid-rebuild it is a truncated workbook, and serving it would hand
someone a corrupt file that looks current.

The other two routes — a shared drive and a daily email — deliver the same one
file and need credentials this repo does not carry.

### Importing the plant's Excel register

`POST /api/imports/preview` parses and reports; `POST /api/imports/commit`
applies. The order is the feature — a single upload endpoint would be smaller
and considerably more dangerous, because the failure mode is not an error
message, it is four thousand plausible-looking tickets that are all one column
out.

The importer reads the **same shape the nightly export writes**, quirks
included, so the loop closes: export, edit in Excel where people are fastest,
upload again. Four rules in `app/importer.py`:

1. **Dry run always.** `plan()` never writes.
2. **Row numbers on every problem**, as Excel numbers them.
3. **Never invent.** An unknown machine code is reported, never fuzzy-matched —
   a typo silently mapped to the wrong press corrupts the analysis.
4. **Idempotent.** Each row's key is a digest of its own content, so a
   re-sorted file is not a new set of breakdowns and re-uploading to check is
   safe. Verified end to end: the same file creates 283 tickets, then creates
   zero.

`GET /api/imports/freshness` is the "refreshed daily" half. Nothing can make
somebody export their spreadsheet; what the system can do is be honest about
age, so a board reading a chart knows whether it is today's plant or last
week's.

### Synthetic-data guard

`app/seed.py` **refuses to run against a non-local database** unless
`ALLOW_REMOTE_SEED=true` is set explicitly. The seed carries the plant's real
section and machine names, and `docs/PHASE-0-ACTION-PACK.md` §2 rule 5 says
those do not leave your machine until hosting is approved in writing.
Remembering a rule is not a control; failing closed is.

The seed deliberately leaves blank what only Phase 0 can supply:
`hourly_downtime_cost` (NULL on every machine), real shift timings (a flagged
placeholder), per-machine criticality (all `B`), and every Hindi name. A guessed
downtime cost becomes a rupee figure on a leadership dashboard, and a wrong
number there is worse than a missing one.

---

## Deploying

`render.yaml` is a blueprint for the API (Docker, free) and the PWA (static,
free), with the `/api/*` rewrite and a full security-header set including the
hashed CSP.

Two things are deliberately **not** on Render:

- **The database.** Render's free Postgres is deleted after 30 days, which would
  wipe the pilot exactly when leadership reviews it. Provision Neon separately
  and paste the connection string into `DATABASE_URL`.
- **Excel generation** (Phase 6). It runs on the GitHub Actions runner against
  Neon directly via a read-only `export_reader` role. Render free is
  512 MB / 0.1 CPU and would OOM building workbooks with charts.

Before the first deploy: generate real `JWT_SECRET` and `PIN_PEPPER` values
(Render's `generateValue: true` does this), confirm the data-residency answer
from `docs/PHASE-0-ACTION-PACK.md` §1.4, and leave `ALLOW_REMOTE_SEED=false`.

### On-prem

If plant IT mandates on-prem, `docker compose up` on their VM is the whole
change. Plain PostgreSQL, no managed-service features in the core path,
everything through environment variables, and the PWA is just a website. You
will need a reverse proxy in front to keep the PWA and `/api` on one origin —
that is what the Render rewrite does in the hosted setup.

---

## What is not built yet

- **Offline sync (Phase 2).** Tickets go straight to the API today. The Dexie
  outbox, the replay reducer and the three-device conflict tests are next. The
  event endpoint was shaped for exactly that replay: client-supplied UUIDv7
  `event_id`, unique-constrained, so a retry is already a no-op.
- **QR scanning (Phase 3).** Tokens, short codes and `raised_via` all exist and
  are issued at machine creation. The camera, the `/s/{token}` route and the
  label PDF are not built — and camera capture needs HTTPS, so it cannot be
  fully exercised until the hosting question is answered.
- **The nightly Excel job (Phase 6),** which runs on the GitHub Actions runner
  against Neon directly.
- **Outbound escalation alerts.** Escalation state is live in the UI and
  correct on every read; pushing it to a Telegram or WhatsApp group needs a
  scheduled job, since Render free has no cron.
- **Hindi and Hinglish (Phase 7).** Every string already goes through `t()` and
  the line-height is already Devanagari-safe; only the JSON files are missing.

## Demo data

`python -m app.seed` generates 90 days of synthetic history — 287 tickets and
1,365 production rows — because charts drawn from ten tickets are noise.

The distributions are shaped, not random, so the dashboard demonstrates the
kind of finding it exists to surface: a Pareto where three causes carry 80% of
downtime, bad-actor machines, a night shift that runs worse on both MTTR and
reject rate, root-cause quality decaying from 83% to 63% across the period, and
a reject-rate lift in the 48 hours around a machine's breakdowns.

**All of it is generated.** `app/demo_data.py` documents exactly which patterns
were planted. Whether any of them exist at Greenlam is what the pilot is for.
`python -m app.seed --thin` skips the history; `--reset` wipes it.

## What is still needed from Greenlam

Nothing below can be invented here, and each one blocks something specific.

**Blocks deployment**
- The IT hosting answer — external cloud, or on-prem? (spec §12.1 Q12)
- A domain, if hosting is external. The same-origin cookie design needs one.

**Blocks real numbers on the dashboard**

Three of these now have a screen to arrive through — **Setup**, for a dashboard
user. They were the only blocked inputs with nowhere in the interface to type
them, which meant the answer had to travel by email and land in a migration.

- `hourly_downtime_cost` per machine, from finance (§12.1 Q7). Until every
  machine that went down has a rate, the board prints a sentence saying how many
  are missing instead of a rupee figure. **All-or-nothing on purpose**: a total
  covering half the plant looks complete and is silently low, which is a worse
  failure than no total at all.
- Real shift timings (§12.1 Q2), as `scheduled_hours_per_day` per machine. With
  every machine scheduled, availability and MTBF divide by hours the plant meant
  to run; without, they divide by 24 and both captions say "calendar hours".
  Same all-or-nothing rule, and the same rule again in the per-machine table so
  the two never disagree on one screen.
- Per-machine criticality A/B/C — everything is seeded as B.
- Production targets per shift (§12.1 Q10).
- The **response-time expectation per priority**. `ACK_SLA_MINUTES` currently
  guesses 10/30/120/480 minutes; set too tight, the board is permanently red and
  everyone learns to ignore it.

**Blocks the pilot**
- The real Excel register, so the export headers match exactly (§12.1 Q5).
- Machine list verified physically, with existing asset tags (§12.1 Q6).
- Two floor champions (§12.1 Q17).
- Who maintains the register today, and how they feel about this (§12.1 Q19).

**Blocks design and Phase 7**
- **Brand assets** — the official logo SVG, and Greenlam's exact hex values if a
  brand guideline exists. The palette here was sampled from a logo image.
- Hindi and Hinglish translations, from someone who speaks the language.
- What language maintenance entries are actually written in today (§12.1 Q18).

**Needs a decision, not a file**
- **What leadership intends to do with technician-level numbers.** The system is
  currently built the safe way — team, section and shift level only, enforced in
  the API. If the real intent is to rank and appraise individuals from this data,
  that changes what the pilot's success metric should be, and it needs saying out
  loud before the board tier goes live (addendum §4.1).
