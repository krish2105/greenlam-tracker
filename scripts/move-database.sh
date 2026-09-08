#!/usr/bin/env bash
#
# Move the Greenlam database to a new Postgres, with the data.
#
#   scripts/move-database.sh "$SOURCE_URL" "$TARGET_URL"
#
# Both are plain `postgresql://` connection strings — NOT the SQLAlchemy
# `postgresql+psycopg://` form the app uses. Strip the `+psycopg` if you copy
# one out of the app's environment.
#
# WHY THIS IS A SCRIPT AND NOT A PARAGRAPH IN A README
#
# It will be run once, under time pressure, by somebody who has not read the
# schema — most likely on the day the current database is about to expire. The
# three things that go wrong are: dumping ownership statements the new server
# rejects, restoring into a database that already has tables, and declaring
# success without looking. All three are handled here.
#
# It does NOT switch the app over. That is a separate, deliberate act: change
# DATABASE_URL, redeploy, check the app, and only then delete anything.

set -euo pipefail

SOURCE="${1:-}"
TARGET="${2:-}"

if [ -z "$SOURCE" ] || [ -z "$TARGET" ]; then
  echo "usage: $0 <source-url> <target-url>" >&2
  echo >&2
  echo "  Both plain postgresql:// URLs. Strip '+psycopg' if present." >&2
  exit 64
fi

for url in "$SOURCE" "$TARGET"; do
  case "$url" in
    *+psycopg*)
      echo "That is a SQLAlchemy URL. Remove '+psycopg' and try again:" >&2
      echo "  ${url/+psycopg/}" >&2
      exit 64
      ;;
  esac
done

DUMP="$(mktemp -t greenlam-move-XXXXXX).sql"
trap 'rm -f "$DUMP"' EXIT

echo "==> Reading the source"
# --no-owner and --no-privileges: the new server has a different superuser and
# a different role name, and GRANT statements naming a role that does not exist
# there fail the restore halfway through.
pg_dump --no-owner --no-privileges --clean --if-exists "$SOURCE" > "$DUMP"
echo "    $(wc -c < "$DUMP" | tr -d ' ') bytes"

echo "==> Checking the target is empty"
EXISTING=$(psql "$TARGET" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
if [ "$EXISTING" != "0" ]; then
  echo "    The target already has $EXISTING table(s)." >&2
  echo "    Refusing — restoring on top of an existing database is how two" >&2
  echo "    half-migrations end up looking like one finished one." >&2
  exit 1
fi

echo "==> Writing to the target"
psql --quiet --set ON_ERROR_STOP=on "$TARGET" -f "$DUMP" > /dev/null

echo "==> Checking what arrived"
psql "$TARGET" -tAc "
  SELECT 'alembic       ' || version_num FROM alembic_version
  UNION ALL SELECT 'machines      ' || count(*) FROM machines
  UNION ALL SELECT 'users         ' || count(*) FROM users
  UNION ALL SELECT 'tickets       ' || count(*) FROM tickets
  UNION ALL SELECT 'production    ' || count(*) FROM production_logs
  UNION ALL SELECT 'plant_settings' || ' ' || count(*) FROM plant_settings
" | sed 's/^/    /'

echo
echo "Done. The app is still pointed at the OLD database."
echo
echo "Next, in this order:"
echo "  1. Set DATABASE_URL to the new one (add '+psycopg': postgresql+psycopg://...)"
echo "  2. Redeploy"
echo "  3. Sign in and check the machine list and a ticket"
echo "  4. Only then let the old database go"
