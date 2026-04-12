#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — macOS installer
#
# Usage:
#   ./install-mac.sh [--hour H] [--minute M] [--output-dir PATH]
#
# What this script does:
#   1. Verifies Python 3.11+ is available
#   2. Copies scripts to ~/Library/Application Support/insights-traffic-collector/
#   3. Creates a Python virtual environment and installs openpyxl
#   4. Creates config.toml with your settings (skipped if it already exists)
#   5. Installs a launchd LaunchAgent that runs the collector on schedule
#   6. Loads the agent so the schedule is active immediately
#
# No root (sudo) is required — all files are placed under your home directory.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Default values ─────────────────────────────────────────────────────────────
HOUR=8
MINUTE=0
LABEL="com.github.insights-traffic-collector"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/Library/Application Support/insights-traffic-collector"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
LOG_FILE="${HOME}/Library/Logs/insights-traffic-collector.log"
OUTPUT_DIR="${HOME}/Documents/GitHubInsights"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hour)
            HOUR="$2"
            shift 2
            ;;
        --minute)
            MINUTE="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --help|-h)
            sed -n '2,/^# ─/p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [--hour H] [--minute M] [--output-dir PATH]" >&2
            exit 1
            ;;
    esac
done

echo "=== GitHub Insights Traffic Collector — macOS Installation ==="
echo "Install directory : ${INSTALL_DIR}"
echo "Output directory  : ${OUTPUT_DIR}"
printf "Schedule          : daily at %02d:%02d\n" "${HOUR}" "${MINUTE}"
echo ""

# ── Python version check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found." >&2
    echo "       Install Python 3.11+ from https://python.org or via Homebrew:" >&2
    echo "         brew install python@3.11" >&2
    exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="${PYTHON_VERSION%%.*}"
PYTHON_MINOR="${PYTHON_VERSION##*.}"

if [[ "${PYTHON_MAJOR}" -lt 3 ]] || { [[ "${PYTHON_MAJOR}" -eq 3 ]] && [[ "${PYTHON_MINOR}" -lt 11 ]]; }; then
    echo "Error: Python 3.11 or higher is required (found Python ${PYTHON_VERSION})." >&2
    exit 1
fi
echo "[OK] Python ${PYTHON_VERSION}"

# ── Create install directory ──────────────────────────────────────────────────
echo "Creating install directory..."
mkdir -p "${INSTALL_DIR}"

# ── Copy scripts ───────────────────────────────────────────────────────────────
echo "Copying scripts..."
cp "${SCRIPT_DIR}/collect_insights.py"  "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/generate_report.py"   "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/requirements.txt"     "${INSTALL_DIR}/"
echo "[OK] Scripts copied"

# ── Create config.toml (preserve existing config on re-install) ───────────────
CONFIG_PATH="${INSTALL_DIR}/config.toml"
if [[ ! -f "${CONFIG_PATH}" ]]; then
    # Look for a token file: first next to the installer, then a common default
    TOKEN_FILE="${SCRIPT_DIR}/git-token.txt"
    if [[ ! -f "${TOKEN_FILE}" ]]; then
        TOKEN_FILE="${HOME}/.github-token"
    fi

    cat > "${CONFIG_PATH}" << EOF
# GitHub Insights Traffic Collector — configuration

[github]
# Path to a file containing your GitHub personal access token.
# The token must have the 'repo' scope to access traffic data.
# Create or manage tokens at: https://github.com/settings/tokens
token_file = "${TOKEN_FILE}"

[output]
# Directory where the CSV data file and XLSX reports will be stored.
directory = "${OUTPUT_DIR}"
EOF
    echo "[NOTE] Config created: ${CONFIG_PATH}"
    echo "       Review and adjust the token_file path if needed."
else
    echo "[SKIP] Config already exists — not overwriting: ${CONFIG_PATH}"
fi

# ── Python virtual environment ────────────────────────────────────────────────
VENV_DIR="${INSTALL_DIR}/venv"
echo "Creating Python virtual environment..."
python3 -m venv "${VENV_DIR}"
echo "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install --requirement "${INSTALL_DIR}/requirements.txt" --quiet
echo "[OK] Python virtual environment ready"

# ── launchd LaunchAgent plist ─────────────────────────────────────────────────
mkdir -p "${LAUNCH_AGENTS_DIR}"
PLIST_FILE="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"

# Unload any previously installed version of the agent before rewriting the plist
if launchctl list "${LABEL}" &>/dev/null 2>&1; then
    echo "Unloading existing LaunchAgent..."
    launchctl unload "${PLIST_FILE}" 2>/dev/null || true
fi

echo "Writing LaunchAgent plist: ${PLIST_FILE}"
cat > "${PLIST_FILE}" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <!-- Script to run (inside its own venv) -->
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/python3</string>
        <string>${INSTALL_DIR}/collect_insights.py</string>
        <string>--config</string>
        <string>${CONFIG_PATH}</string>
    </array>

    <!-- Run once a day at the configured time -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>

    <!-- Append stdout and stderr to a single log file -->
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>

    <!-- Do not run immediately on load — only at the scheduled time -->
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "[OK] LaunchAgent plist written"

# ── Load the agent ─────────────────────────────────────────────────────────────
launchctl load "${PLIST_FILE}"
echo "[OK] LaunchAgent loaded (schedule is active)"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete! ==="
echo ""
printf "The collector will run automatically every day at %02d:%02d.\n" "${HOUR}" "${MINUTE}"
echo ""
echo "Next steps:"
echo "  1. Verify your token path:"
echo "       ${CONFIG_PATH}"
echo ""
echo "  2. Run now to populate initial data:"
echo "       \"${VENV_DIR}/bin/python3\" \"${INSTALL_DIR}/collect_insights.py\""
echo ""
echo "  3. Generate an XLSX report:"
echo "       \"${VENV_DIR}/bin/python3\" \"${INSTALL_DIR}/generate_report.py\""
echo ""
echo "  4. View collector logs:"
echo "       tail -f \"${LOG_FILE}\""
echo ""
