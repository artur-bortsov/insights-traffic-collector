# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] — 2026-09-11

### Added
- Automatic retries with exponential backoff for every GitHub API request
  (4 attempts, 5 → 10 → 20 s by default). Connection timeouts, dropped
  connections, DNS errors and the temporary HTTP statuses 429, 500, 502,
  503 and 504 are retried instead of aborting the run.
- New optional `[network]` section in `config.toml` — `timeout`, `retries`
  and `retry_delay`. Existing config files without the section keep
  working with the built-in defaults.

### Changed
- A repository that stays unreachable after all retries is now skipped
  with a warning; the data collected for the remaining repositories is
  written to the CSV and the XLSX report is still regenerated.
- Unrecoverable API failures are logged as a single readable line instead
  of a Python traceback.
- The script exits with a non-zero status when the run was incomplete, so
  launchd / systemd / Task Scheduler still report the failure.

### Fixed
- A single transient network timeout no longer aborts the whole scheduled
  run, which previously left multi-day gaps in the collected data.
- Corrected a truncated sentence in the README introduction.

---

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
