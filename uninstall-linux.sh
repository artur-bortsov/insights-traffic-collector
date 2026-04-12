#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — Linux uninstaller
#
# Usage:
#   ./uninstall-linux.sh
#
# What this script removes:
#   1. Stops and disables the systemd user timer and service
#   2. Removes the systemd unit files
#   3. Removes the install directory (scripts, venv, config, logs)
#
# Data files (CSV, XLSX) in your configured output directory are NOT removed.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SERVICE_NAME="insights-traffic-collector"
INSTALL_DIR="${HOME}/.local/share/insights-traffic-collector"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

echo "=== GitHub Insights Traffic Collector — Linux Uninstallation ==="
echo ""

# ── Stop and disable timer and service ───────────────────────────────────────
if systemctl --user is-active "${SERVICE_NAME}.timer" &>/dev/null; then
    systemctl --user stop "${SERVICE_NAME}.timer"
    echo "[OK] Timer stopped"
else
    echo "[SKIP] Timer was not active"
fi

if systemctl --user is-enabled "${SERVICE_NAME}.timer" &>/dev/null; then
    systemctl --user disable "${SERVICE_NAME}.timer"
    echo "[OK] Timer disabled"
fi

# ── Remove systemd unit files ─────────────────────────────────────────────────
REMOVED_UNITS=false
for unit in "${SERVICE_NAME}.service" "${SERVICE_NAME}.timer"; do
    UNIT_FILE="${SYSTEMD_USER_DIR}/${unit}"
    if [[ -f "${UNIT_FILE}" ]]; then
        rm "${UNIT_FILE}"
        echo "[OK] Removed: ${UNIT_FILE}"
        REMOVED_UNITS=true
    fi
done

if ${REMOVED_UNITS}; then
    systemctl --user daemon-reload
fi

# ── Remove install directory ───────────────────────────────────────────────────
if [[ -d "${INSTALL_DIR}" ]]; then
    rm -rf "${INSTALL_DIR}"
    echo "[OK] Removed: ${INSTALL_DIR}"
else
    echo "[SKIP] Install directory not found: ${INSTALL_DIR}"
fi

echo ""
echo "=== Uninstallation complete! ==="
echo ""
echo "Your data files (CSV, XLSX) were not removed."
echo "Check your configured output directory to delete them if desired."
echo ""
