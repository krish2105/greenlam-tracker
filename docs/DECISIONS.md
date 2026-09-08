# Decisions worth knowing about

A record of the choices that shaped this system, and what each one cost or
bought. Kept apart from the README so the README can stay short — but kept,
because the reasoning is the part that is expensive to reconstruct and cheap to
lose.

Some of these were later replaced. Where that happened the entry says so and
says why, rather than being deleted: a decision log that only contains the
surviving decisions teaches nothing about how they were arrived at.

---

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

### Six access areas a person can hold in any combination (current)

`hpl_production`, `maintenance`, `supervisor`, `manager`, `dashboard`, `admin`.
Nothing is inherited and nothing is ranked: capabilities are the union of the
areas held, so somebody can hold one, three, or all six, and holding `manager`
grants nothing that `maintenance` grants.

This is V5 §3, and it arrived because the model below — two levels — could not
express the thing the plant actually asked for. A section manager who needs the
dashboard and needs to log production is not "floor" or "leadership"; they are
both, and a two-level model forces whoever administers it to over-grant.

The union rule is the whole design:

```python
def capabilities_of(areas):
    held = [CAPABILITIES[a] for a in (areas or ()) if a in CAPABILITIES]
    if not held: return NONE
    return Capabilities(**{f: any(getattr(c, f) for c in held) for f in _FIELDS})
```

A new account is created with **zero** areas and cannot do anything until an
admin approves it and ticks boxes. The first admin is provisioned at deploy,
because there is nobody above them to approve them.

One correction worth recording, because it cost a day: `admin` and `dashboard`
together do **not** grant `log_production`. The first admin was created with
those two on the reasoning that whoever sets the plant up needs to see whether
it works — which gave them the board and withheld the floor, so the only
account on a fresh system opened the app, found no Production section, and
reasonably concluded something had been deleted. Nothing had. The first admin
now gets all six.

### Two access levels (superseded by the six areas above)

`app` was everyone on the floor — report a breakdown, log production, log a
paper roll. `dashboard` was a named few who also got the board, the Excel
import, the master lists and user management.

That replaced a ten-role, three-axis model (capability × scope × resolution)
which let a shareholder sit at the top of the org chart and see the *least*
operational detail, and scoped a manager to one section. A good model for a
group with five plants and a board; the wrong shape for one plant running one
pilot.

Three things worth knowing about how that removal was done, all of which still
hold under the six-area model:

- **The scoping and redaction code was deleted, not disabled.** Access control
  that is half-removed is worse than none — the next person writes code
  believing a guard still guards.
- **`plant_id` on every row survived**, and so did `scope()`. That is the part
  that would have been expensive to retrofit; the day a second plant arrives,
  the filter is already in the right place and fails closed.
- **The individual-metrics rule did not relax.** A person sees their own
  figures; a dashboard holder sees the team, alphabetically, against the team
  average, never ranked. Two floor users still cannot see each other's numbers
  — `test_a_peer_gets_404_not_403` asserts it against two distinct accounts.

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

---

## From the V5 round

### Solve Time is the number, and it needed a screen before it was true

V5 §5.8 bands a finished repair on **Solve Time**:

```
(correction complete − correction started) − time spent waiting
```

The server computed that subtraction correctly from the first day. Nothing
could feed it. The material step sent `material_source: 'none'` unconditionally
— the only path through it — and hold, resume and correction-pending had
endpoints with no interface at all. So `pending_time` was always zero and every
wait counted as repair work: a twenty-minute fix that sat three hours for a
bearing was banded as a three-hour repair, on a press, silently, on every
ticket.

That is not a missing screen. It is wrong data accumulating quietly, which is
the failure this system exists to prevent. The test that matters asserts four
hours elapsed with three hours of waiting comes out **Medium**; it was High.

### Two criticality fields, deliberately named apart

An open ticket ranks by the machine's own criticality — A/B/C from the machine
master, `A → High, B → Medium, C → Low`. The Solve-Time band is recorded at
half-close as the outcome, in `criticality_calculated`.

One is "how much does this machine matter", the other is "how bad did this
repair turn out". Collapsing them into one column loses both, and the second
does not exist yet at the moment the first is needed — nothing has been
repaired when a ticket is raised.

Machine criticality is read at query time, not copied onto the ticket. A
machine reclassified from B to A during setup changes how its open tickets rank
immediately; a snapshot taken at raise time would keep sorting last week's
tickets by last week's answer.

### Load No. instead of SAP material codes

V5 §6.2A deletes the hardest open question in the project rather than answering
it. SAP stays external, the sixty-odd material codes inside a load are never
entered, and a manually typed **Load No.** becomes the traceability key.

It is a plain indexed string, not a foreign key, because SAP is outside this
system and there is nothing here to validate against. That is the point: an
operator can always type what is on the sheet in front of them, even offline,
even for a load created this morning.

Mandatory at the press — it is the only handle a finished sheet has back to its
load — optional downstream, and **absent from impregnation**, which is
availability-driven and must stay independent of any load.

### Draft and Submitted for a production entry

A press operator fills the form between cycles, not in one sitting. Before V5
§6.3 the only way to save half an entry was to save a whole one: a sheet count
of zero on the dashboard, in the daily log and in the Excel, then a correction
tagged "Edited" for the crime of being written in two goes.

The line sits where the ticket lifecycle already draws it — a ticket is freely
editable while open and only tracked once it closes. Submitted is a production
entry's "closed".

`submitted_at` is a timestamp rather than a flag because §7 counts the
ten-hour correction window from submission. With a boolean there is nothing to
count from, and `created_at` is wrong the moment drafts exist: an entry started
on Monday and finished on Wednesday would arrive with its window already spent.

Building it surfaced a constraint that had been right for four years and became
wrong in one commit. Migration 0001's `rejected_qty = 0 OR reject_reason_id IS
NOT NULL` fires on INSERT, so an operator who had typed the scrap count but not
yet chosen the reason could not save what they had — the exact state drafts
exist to hold. It now applies to submitted rows only, and the router enforces
the same rule at the Done press, so every row that counts is still covered.

### One filter bar, not nine reports

V5 §11.1 is explicit about the alternative: a fixed report per question —
day-wise, time-wise, one machine, all machines of a type, one module, combined.
That list has no end. Somebody always wants morning shift on Press 4 last week,
and then the same for the impregnators, and each one arrives as a request.

So the three dashboards (Maintenance, HPL Production, Combined) are not three
routes and not three components. §11.1 lists "Module" as one filter among
seven, and the switcher is that filter rendered as a switcher. Every panel
declares which views it belongs to.

Two details in the filters themselves:

- The **hour window converts to plant-local time before comparing, and wraps**.
  A night shift is 22:00–06:00, and in UTC an Indian plant's night lands five
  and a half hours off — the filter would answer a different question than the
  one asked, silently. Hour 0 is handled explicitly, because `!value` drops
  midnight.
- **Load No. reaches production only.** A breakdown is raised against a machine,
  never against a load, so offering it on the maintenance view would be a
  control that empties the screen and explains nothing.

Three panels take no filters — the live exception queue, the section rollup and
the root-cause sample. Rather than leave them silently disagreeing with the
filtered numbers beside them, they say so.

### A 250-line xlsx writer, and why not a library or a CSV

Exporting a filtered view had to happen in the browser: `CLAUDE.md` forbids
Excel generation on Render, and the data is already in the page.

No library, because the CSP is `script-src 'self'` — anything used has to be
bundled, and this bundle also serves the floor's cheap Android phones. SheetJS
is around 900 KB for a button most people never press.

Not a CSV, for two reasons that are not cosmetic. Free-text root causes contain
commas and newlines — V5 stores them exactly as typed — so one missed quote
silently shifts a row's columns, producing a corrupted report that still opens.
And Excel on Windows renders a UTF-8 CSV as mojibake without a BOM; half this
plant's data is Devanagari.

An `.xlsx` is a ZIP of XML, and ZIP entries may be **stored** rather than
deflated — which removes the only piece that would have needed a compressor.
What remains is a CRC32, a handful of headers, and four XML parts. Verified by
reading the bytes back (including the CRC, which nothing else would catch and
which makes Excel refuse the file), and cross-checked by opening a generated
workbook with `openpyxl`, the same reader the nightly job uses.

The first sheet of every export states the period, the module and every filter
applied, resolved to names. The file leaves the building: it gets forwarded and
quoted in a meeting three weeks later by somebody who was not in the room, and
"downtime 4 hours" reads as the whole plant until you learn it was one press,
on the night shift, for a fortnight.

### The clear refuses rather than locking everyone out

`start_trial --on-boot` empties a demo so a plant can begin a trial on a clean
system. It deletes every account, and the boot chain relies on `bootstrap`
putting the first admin back — which only happens when `BOOTSTRAP_ADMIN_PIN` is
set and valid.

The README correctly tells people to clear that secret once a trial has
started, because a secret with no remaining purpose is a liability. Which means
the next person to start a trial runs a sequence where both steps report
success and the plant is left with its data gone and no way in. Nothing errors.
The system is simply shut.

It is checked before the delete now, not discovered after it. Refusing to clear
is recoverable in ten seconds; clearing and then finding out is not recoverable
at all. This fired in practice on the first real use, which is the only reason
the trial database still exists.

### Saying the server is waking

Measured on the deployed instance: a cold API takes **43 seconds** to answer,
because Render's free tier sleeps after fifteen minutes idle. For all of that
the app showed one word — "Loading…".

That does not read as slow. It reads as broken, and the person closes the tab
and tells somebody the app does not work. It is the single most likely way this
fails in front of a plant, and nothing is actually wrong.

After four seconds — not before, because on a warm instance the screen is gone
in a few hundred milliseconds and an unnecessary apology makes a fast app look
slow — it says the server is waking and that nothing is wrong. Deliberately
about the server rather than the network: a technician on the floor with one
bar has every reason to blame their signal, and sending them to chase that is
the wrong instruction.
