# Nightly export

Builds the master workbook **on the GitHub Actions runner**, not on Render.

Render free is 512 MB / 0.1 CPU; a workbook with embedded charts will OOM or
time out there. The runner is a 2-core multi-GB machine that was already the
scheduler, so it connects straight to Postgres and Render stays asleep — which
also preserves the free instance-hours for actual users.

## The read-only role

Create it once. **Never give the runner write access.**

```sql
CREATE ROLE export_reader LOGIN PASSWORD '<from the GitHub secret>';
GRANT CONNECT ON DATABASE greenlam TO export_reader;
GRANT USAGE ON SCHEMA public TO export_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO export_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO export_reader;
```

Then set `EXPORT_DATABASE_URL` as a repository secret using that role.

## Run locally

```bash
pip install -r export/requirements.txt
EXPORT_DATABASE_URL="postgresql://greenlam:greenlam@localhost:5432/greenlam" \
  python -m export.build_workbook --out ./dist/exports
```

## Sheets

1. **KPI Summary** — this month vs last, with direction-of-good arrows, and an
   explicit list of what is *not* shown and why
2. **Charts** — native Excel charts including the downtime Pareto with a
   cumulative-% line on a secondary axis
3. **BD Tracker** — the plant's own register headers, verbatim, quirks intact
4. **Production**
5. **Machine Summary** — one row per machine, ending in a verdict
6. **Open Tickets** — with ageing buckets
7. **Event Log** — the evidence layer

## Failure is loud

The workflow asserts the file is non-trivial and fails the run otherwise.
A daily export that quietly stopped three weeks ago is worse than no export,
because people are still acting on it.
