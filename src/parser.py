"""Auto-detect ticker / fair-value columns from sheet headers and parse rows."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional


log = logging.getLogger(__name__)


@dataclass
class Stock:
    ticker: str
    fair_value: float


@dataclass
class ParseResult:
    stocks: list[Stock]
    header_row_index: int  # 0-based; -1 if not found
    ticker_col: int        # 0-based; -1 if not found
    fair_col: int          # 0-based; -1 if not found
    error: Optional[str] = None


def _matches_any(text: str, keywords: list[str]) -> bool:
    text_low = text.lower().strip()
    for kw in keywords:
        if kw.lower() in text_low:
            return True
    return False


def _find_header_row(
    rows: list[list[str]],
    ticker_kws: list[str],
    fair_kws: list[str],
    max_scan: int = 10,
) -> tuple[int, int, int]:
    """Return (header_row_idx, ticker_col_idx, fair_col_idx); -1 if not found."""
    for i, row in enumerate(rows[:max_scan]):
        ticker_col = -1
        fair_col = -1
        for j, cell in enumerate(row):
            if not cell:
                continue
            if ticker_col == -1 and _matches_any(cell, ticker_kws):
                ticker_col = j
            elif fair_col == -1 and _matches_any(cell, fair_kws):
                fair_col = j
        if ticker_col >= 0 and fair_col >= 0:
            return i, ticker_col, fair_col
    return -1, -1, -1


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_number(cell: str) -> Optional[float]:
    if not cell:
        return None
    cleaned = cell.replace(",", "").strip()
    m = _NUM_RE.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse(rows: list[list[str]], header_keywords: dict[str, list[str]]) -> ParseResult:
    if not rows:
        return ParseResult(stocks=[], header_row_index=-1, ticker_col=-1, fair_col=-1,
                           error="sheet is empty")

    ticker_kws = header_keywords.get("ticker", [])
    fair_kws = header_keywords.get("fair_value", [])

    h_idx, t_col, f_col = _find_header_row(rows, ticker_kws, fair_kws)
    if h_idx < 0:
        return ParseResult(
            stocks=[], header_row_index=-1, ticker_col=-1, fair_col=-1,
            error=(
                "Could not auto-detect header row. "
                f"Looked for ticker keywords {ticker_kws} and "
                f"fair-value keywords {fair_kws} in the first 10 rows."
            ),
        )

    stocks: list[Stock] = []
    seen: set[str] = set()
    for row in rows[h_idx + 1 :]:
        if t_col >= len(row) or f_col >= len(row):
            continue
        ticker_raw = row[t_col].strip().upper()
        fair_raw = row[f_col].strip()
        if not ticker_raw or not fair_raw:
            continue
        # Skip header-like duplicates / non-ticker text
        if not re.fullmatch(r"[A-Z0-9\-\.&]{1,10}", ticker_raw):
            continue
        fair = _parse_number(fair_raw)
        if fair is None or fair <= 0:
            continue
        if ticker_raw in seen:
            continue
        seen.add(ticker_raw)
        stocks.append(Stock(ticker=ticker_raw, fair_value=fair))

    return ParseResult(
        stocks=stocks, header_row_index=h_idx, ticker_col=t_col, fair_col=f_col
    )
