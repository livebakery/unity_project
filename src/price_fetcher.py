"""Fetch latest market prices from Yahoo Finance via yfinance."""
from __future__ import annotations

import logging
from typing import Optional

import yfinance as yf


log = logging.getLogger(__name__)


def fetch_prices(tickers: list[str], suffix: str = ".BK") -> dict[str, Optional[float]]:
    """Return mapping of bare ticker -> last price (or None if unavailable)."""
    if not tickers:
        return {}

    yahoo_symbols = [f"{t}{suffix}" for t in tickers]
    out: dict[str, Optional[float]] = {t: None for t in tickers}

    try:
        # period="2d" so weekend / holiday runs still see Friday's close
        df = yf.download(
            tickers=yahoo_symbols,
            period="2d",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=False,
            threads=True,
        )
    except Exception as e:
        log.warning("yf.download failed (%s); falling back to per-ticker fast_info", e)
        df = None

    if df is not None and not df.empty:
        for bare, sym in zip(tickers, yahoo_symbols):
            try:
                if len(yahoo_symbols) == 1:
                    closes = df["Close"].dropna()
                else:
                    closes = df[sym]["Close"].dropna()
                if len(closes) > 0:
                    out[bare] = float(closes.iloc[-1])
            except (KeyError, AttributeError):
                pass

    # Fallback for any still-missing tickers
    for bare, sym in zip(tickers, yahoo_symbols):
        if out[bare] is not None:
            continue
        try:
            info = yf.Ticker(sym).fast_info
            price = info.get("last_price") if hasattr(info, "get") else getattr(info, "last_price", None)
            if price is not None:
                out[bare] = float(price)
        except Exception as e:
            log.warning("Failed to fetch price for %s: %s", sym, e)

    return out
