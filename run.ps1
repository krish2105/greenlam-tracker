# Starts the API and the app together on Windows. Ctrl-C stops both.
#
# Run .\setup.ps1 once first.
#
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#
# Add -Phone to serve the BUILT app instead of the dev server, for testing on
# a real phone. `npm run dev` has no service worker at all (the PWA plugin's
# devOptions are off), so an app installed from the dev server looks installed
# and has no offline shell whatsoever:
#
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Phone

param([switch]$Phone)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$appPort = if ($Phone) { 4173 } else { 5173 }

# MUST match setup.ps1. PIN_PEPPER is mixed into every PIN hash; if these
# differ from the values used at seed time, every sign-in fails.
$env:JWT_SECRET = 'local-dev-secret-padded-out-to-32-bytes-ok'
$env:PIN_PEPPER = 'local-dev-pepper-padded-out-to-32-bytes-ok'
if (-not $env:PGUSER) { $env:PGUSER = 'postgres' }
if (-not $env:PGPASSWORD) {
  $secure = Read-Host 'PostgreSQL password for user "postgres"' -AsSecureString
  # NetworkCredential, not Marshal.PtrToStringAuto. `Auto` resolves to UTF-16
  # on Windows and UTF-8 elsewhere, so under WSL or PowerShell on Linux it
  # truncates a BSTR at the first null byte — "P@ssw0rd" becomes "P", and what
  # you see is an authentication failure that looks exactly like a wrong
  # password. This is correct on every platform and frees the buffer itself.
  $env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $secure).Password
}
# The password goes into a URL, so it has to be percent-encoded. Verified
# failing case: "P@ssw0rd" — one of the commonest passwords anyone sets — makes
# the @ read as the host separator and the whole connection string collapses.
# "a/b#c" breaks the same way. The error you get is about the host, which sends
# you looking in entirely the wrong place.
$pgUserEsc = [Uri]::EscapeDataString($env:PGUSER)
$pgPassEsc = [Uri]::EscapeDataString($env:PGPASSWORD)
$env:DATABASE_URL = "postgresql+psycopg://${pgUserEsc}:${pgPassEsc}@localhost:5432/greenlam"

function Die ($m) { Write-Host "`n  [x] $m`n" -ForegroundColor Red; exit 1 }

if (-not (Test-Path api\.venv))   { Die 'Not set up yet. Run .\setup.ps1 first.' }
if (-not (Test-Path node_modules)) { Die 'Not set up yet. Run .\setup.ps1 first.' }

# Free the ports if a previous run was killed rather than stopped. An orphaned
# uvicorn on 8000 is exactly the "it worked yesterday" failure to avoid.
# Get-NetTCPConnection is missing on some older or trimmed Windows builds, so
# netstat is the fallback. Failing to free a port is not worth stopping for —
# uvicorn will say the address is in use, which is a clear enough message.
foreach ($port in 8000, $appPort) {
  try {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
      Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
          Write-Host "  freeing port $port"
          Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } else {
      netstat -ano | Select-String ":$port\s.*LISTENING" | ForEach-Object {
        $procId = ($_ -split '\s+')[-1]
        if ($procId -match '^\d+$') {
          Write-Host "  freeing port $port"
          Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
      }
    }
  } catch { }
}

Write-Host 'Greenlam Tracker  build 2026-08-27-a' -ForegroundColor DarkGray
Write-Host "`nStarting the API" -ForegroundColor White
# --host 127.0.0.1 explicitly, so the address it binds is the address we probe.
# It is uvicorn's default, but leaving it implicit is what let the probe and
# the server disagree about what "local" means.
$api = Start-Process -PassThru -NoNewWindow -FilePath ".\api\.venv\Scripts\python.exe" `
  -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory "$PSScriptRoot\api" `
  -RedirectStandardOutput "$env:TEMP\greenlam-api.log" -RedirectStandardError "$env:TEMP\greenlam-api.err"

# Probe 127.0.0.1, NOT localhost.
#
# On Windows `localhost` resolves to ::1 (IPv6) before 127.0.0.1, and uvicorn
# binds IPv4 only. Windows PowerShell 5.1's HTTP stack does not fall back to
# the second address, so the probe fails against a server that is running
# perfectly. The symptom is this script printing "API failed to start"
# directly underneath a log that says "Application startup complete" — which
# sends you looking for a bug in the API, where there isn't one.
#
# Clearing DefaultWebProxy covers the other way this fails: on a machine with
# a corporate or PAC proxy, Invoke-WebRequest sends even loopback through it
# unless "bypass proxy for local addresses" happens to be ticked.
[System.Net.WebRequest]::DefaultWebProxy = $null

$up = $false
$probeErr = 'no attempt was made'
foreach ($i in 1..40) {
  try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2 | Out-Null
    $up = $true; break
  } catch { $probeErr = $_.Exception.Message; Start-Sleep -Milliseconds 500 }
  if ($api.HasExited) { break }
}
if (-not $up) {
  # Say WHICH of the two things went wrong, rather than blaming the API for
  # both. "Listening but unreachable" and "never started" need opposite fixes.
  $listening = $false
  try {
    $probe = New-Object System.Net.Sockets.TcpClient
    $probe.Connect('127.0.0.1', 8000)
    $listening = $probe.Connected
    $probe.Close()
  } catch { }

  if ($listening) {
    Write-Host '  The API IS running and holding port 8000, but this script could not talk to it.' -ForegroundColor Red
    Write-Host '  That is a networking problem on this machine, not a problem with the API code.'
    Write-Host "  Last error from the probe: $probeErr"
    Write-Host ''
    Write-Host '  The API is still running, so you can test it directly right now.'
    Write-Host '  Run these two lines and send back what each one prints:'
    Write-Host '     Invoke-WebRequest http://127.0.0.1:8000/api/health -UseBasicParsing'
    Write-Host '     Invoke-WebRequest http://localhost:8000/api/health -UseBasicParsing'
    Write-Host '  If the first works and the second does not, it is the IPv6 name lookup.'
  } else {
    Write-Host '  The API did not start. Nothing is listening on port 8000.' -ForegroundColor Red
    Write-Host "  Last error from the probe: $probeErr"
    Write-Host '  Last lines of the log:'
    Get-Content "$env:TEMP\greenlam-api.err" -Tail 20 -ErrorAction SilentlyContinue
    Get-Content "$env:TEMP\greenlam-api.log" -Tail 20 -ErrorAction SilentlyContinue
  }
  exit 1
}
Write-Host "  [ok] API is up on :8000  (log: $env:TEMP\greenlam-api.log)" -ForegroundColor Green

try {
  if ($Phone) {
    Write-Host "`nBuilding the app (the real service worker only exists in a build)" -ForegroundColor White
    # Rollup's chunk-size notes go to stderr and read like errors to anyone who
    # did not write them. Keep them in a log; show them only on a real failure.
    $buildLog = Join-Path $env:TEMP 'greenlam-build.log'
    & npm run build --silent *> $buildLog
    if ($LASTEXITCODE -ne 0) {
      Write-Host "`n  Build failed:" -ForegroundColor Red
      Get-Content $buildLog -Tail 30
      exit 1
    }
    Write-Host "  [ok] built  (log: $buildLog)" -ForegroundColor Green

    Write-Host "`nServing the built app for a phone" -ForegroundColor White
    Write-Host @'
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
  and a plain http:// LAN address is not one - the app would load and silently
  never go offline-capable. Port forwarding makes it the phone's own localhost,
  which counts.
'@
    Write-Host "  Sign in as EMP004 / 746092 for the floor view.   Ctrl-C stops everything`n"
    & npm run preview --workspace '@greenlam/dashboard' -- --host 0.0.0.0 --port 4173
  }
  else {
    Write-Host "`nStarting the app - open http://localhost:5173" -ForegroundColor White
    Write-Host "  Sign in as EMP002 / 573014        Ctrl-C stops everything`n"
    & npm run dev
  }
}
finally {
  if ($api -and -not $api.HasExited) {
    Write-Host "`n  stopping..."
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
  }
}
