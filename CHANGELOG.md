# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] — 2026-04-12

### Added
- `collect_insights.py` — collects daily views and clones from the GitHub
  Traffic API for all owned repositories and appends new records to a
  local CSV file, avoiding duplicates across runs.
- `generate_report.py` — reads the CSV and produces a two-sheet XLSX
  workbook: **Data** (pivot tables for the last N months, all-time summary)
  and **Charts** (six compact charts in a 2-column grid — no tables).
  Charts reference the Data sheet directly so they always reflect the
  current data.
- Automatic XLSX regeneration after each collection run (configurable via
  `auto_report` in `config.toml`).
- Configurable chart window: `[chart] months = 6` in `config.toml`.
- `install-mac.sh` — macOS installer using a launchd LaunchAgent
  (daily at 08:00 by default, no root required).
- `uninstall-mac.sh` — macOS uninstaller.
- `install-linux.sh` — Linux installer using a systemd user service + timer.
- `uninstall-linux.sh` — Linux uninstaller.
- `install-windows.ps1` — Windows installer using Task Scheduler.
- `uninstall-windows.ps1` — Windows uninstaller.
- `config.toml` — TOML configuration for token path, output directory,
  chart window length, and auto-report switch.
- `requirements.txt` — single runtime dependency: `openpyxl`.
- `README.md`, `LICENSE` (GNU GPL v3), `CHANGELOG.md`.
