# Module Addendum v1.1
## QR scanning · Bilingual UI · Domain-partitioned Excel · Performance reviews

Companion to `GREENLAM-TRACKER-BUILD-SPEC.md`. Where this document and the base spec disagree, this one wins.

---

## 0. What changed in the architecture

One decision from the base spec has to be revised because of the Excel requirements below.

**Excel generation moves off Render entirely and into the GitHub Actions runner.**

Render's free tier gives you 512 MB RAM and 0.1 CPU. Building a master workbook plus per-section and per-machine workbooks, each with embedded charts, will either run out of memory or exceed a sane request timeout. A GitHub Actions runner gives you a 2-core, multi-GB machine for free, and you were already using it as the scheduler.

| | Base spec (v1.0) | Revised (v1.1) |
|---|---|---|
| Scheduler | GitHub Actions | GitHub Actions — unchanged |
| Data query | API endpoint on Render | Runner connects **directly to Neon** with a read-only Postgres role |
| Workbook build | Render (512 MB) | **On the runner** (multi-GB, 2-core) |
| Upload | Render → R2 | Runner → R2 |
| Email | Render | Runner, via Resend |
| Render's role | Everything | Nothing. It stays asleep. |

This also means the nightly job is completely unaffected by Render cold starts, and it keeps your instance-hours free for actual users. Create a dedicated Postgres role for it:

```sql
-- Read-only role for the nightly export runner. Never give the runner write access.
CREATE ROLE export_reader LOGIN PASSWORD '<from GitHub secret>';
GRANT CONNECT ON DATABASE greenlam TO export_reader;
GRANT USAGE ON SCHEMA public TO export_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO export_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO export_reader;
```

The manual "Export now" button on the dashboard still needs to work. Have it trigger the same GitHub Actions workflow via `workflow_dispatch` through the GitHub API, rather than duplicating the build code on Render. One code path, as required.

---

## 1. Module A — QR codes on machines

### 1.1 Why this is the highest-value addition you've asked for

Selecting a section, then finding the right machine in a list of twelve, is where a 30-second ticket becomes a 90-second ticket — and 90 seconds is where people go back to shouting across the floor instead. A QR sticker collapses that to: point camera, tap "Report breakdown", type what's wrong, submit.

It also gives you something you otherwise can't get: **the machine identity is guaranteed correct.** Hand-typed machine names produce "Press 4", "press-4", "P4", and "Pres-4" as four different machines in your analytics within a month.

### 1.2 What goes on the sticker

Encode a URL, not a raw ID:

```
https://gmt.greenlam.internal/s/K7m2Qx9RvB4nZs
                              └─ 22-char random token, stored on the machine row
```

Encoding a URL matters because **the built-in iPhone and Android camera apps will open it directly.** A new operator on their first day can scan a machine and raise a ticket without anyone having installed anything. That is a genuinely large adoption advantage over an app-only scanner.

**Do not encode `machine_id` directly.** It's guessable, it breaks if you ever re-seed the database, and it leaks your row counts. Use a random token with its own column.

**Sticker layout** — the QR is not the only thing on it:

```
┌─────────────────────────────┐
│   ▄▄▄▄▄▄▄  ▄ ▄▄  ▄▄▄▄▄▄▄    │   ← QR, error correction H,
│   █ ▄▄▄ █ ▄█▄▄▄▄ █ ▄▄▄ █    │      minimum 40 mm × 40 mm
│   █ ███ █ ▀ ▄▀▄█ █ ███ █    │
│   █▄▄▄▄▄█ ▄▀█▀█▄ █▄▄▄▄▄█    │
│                             │
│      PRESS-04               │   ← machine code, large
│      प्रेस-04                │   ← Hindi name
│                             │
│   Code: A7K2-M9   ← manual fallback if the QR is damaged
│   Scan to report a breakdown │
│   खराबी दर्ज करने के लिए स्कैन करें │
└─────────────────────────────┘
```

The **manual fallback code** is not optional. Stickers in a laminate plant get scratched, get resin on them, and get scrubbed. A short human-typable code that resolves to the same machine means a damaged sticker never blocks anyone.

**Physical specification for this environment:**

| Property | Requirement | Why |
|---|---|---|
| Error correction | Level H (30% recoverable) | Scratches, dust, partial resin coverage |
| Minimum size | 40 mm × 40 mm QR | Scannable from ~50 cm in poor light |
| Material | Laminated vinyl or anodised aluminium plate | Paper will not survive a press hall |
| Adhesive | Industrial, heat-rated | Presses run hot; standard adhesive fails within weeks |
| Placement | Eye level, at the operator station, on a static surface | Never on a moving part, a hot platen, or a panel that gets opened |
| Quiet zone | 4 modules of white margin | Scanners fail without it and nobody knows why |

### 1.3 Scan flows

**Flow 1 — from inside the app (primary, works offline)**

```
Tap the big [Scan] button
  → camera opens
  → token decoded locally
  → resolved against the LOCAL Dexie machine table
  → machine + section prefilled
  → choose: [Report breakdown] or [Log production]
  → 3 fields → submit → queued to outbox
```

Because the machine master is cached on the device, **scanning works with no network at all.** This is the reason the master list must sync down on login and refresh in the background — it's not just a convenience cache, it's what makes offline QR work.

**Flow 2 — from the phone's native camera (onboarding, no app needed)**

Scan → browser opens `/s/<token>` → if not signed in, PIN login → same prefilled form → and a prompt to install the app to the home screen. This is your best install funnel; don't treat it as a fallback.

### 1.4 Implementation

**Generating tokens and QR images (Python, API side):**

```python
import secrets
import qrcode
from qrcode.constants import ERROR_CORRECT_H

def issue_qr_token() -> str:
    """22-char URL-safe token. 128 bits of entropy — not guessable,
    and short enough to keep the QR's module count low so it stays
    scannable when printed small."""
    return secrets.token_urlsafe(16)

def build_qr_image(token: str, base_url: str):
    qr = qrcode.QRCode(
        version=None,              # auto-size to the smallest that fits
        error_correction=ERROR_CORRECT_H,   # 30% damage tolerance — plant floor
        box_size=10,
        border=4,                  # the 4-module quiet zone; do not reduce
    )
    qr.add_data(f"{base_url}/s/{token}")
    qr.make(fit=True)
    return qr.make_image(fill_color="#1F5F3F", back_color="white")
```

Note the fill colour: QR codes tolerate a dark colour on a light background, so using Greenlam's forest green instead of black is safe and makes the labels look deliberate rather than improvised. Do not invert it — light-on-dark fails on many scanners.

**Scanning in the PWA:**

Use the native `BarcodeDetector` API where available (Chrome/Android — fast, hardware-accelerated, no library), and fall back to `@zxing/browser` on iOS Safari, which doesn't support it yet.

```javascript
// Prefer the platform API; fall back to a JS decoder on iOS.
async function getScanner() {
  if ('BarcodeDetector' in window) {
    const formats = await BarcodeDetector.getSupportedFormats();
    if (formats.includes('qr_code')) {
      return new BarcodeDetector({ formats: ['qr_code'] });
    }
  }
  const { BrowserQRCodeReader } = await import('@zxing/browser');
  return new BrowserQRCodeReader();   // lazy-loaded, keeps the main bundle small
}
```

Camera access requires HTTPS (Render and any intranet server with a cert both satisfy this) and a user gesture to start. Request `facingMode: 'environment'` for the rear camera.

**Printable label sheets:** an admin screen that takes a section, generates an A4 PDF of labels laid out for standard sticker stock, and marks `label_printed_at` on each machine so you can tell which machines have been tagged and which haven't. Reprinting a single damaged label must not require reprinting the sheet.

### 1.5 Schema additions

```sql
ALTER TABLE machines
  ADD COLUMN qr_token       TEXT UNIQUE NOT NULL,
  ADD COLUMN qr_short_code  TEXT UNIQUE NOT NULL,   -- 'A7K2-M9', the manual fallback
  ADD COLUMN qr_issued_at   TIMESTAMPTZ,
  ADD COLUMN label_printed_at TIMESTAMPTZ;

-- Every scan, logged. Two reasons: it proves QR adoption to leadership,
-- and a machine that never gets scanned tells you its sticker fell off.
CREATE TABLE qr_scans (
  id           BIGSERIAL PRIMARY KEY,
  plant_id     INT NOT NULL,
  machine_id   INT NOT NULL,
  user_id      INT,                    -- null if scanned before login
  scanned_at   TIMESTAMPTZ NOT NULL,
  resulted_in  TEXT,                   -- ticket | production | abandoned
  source       TEXT                    -- in_app | native_camera
);

ALTER TABLE tickets
  ADD COLUMN raised_via TEXT DEFAULT 'manual';   -- qr | manual | web
```

`raised_via` is small and it earns its keep: at the pilot review you can say "68% of tickets were raised by scanning, and those took an average of 34 seconds versus 81 seconds typed." That is the kind of number that gets a plant-wide rollout approved.

### 1.6 Security note

The token is a machine identifier, not a credential. Scanning it does not authenticate anyone — `/s/<token>` still requires a valid session before a ticket can be raised. Treat the token as public information, because it is: it's printed on a wall. Have a "reissue token" admin action for the case where a machine is decommissioned or a label needs invalidating.

---

## 2. Module B — Bilingual (and the third option you should consider)

### 2.1 Offer three languages, not two

| Mode | Example | Who uses it |
|---|---|---|
| **English** | "Belt broken on Press-4" | Supervisors, engineers, leadership |
| **हिंदी (Devanagari)** | "प्रेस-4 पर बेल्ट टूट गई" | Operators comfortable reading Devanagari |
| **Hinglish (Latin script)** | "Press-4 pe belt tut gayi" | Very often the highest-adoption option |

The third one costs you one extra JSON string file and is frequently what people on the floor actually read fastest — many are more fluent in spoken Hindi than in reading Devanagari, and type Hindi in Latin script on WhatsApp every day. Build the infrastructure for three from the start; you can decide which to ship after Phase 0 observation.

### 2.2 Set up i18n in Phase 1, not Phase 7

This is the one piece of sequencing advice in this document that will save you real pain. **Retrofitting internationalisation across a finished app is one of the most tedious refactors in frontend work** — every hardcoded string, in every component, plus the layout breakage you then discover all at once.

Wrap every user-visible string in `t()` from your very first component, even while the only translation file is English. The Hindi strings can arrive in Phase 7. The *structure* has to exist in Phase 1.

```javascript
// Phase 1: only en.json exists. Still write it this way.
const { t } = useTranslation();
<button>{t('ticket.raise')}</button>          // not <button>Raise ticket</button>
```

Stack: `i18next` + `react-i18next`, with `en.json`, `hi.json`, `hi-Latn.json`.

### 2.3 Where translations live — two different places

**UI labels → i18n JSON files.** Buttons, headings, errors, empty states.

**Master data → database columns.** Section names, issue categories, reject reasons, priorities, machine names. These are admin-editable, so they cannot live in a JSON file you'd have to redeploy to change.

```sql
ALTER TABLE sections       ADD COLUMN name_hi TEXT, ADD COLUMN name_hi_latn TEXT;
ALTER TABLE machines       ADD COLUMN name_hi TEXT;
ALTER TABLE reject_reasons ADD COLUMN name_hi TEXT, ADD COLUMN name_hi_latn TEXT;
ALTER TABLE categories     ADD COLUMN name_hi TEXT, ADD COLUMN name_hi_latn TEXT;

ALTER TABLE users ADD COLUMN preferred_language TEXT DEFAULT 'en';  -- en | hi | hi-Latn
```

Fall back to `name_en` when a translation is missing rather than showing an empty cell.

### 2.4 Do not auto-translate free text

Root cause, immediate correction, and preventive action are typed by technicians. **Store them exactly as typed and display them exactly as typed.** Do not run them through a translation API.

Maintenance Hinglish is full of trade terms, machine slang, and abbreviations that general-purpose translation mangles — and once a mangled translation is what's stored, your root-cause data is corrupted permanently and silently. Record `input_language` on the event for analytics, and if a supervisor needs a translation, give them a per-entry "translate this" button whose output is displayed but never saved.

### 2.5 Devanagari rendering — the details that break layouts

- **Font:** Noto Sans Devanagari. Self-host the subset; don't rely on device fonts, which vary badly on older Android.
- **Line height:** Devanagari needs roughly 1.6–1.7 versus 1.4 for Latin. At tighter leading the matras (the marks above and below) clip. This is the single most common Devanagari rendering bug.
- **String length:** Hindi runs 15–30% longer than English. Test every button and every table header with the longest Hindi string, not the shortest. Fixed-width buttons will break.
- **Numerals:** use Latin digits (4, not ४) throughout. Everyone in the plant reads machine codes and quantities in Latin digits, and mixed numeral systems in a data table are genuinely confusing.

### 2.6 Voice input — worth doing in Phase 7

The Web Speech API supports `hi-IN`. A microphone button on the root-cause field lets a technician speak instead of typing, which matters a lot for people who type slowly on a phone. It measurably improves root-cause entry quality, which is the field most at risk of degrading into "machine stopped".

Support is Chrome/Android-solid and patchier on iOS Safari — treat it as an enhancement, never the only input method.

### 2.7 Bilingual Excel

Header rows carry both languages, English first:

```
Machine / मशीन  |  Section / अनुभाग  |  Downtime (hrs) / बंद समय (घंटे)
```

Keep the **original English header text intact and first** so any existing pivot tables or Power Query connections in leadership's own files continue to resolve. Making the file bilingual must not break what people have already built on top of it.

---

## 3. Module C — The nightly Excel, partitioned by domain

### 3.1 Output structure

Every 24 hours the job rebuilds and stores files partitioned the way people actually look for them — the whole plant, one section, or one machine.

```
r2://greenlam/exports/
│
├── LATEST/                                   ← stable paths, overwritten nightly.
│   ├── Greenlam_Master_LATEST.xlsx              Point Power Query here and it
│   ├── Greenlam_Press_LATEST.xlsx               never needs re-linking.
│   └── ...
│
├── daily/2026-08-24/
│   ├── Greenlam_Master_2026-08-24.xlsx        ← full plant, all sheets
│   ├── by-section/
│   │   ├── Press_2026-08-24.xlsx
│   │   ├── Impregnation_2026-08-24.xlsx
│   │   └── Sanding_2026-08-24.xlsx
│   └── by-machine/
│       ├── PRESS-04_2026-08-24.xlsx           ← that machine's entire life history
│       ├── IMP-07_2026-08-24.xlsx
│       └── ...
│
├── reviews/
│   ├── weekly/2026-W34_Review_Pack.xlsx       ← Monday 07:00
│   └── monthly/2026-08_Management_Review.xlsx ← 1st of month, 07:00
│
└── backups/
    └── 2026-08-24_pgdump.sql.gz               ← same job, second safety net
```

**Retention:** daily files for 90 days, then monthly snapshots only. `LATEST/` and `reviews/` forever.

### 3.2 Workbook contents

**Master workbook** — 9 sheets, in this order (leadership opens sheet 1 and often stops there):

| # | Sheet | Contents |
|---|---|---|
| 1 | **KPI Summary** | This month vs last, with direction-of-good arrows. Downtime hrs, cost, MTTR, MTTA, MTBF, availability, reject %, open ticket count. |
| 2 | **Charts** | All visuals on one sheet — see §3.3 |
| 3 | **BD Tracker** | Exact column headers from the plant's existing register. Unchanged. |
| 4 | **Production** | Date, shift, machine, size, texture, produced, rejected, reason, logged by |
| 5 | **Machine Summary** | One row per machine: breakdowns, downtime, cost, MTTR, MTBF, last failure, PM flag, verdict |
| 6 | **Section Summary** | Rolled up, month over month |
| 7 | **Shift Comparison** | A vs B vs C on every metric |
| 8 | **Open Tickets** | Live snapshot with ageing buckets |
| 9 | **Event Log** | Full append-only audit trail |

**Per-machine workbook** — this is the "each machine stores its own" requirement. One file per machine, containing that machine's complete history:

| Sheet | Contents |
|---|---|
| Machine Profile | Code, section, make, model, install date, criticality, hourly cost, PM schedule |
| Breakdown History | Every ticket ever, oldest to newest, with full root-cause text |
| Reliability Trend | Monthly MTBF, MTTR, downtime hrs, breakdown count — with a line chart |
| Cost | Downtime cost + spares cost, monthly |
| Production | Output and reject rate for this machine |
| Recurring Faults | Same-category repeats, ranked, with the previous root causes side by side |

That last sheet is the one a maintenance engineer will actually use. Seeing four separate breakdowns with four differently-worded root causes for what is obviously the same underlying fault is how a preventive action finally gets written.

### 3.3 Charts inside the workbook

`openpyxl` writes native Excel charts — they stay live and interactive in Excel, which is far better than pasted images.

| Chart | Type | Sheet |
|---|---|---|
| Daily downtime, 90 days, stacked by category | Stacked area | Charts |
| Downtime hours by section | Bar | Charts |
| **Downtime Pareto by cause** | Bar + cumulative % line on secondary axis | Charts |
| MTTR trend, 12 months | Line | Charts |
| Reject rate trend, daily | Line | Charts |
| **Rejection Pareto by reason** | Bar + cumulative % line | Charts |
| Top 10 machines by downtime | Horizontal bar | Charts |
| Shift comparison | Grouped bar | Shift Comparison |
| Per-machine reliability | Line, dual axis (MTBF and MTTR) | Per-machine file |

The two Pareto charts are the ones that change behaviour. They make the 80/20 visible: usually three or four causes account for most of the downtime, and that is the entire agenda for the next month's maintenance planning.

```python
from openpyxl.chart import BarChart, LineChart, Reference

def add_pareto(ws, data_start, data_end, anchor="A1"):
    """Downtime Pareto: bars descending by cause, with a cumulative-%
    line on a secondary axis. The 80% crossing point is where you stop reading."""
    bars = BarChart()
    bars.type = "col"
    bars.add_data(Reference(ws, min_col=2, min_row=data_start - 1, max_row=data_end),
                  titles_from_data=True)
    bars.set_categories(Reference(ws, min_col=1, min_row=data_start, max_row=data_end))
    bars.y_axis.title = "Downtime (hours)"

    cum = LineChart()
    cum.add_data(Reference(ws, min_col=3, min_row=data_start - 1, max_row=data_end),
                 titles_from_data=True)
    cum.y_axis.axId = 200               # secondary axis, 0–100%
    cum.y_axis.title = "Cumulative %"
    cum.y_axis.crosses = "max"          # draw it on the right-hand side

    bars += cum                         # overlay the line onto the bars
    ws.add_chart(bars, anchor)
```

Also apply, on every data sheet: frozen header row, autofilter, column widths sized to content, red/amber/green conditional formatting on KPI deltas, and data bars on downtime columns. These take twenty minutes and are the difference between a file that looks generated and one that looks made.

**One limitation to know:** `openpyxl` cannot write sparklines. If leadership specifically wants in-cell sparklines, either use tiny embedded line charts instead or accept a small `xlsxwriter` module for those sheets.

### 3.4 Build strategy — what to rebuild and when

Rebuilding every per-machine workbook nightly is wasteful once you're at 40+ machines across a full plant.

| Artifact | Cadence |
|---|---|
| Master workbook | Full rebuild nightly (complete snapshot, so a missed night self-heals) |
| Per-section workbooks | Nightly |
| Per-machine workbooks | Nightly **only for machines with activity in the last 24 h**; full rebuild of all machines every Sunday |
| Weekly review pack | Monday 06:30 IST |
| Monthly management review | 1st of month, 06:30 IST |
| Postgres dump | Nightly |

Every artifact must be idempotent — re-running for the same date produces an identical file with no duplicate rows.

### 3.5 The schedule

```yaml
# .github/workflows/nightly-export.yml
on:
  schedule:
    - cron: '45 18 * * *'      # 00:15 IST — note GH Actions cron is UTC
  workflow_dispatch:            # the dashboard's "Export now" button calls this
```

Add a second workflow for the weekly and monthly packs. And keep the alerting from the base spec: if the job fails, the workflow fails, GitHub emails you, and a Telegram message hits the maintenance group. A daily export that quietly stopped three weeks ago is worse than no export, because people are still acting on it.

---

## 4. Module D — Performance and review packs

### 4.1 Read this before building individual performance metrics

Technician-level performance metrics are the most dangerous feature in this entire system.

The moment floor staff conclude that the app is a monitoring tool pointed at them rather than a tool that helps them, adoption collapses — and unlike a bug, you cannot fix it by shipping a patch. People will log tickets late, close them early, and write "belt issue" in every root cause field. You end up with a system that reports excellent numbers and describes nothing real.

**Design rules:**

1. **Default to team and section level.** Individual metrics exist in the database but are not on the main dashboard.
2. **Individual metrics are visible to that person's supervisor only** — and to the person themselves. Never to peers.
3. **Never put individual rankings in the emailed workbook.** A leaderboard of technicians circulating in a plant-wide email will do more damage than the metric is worth.
4. **Frame them as workload and support, not ranking.** "Ravi handled 34 tickets this month, 12 of them Critical" is a staffing observation. "Ravi is ranked 7th of 9" is a threat.
5. **Show people their own numbers first.** Someone who has seen their own MTTR for a month before anyone else discusses it reacts very differently to it being raised.

Say this out loud to your sponsor in Phase 0. If leadership's intent is to rank and discipline technicians with this tool, you need to know that before you build it, because it changes what the pilot's success metric should be.

### 4.2 The five reviews

**1. Machine performance review** *(the safest and most valuable one — start here)*

Per machine: breakdown count, downtime hours, downtime cost, MTTR, MTBF trend, PM compliance, repeat-failure count, criticality-weighted rank. Ending in a verdict:

| Verdict | Trigger |
|---|---|
| **Stable** | MTBF improving or flat, no repeats |
| **Watch** | MTBF declining 2 months running |
| **Intervene** | ≥3 breakdowns in 30 days, or MTBF down >30% |
| **Replacement candidate** | Cumulative downtime cost over 12 months approaching replacement cost |

That last row is what turns this from a logbook into a capex argument.

**2. Section performance review** — downtime, availability %, output vs target, reject %, ticket ageing, month-over-month deltas. Section heads compare directly, which creates useful pressure without naming individuals.

**3. Shift performance review** — A vs B vs C on identical metrics. This one reliably surfaces things nobody expected: a night shift with double the reject rate is almost always a training or supervision gap, not a machine problem, and you can only see it if `shift_id` is on every record from day one.

**4. Team performance review** — maintenance team as a unit: avg MTTA, avg MTTR, first-time-fix rate, reopen rate, tickets closed vs raised (backlog trend), root-cause completeness %. All team-level.

**5. Root-cause quality review** *(the one nobody builds, and the one that keeps the data alive)*

Score each closed ticket's root-cause entry: has ≥3 why-levels, exceeds a minimum length, has a distinct preventive action, isn't near-identical to the same technician's previous entry for that machine. Report the **percentage of tickets with a usable root cause** at team level, monthly.

Watch this number. When it starts falling, your analytics are about to become worthless, and you'll have three weeks of warning rather than discovering it at the quarterly review.

### 4.3 Review pack cadence

| Pack | When | To whom | Contents |
|---|---|---|---|
| **Daily digest** | 07:00 IST | Maintenance head, shift in-charge | Yesterday: tickets raised/closed, downtime hrs, open criticals, ageing >3 days. Short — 10 lines in the email body, no attachment. |
| **Weekly review pack** | Monday 06:30 | Plant head, section heads, maintenance head | Built for the Monday morning meeting: top 5 downtime machines, new PM candidates, ageing tickets, reject Pareto, week-over-week deltas, actions closed vs open |
| **Monthly management review** | 1st, 06:30 | Plant head, unit head | Month vs month, YTD trend, downtime cost, estimated cost avoided, machine verdicts, PM compliance, adoption % |
| **Quarterly** | Manual | Corporate | Cross-plant comparison once you're multi-plant. This is the artifact that sells the national rollout. |

The weekly pack has a specific job: **be the agenda for a meeting that already happens.** Attaching your file to a meeting that exists is how the system becomes indispensable. Creating a new meeting for it is how it becomes a chore.

### 4.4 Schema additions

```sql
CREATE TABLE review_runs (
  id           BIGSERIAL PRIMARY KEY,
  plant_id     INT NOT NULL,
  review_type  TEXT NOT NULL,     -- daily | weekly | monthly | quarterly
  period_start DATE NOT NULL,
  period_end   DATE NOT NULL,
  status       TEXT NOT NULL,
  storage_key  TEXT,
  metrics      JSONB,             -- snapshot of the numbers AS PUBLISHED
  sent_at      TIMESTAMPTZ,
  error_message TEXT,
  UNIQUE (plant_id, review_type, period_start)   -- idempotent by construction
);
```

Storing `metrics` as a snapshot matters. When someone asks in November why the August pack said 47 hours and the dashboard now says 51, you can answer precisely: a ticket was reopened and backdated. Without the snapshot, you're guessing, and your credibility takes the hit.

---

## 5. Revised timeline

The four modules add roughly a week overall, mostly because i18n is threaded through existing phases rather than added at the end.

| Phase | v1.0 | v1.1 | What changed |
|---|---|---|---|
| 0 — Discovery | 1 | 1 | Add: language observation, sticker placement survey, ask about individual-metrics intent |
| 1 — Foundation | 1 | 1 | **i18n scaffolding starts here** (structure only), QR token columns in the first migration |
| 2 — Sync engine | 1.5 | 1.5 | Machine master must sync down for offline QR resolution |
| 3 — Floor PWA + QR | 1.5 | **2** | + camera scanning, `/s/<token>` route, label PDF generator |
| 4 — Production | 0.5 | 0.5 | — |
| 5 — Dashboard | 1.5 | 1.5 | — |
| 6 — Excel + charts | 1 | **1.5** | + partitioned outputs, native charts, runner-side build |
| 7 — Reviews + Hindi | 1 | **1.5** | + review packs, Hindi/Hinglish strings, voice input |
| **To pilot-ready** | **9** | **~10 weeks** | |
| 8 — Pilot | 4–6 | 4–6 | + print and mount labels before day one |

**Add to Phase 0:** the QR labels have to be designed, printed, and physically mounted *before* the pilot starts. Printing turnaround for laminated vinyl is typically 3–5 days locally. Order them during Phase 6 so they're on the machines before Phase 8 begins — this is the kind of physical dependency that quietly delays a launch by a week.

---

## 6. Claude Code prompt — additions

Append to `PROJECT_BRIEF.md`:

````markdown
## Additional modules (v1.1 addendum — read `MODULE-ADDENDUM-v1.1.md`)

### QR codes
Every machine gets a printed QR label encoding `{BASE_URL}/s/{qr_token}` where
qr_token is a 22-char random URL-safe string on the machine row — never the
machine_id. Scanning must work OFFLINE: the machine master syncs to local Dexie
on login, and the token resolves against local data. Use the BarcodeDetector API
where available, lazy-load @zxing/browser as an iOS fallback. Also build an admin
screen that generates print-ready A4 label sheets as PDF. Log every scan to
qr_scans and set tickets.raised_via so we can measure QR adoption.

### Bilingual
Set up i18next in PHASE 1, not later — wrap every user-visible string in t()
from the first component even while only en.json exists. Three locales:
en, hi (Devanagari), hi-Latn (Hinglish). UI strings live in JSON; master data
names live in name_hi / name_hi_latn database columns because admins edit them.
NEVER auto-translate free-text root-cause entries — store and display exactly as
typed. Devanagari needs line-height 1.6+ or matras clip, and Hindi strings run
15–30% longer than English, so test layouts with the longest strings.

### Nightly Excel — IMPORTANT ARCHITECTURE CHANGE
Excel generation runs ON THE GITHUB ACTIONS RUNNER, not on Render. Render free
is 512 MB / 0.1 CPU and will OOM building workbooks with charts. The runner
connects directly to Neon with a read-only `export_reader` Postgres role.
Render is not involved in the nightly job at all.

Outputs are partitioned by domain: a master workbook, one workbook per section,
and one workbook per machine containing that machine's complete history. Plus
stable LATEST/ paths that are overwritten nightly so Power Query links never
break. Embed native openpyxl charts including two Pareto charts (bar +
cumulative % on a secondary axis). Per-machine files rebuild nightly only for
machines with activity; full rebuild Sundays. Everything idempotent.

### Review packs
Daily digest, weekly pack (Monday 06:30, built to be the agenda for the existing
Monday meeting), monthly management review. Snapshot the published metrics into
review_runs.metrics as JSONB so historical packs remain explainable.

IMPORTANT: individual technician performance metrics are visible to that person
and their supervisor ONLY. Never on the main dashboard, never in an emailed
workbook, never as a peer-visible ranking. Default every performance view to
team or section level. Ask me before exposing any individual-level metric
anywhere new.
````
