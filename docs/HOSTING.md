# Hosting: what runs where, and what has to change before 30 September

This answers the part of open question 11-A that cannot wait. It does **not**
settle 11-A itself — where Greenlam finally runs this, TCS or otherwise, is
still theirs to decide, and nothing here makes that decision harder.

## The deadline, precisely

The trial database is Render's free Postgres. It was created on **31 August
2026** and Render's free tier expires a database **30 days after creation**,
then keeps it for a **14-day grace period** before deleting it.

    30 September   the database expires
    14 October     the database and everything in it is deleted

So a trial that starts in mid-September and runs four weeks loses its data
partway through, on a date nobody is watching for.

## What the numbers actually are

Measured, not estimated.

| | |
|---|---|
| 90 days of synthetic history | **15 MB** |
| Full database dump | **136 KB** |
| Free-tier storage anywhere | 0.5–1 GB |

**Storage is not the problem and will not become one.** Three years of a
single unit's tickets and production would fit inside any free tier here. Every
option below is chosen on durability, not capacity.

## The second problem, which is not about data

Render's free *web service* sleeps after 15 minutes idle and takes about a
minute to wake. On a factory floor that is a technician tapping "report a
breakdown" next to a stopped press and watching a blank screen for a minute.
They will conclude the app is broken, and they will be nearly right.

Keeping it awake with a pinger is not a free workaround: Render grants **750
instance-hours per workspace per month**, a month is 744 hours, and this
workspace has around fifteen services. One always-on service would consume
essentially the entire allowance and suspend the rest.

The offline-first design covers part of this — a breakdown raised with no
signal queues locally and syncs later — but signing in and reading the ticket
list both need the API awake.

## Options

### Database

| | Cost | Expires | Idles | Region |
|---|---|---|---|---|
| **Neon free** | £0 | never | scales to zero, wakes on connect | Singapore / Frankfurt |
| Supabase free | £0 | never | **pauses after 7 days idle**, manual resume | Mumbai |
| Render Basic-256mb | ~$6/mo | never | always on | Singapore |

Neon is what `CLAUDE.md` names as the database from the start, and its
scale-to-zero wakes by itself on the next connection — a delay, not an outage.

Supabase pauses rather than sleeps, and a paused project stays paused until
somebody clicks resume. One of this account's own Supabase projects is already
sitting `INACTIVE`, which is the failure mode arriving in practice. During a
trial with daily use it would not trigger; across a festival break it would,
and the plant would find the app locked out on the Monday.

### App

| | Cost | Cold start |
|---|---|---|
| Render free | £0 | ~1 min after 15 min idle |
| Render Starter | $7/mo | none |

## Moving the database

`scripts/move-database.sh` does it, and has been run end to end against a real
copy of this schema:

    scripts/move-database.sh "$OLD_URL" "$NEW_URL"

It dumps without ownership or grants (a new server has a different role name
and the GRANTs fail halfway through a restore), refuses a target that already
has tables, and prints the row counts that arrived. It does **not** switch the
app over — that is deliberate:

1. Run the script
2. Set `DATABASE_URL` to the new database, with `+psycopg` back in the scheme
3. Redeploy
4. Sign in, check the machine list and raise a ticket
5. **Only then** let the old database go

## Do it now, not in three weeks

The database is currently empty apart from the machine master and one admin
account. Moving 136 KB with nothing in it is a five-minute job that can be
retried freely. Moving it in October, mid-trial, with three weeks of the
plant's real breakdown history in it, is the same job with a consequence
attached.

## What this does not decide

Whether the system finally lives on a TCS-managed server, a plant server, or a
cloud account of Greenlam's own (V5 §14, open question 11-A). Nothing above
forecloses any of them: the app is a container, the database is a connection
string, and `docker-compose.yml` has existed since the first commit precisely
so that an on-prem mandate is a deployment change rather than a rewrite.

The two things that follow the system wherever it goes are still unanswered and
still needed from Greenlam IT:

- **11-B** — who provides the TLS certificate and the stable hostname. Without
  a trusted certificate there is no installable app, no offline shell and no
  notifications, on any host.
- **Whose account.** All of this currently sits in a personal Render account.
  Before a pilot becomes a rollout, it needs to belong to Greenlam.
