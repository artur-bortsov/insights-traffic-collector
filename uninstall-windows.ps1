# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — Windows uninstaller
#
# Usage (from PowerShell):
#   .\uninstall-windows.ps1
#
# What this script removes:
#   1. Unregisters the Task Scheduler task
#   2. Removes the install directory (scripts, venv, config, logs)
#
# Data files (CSV, XLSX) in your configured output directory are NOT removed.
# ─────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

$TaskName   = "insights-traffic-collector"
$InstallDir = "$env:LOCALAPPDATA\insights-traffic-collector"

Write-Host "=== GitHub Insights Traffic Collector — Windows Uninstallation ==="
Write-Host ""

# ── Remove Task Scheduler task ─────────────────────────────────────────────────
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Scheduled task removed: $TaskName"
} else {
    Write-Host "[SKIP] Scheduled task not found: $TaskName"
}

# ── Remove install directory ───────────────────────────────────────────────────
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "[OK] Install directory removed: $InstallDir"
} else {
    Write-Host "[SKIP] Install directory not found: $InstallDir"
}

Write-Host ""
Write-Host "=== Uninstallation complete! ==="
Write-Host ""
Write-Host "Your data files (CSV, XLSX) were not removed."
Write-Host "Check your configured output directory to delete them if desired."
Write-Host ""
