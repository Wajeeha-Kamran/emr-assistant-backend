<#
  Starts the whole backend with one command.

  WHY THIS EXISTS
  Running the system by hand means: confirm PostgreSQL is up, open two terminals,
  remember two uvicorn commands, and hope .env is right. That is fine while you
  are already working on the backend. It is not fine when you are three hours
  into a frontend layout and a supervisor asks to see the system working.

  This is the lightweight stand-in for Module 10.1 (containerisation). Docker
  would do the same job more thoroughly, including PostgreSQL; this does the part
  that matters today, in two seconds, with nothing to install.

  IMPORTANT: --host 0.0.0.0
  By default uvicorn listens only on 127.0.0.1, which means "this machine and
  nothing else". A phone or an Android emulator cannot reach that, no matter what
  address it uses. Binding to 0.0.0.0 listens on every network interface, which
  is what lets the mobile app connect. Windows Firewall will ask for permission
  the first time -- allow it on private networks.

  THE USB CABLE
  If an Android phone is plugged in, this script also runs

      adb reverse tcp:8000 tcp:8000

  which makes port 8000 on the phone the same port here, down the cable. The
  app then uses http://127.0.0.1:8000 with no LAN address and no firewall rule.
  That tunnel is cleared by unplugging, a phone reboot, or Visual Studio
  starting its own adb server -- and the only symptom is an app that installs
  and runs but cannot log in. Re-applying it here means it is set at the one
  moment it is needed, so it cannot be the thing that is forgotten on the day.

  Usage:
      .\run_backend.ps1            start both services, reachable from your phone
      .\run_backend.ps1 -Local     bind to 127.0.0.1 only (this machine)
      .\run_backend.ps1 -Stop      stop both services
#>

param(
    [switch]$Local,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
# Prefer .venv312 (Python 3.12). NeMo does not support Python 3.14, so the
# Sortformer diarizer only runs there; on .venv the service silently falls back
# to pyannote. See docs/module_9_3_sortformer.md.
$python = Join-Path $root ".venv312\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $root ".venv\Scripts\python.exe"
    Write-Host "WARNING: .venv312 not found, falling back to .venv." -ForegroundColor Yellow
    Write-Host "         Sortformer will not load; diarization will use pyannote." -ForegroundColor Yellow
}

if (-not (Test-Path $python)) {
    throw "Cannot find $python. Run this from the repository root with the venv created."
}

# ---------------------------------------------------------------- stop
if ($Stop) {
    $killed = 0
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | ForEach-Object {
        if ($_.CommandLine -and $_.CommandLine -match "uvicorn (app\.main|simulated_emr_service\.main)") {
            Stop-Process -Id $_.ProcessId -Force
            $killed++
        }
    }
    Write-Host "Stopped $killed backend process(es)." -ForegroundColor Yellow
    exit 0
}

$bindHost = if ($Local) { "127.0.0.1" } else { "0.0.0.0" }

# Refuse to start a second copy rather than failing later with a confusing
# "address already in use" from inside uvicorn.
$already = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "uvicorn (app\.main|simulated_emr_service\.main)" }
if ($already) {
    Write-Host "The backend already appears to be running." -ForegroundColor Yellow
    Write-Host "Stop it first with:  .\run_backend.ps1 -Stop" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Starting AI-Powered EMR Assistant backend..." -ForegroundColor Cyan
Write-Host ""

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root'; Write-Host 'API  (port 8000)' -ForegroundColor Green; " +
    "& '$python' -m uvicorn app.main:app --host $bindHost --port 8000 --reload"
)

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root'; Write-Host 'Simulated EMR  (port 8001)' -ForegroundColor Green; " +
    "& '$python' -m uvicorn simulated_emr_service.main:app --host $bindHost --port 8001"
)

# Wait for the API to answer rather than assuming it started. Two windows opening
# is not evidence that anything works.
Write-Host "Waiting for the API to respond..." -NoNewline
$ok = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch { }
}
Write-Host ""

if (-not $ok) {
    Write-Host ""
    Write-Host "The API did not respond within 30 seconds." -ForegroundColor Red
    Write-Host "Check the API window for the error. The usual causes are PostgreSQL" -ForegroundColor Red
    Write-Host "not running, or a missing value in .env." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------- the phone, over the cable
# Nothing here is allowed to stop the backend starting. A missing adb, a
# mismatched adb, or no phone plugged in are all ordinary situations, not
# errors: the backend is perfectly usable from this machine and the emulator
# without any of it.
function Find-Adb {
    $candidates = @(
        "adb",
        "D:\platform-tools\adb.exe",
        (Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"),
        "C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe"
    )
    foreach ($candidate in $candidates) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

$phoneReady = $false
$adbFound = $false
$phoneAttached = $false

if (-not $Local) {
    try {
        $adb = Find-Adb
        if ($adb) {
            $adbFound = $true
            # Lines read "R58T41H57ZN<tab>device". "unauthorized" (the prompt on
            # the phone was never accepted) and "offline" are deliberately not
            # matched -- a tunnel to either of those silently does nothing.
            $attached = & $adb devices 2>$null |
                Where-Object { $_ -match '^\S+\s+device$' }
            if ($attached) {
                $phoneAttached = $true
                & $adb reverse tcp:8000 tcp:8000 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $phoneReady = $true }
            }
        }
    } catch {
        # Deliberately swallowed. See the comment above this block.
    }
}

# The LAN address is what a physical phone needs when the cable is not used.
# Print it so it does not have to be looked up every time.
$lan = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
        Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "  Backend is up." -ForegroundColor Green
Write-Host ""
Write-Host "  This machine        http://127.0.0.1:8000"
Write-Host "  API documentation   http://127.0.0.1:8000/docs"
Write-Host "  Simulated EMR       http://127.0.0.1:8001/docs"
if (-not $Local) {
    Write-Host ""
    if ($phoneReady) {
        Write-Host "  Phone on the cable          http://127.0.0.1:8000  (adb reverse set)" -ForegroundColor Green
    }
    elseif ($adbFound -and -not $phoneAttached) {
        Write-Host "  No phone detected on USB. Plug one in and re-run this script," -ForegroundColor DarkGray
        Write-Host "  or set the tunnel by hand:  adb reverse tcp:8000 tcp:8000" -ForegroundColor DarkGray
    }
    elseif (-not $adbFound) {
        Write-Host "  adb not found, so no USB tunnel was set. The emulator and the" -ForegroundColor DarkGray
        Write-Host "  LAN address below still work." -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  From the Android emulator   http://10.0.2.2:8000"
    if ($lan) {
        Write-Host "  From a phone on this WiFi   http://$lan`:8000"
    }
}
Write-Host ""
Write-Host "  Stop with:  .\run_backend.ps1 -Stop"
Write-Host ""
