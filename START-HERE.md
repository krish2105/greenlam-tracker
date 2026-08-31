# Start here

You have been sent the **Greenlam Tracker** — a maintenance and production
system for a laminate plant. This file gets it running on your machine.

**If you are presenting this to a panel, open `docs/demo-runbook.html` in your
browser first.** It has the full setup, a timed twelve-minute demo script, and
the answers to the questions a board will ask. This file is just the fast path.

---

## 1. Install four things

| Need | Check it is there with |
| --- | --- |
| Python 3.12+ | `python3 --version` |
| Node.js 20+ | `node --version` |
| PostgreSQL 16+ | `psql --version` |
| Git | `git --version` |

**macOS** — one line:

```
brew install python@3.12 node postgresql@16 git && brew services start postgresql@16
```

**Ubuntu / WSL**:

```
sudo apt update && sudo apt install -y python3.12 python3.12-venv nodejs npm postgresql git
sudo service postgresql start
```

**Windows** — install each from its own site, ticking **"Add to PATH"** on the
Python installer:

- Python 3.12+ — <https://python.org/downloads>
- Node.js 20+ — <https://nodejs.org>
- PostgreSQL 16+ — <https://postgresql.org/download/windows> (remember the
  password you set for the `postgres` user, you will be asked for it)
- Git — <https://git-scm.com/download/win>

Then reopen PowerShell so the new PATH takes effect.

---

## 2. Run it — one command

**macOS or Linux** — open a terminal in this folder:

```
./setup.sh
```

**Windows** — open PowerShell in this folder:

```
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

That checks your machine, creates the database, installs everything and fills
it with demo data. It takes a few minutes the first time and tells you exactly
what is wrong if something is missing. Run it once.

Then, every time you want the app:

```
./run.sh
```

On Windows:

```
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

That starts both servers and prints the address. **Ctrl-C stops everything.**

Now open <http://localhost:5173>.

<details>
<summary>If the scripts will not run</summary>

On macOS or Linux, make them executable first:

```
chmod +x setup.sh run.sh
```

On Windows, use WSL. If you would rather do it by hand, the same steps are:

```
createdb greenlam
cd api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://$USER@localhost:5432/greenlam"
export JWT_SECRET="local-dev-secret-padded-out-to-32-bytes-ok"
export PIN_PEPPER="local-dev-pepper-padded-out-to-32-bytes-ok"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --port 8000
```

then, in a second terminal from this folder, `npm install && npm run dev`.

</details>

---

## 3. Sign in

There are **two access levels**, not ten roles:

- **App** — everyone on the floor. Report breakdowns, log production, log paper
  rolls. That is the whole job.
- **Dashboard** — a named few. Everything above, plus the dashboard, the Excel
  import and the master lists.

| Employee ID | PIN | Level | Use it for |
| --- | --- | --- | --- |
| `EMP002` | `573014` | Dashboard | **Start here.** Sees everything. |
| `EMP004` | `746092` | App | The floor view — no dashboard tab at all |
| `EMP001` | `481920` | Dashboard | A second dashboard holder |
| `EMP005` | `819473` | App | A second floor user |

Seven accounts in total; the seed prints all of them when it runs.

Sign in as `EMP004` once. The point is what is **missing** — no Dashboard tab,
no Import tab. Access is not a setting somebody forgot to switch on; the tabs
are not there.

---

## 4. Check it actually worked

1. Sign in as `EMP002` / `573014` → you land on **"4 things need you"**
2. Click **Dashboard** → six numbers, a plant map, four charts
3. **Click a block on the plant map** → a strip appears at the top joining that
   machine's downtime, MTBF, reject rate and quality lift
4. Scroll to **Machine by machine** → switch to **Impregnation** → it should say
   out-of-spec paper rejects about 44% more
5. Click **हिं**, top right → the whole interface turns Hindi
6. Scroll to the bottom of the dashboard → **The register workbook** → click
   **Download**. A real .xlsx should save, with the same columns as the register.
7. Click **Setup** → 33 machines, both counters at **0 / 33**. Type `38000`
   and `16` in the two "fill every machine at once" boxes, press each **Apply
   to all** → both bars fill green
8. Go back to **Dashboard** → the withheld rupee line has become
   **₹2,10,85,198 lost to downtime**, and the Reliability captions have
   changed from "Calendar hours" to "Scheduled production hours"
9. Sign out, sign in as `EMP004` / `746092` → **no Dashboard tab**

All nine working means you are ready.

> The download needs a workbook to exist. `./setup.sh` does not build one — run
> `cd export && python build_workbook.py` once, or the button will honestly say
> nothing has been built yet.

---

## 5. Install it as an app on a phone

It is a proper installable app — no app store, no download, no 30% cut.

Use `--phone`, not the normal command:

```
./run.sh --phone
```

On Windows:

```
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Phone
```

**Why a different command.** The everyday `./run.sh` runs a development server,
and the development server has **no service worker at all**. An app installed
from it looks installed, opens without browser chrome, and then shows a browser
error page the moment there is no signal — the offline shell was never there.
The service worker only exists in a production build, so `--phone` builds the
app first and serves the build. Testing the offline promise means testing the
build, or you are testing nothing.

The command then prints the phone steps. In short:

1. On the phone: Settings → About phone → tap **Build number** seven times,
   then Settings → System → Developer options → **USB debugging** on
2. Plug in the cable and tap **Always allow** on the prompt
3. On the computer, in Chrome: `chrome://inspect/#devices` → tick **Discover
   USB devices** → **Port forwarding…** → add `4173` → `localhost:4173`, and
   tick **Enable port forwarding**
4. On the **phone**, open `http://localhost:4173`
5. Chrome menu → **Add to Home screen**

**It has to be `localhost`, not your computer's LAN IP.** Service workers only
run on a secure origin, and a plain `http://192.168.x.x` address is not one.
Over the LAN the app loads perfectly and simply never becomes offline-capable —
which looks like success until you switch the wifi off. The USB port forwarding
makes it the phone's *own* localhost, which does count as secure. A real
deployment behind HTTPS has none of this problem.

### Proving it actually works offline

The order matters — most of these steps pass for the wrong reasons if you
shuffle them.

1. Sign in as `EMP004` / `746092` (the floor view)
2. Add to Home screen, then open it **from the home screen icon**
3. Let it sit for ten seconds so the service worker finishes caching
4. **Aeroplane mode on**
5. Swipe the app fully closed, then reopen it from the icon — a **cold start
   with no network**. This is the real test; a warm reload proves very little.
6. Raise a ticket. It should save, and the outbox banner should say it is
   waiting.
7. Switch to Hindi. The Devanagari font is precached, so the text must stay
   text and not turn into boxes.
8. **Aeroplane mode off.** The banner clears on its own and the ticket appears
   on the dashboard.

---

## If something breaks

**Every account says "Employee ID or PIN is incorrect."**
`PIN_PEPPER` differed between seeding and serving — it is mixed into every PIN
hash. `setup.sh` and `run.sh` set the same value, so this only happens if you
ran the commands by hand. Re-run `./setup.sh`.

**Nothing happens when you sign in.**
The API is not running. Check the first terminal, or open
<http://localhost:8000/api/health>.

**`createdb: command not found`**
Postgres is not on your PATH. macOS:
`export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"`

**`connection refused` on port 5432**
Postgres is not started. `brew services start postgresql@16` or
`sudo service postgresql start`.

**The dashboard is empty.**
The seed did not run. `cd api && .venv/bin/python -m app.seed --reset`

**Port already in use.**
`run.sh` clears ports 8000 and 5173 itself before starting. If you are running
by hand: `lsof -ti:5173 | xargs kill -9`, same for 8000.

### Windows only

**`python` opens the Microsoft Store instead of running.**
That is Windows' app-execution alias, a 0-byte stub. `setup.ps1` detects it and
says so. Fix it in **Settings → Apps → Advanced app settings → App execution
aliases** — turn OFF both `python.exe` entries. Then reopen PowerShell.

**"API failed to start" — but the log underneath says `Application startup
complete`.**
The API was fine; the launcher could not reach it. `localhost` on Windows
resolves to `::1` (IPv6) before `127.0.0.1`, and the API listens on IPv4 only,
so the health check talked to an address nothing was listening on. Fixed —
`run.ps1` now probes `127.0.0.1` directly and clears any system proxy first. If
you still see it, the script now tells you whether anything is actually holding
port 8000, which separates "did not start" from "started but unreachable".

**`running scripts is disabled on this system`.**
Use the full command including the flag:
`powershell -ExecutionPolicy Bypass -File .\setup.ps1`

**`psql: command not found` even though PostgreSQL is installed.**
`setup.ps1` looks in `C:\Program Files\PostgreSQL\*\bin` and adds it for the
session. If your install is elsewhere, add that `bin` folder to PATH and reopen
PowerShell.

**It asks for a PostgreSQL password.**
The one you set for the `postgres` user during installation. Passwords with
`@`, `/`, `#` or `:` are handled correctly — they are percent-encoded before
going into the connection string.

**Ctrl-C leaves the API running.**
PowerShell does not always run cleanup on Ctrl-C. `run.ps1` frees ports 8000
and 5173 on its next start, so just run it again.

More symptoms and fixes are in `docs/demo-runbook.html`.

---

## Two things to know before you show anyone

**All the data is fake.** Ninety days of generated history with realistic
structure and invented numbers. Say so early. The seeding script physically
refuses to write to any non-local database, which is why it is safe to hand
this around.

**The session expires after 30 minutes.** If you leave the board open through
a long meeting you will need to sign in again. Refresh before you present.

**The rupee figure starts switched off, on purpose.** Nobody has told the
system what an hour of downtime costs, so it refuses to print a total and says
why. The **Setup** screen is where that answer goes in — three questions, and
each one switches on a number that is currently held back. That refusal is the
part worth pointing at: a system that invents a plausible cost is worse than
one that admits it does not know.

**The impregnation numbers are the interesting part.** RC and VC are the two
readings that predict a blister in the press. Log a roll from the floor screen
with VC above 7% and the warning fires while you type — before the paper ever
reaches the press. That is the one thing here that prevents a defect rather
than counting one.

---

## What else is in here

| File | What it is |
| --- | --- |
| `docs/sample-breakdown-register.xlsx` | **A sample Excel register — use this to demo the Import screen.** Drag it onto the drop zone. Then drop it a second time: it will create zero, because re-importing is safe. |
| `docs/BUILD-PROMPT.md` | The specification everything here was built from |
| `docs/demo-runbook.html` | Setup + the twelve-minute demo script + hard questions |
| `docs/master-plan.html` | The business case, for a board |
| `README.md` | Every engineering decision and why |
| `http://localhost:8000/api/docs` | Live API explorer, once the server is up |

If the panel is technical, run the tests on screen. It takes a minute and
prints `129 passed`, which answers "is this production quality" better than
any slide:

```
cd api && .venv/bin/python -m pytest -q
```
