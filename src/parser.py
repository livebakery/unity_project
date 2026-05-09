"""Auto-detect columns from sheet headers and parse stock valuation rows.

Required columns (auto-detected by header keywords):
- Stock / ticker
- Fair Price [Premium]    -> base case fair price (1Y target)
- 3Y CAGR [Premium]       -> annual growth rate used to project 3Y target
- Fair Price [Core]       -> Core P/E target (no-growth assumption)

Live ratio (computed in alert_logic with live market price):
    fair_price_3y_premium = fair_price_premium * (1 + cagr_3y/100) ** 3
    updown_3y_premium = (fair_price_3y_premium - live_price) / live_price * 100
    updown_core      = (fair_price_core      - live_price) / live_price * 100
    ratio = |updown_3y_premium| / |updown_core|

Buy signal: ratio >= 10
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional


log = logging.getLogger(__name__)


@dataclass
class Stock:
    ticker: str
    fair_price_premium: float
    cagr_3y_premium: float          # percent, e.g. 15.0 means 15% / year
    fair_price_core: float


@dataclass
class ParseResult:
    stocks: list[Stock]
    header_row_index: int
    columns: dict[str, int]         # name -> 0-based col index
    error: Optional[str] = None


_REQUIRED_COLUMN_KEYWORDS = {
    "ticker": [
        ("stock",), ("ticker",), ("symbol",), ("หุ้น",), ("ชื่อย่อ",),
    ],
    "fair_price_premium": [
        ("fair", "price", "premium"),
        ("fair price", "premium"),
        ("ราคาเหมาะสม", "premium"),
    ],
    "cagr_3y_premium": [
        ("3y", "cagr", "premium"),
        ("cagr", "3y", "premium"),
    ],
    "fair_price_core": [
        ("fair", "price", "core"),
        ("fair price", "core"),
        ("ราคาเหมาะสม", "core"),
    ],
}


def _cell_matches(cell: str, all_terms: tuple[str, ...]) -> bool:
    low = cell.lower()
    return all(term.lower() in low for term in all_terms)


def _find_columns(
    rows: list[list[str]], max_scan: int = 10
) -> tuple[int, dict[str, int]]:
    """Return (header_row_idx, {column_name: col_idx}). Missing cols not included."""
    best_row = -1
    best_cols: dict[str, int] = {}
    for i, row in enumerate(rows[:max_scan]):
        cols: dict[str, int] = {}
        for col_name, keyword_groups in _REQUIRED_COLUMN_KEYWORDS.items():
            for j, cell in enumerate(row):
                if not cell:
                    continue
                if any(_cell_matches(cell, group) for group in keyword_groups):
                    if col_name not in cols:
                        cols[col_name] = j
                        break
        if len(cols) > len(best_cols):
            best_cols = cols
            best_row = i
            if len(cols) == len(_REQUIRED_COLUMN_KEYWORDS):
                break
    return best_row, best_cols


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_number(cell: str) -> Optional[float]:
    if not cell:
        return None
    cleaned = cell.replace(",", "").replace("%", "").strip()
    m = _NUM_RE.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


_TICKER_RE = re.compile(r"^[A-Z0-9\-\.&]{1,10}$")


def parse(
    rows: list[list[str]],
    watchlist: Optional[list[str]] = None,
) -> ParseResult:
    """Parse rows; if watchlist is given, return only those tickers (case-insensitive)."""
    if not rows:
        return ParseResult(stocks=[], header_row_index=-1, columns={},
                           error="sheet is empty")

    h_idx, cols = _find_columns(rows)
    missing = set(_REQUIRED_COLUMN_KEYWORDS) - set(cols)
    if missing:
        return ParseResult(
            stocks=[], header_row_index=h_idx, columns=cols,
            error=(
                f"Could not auto-detect columns: {sorted(missing)}. "
                f"Found columns at row {h_idx}: {cols}. "
                "Adjust header_keywords in config.yaml or rename sheet headers."
            ),
        )

    watch_set = {t.upper() for t in watchlist} if watchlist else None
    t_col = cols["ticker"]
    fp_col = cols["fair_price_premium"]
    cagr_col = cols["cagr_3y_premium"]
    fc_col = cols["fair_price_core"]
    max_col = max(cols.values())

    stocks: list[Stock] = []
    seen: set[str] = set()
    for row in rows[h_idx + 1 :]:
        if len(row) <= max_col:
            continue
        ticker_raw = (row[t_col] or "").strip().upper()
        if not ticker_raw or not _TICKER_RE.fullmatch(ticker_raw):
            continue
        if watch_set is not None and ticker_raw not in watch_set:
            continue
        if ticker_raw in seen:
            continue

        fp = _parse_number(row[fp_col])
        cagr = _parse_number(row[cagr_col])
        fc = _parse_number(row[fc_col])
        if fp is None or fp <= 0:
            log.warning("Skip %s: fair_price_premium missing or invalid (%r)",
                        ticker_raw, row[fp_col])
            continue
        if cagr is None:
            log.warning("Skip %s: cagr_3y_premium missing (%r)", ticker_raw, row[cagr_col])
            continue
        if fc is None or fc <= 0:
            log.warning("Skip %s: fair_price_core missing or invalid (%r)",
                        ticker_raw, row[fc_col])
            continue

        seen.add(ticker_raw)
        stocks.append(Stock(
            ticker=ticker_raw,
            fair_price_premium=fp,
            cagr_3y_premium=cagr,
            fair_price_core=fc,
        ))

    return ParseResult(stocks=stocks, header_row_index=h_idx, columns=cols)
