#!/usr/bin/env python3
"""
GitHub Insights Traffic Collector
==================================
Fetches daily traffic data (views, clones) for all GitHub repositories owned
by the authenticated user and appends new records to a local CSV file.

The GitHub Traffic API exposes data for the last 14 days, so this script
should be run at least once every two weeks.  Running it daily (the default
schedule) guarantees no gaps in the historical record.

CSV output columns:
  date            ISO date (YYYY-MM-DD)
  repo            Repository full name (owner/repo)
  views           Total page views on that day
  views_uniques   Unique visitors on that day
  clones          Total clones on that day
  clones_uniques  Unique cloners on that day

Usage:
  python3 collect_insights.py [--config PATH] [--output-dir PATH]

Requirements:
  Python 3.11+ (stdlib only — no third-party packages needed)
"""

import argparse
import csv
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"

# Minimum required Python version (tomllib is stdlib from 3.11 onward)
_MIN_PYTHON = (3, 11)

# GitHub REST API base URL
_GITHUB_API = "https://api.github.com"

# Column order for the CSV file
_CSV_COLUMNS = ["date", "repo", "views", "views_uniques", "clones", "clones_uniques"]


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Print a UTC-timestamped message to stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


# ── Configuration ─────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """
    Load a TOML configuration file.  Returns an empty dict if the file does
    not exist so that the script can still run with environment variables.
    """
    if not config_path.exists():
        log(f"Config file not found: {config_path} — using defaults / environment variables.")
        return {}
    with open(config_path, "rb") as fh:
        return tomllib.load(fh)


def read_token(config: dict) -> str:
    """
    Resolve the GitHub personal access token from (in priority order):
      1. GITHUB_TOKEN environment variable
      2. token_file path in [github] section of config
      3. token string in [github] section of config
    Exits with an error message when no token can be found.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token

    token_file = config.get("github", {}).get("token_file", "").strip()
    if token_file:
        token_path = Path(token_file).expanduser()
        if token_path.exists():
            return token_path.read_text().strip()
        log(f"Warning: token_file not found: {token_path}")

    token = config.get("github", {}).get("token", "").strip()
    if token:
        return token

    log("Error: no GitHub token configured.")
    log("  Option 1 — set the GITHUB_TOKEN environment variable.")
    log("  Option 2 — set token_file in config.toml to point at a file with your token.")
    log("  Create a token with 'repo' scope at: https://github.com/settings/tokens")
    sys.exit(1)


# ── GitHub API helpers ─────────────────────────────────────────────────────────

def _github_get(url: str, token: str) -> dict | list:
    """
    Perform an authenticated GET request to the GitHub REST API and return the
    parsed JSON body.

    A 403 response is treated as a soft error (no push access to that repo)
    and returns an empty dict so the caller can skip the entry gracefully.
    All other HTTP errors are re-raised.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"insights-traffic-collector/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            # Traffic API requires push access; repos where access is denied
            # are skipped silently to keep the output clean.
            log(f"  [403 skipped] {url}")
            return {}
        raise


def get_username(token: str) -> str:
    """Return the GitHub login name of the authenticated user."""
    data = _github_get(f"{_GITHUB_API}/user", token)
    return data["login"]


def get_owned_repos(token: str) -> list[dict]:
    """
    Return all repositories owned by the authenticated user.
    Paginates automatically; supports up to 300 repositories.
    Only 'owner' affiliation is requested because the Traffic API is only
    available for repos you own or have push access to, and we want to track
    traffic for the user's own repos.
    """
    repos: list[dict] = []
    page = 1
    while True:
        url = (
            f"{_GITHUB_API}/user/repos"
            f"?affiliation=owner&sort=updated&per_page=100&page={page}"
        )
        batch = _github_get(url, token)
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def get_repo_traffic(token: str, full_name: str) -> dict:
    """
    Fetch daily views and clones for one repository (last 14 days).
    Returns a dict with keys 'views' and 'clones', each containing the raw
    API response.  Returns empty dicts for repos without push access.
    """
    views  = _github_get(f"{_GITHUB_API}/repos/{full_name}/traffic/views?per=day",  token)
    clones = _github_get(f"{_GITHUB_API}/repos/{full_name}/traffic/clones?per=day", token)
    return {"views": views, "clones": clones}


# ── CSV helpers ────────────────────────────────────────────────────────────────

def load_existing_keys(csv_path: Path) -> set[tuple[str, str]]:
    """
    Read the CSV and return a set of (date, repo) tuples that are already
    recorded.  Used to prevent duplicate rows when the script is run multiple
    times within the same 14-day window.
    """
    seen: set[tuple[str, str]] = set()
    if csv_path.exists() and csv_path.stat().st_size > 0:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                seen.add((row["date"], row["repo"]))
    return seen


# ── Main collection routine ────────────────────────────────────────────────────

def collect(output_dir: Path, token: str) -> None:
    """
    Fetch traffic data for every owned repository and append new rows to the
    CSV file.  Rows whose (date, repo) key already exists are skipped so the
    file always contains exactly one entry per (date, repo) pair.
    """
    username = get_username(token)
    log(f"Authenticated as: {username}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"insights-traffic-{username}.csv"

    existing_keys = load_existing_keys(csv_path)
    repos = get_owned_repos(token)
    log(f"Found {len(repos)} owned repositories")

    new_rows: list[dict] = []

    for repo in repos:
        full_name = repo["full_name"]
        log(f"  Fetching: {full_name}")
        traffic = get_repo_traffic(token, full_name)

        # Index entries by date string (YYYY-MM-DD) for easy lookup
        views_by_date: dict[str, dict] = {
            entry["timestamp"][:10]: entry
            for entry in traffic.get("views", {}).get("views", [])
        }
        clones_by_date: dict[str, dict] = {
            entry["timestamp"][:10]: entry
            for entry in traffic.get("clones", {}).get("clones", [])
        }

        # Union of all dates that have any data for this repo
        all_dates = sorted(set(views_by_date) | set(clones_by_date))

        for date_str in all_dates:
            key = (date_str, full_name)
            if key not in existing_keys:
                v = views_by_date.get(date_str, {})
                c = clones_by_date.get(date_str, {})
                new_rows.append({
                    "date":           date_str,
                    "repo":           full_name,
                    "views":          v.get("count",   0),
                    "views_uniques":  v.get("uniques", 0),
                    "clones":         c.get("count",   0),
                    "clones_uniques": c.get("uniques", 0),
                })

    if not new_rows:
        log("No new records to append — all data is already up to date.")
        return

    # Sort chronologically so the CSV file remains naturally ordered
    new_rows.sort(key=lambda r: (r["date"], r["repo"]))

    is_new_file = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        if is_new_file:
            writer.writeheader()
        writer.writerows(new_rows)

    log(f"Appended {len(new_rows)} new records → {csv_path}")


# ── Report generation ─────────────────────────────────────────────────────────

def _try_generate_report(output_dir: Path, config: dict) -> None:
    """
    Generate the XLSX report by importing generate_report.py from the same
    directory as this script.  Errors are logged but do not affect the exit
    code of the collector — the CSV is always the authoritative data store.
    """
    report_script = Path(__file__).parent / "generate_report.py"
    if not report_script.exists():
        log("generate_report.py not found — skipping XLSX generation.")
        return

    import importlib.util
    spec = importlib.util.spec_from_file_location("generate_report", report_script)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        csv_files = sorted(output_dir.glob("insights-traffic-*.csv"))
        if not csv_files:
            return
        chart_months = config.get("chart", {}).get("months", 6)
        output_path  = csv_files[0].with_suffix(".xlsx")
        mod.generate_report(csv_files[0], output_path, chart_months)
    except Exception as exc:
        log(f"Warning: XLSX report generation failed: {exc}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if sys.version_info < _MIN_PYTHON:
        sys.exit(
            f"Python {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}+ is required "
            f"(running {sys.version})."
        )

    parser = argparse.ArgumentParser(
        description="GitHub Insights Traffic Collector — fetches daily traffic data for all owned repos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", type=Path, metavar="PATH",
        help="Path to config.toml (default: config.toml next to this script)",
    )
    parser.add_argument(
        "--output-dir", type=Path, metavar="PATH",
        help="Directory for the CSV output file (overrides config.toml setting)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    log(f"GitHub Insights Traffic Collector v{__version__}")

    config_path = args.config or (Path(__file__).parent / "config.toml")
    config      = load_config(config_path)
    token       = read_token(config)

    if args.output_dir:
        output_dir = args.output_dir.expanduser()
    else:
        default_dir = config.get("output", {}).get("directory", "~/Documents/GitHubInsights")
        output_dir  = Path(default_dir).expanduser()

    collect(output_dir, token)
    if config.get("chart", {}).get("auto_report", True):
        _try_generate_report(output_dir, config)


if __name__ == "__main__":
    main()
