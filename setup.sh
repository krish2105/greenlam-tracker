#!/usr/bin/env bash
#
# One-time setup. Installs dependencies, creates the database, migrates it and
# fills it with demo data. Run this once, then use ./run.sh every time after.
#
# Written to fail LOUDLY and EARLY. The worst version of this script is one
# that half-works and leaves you debugging a blank dashboard twenty minutes
# later — so every prerequisite is checked up front, and every step stops the
# script if it fails.

set -euo pipefail

# These two must match between seeding and serving. PIN_PEPPER is mixed into
# every PIN hash, so a mismatch makes every account fail to sign in with no
# useful error. run.sh exports the identical values.
export JWT_SECRET="local-dev-secret-padded-out-to-32-bytes-ok"
export PIN_PEPPER="local-dev-pepper-padded-out-to-32-bytes-ok"

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\n  \033[31m✗ %s\033[0m\n\n' "$1" >&2; exit 1; }

bold "Checking what you have installed"

command -v python3 >/dev/null || die "Python 3 not found. macOS: brew install python@3.12"
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' \
  || die "Python $PYV found, but 3.12 or newer is required."
ok "Python $PYV"

command -v node >/dev/null || die "Node.js not found. macOS: brew install node"
NODEV=$(node -v | tr -d 'v')
[ "${NODEV%%.*}" -ge 20 ] || die "Node $NODEV found, but 20 or newer is required."
ok "Node $NODEV"

# psql may be installed but off PATH — the single most common Postgres problem
# on a Mac, and the error it produces otherwise ("createdb: command not found")
# does not hint at the cause.
if ! command -v psql >/dev/null; then
  for d in /opt/homebrew/opt/postgresql@1[6-9]/bin /usr/local/opt/postgresql@1[6-9]/bin /Library/PostgreSQL/*/bin; do
    [ -d "$d" ] && export PATH="$d:$PATH" && break
  done
fi
command -v psql >/dev/null || die "PostgreSQL not found. macOS: brew install postgresql@16 && brew services start postgresql@16"
ok "PostgreSQL $(psql --version | awk '{print $3}')"

pg_isready -q 2>/dev/null \
  || die "PostgreSQL is installed but not running. macOS: brew services start postgresql@16   Linux: sudo service postgresql start"
ok "PostgreSQL is accepting connections"

echo
bold "Creating the database"
if psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw greenlam; then
  ok "'greenlam' already exists — leaving it alone"
else
  createdb greenlam && ok "created 'greenlam'"
fi
# The tests use a separate database and the runbook suggests running them in
# front of a technical panel. Creating it here costs nothing and saves a
# confusing failure at exactly the wrong moment.
if ! psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw greenlam_test; then
  createdb greenlam_test 2>/dev/null && ok "created 'greenlam_test' (for pytest)" || true
fi
export DATABASE_URL="postgresql+psycopg://${USER}@localhost:5432/greenlam"

echo
bold "Installing the API (this is the slow part — a few minutes)"
cd api
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"
ok "Python packages installed"

.venv/bin/python -m alembic upgrade head >/dev/null
ok "Database tables created"

.venv/bin/python -m app.seed --reset
cd ..

echo
bold "Installing the app"
npm install --silent
ok "Node packages installed"

echo
printf '\033[1m\033[32m%s\033[0m\n' "Setup complete."
echo
echo "  Start everything with:"
printf '    \033[1m./run.sh\033[0m\n'
echo
echo "  Then open http://localhost:5173 and sign in as EMP002 / 573014"
echo
