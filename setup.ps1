# One-time setup on Windows. PowerShell 5.1 or newer.
#
# The mirror of setup.sh, and it fails the same way: loudly and early. The
# worst version of this script is one that half-works and leaves you debugging
# a blank dashboard twenty minutes later.
#
# Run it from this folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# These two must match between seeding and serving. PIN_PEPPER is mixed into
# every PIN hash, so a mismatch makes every account fail to sign in with no
# useful error. run.ps1 exports the identical values.
$env:JWT_SECRET = 'local-dev-secret-padded-out-to-32-bytes-ok'
$env:PIN_PEPPER = 'local-dev-pepper-padded-out-to-32-bytes-ok'

function Ok  ($m) { Write-Host "  [ok] $m" -ForegroundColor Green }
function Die ($m) { Write-Host "`n  [x] $m`n" -ForegroundColor Red; exit 1 }
function Head($m) { Write-Host "`n$m" -ForegroundColor White }

# Printed so a bug report says which copy is actually running. Every time
# this has been debugged remotely, the first question has been whether the
# fix was even in the folder being run.
Write-Host 'Greenlam Tracker  build 2026-08-27-a' -ForegroundColor DarkGray

Head 'Checking what you have installed'

# Windows ships an "app execution alias" at WindowsApps\python.exe that is a
# 0-byte stub: running it opens the Microsoft Store instead of Python. It
# satisfies Get-Command, so without this check the script sails past and fails
# much later with something unrelated.
$py = $null
foreach ($name in 'python', 'python3', 'py') {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $cmd) { continue }
  if ($cmd.Source -like '*WindowsApps*') { continue }
  $py = $cmd
  break
}
if (-not $py) {
  Die @'
Python not found (or only the Microsoft Store stub is on PATH).
Install 3.12+ from https://python.org/downloads and tick "Add python.exe to PATH".
If you already did: Settings > Apps > Advanced app settings > App execution
aliases, and turn OFF both python.exe entries.
'@
}
# --version, NOT `-c "..."`.
#
# Windows PowerShell 5.1 strips the inner double quotes when it hands an
# argument to a native .exe. `-c 'print(f"{x}")'` therefore reaches Python as
# print(f{x}), which dies with "SyntaxError: invalid syntax. Perhaps you forgot
# a comma?" — an error that points at Python and reads like a bug in this
# script, on the very first check, before anything has been installed.
# --version carries no quotes at all, so there is nothing to strip.
#
# 2>&1 because a Python 2 on PATH prints its version to stderr; without it
# $pyv would be empty and the next line would fail on a null instead of saying
# which Python it found.
# try/catch because $ErrorActionPreference is 'Stop' at the top of this file:
# in PowerShell 5.1 a native command writing to stderr under `2>&1` raises a
# terminating NativeCommandError, which would replace the clear message below
# with a stack trace.
$pyv = ''
try {
  $pyv = ((& $py.Source --version 2>&1) | Out-String).Trim() -replace '^Python\s+', ''
} catch { $pyv = '' }
if ($pyv -notmatch '^\d+\.\d+') {
  Die @"
Found Python at $($py.Source), but could not read a version number from it.
It printed: $pyv

Run this yourself to see what it says:
    & "$($py.Source)" --version
"@
}
$parts = $pyv.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 12)) {
  Die "Python $pyv found, but 3.12 or newer is required."
}
Ok "Python $pyv"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die 'Node.js not found. Install 20+ from nodejs.org.' }
$nodev = (node -v).TrimStart('v')
if ([int]$nodev.Split('.')[0] -lt 20) { Die "Node $nodev found, but 20 or newer is required." }
Ok "Node $nodev"

# psql is commonly installed but off PATH on Windows — the same problem as on
# a Mac, and the error it otherwise produces says nothing about the cause.
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
  $found = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
           Sort-Object FullName -Descending | Select-Object -First 1
  if ($found) { $env:Path = "$($found.Directory.FullName);$env:Path" }
}
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
  Die 'PostgreSQL not found. Install 16+ from postgresql.org, then reopen PowerShell.'
}
Ok "PostgreSQL $((psql --version).Split(' ')[2])"

# On Windows the installer creates a `postgres` superuser rather than one named
# after you, so the connection string differs from the Unix one.
if (-not $env:PGUSER)     { $env:PGUSER = 'postgres' }
if (-not $env:PGPASSWORD) {
  $secure = Read-Host 'PostgreSQL password for user "postgres"' -AsSecureString
  # NetworkCredential, not Marshal.PtrToStringAuto. `Auto` resolves to UTF-16
  # on Windows and UTF-8 elsewhere, so under WSL or PowerShell on Linux it
  # truncates a BSTR at the first null byte — "P@ssw0rd" becomes "P", and what
  # you see is an authentication failure that looks exactly like a wrong
  # password. This is correct on every platform and frees the buffer itself.
  $env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $secure).Password
}
if (Get-Command pg_isready -ErrorAction SilentlyContinue) {
  & pg_isready -q 2>$null
  if ($LASTEXITCODE -ne 0) {
    Die 'PostgreSQL is installed but not running. Open Services and start postgresql-x64-16.'
  }
} else {
  # Not fatal on its own — psql is what actually matters, and it is already
  # confirmed above. Say so rather than stopping over a missing helper.
  Write-Host '  [!] pg_isready not found - continuing, psql will tell us soon enough' -ForegroundColor Yellow
}
Ok 'PostgreSQL is accepting connections'

Head 'Creating the database'
$exists = & psql -U $env:PGUSER -lqt 2>$null | Select-String -Pattern '^\s*greenlam\s*\|'
if ($exists) { Ok "'greenlam' already exists - leaving it alone" }
else { & createdb -U $env:PGUSER greenlam; Ok "created 'greenlam'" }

# The tests use a separate database, and the runbook suggests running them in
# front of a technical panel. Creating it here saves a confusing failure at
# exactly the wrong moment.
$testExists = & psql -U $env:PGUSER -lqt 2>$null | Select-String -Pattern '^\s*greenlam_test\s*\|'
if (-not $testExists) {
  & createdb -U $env:PGUSER greenlam_test 2>$null
  if ($LASTEXITCODE -eq 0) { Ok "created 'greenlam_test' (for pytest)" }
}
# The password goes into a URL, so it has to be percent-encoded. Verified
# failing case: "P@ssw0rd" — one of the commonest passwords anyone sets — makes
# the @ read as the host separator and the whole connection string collapses.
# "a/b#c" breaks the same way. The error you get is about the host, which sends
# you looking in entirely the wrong place.
$pgUserEsc = [Uri]::EscapeDataString($env:PGUSER)
$pgPassEsc = [Uri]::EscapeDataString($env:PGPASSWORD)
$env:DATABASE_URL = "postgresql+psycopg://${pgUserEsc}:${pgPassEsc}@localhost:5432/greenlam"

Head 'Installing the API (this is the slow part - a few minutes)'
Set-Location api
if (-not (Test-Path .venv)) { & $py.Source -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -e '.[dev]'
Ok 'Python packages installed'

& .\.venv\Scripts\python.exe -m alembic upgrade head | Out-Null
Ok 'Database tables created'

& .\.venv\Scripts\python.exe -m app.seed --reset
Set-Location ..

Head 'Installing the app'
& npm install --silent
Ok 'Node packages installed'

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "`n  Start everything with:"
Write-Host "    .\run.ps1" -ForegroundColor White
Write-Host "`n  Then open http://localhost:5173 and sign in as EMP002 / 573014`n"
