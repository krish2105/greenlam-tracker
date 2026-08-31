# Phase 0 Action Pack
## Greenlam Maintenance & Production Intelligence System

Companion to `GREENLAM-TRACKER-BUILD-SPEC.md`. This covers the next 7 days.

---

## 1. The IT hosting question — how to find who to ask

You don't need to know the right person. You need to ask the right person *to tell you* who the right person is. That's a much easier question, and asking it correctly is also good politics.

### 1.1 Go through your sponsor, not around them

**Start with whoever assigned you this project.** Ask them one question:

> "Who owns IT infrastructure approvals here? Before I finalise the architecture I need to confirm whether plant data can sit on external cloud services, or whether it has to stay on company infrastructure. I'd rather find that out now than rebuild later."

That sentence does three jobs: it gets you the name, it signals you're thinking about compliance unprompted, and it puts the risk on record early rather than surfacing it in week eight. Going directly to IT without telling your sponsor is the classic intern mistake — in most Indian manufacturing companies it reads as going over someone's head, and you'll pay for it later.

### 1.2 If your sponsor doesn't know, these are the people who will

In rough order of how likely they are to give you a real answer:

| Who | Why them |
|---|---|
| **Plant SAP / ERP coordinator** | Usually the fastest genuine answer. This person already handles what data leaves the plant and knows the actual policy, not the theoretical one. Almost every plant of this size has one. |
| **Plant IT Manager / IT Executive** | The formal owner of the question. May need to escalate to corporate. |
| **Corporate Head of IT / CIO** (Greenlam Industries HQ) | Where the actual written policy lives. Slow, and you'd normally reach them via the plant IT manager rather than directly. |
| **Whoever administers company email and laptops** | Even if they can't approve, they know who can, and they know whether the company is on Microsoft 365 or Google Workspace — which you also need. |

Practically: walk to the plant IT room and ask in person. You'll get a straighter answer in five minutes than in two weeks of email. Take your sponsor's name with you.

### 1.3 Message to send

Keep it short and make it easy to say yes. Long emails asking for policy decisions get deferred.

> **Subject:** Quick infrastructure question — maintenance tracking project
>
> Hi [Name],
>
> I'm building the maintenance and production tracking system for [unit/section], assigned by [sponsor's name].
>
> Before I lock the architecture, I need to confirm one thing: can plant operational data (breakdown logs, production counts, machine names) be stored on an external cloud service, or does it need to stay on company infrastructure?
>
> I've designed it so either option works — it's containerised and can run on an internal server just as easily — but the answer changes what I build this month, so I'd rather ask now.
>
> If it's easier, five minutes in person works too. And if this isn't your call, could you point me to who decides?
>
> Thanks,
> Krishna

### 1.4 The full list to ask once you have them

Don't waste the meeting on one question. Bring all eight:

1. Can plant operational data be stored on external cloud services, or is company infrastructure required?
2. Is there a data-residency requirement (India region only)?
3. Is there an approved cloud-vendor list I should work from?
4. If external hosting isn't allowed — is there an internal server or VM I could deploy a container to?
5. Who signs off, and what's the typical turnaround?
6. Is the company on **Microsoft 365 or Google Workspace**? *(Decides where the nightly Excel file lands — a shared folder is much better than email.)*
7. Is there a company **Apple Developer** or **Google Play** account? *(Needed later for the native app, not for the pilot.)*
8. What's the Wi-Fi situation in the production halls — is there coverage, and can devices connect to it or only to a guest network?

---

## 2. Don't wait for the answer — build so it doesn't matter

You should not lose a week blocked on this. The mitigation is to make the hosting decision a *deployment* choice rather than an *architecture* choice.

**Rules to follow from commit one:**

1. **`docker-compose.yml` from day one.** API + Postgres + dashboard, all running locally with one command. If IT says on-prem, deployment becomes `docker compose up` on their VM instead of a Render deploy. Same code.
2. **Plain PostgreSQL only.** No Neon-specific features, no Supabase Auth, no managed-service lock-in in the core path. Your connection string must be swappable for a plain Postgres instance.
3. **Everything through environment variables.** No hardcoded URLs, no hardcoded bucket names, no hardcoded email addresses.
4. **Object storage behind an interface.** One `StorageBackend` class with an R2 implementation and a local-filesystem implementation. On-prem swaps the implementation, nothing else.
5. **Synthetic data until you have approval in writing.** Build and demo with realistic fake data. No real Greenlam machine names, downtime figures, or employee names touch an external server until someone with authority has said yes. This is the single most important line in this document — it keeps you personally clean regardless of how the policy question lands.
6. **The PWA choice already hedges this.** A website served from a plant intranet server needs zero code changes. This is a real reason the PWA decision was the right one.

If the answer comes back "on-prem only," your cost drops to ₹0 permanently and your architecture barely moves. If it comes back "cloud is fine," you deploy to Render and Neon as specced. Either way you were building the same thing.

---

## 3. Week 1, day by day

You're solo and full-time, so the constraint isn't hours — it's making sure the hours go into discovery rather than into code you'll throw away. Resist opening the editor until Day 4.

**Day 1 — People and permission**
- Meet your sponsor. Confirm the pilot unit, the executive sponsor, and the one number they want to improve.
- Ask the "who owns IT approvals" question.
- Get the current Excel register file. The actual one, with real data in it, not a blank template.

**Day 2 — The floor**
- Spend a full shift on the floor. Not an hour. A shift.
- Watch what actually happens when a machine stops: who notices, who they tell, how, how long before a technician arrives, what gets written down and when.
- Time it. If the informal process takes 40 seconds and your app takes 90, your app loses.
- Check phone signal and Wi-Fi in every hall, especially near the presses. Note the dead zones.
- Identify your two champions — the operator and the technician everyone else listens to.

**Day 3 — Masters and numbers**
- Walk the machine list physically. Confirm every code in the prototype exists, find the ones missing, note existing asset tags.
- Get shift timings, production targets, and reject-reason vocabulary as people actually say it.
- Get an hourly downtime cost per machine or per section from production or finance. A rough number is fine. No number is not.
- Ask what `sheets_after_sanding` means and where it applies.

**Day 4 — Freeze and set up**
- Write a one-page scope freeze and get your sponsor to acknowledge it in writing (email is enough). List what's in the pilot and what's explicitly Phase 2.
- Create the repo. Drop in `PROJECT_BRIEF.md` (the build spec), the reference `.jsx` prototype, and the real Excel register.
- Open Claude Code and run Phase 1 from the starter prompt in Section 11 of the spec.

**Day 5 — Foundation**
- Schema, migrations, Docker Compose, seed script loaded with the *verified* machine list.
- Get the API deployed and reachable, even if it does almost nothing. Deploying early and often beats a big-bang deploy in week eight.

**Days 6–7 — Auth and masters, then demo**
- PIN login, roles, masters CRUD.
- Show one of your champions something on their phone by end of week 1, even if it's a login screen and a list of machines. Early visible progress is how you keep a sponsor engaged for fifteen weeks.

---

## 4. Two things that will decide this project, and neither is technical

**Adoption is the whole game.** A maintenance system that operators route around has failed no matter how good the dashboard is. The single metric to track from pilot day one is: *breakdowns logged in the app ÷ breakdowns that actually happened* (cross-check against the paper register for the first month). If that number is below 80% by week three, stop adding features and go find out why. It will almost always be friction in the raise-ticket flow or a person who feels the system was imposed on them.

**Root-cause quality decays fast.** Within two weeks, "machine stopped" and "belt issue" will start appearing in the root cause field, and once that happens the analytics are worthless. Design against it: three prompted why-levels instead of one free-text box, a supervisor verification step before close, and show the technician their own previous entries for that machine so repetition is visible to them. This is worth more engineering effort than any chart on the dashboard.
