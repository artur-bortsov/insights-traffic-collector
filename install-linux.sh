#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — Linux installer
#
# Usage:
#   ./install-linux.sh [--hour H] [--minute M] [--output-dir PATH]
#
# What this script does:
#   1. Verifies Python 3.11+ is available
#   2. Copies scripts to ~/.local/share/insights-traffic-collector/
#   3. Creates a Python virtual environment and installs openpyxl
#   4. Creates config.toml with your settings (skipped if it already exists)
#   5. Installs a systemd user service and timer for daily scheduling
#   6. Enables and starts the timer (no reboot required)
#
# No root (sudo) is required — all files go under your home directory.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Default values ─────────────────────────────────────────────────────────────
HOUR=8
MINUTE=0
SERVICE_NAME="insights-traffic-collector"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/insights-traffic-collector"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
LOG_FILE="${INSTALL_DIR}/insights-traffic-collector.log"
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

echo "=== GitHub Insights Traffic Collector — Linux Installation ==="
echo "Install directory : ${INSTALL_DIR}"
echo "Output directory  : ${OUTPUT_DIR}"
printf "Schedule          : daily at %02d:%02d\n" "${HOUR}" "${MINUTE}"
echo ""

# ── Python version check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found.  Install Python 3.11+ first:" >&2
    echo "  Ubuntu/Debian:  sudo apt install python3.11 python3.11-venv" >&2
    echo "  Fedora/RHEL:    sudo dnf install python3.11" >&2
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

# ── Check systemd user session ────────────────────────────────────────────────
if ! systemctl --user status &>/dev/null; then
    echo "Warning: systemd user session does not appear to be running." >&2
    echo "         If you are on a headless server, enable lingering first:" >&2
    echo "           sudo loginctl enable-linger $(id -un)" >&2
fi

# ── Create install directory ──────────────────────────────────────────────────
echo "Creating install directory..."
mkdir -p "${INSTALL_DIR}"

# ── Copy scripts ───────────────────────────────────────────────────────────────
echo "Copying scripts..."
cp "${SCRIPT_DIR}/collect_insights.py"  "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/generate_report.py"   "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/requirements.txt"     "${INSTALL_DIR}/"
echo "[OK] Scripts copied"

# ── Create config.toml (preserve existing on re-install) ─────────────────────
CONFIG_PATH="${INSTALL_DIR}/config.toml"
if [[ ! -f "${CONFIG_PATH}" ]]; then
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

# ── systemd user service ──────────────────────────────────────────────────────
mkdir -p "${SYSTEMD_USER_DIR}"

cat > "${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service" << EOF
[Unit]
Description=GitHub Insights Traffic Collector

[Service]
Type=oneshot
ExecStart=${VENV_DIR}/bin/python3 ${INSTALL_DIR}/collect_insights.py --config ${CONFIG_PATH}
# Append stdout and stderr to a persistent log file
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}
EOF

# ── systemd user timer ────────────────────────────────────────────────────────
MINUTE_PAD="$(printf '%02d' "${MINUTE}")"
HOUR_PAD="$(printf '%02d' "${HOUR}")"

cat > "${SYSTEMD_USER_DIR}/${SERVICE_NAME}.timer" << EOF
[Unit]
Description=GitHub Insights Traffic Collector — Daily Timer

[Timer]
# Fire daily at the configured time; if a scheduled run was missed (e.g. the
# machine was off), Persistent=true causes it to run as soon as possible.
OnCalendar=*-*-* ${HOUR_PAD}:${MINUTE_PAD}:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "[OK] systemd unit files written"

# ── Enable and start the timer ─────────────────────────────────────────────────
systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}.timer"
echo "[OK] Timer enabled and started: ${SERVICE_NAME}.timer"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete! ==="
echo ""
printf "The collector will run automatically every day at %02d:%02d.\n" "${HOUR}" "${MINUTE}"
echo ""
echo "Useful commands:"
echo "  Run now:          systemctl --user start ${SERVICE_NAME}.service"
echo "  Timer status:     systemctl --user status ${SERVICE_NAME}.timer"
echo "  Service logs:     journalctl --user -u ${SERVICE_NAME}.service -f"
echo "  Collector logs:   tail -f \"${LOG_FILE}\""
echo "  Generate report:  \"${VENV_DIR}/bin/python3\" \"${INSTALL_DIR}/generate_report.py\""
echo ""
