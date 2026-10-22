<#
.SYNOPSIS
  Starts the Digital Twin (emulator, API, engine and HTTPS front door) and opens the dashboard.

.DESCRIPTION
  Runs deploy\supervisor.py in the background. The supervisor starts every service, restarts
  any that stop, and writes their logs to var\log. Stop everything with deploy\stop.ps1.

.PARAMETER Speed
  Emulator speed: network seconds per real second. 1 = real time. For a demo, 10 or 20 makes a
  day of campus traffic pass in a couple of hours; choose a speed at which the System page
  shows no missed cycles on your laptop.

.PARAMETER LocalDatabase
  Use the local PostgreSQL instead of Neon (for demos without internet).

.PARAMETER NoBrowser
  Do not open the dashboard in the browser at the end.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10
#>
param(
    [double]$Speed = 1,
    [switch]$LocalDatabase,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "The system is not installed yet. Run deploy\setup.ps1 first." -ForegroundColor Red
    exit 1
}
if (Test-Path (Join-Path $root "var\run\supervisor.json")) {
    & $python (Join-Path $root "deploy\supervisor.py") status
    Write-Host "The system seems to be running already. Use deploy\stop.ps1 first if it is not." -ForegroundColor Yellow
    exit 1
}

$arguments = @("deploy\supervisor.py", "run", "--speed", "$Speed")
if ($LocalDatabase) { $arguments += "--local-db" }
New-Item -ItemType Directory -Force (Join-Path $root "var\log") | Out-Null
Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardError (Join-Path $root "var\log\supervisor.log")

Write-Host "Starting the Digital Twin (emulator speed $($Speed)x)..."
# Ready when the supervisor reports every service running and both the API and Caddy answer on
# their local ports (plain HTTP, so this works even before the HTTPS certificate is trusted).
$state = Join-Path $root "var\run\supervisor.json"
$deadline = (Get-Date).AddSeconds(180)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    try {
        $services = (Get-Content $state -Raw -ErrorAction Stop | ConvertFrom-Json).services
        $states = @($services.PSObject.Properties | ForEach-Object { $_.Value.state })
        if (($states | Where-Object { $_ -ne "running" }).Count -gt 0) { continue }
        $api = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/auth/csrf" -UseBasicParsing -TimeoutSec 5
        $caddy = Invoke-WebRequest -Uri "http://127.0.0.1:2019/config/" -UseBasicParsing -TimeoutSec 5
        if ($api.StatusCode -eq 200 -and $caddy.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
& $python (Join-Path $root "deploy\supervisor.py") status
if ($ready) {
    Write-Host "Ready: https://localhost" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "https://localhost" }
} else {
    Write-Host "Not ready after 3 minutes. Check the logs in var\log (api.log, caddy.log, engine.log)." -ForegroundColor Yellow
}
