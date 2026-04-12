# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — Windows installer
#
# Usage (from PowerShell):
#   .\install-windows.ps1 [-Hour 8] [-Minute 0] [-OutputDir "~\Documents\GitHubInsights"]
#
# What this script does:
#   1. Verifies Python 3.11+ is available
#   2. Copies scripts to %LOCALAPPDATA%\insights-traffic-collector\
#   3. Creates a Python virtual environment and installs openpyxl
#   4. Creates config.toml with your settings (skipped if it already exists)
#   5. Registers a Task Scheduler task for daily scheduling
#
# No administrator privileges are required (all files go under %LOCALAPPDATA%).
# ─────────────────────────────────────────────────────────────────────────────
param(
    [int]    $Hour      = 8,
    [int]    $Minute    = 0,
    [string] $OutputDir = "$env:USERPROFILE\Documents\GitHubInsights"
)

$ErrorActionPreference = "Stop"

$TaskName   = "insights-traffic-collector"
$InstallDir = "$env:LOCALAPPDATA\insights-traffic-collector"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir    = "$InstallDir\venv"
$ConfigPath = "$InstallDir\config.toml"
$LogFile    = "$InstallDir\insights-traffic-collector.log"

Write-Host "=== GitHub Insights Traffic Collector — Windows Installation ==="
Write-Host "Install directory : $InstallDir"
Write-Host "Output directory  : $OutputDir"
Write-Host ("Schedule          : daily at {0:D2}:{1:D2}" -f $Hour, $Minute)
Write-Host ""

# ── Python version check ──────────────────────────────────────────────────────
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pythonCmd = $cmd
        break
    }
}

if ($null -eq $pythonCmd) {
    Write-Error "Python not found.  Install Python 3.11+ from https://python.org"
    exit 1
}

$pyVersionOutput = & $pythonCmd --version 2>&1
if ($pyVersionOutput -notmatch "Python (\d+)\.(\d+)") {
    Write-Error "Could not parse Python version from: $pyVersionOutput"
    exit 1
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Write-Error "Python 3.11 or higher is required (found Python $pyMajor.$pyMinor)."
    exit 1
}
Write-Host "[OK] Python $pyMajor.$pyMinor"

# ── Create install directory ──────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Write-Host "[OK] Install directory: $InstallDir"

# ── Copy scripts ───────────────────────────────────────────────────────────────
Copy-Item "$ScriptDir\collect_insights.py"  "$InstallDir\" -Force
Copy-Item "$ScriptDir\generate_report.py"   "$InstallDir\" -Force
Copy-Item "$ScriptDir\requirements.txt"     "$InstallDir\" -Force
Write-Host "[OK] Scripts copied"

# ── Create config.toml (preserve existing on re-install) ─────────────────────
if (-not (Test-Path $ConfigPath)) {
    # Look for a token file next to the installer; fall back to a common default
    $TokenFile = "$ScriptDir\git-token.txt"
    if (-not (Test-Path $TokenFile)) {
        $TokenFile = "$env:USERPROFILE\.github-token"
    }

    # Use forward slashes in TOML values so the path parses correctly
    $TokenFileToml  = $TokenFile  -replace "\\", "/"
    $OutputDirToml  = $OutputDir  -replace "\\", "/"

    $configContent = @"
# GitHub Insights Traffic Collector — configuration

[github]
# Path to a file containing your GitHub personal access token.
# The token must have the 'repo' scope to access traffic data.
# Create or manage tokens at: https://github.com/settings/tokens
token_file = "$TokenFileToml"

[output]
# Directory where the CSV data file and XLSX reports will be stored.
directory = "$OutputDirToml"
"@
    Set-Content -Path $ConfigPath -Value $configContent -Encoding UTF8
    Write-Host "[NOTE] Config created: $ConfigPath"
    Write-Host "       Review and adjust the token_file path if needed."
} else {
    Write-Host "[SKIP] Config already exists — not overwriting: $ConfigPath"
}

# ── Python virtual environment ────────────────────────────────────────────────
Write-Host "Creating Python virtual environment..."
& $pythonCmd -m venv $VenvDir
& "$VenvDir\Scripts\pip" install --upgrade pip --quiet
& "$VenvDir\Scripts\pip" install --requirement "$InstallDir\requirements.txt" --quiet
Write-Host "[OK] Python virtual environment ready"

# ── Task Scheduler task ───────────────────────────────────────────────────────
$PythonExe  = "$VenvDir\Scripts\python.exe"
$ScriptPath = "$InstallDir\collect_insights.py"
$Arguments  = "`"$ScriptPath`" --config `"$ConfigPath`""

$Action = New-ScheduledTaskAction `
    -Execute    $PythonExe `
    -Argument   $Arguments `
    -WorkingDirectory $InstallDir

$TriggerTime = "{0:D2}:{1:D2}" -f $Hour, $Minute
$Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime

# StartWhenAvailable ensures a missed run (e.g. machine was off) fires soon after boot
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Remove a previous installation of the task if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -Description "Collects daily GitHub traffic data for all owned repositories" `
    | Out-Null

Write-Host "[OK] Task Scheduler task registered: $TaskName"

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Installation complete! ==="
Write-Host ""
Write-Host ("The collector will run automatically every day at {0:D2}:{1:D2}." -f $Hour, $Minute)
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Verify your token path:"
Write-Host "       $ConfigPath"
Write-Host ""
Write-Host "  2. Run now to populate initial data:"
Write-Host "       & `"$PythonExe`" `"$ScriptPath`" --config `"$ConfigPath`""
Write-Host ""
Write-Host "  3. Generate an XLSX report:"
Write-Host "       & `"$PythonExe`" `"$InstallDir\generate_report.py`""
Write-Host ""
Write-Host "  4. View logs:"
Write-Host "       Get-Content `"$LogFile`" -Wait"
Write-Host ""
