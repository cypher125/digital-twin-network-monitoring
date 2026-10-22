<#
.SYNOPSIS
  One-off installation of the Digital Twin on a Windows 10/11 laptop (plan section 12.2).

.DESCRIPTION
  1. Checks the prerequisites (uv, Node.js, Caddy).
  2. Installs the Python packages (exact versions from backend\uv.lock) and the dashboard's packages.
  3. Writes backend\.env (a new secret key and the database connection string), if it does not exist.
  4. Prepares the database: tables, roles, the first Senior Administrator, the campus topology.
  5. Generates 14 days of network history and trains the forecasting models (about an hour on a
     slow laptop; skip with -SkipHistory and run it later).
  6. Builds the dashboard and collects the admin site's files.
  7. Makes the browser trust the local HTTPS certificate (Windows asks for permission once).
  8. Records the installed versions in docs\evidence\versions.txt.
  Safe to run again: finished steps are skipped or repeated harmlessly.

.PARAMETER AdminUser
  Username of the first Senior Administrator (you are asked for the password).

.PARAMETER SkipHistory
  Do not generate history or train the models now.

.PARAMETER LocalDatabase
  Use the local PostgreSQL (offline fallback) instead of Neon.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\setup.ps1 -AdminUser okafor
#>
param(
    [string]$AdminUser = "admin",
    [switch]$SkipHistory,
    [switch]$LocalDatabase
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"

function Step([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }

function Need([string]$command, [string]$hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $command. $hint" -ForegroundColor Red
        exit 1
    }
}

function Run([string]$exe, [string[]]$arguments, [string]$workdir) {
    Push-Location $workdir
    try {
        & $exe @arguments
        if ($LASTEXITCODE -ne 0) { throw "'$exe $($arguments -join ' ')' failed (exit code $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

function Wait-Url([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

# ---------------------------------------------------------------- 1
Step "Checking the prerequisites"
# A PowerShell window opened before winget installed Caddy does not have it on its PATH yet
if (-not (Get-Command "caddy" -ErrorAction SilentlyContinue)) {
    $caddyDir = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Directory -Filter "CaddyServer.Caddy_*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($caddyDir) { $env:Path = "$($caddyDir.FullName);$env:Path" }
}
Need "uv" "Install it with:  winget install astral-sh.uv   (then open a new PowerShell window)"
Need "node" "Install Node.js 22 LTS with:  winget install OpenJS.NodeJS.LTS"
Need "npm" "It is installed with Node.js."
Need "caddy" "Install it with:  winget install CaddyServer.Caddy   (then open a new PowerShell window)"
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 20) {
    Write-Host "Node.js $nodeMajor is too old: version 20 or later is needed." -ForegroundColor Red
    exit 1
}
Write-Host "uv, Node.js $(node --version) and Caddy found."

# ---------------------------------------------------------------- 2
Step "Installing the Python packages (exact versions from uv.lock)"
Run "uv" @("sync", "--frozen", "--python", "3.13") $backend

# ---------------------------------------------------------------- 3
Step "Settings (backend\.env)"
$envFile = Join-Path $backend ".env"
if (Test-Path $envFile) {
    Write-Host "backend\.env already exists; keeping it."
} else {
    $secret = & $python -c "import secrets; print(secrets.token_urlsafe(50))"
    $databaseUrl = ""
    if (-not $LocalDatabase) {
        Write-Host "Paste the Neon DIRECT connection string (Neon console > your project > Connect)."
        Write-Host "It is not shown while you type or paste."
        $secure = Read-Host -AsSecureString "DATABASE_URL"
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $databaseUrl = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        if (-not $databaseUrl.StartsWith("postgresql://")) {
            Write-Host "That does not look like a postgresql:// connection string." -ForegroundColor Red
            exit 1
        }
    }
    @(
        "# Written by deploy\setup.ps1. Never share or commit this file.",
        "DJANGO_SECRET_KEY=$secret",
        "DJANGO_DEBUG=0",
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost,https://127.0.0.1",
        "DATABASE_URL=$databaseUrl"
    ) | Set-Content -Path $envFile -Encoding ascii
    Write-Host "Wrote backend\.env."
}

if ($LocalDatabase) {
    Step "Local database (offline fallback)"
    $pgenv = Join-Path $root "var\localpg\pgenv"
    if (-not (Test-Path (Join-Path $pgenv "Scripts\python.exe"))) {
        Run "uv" @("venv", "--python", "3.12", $pgenv) $root
        Run "uv" @("pip", "install", "--python", $pgenv, "pgserver==0.1.4", "tzdata") $root
    }
    $pgpython = Join-Path $pgenv "Scripts\python.exe"
    Run $pgpython @("deploy\localpg.py", "install-timezones") $root
    $uri = (& $pgpython (Join-Path $root "deploy\localpg.py") start | Select-Object -Last 1)
    if ($uri -notmatch "sslmode") { $uri = $uri + $(if ($uri.Contains("?")) { "&" } else { "?" }) + "sslmode=disable" }
    $env:DATABASE_URL = $uri
    Write-Host "Using the local PostgreSQL."
}

# ---------------------------------------------------------------- 4
Step "Preparing the database"
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
Run $python @("manage.py", "check") $backend
Run $python @("manage.py", "migrate", "--noinput") $backend
Run $python @("manage.py", "createcachetable") $backend
Run $python @("manage.py", "setup_roles") $backend
$exists = & $python (Join-Path $backend "manage.py") shell -c "from django.contrib.auth.models import User; print(User.objects.filter(username='$AdminUser').exists())"
if (($exists | Select-Object -Last 1) -eq "True") {
    Write-Host "Senior Administrator '$AdminUser' already exists."
} else {
    Write-Host "Choose a password for the Senior Administrator '$AdminUser' (at least 10 characters)."
    Run $python @("manage.py", "setup_roles", "--create-user", $AdminUser, "--role", "senior") $backend
}
Run $python @("manage.py", "import_topology", "..\data\topologies\campus.yaml") $backend

# ---------------------------------------------------------------- 5
$hasHistory = & $python (Join-Path $backend "manage.py") shell -c "from apps.twin.models import MonitoringRecord; print(MonitoringRecord.objects.exists())"
if ($SkipHistory) {
    Step "Skipping the history and the models (-SkipHistory)"
} elseif (($hasHistory | Select-Object -Last 1) -eq "True") {
    Step "History already exists; not generating it again"
    Write-Host "(The network clock never goes back, so history is only generated once.)"
} else {
    Step "Generating 14 days of network history and training the models (about an hour)"
    # the emulator starts at midnight West Africa Time 14 days ago and is stepped by the backfill
    $start = (Get-Date).ToUniversalTime().AddHours(1).Date.AddDays(-14).ToString("yyyy-MM-dd") + "T00:00:00+01:00"
    $emulator = Start-Process -FilePath $python -ArgumentList @("-m", "netemu", "serve", "--mode", "stepped", "--start", $start) `
        -WorkingDirectory $backend -WindowStyle Hidden -PassThru
    try {
        if (-not (Wait-Url "http://127.0.0.1:9161/v1/info" 60)) { throw "the emulator did not start" }
        Run $python @("manage.py", "backfill_history", "--days", "14") $backend
        Run $python @("manage.py", "train_models", "--days", "14") $backend
    } finally {
        taskkill /PID $emulator.Id /T /F | Out-Null
    }
}

# ---------------------------------------------------------------- 6
Step "Building the dashboard"
Run "npm" @("ci", "--no-audit", "--no-fund") $frontend
$env:NEXT_TELEMETRY_DISABLED = "1"
Run "npm" @("run", "build") $frontend
Step "Collecting the admin site's files"
Run $python @("manage.py", "collectstatic", "--noinput") $backend

# ---------------------------------------------------------------- 7
Step "Trusting the local HTTPS certificate (Windows may ask for permission)"
Push-Location $root
try {
    caddy start --config deploy\Caddyfile --adapter caddyfile | Out-Null
    Start-Sleep -Seconds 3
    caddy trust
    caddy stop | Out-Null
} catch {
    Write-Host "Could not install the certificate automatically: $_" -ForegroundColor Yellow
    Write-Host "Run 'caddy trust' in an administrator PowerShell later."
} finally {
    Pop-Location
}

# ---------------------------------------------------------------- 8
Step "Recording the installed versions (evidence)"
$evidence = Join-Path $root "docs\evidence"
New-Item -ItemType Directory -Force $evidence | Out-Null
$versions = Join-Path $evidence "versions.txt"
@("Recorded by deploy\setup.ps1 on $(Get-Date -Format s)", "", "Python packages:") | Set-Content $versions -Encoding utf8
Push-Location $backend
try { uv pip freeze --python $python | Add-Content $versions -Encoding utf8 } finally { Pop-Location }
@("", "Node.js $(node --version), npm $(npm --version)", "Caddy $(caddy version)", "", "Dashboard packages:") | Add-Content $versions -Encoding utf8
Push-Location $frontend
try { npm ls --depth=0 | Add-Content $versions -Encoding utf8 } finally { Pop-Location }

Write-Host ""
Write-Host "Installation finished." -ForegroundColor Green
Write-Host "Start the system with:  powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10"
