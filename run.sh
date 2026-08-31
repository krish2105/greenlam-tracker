#!/usr/bin/env bash
#
# Starts the API and the app together. Ctrl-C stops both.
#
# Run ./setup.sh once first.
#
# The two servers normally need two terminals, which is two chances to close
# the wrong window mid-demo. This runs the API in the background, the app in
# the foreground, and traps the exit so neither is left orphaned holding a port
# — an orphaned uvicorn on 8000 is exactly the "it worked yesterday" failure
# you do not want ten minutes before presenting.

set -euo pipefail
cd "$(dirname "$0")"

# --phone serves the BUILT app instead of the dev server.
#
# This is not a nicety. `npm run dev` has no service worker at all (the PWA
# plugin's devOptions are off), so an app installed from the dev server looks
# installed and has no offline shell whatsoever. Testing the offline promise
# means testing the build, or you are testing nothing.
PHONE=0
[ "${1:-}" = "--phone" ] && PHONE=1
PORT=5173
[ "$PHONE" = "1" ] && PORT=4173

# MUST match setup.sh. PIN_PEPPER is mixed into every PIN hash; if these differ
# from the values used at seed time, every sign-in fails.
export JWT_SECRET="local-dev-secret-padded-out-to-32-bytes-ok"
export PIN_PEPPER="local-dev-pepper-padded-out-to-32-bytes-ok"
export DATABASE_URL="postgresql+psycopg://${USER}@localhost:5432/greenlam"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
die()  { printf '\n  \033[31m✗ %s\033[0m\n\n' "$1" >&2; exit 1; }

[ -d api/.venv ] || die "Not set up yet. Run ./setup.sh first."
[ -d node_modules ] || die "Not set up yet. Run ./setup.sh first."

if ! command -v psql >/dev/null; then
  for d in /opt/homebrew/opt/postgresql@1[6-9]/bin /usr/local/opt/postgresql@1[6-9]/bin; do
    [ -d "$d" ] && export PATH="$d:$PATH" && break
  done
fi
pg_isready -q 2>/dev/null \
  || die "PostgreSQL is not running. macOS: brew services start postgresql@16   Linux: sudo service postgresql start"

# Free the ports if a previous run was killed rather than stopped.
for port in 8000 "$PORT"; do
  pids=$(lsof -ti:$port 2>/dev/null || true)
  [ -n "$pids" ] && { echo "  freeing port $port"; kill -9 $pids 2>/dev/null || true; }
done

API_PID=""
cleanup() {
  echo
  echo "  stopping…"
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

bold "Starting the API"
( cd api && .venv/bin/uvicorn app.main:app --port 8000 >/tmp/greenlam-api.log 2>&1 ) &
API_PID=$!

# Wait for it to answer rather than guessing with a sleep. A slow first import
# on a cold machine can take longer than any fixed delay you would pick.
for _ in $(seq 1 40); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then break; fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo; echo "  API failed to start. Last lines of the log:"; tail -20 /tmp/greenlam-api.log
    exit 1
  fi
  sleep 0.5
done
curl -fsS http://localhost:8000/api/health >/dev/null 2>&1 \
  || { echo "  API did not come up. Log:"; tail -20 /tmp/greenlam-api.log; exit 1; }

printf '  \033[32m✓\033[0m API is up on :8000  (log: /tmp/greenlam-api.log)\n'
echo
if [ "$PHONE" = "1" ]; then
  bold "Building the app (the real service worker only exists in a build)"
  # Rollup's chunk-size and dynamic-import notes go to stderr and read like
  # errors to anyone who did not write them. Keep them in a log; show them only
  # if the build actually fails.
  if ! npm run build --silent >/tmp/greenlam-build.log 2>&1; then
    echo; echo "  Build failed:"; tail -30 /tmp/greenlam-build.log; exit 1
  fi
  printf '  \033[32m✓\033[0m built  (log: /tmp/greenlam-build.log)\n\n'

  bold "Serving the built app for a phone"
  cat <<'EOF'
  On the phone:
    1. Settings > About phone > tap "Build number" 7 times
    2. Settings > System > Developer options > USB debugging ON
    3. Plug in the cable, tap "Always allow" on the prompt

  On this computer, in Chrome:
    4. Open  chrome://inspect/#devices
    5. Tick "Discover USB devices", then click "Port forwarding..."
    6. Add   4173  ->  localhost:4173   and tick "Enable port forwarding"

  Then on the PHONE open:  http://localhost:4173

  It must be localhost, not the LAN IP. Service workers need a secure origin,
  and a plain http:// LAN address is not one — the app would load and silently
  never go offline-capable. Port forwarding makes it the phone's own localhost,
  which counts.

EOF
  echo "  Sign in as EMP004 / 746092 for the floor view.   Ctrl-C stops everything"
  echo
  npm run preview --workspace @greenlam/dashboard -- --host 0.0.0.0 --port 4173
else
  bold "Starting the app — open http://localhost:5173"
  echo "  Sign in as EMP002 / 573014        Ctrl-C stops everything"
  echo
  npm run dev
fi
