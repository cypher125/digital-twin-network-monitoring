<#
.SYNOPSIS
  Stops the Digital Twin: every service started by deploy\start.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\stop.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
& $python (Join-Path $root "deploy\supervisor.py") stop
