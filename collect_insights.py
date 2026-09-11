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
import http.client
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.1.0"

# Minimum required Python version (tomllib is stdlib from 3.11 onward)
_MIN_PYTHON = (3, 11)

# GitHub REST API base URL
_GITHUB_API = "https://api.github.com"

# Column order for the CSV file
_CSV_COLUMNS = ["date", "repo", "views", "views_uniques", "clones", "clones_uniques"]

# ── Network resilience defaults ────────────────────────────────────────────────
# api.github.com is occasionally unreachable for a few seconds (TLS handshake
# stalls, DNS hiccups, transient 5xx).  Without retries a single blip aborts the
# whole scheduled run and leaves a gap in the CSV until the next day, so every
# request is retried a few times with an exponentially growing pause.
_DEFAULT_TIMEOUT     = 30   # seconds to wait for a single HTTP request
_DEFAULT_RETRIES     = 4    # total attempts per request (1 initial + 3 retries)
_DEFAULT_RETRY_DELAY = 5    # seconds before the first retry, doubled each time

# Effective network settings; replaced once at startup by apply_network_config().
_network = {
    "timeout":     _DEFAULT_TIMEOUT,
    "retries":     _DEFAULT_RETRIES,
    "retry_delay": _DEFAULT_RETRY_DELAY,
}

# HTTP status codes that indicate a temporary, server-side problem.  GitHub
# returns 429 for secondary rate limits and 5xx during maintenance or overload.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


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


def apply_network_config(config: dict) -> None:
    """
    Override the built-in network defaults from the optional [network] section
    of config.toml.  Missing or malformed values fall back to the defaults, so
    an older config file keeps working unchanged.
    """
    section = config.get("network", {})
    try:
        _network["timeout"]     = max(1,   int(section.get("timeout",     _DEFAULT_TIMEOUT)))
        _network["retries"]     = max(1,   int(section.get("retries",     _DEFAULT_RETRIES)))
        _network["retry_delay"] = max(0.0, float(section.get("retry_delay", _DEFAULT_RETRY_DELAY)))
    except (TypeError, ValueError):
        log("Warning: invalid [network] settings in config — using defaults.")


# ── GitHub API helpers ─────────────────────────────────────────────────────────

class GitHubRequestError(RuntimeError):
    """Raised when a GitHub API request still fails after all retry attempts."""


def _describe_error(exc: Exception) -> str:
    """Render an exception as a short one-line reason suitable for the log."""
    reason = getattr(exc, "reason", None) or exc
    return f"{type(exc).__name__}: {reason}"


def _github_get(url: str, token: str) -> dict | list:
    """
    Perform an authenticated GET request to the GitHub REST API and return the
    parsed JSON body.

    Transient failures — connection timeouts, dropped connections, DNS errors
    and the temporary HTTP statuses in _RETRYABLE_STATUS — are retried with an
    exponentially growing pause between attempts.  Only when every attempt has
    failed is GitHubRequestError raised, so a momentary network blip no longer
    aborts the whole collection run.

    A 403 response is treated as a soft error (no push access to that repo)
    and returns an empty dict so the caller can skip the entry gracefully.
    Permanent HTTP errors (401, 404, …) are re-raised immediately.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"insights-traffic-collector/{__version__}",
        },
    )

    attempts   = _network["retries"]
    delay      = _network["retry_delay"]
    last_error = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=_network["timeout"]) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # Traffic API requires push access; repos where access is denied
                # are skipped silently to keep the output clean.
                log(f"  [403 skipped] {url}")
                return {}
            if exc.code not in _RETRYABLE_STATUS:
                raise
            last_error = f"HTTP {exc.code} {exc.reason}"
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException) as exc:
            last_error = _describe_error(exc)

        # Reached only when the attempt failed with a retryable condition.
        if attempt < attempts:
            log(f"  [retry {attempt}/{attempts - 1}] {last_error} — retrying in {delay:g}s")
            time.sleep(delay)
            delay *= 2

    raise GitHubRequestError(f"{last_error} (after {attempts} attempts) — {url}")


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


# ── Main collection routine ───────────────────────────────────────────────────

def _new_rows_for_repo(
    full_name: str,
    traffic: dict,
    existing_keys: set[tuple[str, str]],
) -> list[dict]:
    """
    Turn one repository's raw traffic response into CSV rows, leaving out the
    (date, repo) pairs that the CSV already contains.
    """
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

    rows: list[dict] = []
    for date_str in all_dates:
        key = (date_str, full_name)
        if key not in existing_keys:
            v = views_by_date.get(date_str, {})
            c = clones_by_date.get(date_str, {})
            rows.append({
                "date":           date_str,
                "repo":           full_name,
                "views":          v.get("count",   0),
                "views_uniques":  v.get("uniques", 0),
                "clones":         c.get("count",   0),
                "clones_uniques": c.get("uniques", 0),
            })
    return rows


def append_rows(csv_path: Path, rows: list[dict]) -> None:
    """Append rows to the CSV file in chronological order, writing the header
    first when the file is being created."""
    ordered = sorted(rows, key=lambda r: (r["date"], r["repo"]))

    is_new_file = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        if is_new_file:
            writer.writeheader()
        writer.writerows(ordered)


def collect(output_dir: Path, token: str) -> bool:
    """
    Fetch traffic data for every owned repository and append new rows to the
    CSV file.  Rows whose (date, repo) key already exists are skipped so the
    file always contains exactly one entry per (date, repo) pair.

    Returns True when every repository was fetched successfully.  A repository
    that is still unreachable after all retries is reported and skipped rather
    than aborting the run, so the data gathered for the remaining repositories
    is written to the CSV regardless.
    """
    username = get_username(token)
    log(f"Authenticated as: {username}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"insights-traffic-{username}.csv"

    existing_keys = load_existing_keys(csv_path)
    repos = get_owned_repos(token)
    log(f"Found {len(repos)} owned repositories")

    new_rows:     list[dict] = []
    failed_repos: list[str]  = []

    for repo in repos:
        full_name = repo["full_name"]
        log(f"  Fetching: {full_name}")
        try:
            traffic = get_repo_traffic(token, full_name)
            new_rows.extend(_new_rows_for_repo(full_name, traffic, existing_keys))
        except (GitHubRequestError, urllib.error.HTTPError) as exc:
            # A single unreachable repository must not discard the data that
            # has already been collected for the others.
            log(f"  Warning: skipped {full_name} — {exc}")
            failed_repos.append(full_name)

    if new_rows:
        append_rows(csv_path, new_rows)
        log(f"Appended {len(new_rows)} new records → {csv_path}")
    else:
        log("No new records to append — all data is already up to date.")

    if failed_repos:
        log(
            f"Warning: {len(failed_repos)} of {len(repos)} repositories could not be "
            f"fetched: {', '.join(failed_repos)}"
        )

    return not failed_repos


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
    apply_network_config(config)

    if args.output_dir:
        output_dir = args.output_dir.expanduser()
    else:
        default_dir = config.get("output", {}).get("directory", "~/Documents/GitHubInsights")
        output_dir  = Path(default_dir).expanduser()

    # Failures that survive every retry are reported as a single readable line
    # instead of a traceback — the log is read by humans, not by a debugger.
    try:
        complete = collect(output_dir, token)
    except GitHubRequestError as exc:
        log(f"Error: GitHub API is unreachable — {exc}")
        sys.exit(1)
    except urllib.error.HTTPError as exc:
        log(f"Error: GitHub API returned HTTP {exc.code} {exc.reason} — check the token and its scopes.")
        sys.exit(1)

    if config.get("chart", {}).get("auto_report", True):
        _try_generate_report(output_dir, config)

    # Signal an incomplete run to the scheduler so the failure is visible,
    # while the data that was collected has already been saved above.
    if not complete:
        sys.exit(1)


if __name__ == "__main__":
    main()
