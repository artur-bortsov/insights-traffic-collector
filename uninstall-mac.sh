#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GitHub Insights Traffic Collector — macOS uninstaller
#
# Usage:
#   ./uninstall-mac.sh
#
# What this script removes:
#   1. Unloads and deletes the launchd LaunchAgent
#   2. Removes the install directory (scripts, venv, config)
#
# Data files (CSV, XLSX) in your configured output directory are NOT removed.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

LABEL="com.github.insights-traffic-collector"
INSTALL_DIR="${HOME}/Library/Application Support/insights-traffic-collector"
PLIST_FILE="${HOME}/Library/LaunchAgents/${LABEL}.plist"

echo "=== GitHub Insights Traffic Collector — macOS Uninstallation ==="
echo ""

# ── Unload LaunchAgent ────────────────────────────────────────────────────────
if launchctl list "${LABEL}" &>/dev/null 2>&1; then
    echo "Unloading LaunchAgent..."
    launchctl unload "${PLIST_FILE}" 2>/dev/null || true
    echo "[OK] LaunchAgent unloaded"
else
    echo "[SKIP] LaunchAgent is not currently loaded"
fi

# ── Remove plist file ─────────────────────────────────────────────────────────
if [[ -f "${PLIST_FILE}" ]]; then
    rm "${PLIST_FILE}"
    echo "[OK] Removed: ${PLIST_FILE}"
else
    echo "[SKIP] Plist file not found: ${PLIST_FILE}"
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
