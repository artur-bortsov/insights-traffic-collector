#!/usr/bin/env python3
"""
GitHub Insights Report Generator
==================================
Reads an insights-traffic-<username>.csv file produced by collect_insights.py
and writes a two-sheet XLSX workbook:

  Data    — pivot table with the last N months of data (chart window), one row
            per date, one column per repository, for each of 4 metrics.  Also
            contains an all-time summary block at the bottom.  This is the
            single data source that all charts reference.

  Charts  — six compact charts only (no tables).  All charts pull their data
            directly from the Data sheet so they always reflect the current
            data.  The chart window length (default 6 months) is read from
            config.toml [chart] months.

The XLSX is regenerated from the CSV on every data-collection run so the
charts are always current after collect_insights.py finishes.

Usage:
  python3 generate_report.py [--csv PATH] [--output PATH]
                             [--config PATH] [--months N]

Requirements:
  Python 3.11+, openpyxl >= 3.0.0
"""

import argparse
import calendar
import csv
import sys
import tomllib
from datetime import date as _date
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.exit(
        "openpyxl is required.  Install it with:\n"
        "  pip install openpyxl"
    )

__version__ = "1.1.0"

# ── Visual style constants ─────────────────────────────────────────────────────

# Header: dark blue background, white bold text
_HEADER_FILL  = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT  = Font(color="FFFFFF", bold=True, size=10)
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Alternating row fill for readability
_ALT_ROW_FILL = PatternFill("solid", fgColor="DCE6F1")

# Chart dimensions in centimetres — two charts per row, compact layout
_CHART_W = 17
_CHART_H = 12

# Approx row count each chart occupies on the Charts sheet (12 cm / ~0.5 cm per row)
_CHART_ROW_STEP = 29

# Column where the right-hand chart of each pair starts.
# 17 cm ÷ ~1.78 cm per default column ≈ 9.6 columns; column L (12) adds ~2 columns
# of breathing room between the two charts in each row.
_CHART_RIGHT_COL = "L"

# Blank rows separating data blocks on the Data sheet
_BLOCK_SEP = 2

# openpyxl chart style (1–48); style 10 gives clear distinct colours
_CHART_STYLE = 10


# ── Style helpers ──────────────────────────────────────────────────────────────

def _header(cell, value: str) -> None:
    """Write value and apply the standard header style to a cell."""
    cell.value     = value
    cell.font      = _HEADER_FONT
    cell.fill      = _HEADER_FILL
    cell.alignment = _HEADER_ALIGN


def _alt_row(ws, row_idx: int, num_cols: int) -> None:
    """Apply the alternating-row fill to every other data row (0-based index)."""
    if row_idx % 2 == 0:
        for col in range(1, num_cols + 1):
            ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL


def _col_width(ws, col_idx: int, width: float) -> None:
    """Set the width of a single column by 1-based index."""
    ws.column_dimensions[get_column_letter(col_idx)].width = width


# ── Date helpers ───────────────────────────────────────────────────────────────

def _cutoff_date(months: int) -> str:
    """
    Return the ISO date string (YYYY-MM-DD) for exactly `months` calendar
    months before today.  Day is clamped to the last day of the target month.
    """
    today = _date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year  -= 1
    last_day = calendar.monthrange(year, month)[1]
    return _date(year, month, min(today.day, last_day)).strftime("%Y-%m-%d")


# ── CSV loading ────────────────────────────────────────────────────────────────

def load_csv(csv_path: Path) -> list[dict]:
    """
    Load all rows from the insights CSV file.
    Numeric fields are cast to int; rows are returned sorted by date then repo.
    """
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append({
                "date":           row["date"],
                "repo":           row["repo"],
                "views":          int(row.get("views",          0) or 0),
                "views_uniques":  int(row.get("views_uniques",  0) or 0),
                "clones":         int(row.get("clones",         0) or 0),
                "clones_uniques": int(row.get("clones_uniques", 0) or 0),
            })
    rows.sort(key=lambda r: (r["date"], r["repo"]))
    return rows


def _pivot(rows: list[dict], repos: list[str], dates: list[str],
           field: str) -> dict[str, dict[str, int]]:
    """
    Build {date → {repo → value}} for the requested field over the given dates.
    Missing (date, repo) pairs default to 0.
    """
    result: dict[str, dict[str, int]] = {d: {r: 0 for r in repos} for d in dates}
    for row in rows:
        if row["date"] in result and row["repo"] in result[row["date"]]:
            result[row["date"]][row["repo"]] = row[field]
    return result


def _compute_totals(rows: list[dict], repos: list[str]) -> dict[str, dict[str, int]]:
    """Sum all four traffic fields per repository across all rows."""
    totals: dict[str, dict[str, int]] = {
        repo: {"views": 0, "views_uniques": 0, "clones": 0, "clones_uniques": 0}
        for repo in repos
    }
    for row in rows:
        if row["repo"] in totals:
            for field in ("views", "views_uniques", "clones", "clones_uniques"):
                totals[row["repo"]][field] += row[field]
    return totals


# ── Data sheet ─────────────────────────────────────────────────────────────────

def _write_metric_block(
    ws,
    start_row: int,
    label: str,
    repos: list[str],
    dates: list[str],
    pivot: dict,
) -> tuple[int, int, int]:
    """
    Write one metric block (header + data rows) to the Data sheet.
    Returns (header_row, data_start_row, data_end_row) — all 1-based.
    """
    num_cols = len(repos) + 1  # date column + one column per repo

    # Header: first column is the metric label; remaining columns are repo names
    _header(ws.cell(row=start_row, column=1), label)
    for col, repo in enumerate(repos, 2):
        _header(ws.cell(row=start_row, column=col), repo.split("/")[-1])
    ws.row_dimensions[start_row].height = 28

    # Data rows: one row per date
    for i, date in enumerate(dates):
        row = start_row + 1 + i
        ws.cell(row=row, column=1).value = date
        for col, repo in enumerate(repos, 2):
            ws.cell(row=row, column=col).value = pivot[date].get(repo, 0)
        _alt_row(ws, row, num_cols)

    return start_row, start_row + 1, start_row + len(dates)


def _write_summary_block(
    ws,
    start_row: int,
    repos: list[str],
    totals: dict[str, dict[str, int]],
) -> tuple[int, int, int]:
    """
    Write the all-time summary block (one row per repo) to the Data sheet.
    Returns (header_row, data_start_row, data_end_row).
    """
    headers = ["Repository", "All-time Views", "Unique Visitors",
               "All-time Clones", "Unique Cloners"]
    for col, h in enumerate(headers, 1):
        _header(ws.cell(row=start_row, column=col), h)
    ws.row_dimensions[start_row].height = 28

    for i, repo in enumerate(repos):
        row = start_row + 1 + i
        t = totals[repo]
        ws.cell(row=row, column=1).value = repo.split("/")[-1]
        ws.cell(row=row, column=2).value = t["views"]
        ws.cell(row=row, column=3).value = t["views_uniques"]
        ws.cell(row=row, column=4).value = t["clones"]
        ws.cell(row=row, column=5).value = t["clones_uniques"]
        _alt_row(ws, row, 5)

    return start_row, start_row + 1, start_row + len(repos)


def build_data_sheet(
    wb: Workbook,
    all_rows: list[dict],
    repos: list[str],
    chart_dates: list[str],
) -> dict:
    """
    Build the 'Data' sheet and return a dict of block position tuples so the
    Charts sheet can reference the correct cell ranges.

    Sheet layout (all dates = chart window = last N months):
      Block 0  — Views          (header + one row per chart-window date)
      Block 1  — Unique Visitors
      Block 2  — Clones
      Block 3  — Unique Cloners
      Summary  — All-time totals per repository (all CSV rows, not filtered)

    Block format per row: date | repo1 | repo2 | ... | repoN
    Summary format:       repo | views | uniques | clones | clones_uniques
    """
    ws = wb.create_sheet("Data")
    ws.freeze_panes = "B2"

    # Chart-window rows for the four metric blocks
    chart_date_set = set(chart_dates)
    chart_rows = [r for r in all_rows if r["date"] in chart_date_set]

    pivots = {
        "views":          _pivot(chart_rows, repos, chart_dates, "views"),
        "views_uniques":  _pivot(chart_rows, repos, chart_dates, "views_uniques"),
        "clones":         _pivot(chart_rows, repos, chart_dates, "clones"),
        "clones_uniques": _pivot(chart_rows, repos, chart_dates, "clones_uniques"),
    }

    # All-time totals use every CSV row (not filtered to chart window)
    totals = _compute_totals(all_rows, repos)

    # Each metric block occupies (len(chart_dates) + 1) rows, then _BLOCK_SEP blank rows
    block_height = len(chart_dates) + 1

    def block_start(idx: int) -> int:
        return 1 + idx * (block_height + _BLOCK_SEP)

    b_views    = _write_metric_block(ws, block_start(0), "Views",
                                     repos, chart_dates, pivots["views"])
    b_uniques  = _write_metric_block(ws, block_start(1), "Unique Visitors",
                                     repos, chart_dates, pivots["views_uniques"])
    b_clones   = _write_metric_block(ws, block_start(2), "Clones",
                                     repos, chart_dates, pivots["clones"])
    b_cu       = _write_metric_block(ws, block_start(3), "Unique Cloners",
                                     repos, chart_dates, pivots["clones_uniques"])
    b_summary  = _write_summary_block(ws, block_start(4), repos, totals)

    # Column widths: date col + repo cols
    _col_width(ws, 1, 12)
    for col, repo in enumerate(repos, 2):
        _col_width(ws, col, max(10, len(repo.split("/")[-1]) + 2))
    # Summary block uses up to column 5; widen if narrower than repo cols
    for col in range(2, 6):
        existing = ws.column_dimensions[get_column_letter(col)].width or 0
        ws.column_dimensions[get_column_letter(col)].width = max(existing, 15)

    return {
        "ws":             ws,
        "views":          b_views,
        "views_uniques":  b_uniques,
        "clones":         b_clones,
        "clones_uniques": b_cu,
        "summary":        b_summary,
    }


# ── Charts sheet ───────────────────────────────────────────────────────────────

def _make_line_chart(
    data_ws,
    repos: list[str],
    block: tuple[int, int, int],
    title: str,
    y_label: str,
) -> LineChart:
    """
    Build a LineChart whose series and categories reference a metric block on
    the Data sheet.  Each repository becomes one series on the same chart.
    """
    header_row, data_start, data_end = block

    chart = LineChart()
    chart.title         = title
    chart.style         = _CHART_STYLE
    chart.y_axis.title  = y_label
    chart.x_axis.title  = "Date"
    chart.width         = _CHART_W
    chart.height        = _CHART_H

    # Row `header_row` holds repo names → used as series titles via titles_from_data
    data_ref = Reference(data_ws, min_col=2, max_col=len(repos) + 1,
                         min_row=header_row, max_row=data_end)
    chart.add_data(data_ref, titles_from_data=True)

    # Date column supplies the x-axis category labels (skip header row)
    cats_ref = Reference(data_ws, min_col=1, min_row=data_start, max_row=data_end)
    chart.set_categories(cats_ref)

    return chart


def _make_bar_chart(
    data_ws,
    repos: list[str],
    block: tuple[int, int, int],
    title: str,
    data_min_col: int,
    data_max_col: int,
) -> BarChart:
    """
    Build a clustered BarChart from the summary block on the Data sheet.
    `data_min_col` / `data_max_col` select which summary columns to plot.
    """
    header_row, data_start, data_end = block

    chart = BarChart()
    chart.type         = "col"
    chart.grouping     = "clustered"
    chart.title        = title
    chart.style        = _CHART_STYLE
    chart.y_axis.title = "Count"
    chart.width        = _CHART_W
    chart.height       = _CHART_H

    data_ref = Reference(data_ws, min_col=data_min_col, max_col=data_max_col,
                         min_row=header_row, max_row=data_end)
    chart.add_data(data_ref, titles_from_data=True)

    cats_ref = Reference(data_ws, min_col=1, min_row=data_start, max_row=data_end)
    chart.set_categories(cats_ref)

    return chart


def build_charts_sheet(wb: Workbook, blocks: dict, repos: list[str]) -> None:
    """
    Build the 'Charts' sheet — six compact charts in a 2-column grid.

    Layout (left column A, right column _CHART_RIGHT_COL):
      Row 1:              Views (left)      |  Unique Visitors (right)
      Row 1+_CHART_ROW_STEP:  Clones (left) |  Unique Cloners (right)
      Row 1+2*_CHART_ROW_STEP: All-time Views (left) | All-time Clones (right)

    All charts reference the 'Data' sheet — no tables are written here.
    """
    ws = wb.create_sheet("Charts")
    data_ws = blocks["ws"]

    line_specs = [
        ("views",          "Views",           "Daily Views by Repository"),
        ("views_uniques",  "Unique Visitors",  "Daily Unique Visitors by Repository"),
        ("clones",         "Clones",           "Daily Clones by Repository"),
        ("clones_uniques", "Unique Cloners",   "Daily Unique Cloners by Repository"),
    ]

    for i, (field, y_label, title) in enumerate(line_specs):
        chart = _make_line_chart(data_ws, repos, blocks[field], title, y_label)
        anchor_row = 1 + (i // 2) * _CHART_ROW_STEP
        anchor_col = "A" if i % 2 == 0 else _CHART_RIGHT_COL
        ws.add_chart(chart, f"{anchor_col}{anchor_row}")

    # Summary bar charts go in the third pair row
    bar_row = 1 + 2 * _CHART_ROW_STEP
    bar_views = _make_bar_chart(data_ws, repos, blocks["summary"],
                                "All-time Views by Repository", 2, 3)
    bar_clones = _make_bar_chart(data_ws, repos, blocks["summary"],
                                 "All-time Clones by Repository", 4, 5)
    ws.add_chart(bar_views,  f"A{bar_row}")
    ws.add_chart(bar_clones, f"{_CHART_RIGHT_COL}{bar_row}")


# ── Report assembly ────────────────────────────────────────────────────────────

def generate_report(csv_path: Path, output_path: Path, chart_months: int = 6) -> None:
    """
    Read the CSV and write a two-sheet XLSX report.

    Sheet 'Data'  — pivot of last `chart_months` months, plus all-time summary.
    Sheet 'Charts'— six charts referencing 'Data'; no tables.
    """
    print(f"Reading: {csv_path}")
    rows = load_csv(csv_path)

    if not rows:
        sys.exit("The CSV file is empty or contains no data rows.")

    repos     = sorted({row["repo"] for row in rows})
    all_dates = sorted({row["date"] for row in rows})

    # Chart window: last chart_months calendar months
    cutoff      = _cutoff_date(chart_months)
    chart_dates = [d for d in all_dates if d >= cutoff]
    if not chart_dates:
        # Fallback: if the filter removes everything, show all available dates
        chart_dates = all_dates

    print(
        f"  {len(rows)} rows  |  {len(repos)} repos  |  "
        f"{len(all_dates)} dates total  |  "
        f"{len(chart_dates)} dates in chart window ({chart_months} months)"
    )

    wb = Workbook()
    wb.remove(wb.active)  # remove the default blank sheet

    blocks = build_data_sheet(wb, rows, repos, chart_dates)
    build_charts_sheet(wb, blocks, repos)

    wb.save(output_path)
    print(f"Report saved: {output_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GitHub Insights Report Generator — "
            "converts insights-traffic-*.csv into a two-sheet XLSX report."
        )
    )
    parser.add_argument(
        "--csv", type=Path, metavar="PATH",
        help="Path to the insights CSV file",
    )
    parser.add_argument(
        "--output", type=Path, metavar="PATH",
        help="Output XLSX path (default: same directory as CSV, .xlsx extension)",
    )
    parser.add_argument(
        "--config", type=Path, metavar="PATH",
        help="Path to config.toml (used to locate the CSV automatically)",
    )
    parser.add_argument(
        "--months", type=int, default=None, metavar="N",
        help="Number of months to display in charts (overrides config.toml)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    csv_path = args.csv

    # Auto-detect the CSV file when no explicit path is given
    if csv_path is None:
        config_path = args.config or (Path(__file__).parent / "config.toml")
        if config_path.exists():
            with open(config_path, "rb") as fh:
                config = tomllib.load(fh)
            output_dir = Path(
                config.get("output", {}).get("directory", "~/Documents/GitHubInsights")
            ).expanduser()
        else:
            config     = {}
            output_dir = Path("~/Documents/GitHubInsights").expanduser()

        chart_months = args.months or config.get("chart", {}).get("months", 6)

        candidates = sorted(output_dir.glob("insights-traffic-*.csv"))
        if not candidates:
            sys.exit(f"No insights-traffic-*.csv file found in {output_dir}")
        csv_path = candidates[0]
        if len(candidates) > 1:
            print(f"Multiple CSV files found; using: {csv_path.name}")
    else:
        chart_months = args.months or 6

    csv_path = csv_path.expanduser().resolve()
    if not csv_path.exists():
        sys.exit(f"CSV file not found: {csv_path}")

    output_path = args.output.expanduser() if args.output else csv_path.with_suffix(".xlsx")

    generate_report(csv_path, output_path, chart_months)


if __name__ == "__main__":
    main()
