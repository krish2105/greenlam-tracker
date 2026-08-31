# Build prompt — Greenlam plant tracker

> **Status: implemented.** Everything below has been built and verified. The
> file is kept as the specification it was written from — what the system is
> supposed to do, and why each decision was made. Read it as the contract, not
> as a to-do list.

---

## What this is

A maintenance and production tracking system for a Greenlam Laminates plant.
Two surfaces, one database:

- **The app** — used on phones on the shop floor. Two jobs: raise a breakdown
  ticket when a machine stops, and log what was produced each day.
- **The dashboard** — used by leadership. Shows where the plant is losing time
  and which machines are performing badly.

Everything the app records appears on the dashboard immediately. There is no
second data entry anywhere.

---

## Who uses it — exactly two levels

Replace the current ten-role hierarchy with two:

| Level | Who | Can do |
| --- | --- | --- |
| **App user** | Everyone on the floor — operators, technicians, fitters | Raise and work breakdown tickets. Log daily production. Nothing else. |
| **Dashboard user** | A named list of people — managers, plant leadership | Everything an app user can do, **plus** the dashboard, the Excel import, and editing master lists. |

Rules:

- App access is for **everybody**. Nobody is scoped to one section any more.
- Dashboard access is for **several named people**, not one. An admin adds and
  removes them.
- **Remove the name and role line from the header.** Today it shows
  `Vikram Shetty · Plant head`. Delete both parts. The header should carry the
  product name, the navigation, the language switch and sign-out — nothing about
  who is signed in.

> **Note this consequence before you start.** The current build has a
> three-axis access model (capability × scope × resolution) and redacts ticket
> detail for corporate tiers. Collapsing to two levels makes that redaction and
> the per-section scoping dead code. Delete it rather than leaving it switched
> off — half-removed access control is worse than none, because the next person
> cannot tell which rules still apply.

---

## What already works — do not rebuild these

- Sign-in with an employee ID and a 6-digit PIN, with lockout after repeated
  failures
- Raising a breakdown in about thirty seconds, by scanning the machine's QR
  label or typing its code
- The full ticket lifecycle: raised → acknowledged → repair → running again →
  root cause → verified and closed
- Guided why-why root cause with a quality score that rejects useless entries
  like "belt issue"
- Works fully offline; queues everything and reconciles when signal returns
- Dashboard charts: downtime Pareto by cause, daily downtime trend, worst
  machines, repair-time trend, an isometric plant map, production quality
- Interface in English, Hindi and Hinglish, including machine sections and
  categories
- Excel register import with a dry run that shows what would change before
  anything is saved, and safe re-upload
- A nightly Excel workbook with the plant's existing column headers preserved

---

## What to build

### 1. Add `design` to production logging

Production is logged per machine per day. Today it captures:

`date · machine · shift · size · texture · thickness · produced · rejected · reject reason`

**Add `design`** — the décor name, e.g. *Walnut Oak*.

It must be picked from a **master list**, not typed free-text. Add a `designs`
master alongside the existing sections, categories and reject reasons, with
add/edit/deactivate for dashboard users, and Hindi and Hinglish name columns
like the others have.

> **Fix the inconsistency while you are here.** `size`, `texture` and
> `thickness` are currently free-text strings on the production row, not
> masters. That is why the same texture can be spelled three ways and split
> itself across three rows in any analysis. Make all four — design, size,
> texture, thickness — masters with the same shape. This is the difference
> between the reject analysis working and looking like it works.

### 2. Impregnation — log the paper roll

**This is the most valuable data in the plant, and it is currently not
recorded anywhere.**

The impregnation line takes a base paper roll, passes it through a resin bath,
dries it, and cuts it. Everything downstream inherits what happens here. In
particular: **blistering in the press is mostly caused upstream, at
impregnation, not by the press itself.** Residual volatiles flash to vapour
under the hot platen and lift the layers. So the two numbers below — RC and VC
— are the control parameters for a defect that currently gets blamed on the
press and "fixed" by re-plating the wrong machine.

Add a **separate log for impregnation**, one entry per roll. Not extra fields
on the sheet-production form: a roll is measured in metres and kilograms, a
sheet in units, and folding them together would show a Press operator eight
empty paper fields they will never fill.

Each entry records:

**Identity**

| Field | Notes |
| --- | --- |
| Date | |
| Machine | The impregnator — IMP-1 … IMP-12 |
| Shift | |
| Roll / batch number | **The key to everything in section 3.** Must be unique. |

**Incoming paper — before drying**

| Field | Unit | Notes |
| --- | --- | --- |
| GSM | g/m² | Base paper weight |
| Thickness before drying | **mm** | Three decimals — décor paper is 0.08–0.25 mm |
| Paper grade | — | **From a master list** |
| Paper company | — | **From a master list** — the supplier |

**Treated paper — after drying**

| Field | Unit | Notes |
| --- | --- | --- |
| Cut size | — | From the size master |
| Thickness after drying | **mm** | Three decimals |
| **RC — resin content** | % | Resin pickup |
| **VC — volatile content** | % | **The blister number.** Too high and the sheet blisters in the press. |

Two new masters, same shape as the others (add / edit / deactivate, with Hindi
and Hinglish names): **paper grades** and **paper companies**.

#### Spec limits and live alerts

Each paper grade carries a **minimum and maximum for RC and for VC**, set by
dashboard users.

When an operator logs a roll outside those limits, **warn immediately, on the
screen, at the moment of entry** — while the roll is still on the floor and
before it reaches the press. Do not merely colour it red on a chart tomorrow.

This is the whole point. A chart that tells you last week's VC was high is a
post-mortem. A warning that tells you *this roll* is out of spec is prevention,
and it is the difference between recording scrap and preventing it.

The warning must not block the entry. If the operator says the reading is what
it is, it gets saved, flagged, and shown on the dashboard as an out-of-spec
roll. Never make someone choose between an honest number and getting on with
their shift — that is how data quality dies.

### 3. Traceability — connect the roll to the sheet

When production is logged at the press, the operator also selects the **roll /
batch number** the sheets came from.

That single field is what makes this system able to answer a question no
maintenance product can:

> A batch blistered. Which impregnation run produced the paper, on which
> machine, on which shift, from which supplier's stock — and is the rest of
> that roll still in the plant?

Build it so it can be walked in both directions:

- **From a reject, backwards** — pick a bad batch of sheets, see the roll, its
  RC and VC, the impregnator, the shift, the paper grade and the supplier
- **From a roll, forwards** — pick a roll, see every sheet pressed from it and
  how many were rejected

Then show the correlation the plant actually needs: **reject rate against VC,
against RC, and against supplier.** If out-of-spec VC produces more blistering,
this proves it with the plant's own numbers rather than asserting it.

Make the roll field on the press form fast — recent rolls first, searchable,
scannable if the roll carries a label. An operator will not scroll a list of
four hundred roll numbers, and a field people skip is a field that breaks the
whole chain.

### 4. Machine performance analysis

The point of collecting the above. For each machine, show together:

- Sheets produced and sheets rejected
- Reject rate, and which reasons drive it
- Reject rate broken down by **design**, size, texture, thickness and shift
- For impregnators: RC and VC over time, and how often that machine runs out of
  spec
- Downtime hours and number of breakdowns
- Time between failures, and time to repair

The question this must answer in one screen: *which machine is worst, and is it
worst because it breaks down or because it produces scrap?* Those are different
problems with different fixes, and today a reader has to hold numbers from four
charts in their head to tell them apart.

### 5. One Excel in — never twice

Today someone uploads the register in the app, and believes they must upload it
again for the dashboard.

**They do not, and they never did — the app and the dashboard read the same
database.** One upload already feeds both. This is a communication failure, not
an architecture one, so fix it in the interface rather than in the plumbing:

- Make the import screen say plainly that one upload feeds everything
- After an import, show what changed on the dashboard, so the person who
  uploaded can see it landed
- Show the dashboard's data age everywhere it matters — "register last imported
  2 hours ago" — and warn clearly when it is more than a day stale
- Make absolutely sure there is no second upload control anywhere

### 6. One Excel out — updated daily, three places

Today the export writes a new dated file every night. Replace that with **one
canonical file that updates daily**, delivered to all three of:

1. **A shared drive** — Google Drive or OneDrive. Same file, overwritten each
   night, so the **link never changes**. Everyone's bookmarks and pivot tables
   keep working.
2. **A download button on the dashboard** — always serves the latest, needs no
   cloud account.
3. **A daily email** — to a list of recipients an admin manages, with the file
   attached.

Requirements:

- **Exactly one file.** Not a new file per day. Overwrite in place.
- **Keep the existing column headers exactly as they are**, including their
  quirks — leadership's pivot tables reference them by name and will break
  silently if a header is "tidied".
- It must contain everything: breakdowns, production, machine summary, and the
  KPIs.
- If a night's run fails, the previous file must stay intact and somebody must
  be told. A silently stale file that looks current is worse than a missing one.

---

## Rules that must not be broken

1. **Offline first.** No action on the floor may wait for the network. The
   phone saves locally and syncs later.
2. **Never invent a number.** If an input is missing, say so on screen instead
   of showing an estimate. The dashboard currently refuses to show a rupee cost
   of downtime because no hourly rate has been supplied — keep that behaviour
   and apply it to anything new.
3. **Never guess at import.** An unknown machine code is reported with its row
   number, never matched to the nearest similar machine.
4. **Synthetic data only** until the plant approves real data in writing.
5. **All three languages, everywhere.** Every new string — including new master
   names and any new error message — must exist in English, Hindi and Hinglish
   before it ships.
6. **Machine codes stay in Latin script.** `Press-4` is painted on the machine.
   Translating it would send a technician to an asset that is not labelled that
   way.

---

## Still needed from the plant

These block features that are otherwise built:

1. **Hourly downtime cost per machine** — unlocks every rupee figure
2. **Real shift timings** — currently a placeholder 3×8
3. **Machine criticality A/B/C** — drives response targets
4. **Scheduled production hours** — turns availability into a real OEE figure
5. **The design / size / texture / thickness master lists** — the actual values
   used in the plant
6. **The paper grade and paper supplier lists**
7. **RC and VC min/max for each paper grade** — without these the alert in
   section 2 cannot fire, and that alert is the most valuable thing here
8. ~~Confirm the units~~ — **answered: millimetres.** GSM in g/m², thickness in
   mm to three decimals, RC and VC as percentages
9. **Where the roll number comes from** — is it already printed or written on
   the roll today, or does the plant need to start labelling them? If nobody
   marks rolls yet, section 3 needs that habit to exist first.
10. **One real breakdown register file** — to prove the import against
11. **Written approval** before any real plant data leaves the building

---

## How to verify

Before calling any of this done:

- An app user can sign in, raise a breakdown, and log production — and cannot
  reach the dashboard
- A dashboard user can do all of that plus open the dashboard and import
- The header shows no name and no role
- Logging production requires picking a design from the list
- An impregnator roll can be logged with GSM, both thicknesses, grade,
  supplier, cut size, RC and VC
- Logging a roll with VC above its grade's limit warns on screen straight away,
  and still saves when the operator confirms
- A press production entry can name the roll it came from
- From a rejected batch you can reach the roll's RC and VC in one step, and
  from a roll you can reach every sheet made from it
- One Excel upload updates the dashboard, with no second upload anywhere
- The nightly job overwrites one file, and that same file arrives by email and
  downloads from the dashboard
- Switching to Hindi leaves no English text on screen except machine codes
- Tests, type checks and the locale parity check all pass
