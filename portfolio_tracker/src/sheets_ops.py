"""Google Sheets operations: pick source tab, duplicate, apply prices."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


log = logging.getLogger(__name__)


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON env var is not set."
        )
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(sheet_id: str) -> gspread.Spreadsheet:
    return _client().open_by_key(sheet_id)


_DATED_TAB_RE = re.compile(r"^(\d{2})[/\-]?(\d{2})[/\-]?(\d{4})$")


def _parse_dated_tab(name: str) -> Optional[datetime]:
    """Match `DDMMYYYY`, `DD/MM/YYYY`, or `DD-MM-YYYY`."""
    m = _DATED_TAB_RE.match(name.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def find_tab_for_date(
    ss, target_date: datetime
) -> Optional[str]:
    """Return the tab title matching target_date (any accepted format), or None."""
    for ws in ss.worksheets():
        d = _parse_dated_tab(ws.title)
        if d is not None and d.date() == target_date.date():
            return ws.title
    return None


def pick_source_tab(
    ss: gspread.Spreadsheet, strategy: str = "latest_dated"
) -> gspread.Worksheet:
    """Return the worksheet to use as the source template.

    strategy:
      "latest_dated" — worksheet with the newest DDMMYYYY-parsed name;
                       falls back to last worksheet if no dated names.
      "last"         — the last worksheet in the workbook.
    """
    worksheets = ss.worksheets()
    if not worksheets:
        raise RuntimeError("Spreadsheet has no worksheets.")

    if strategy == "last":
        return worksheets[-1]

    dated: list[tuple[datetime, gspread.Worksheet]] = []
    for ws in worksheets:
        d = _parse_dated_tab(ws.title)
        if d is not None:
            dated.append((d, ws))
    if dated:
        dated.sort(key=lambda x: x[0])
        return dated[-1][1]
    log.warning("No dated tabs found; falling back to last worksheet %r",
                worksheets[-1].title)
    return worksheets[-1]


def duplicate_tab(
    ss: gspread.Spreadsheet,
    source_ws: gspread.Worksheet,
    new_title: str,
) -> gspread.Worksheet:
    """Duplicate source_ws to a new worksheet titled new_title.

    Inserted at the end. Raises if a worksheet with new_title already exists.
    """
    existing = {ws.title for ws in ss.worksheets()}
    if new_title in existing:
        raise RuntimeError(
            f"Worksheet {new_title!r} already exists; nothing to do."
        )
    new_ws = source_ws.duplicate(
        insert_sheet_index=len(ss.worksheets()),
        new_sheet_name=new_title,
    )
    log.info("Duplicated %r → %r (sheet id %d)",
             source_ws.title, new_ws.title, new_ws.id)
    return new_ws


def _col_letter(idx: int) -> str:
    """1 → A, 26 → Z, 27 → AA."""
    s = ""
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def apply_prices(
    ws: gspread.Worksheet,
    prices: dict[str, float],
    columns: dict[str, int],
) -> tuple[int, list[str]]:
    """Iterate the worksheet rows and update market_price + derived cells.

    Only updates rows whose ticker column matches a key in `prices`.
    Derived columns updated: total_market (shares * market_price),
    upl_pct ((market - cost) / cost * 100), proportion is left alone (needs
    grand total). Non-position rows (blanks, summaries) are untouched.

    Returns (rows_updated, missing_tickers_in_prices).
    """
    values = ws.get_all_values()
    t_col = columns["ticker"] - 1
    s_col = columns["shares"] - 1
    ac_col = columns["avg_cost"] - 1
    mp_col = columns["market_price"] - 1
    tm_col = columns["total_market"] - 1
    upl_col = columns["upl_pct"] - 1

    updates: list[dict] = []
    hits = 0
    missing_from_prices: set[str] = set()

    for i, row in enumerate(values):
        if len(row) <= max(t_col, s_col, ac_col):
            continue
        ticker = (row[t_col] or "").strip().upper()
        if not ticker or not re.fullmatch(r"[A-Z0-9\-\.&]{1,10}", ticker):
            continue
        try:
            shares = float((row[s_col] or "0").replace(",", ""))
            avg_cost = float((row[ac_col] or "0").replace(",", ""))
        except ValueError:
            continue
        if shares <= 0 or avg_cost <= 0:
            continue

        new_price = prices.get(ticker)
        if new_price is None:
            missing_from_prices.add(ticker)
            continue

        total_market = shares * new_price
        upl_pct = (new_price - avg_cost) / avg_cost * 100.0
        row_num = i + 1  # 1-based

        updates.append({
            "range": f"{_col_letter(mp_col + 1)}{row_num}",
            "values": [[new_price]],
        })
        updates.append({
            "range": f"{_col_letter(tm_col + 1)}{row_num}",
            "values": [[total_market]],
        })
        updates.append({
            "range": f"{_col_letter(upl_col + 1)}{row_num}",
            "values": [[upl_pct]],
        })
        hits += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info("Applied prices to %d rows (%d cell updates)", hits, len(updates))

    return hits, sorted(missing_from_prices)


def extract_tickers(ws: gspread.Worksheet, ticker_col: int) -> list[str]:
    """Return unique tickers from the worksheet (upper-case, order-preserved)."""
    values = ws.get_all_values()
    tc = ticker_col - 1
    seen: set[str] = set()
    out: list[str] = []
    for row in values:
        if len(row) <= tc:
            continue
        t = (row[tc] or "").strip().upper()
        if not t or not re.fullmatch(r"[A-Z0-9\-\.&]{1,10}", t):
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def portfolio_totals(
    ws: gspread.Worksheet,
    columns: dict[str, int],
) -> tuple[float, float]:
    """Sum total_cost and total_market columns across position rows.

    Non-position rows (blanks, summaries) contribute 0.
    """
    values = ws.get_all_values()
    t_col = columns["ticker"] - 1
    tc_col = columns["total_cost"] - 1
    tm_col = columns["total_market"] - 1

    total_cost = 0.0
    total_market = 0.0
    for row in values:
        if len(row) <= max(t_col, tc_col, tm_col):
            continue
        ticker = (row[t_col] or "").strip().upper()
        if not ticker or not re.fullmatch(r"[A-Z0-9\-\.&]{1,10}", ticker):
            continue
        try:
            tc = float((row[tc_col] or "0").replace(",", "")) if row[tc_col] else 0.0
            tm = float((row[tm_col] or "0").replace(",", "")) if row[tm_col] else 0.0
        except ValueError:
            continue
        total_cost += tc
        total_market += tm
    return total_cost, total_market
