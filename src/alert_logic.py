"""Compute live ratio (Up/Down 3Y Premium / Up/Down Core) and dedupe alerts.

For each watchlist ticker:
    fair_3y_premium = fair_price_premium * (1 + cagr_3y/100) ** 3
    updown_3y       = (fair_3y_premium - live_price) / live_price * 100
    updown_core     = (fair_price_core - live_price) / live_price * 100
    ratio           = abs(updown_3y) / abs(updown_core)

Alert when ratio >= ratio_threshold (default 10).

Dedupe: only fire when "in_signal" transitions False -> True. When ratio
drops back below threshold, reset state so the next cross fires again.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from src.parser import Stock


@dataclass
class Snapshot:
    ticker: str
    fair_price_premium: float
    cagr_3y_premium: float
    fair_price_core: float
    fair_3y_premium: float          # implied 3-year base case target
    live_price: float
    updown_3y_pct: float
    updown_core_pct: float
    ratio: float                    # math.inf if denominator is ~0
    triggered: bool                 # ratio >= threshold


def compute_snapshot(stock: Stock, live_price: float) -> Snapshot:
    fair_3y = stock.fair_price_premium * (1.0 + stock.cagr_3y_premium / 100.0) ** 3
    updown_3y = (fair_3y - live_price) / live_price * 100.0
    updown_core = (stock.fair_price_core - live_price) / live_price * 100.0
    denom = abs(updown_core)
    if denom < 1e-9:
        ratio = math.inf
    else:
        ratio = abs(updown_3y) / denom
    return Snapshot(
        ticker=stock.ticker,
        fair_price_premium=stock.fair_price_premium,
        cagr_3y_premium=stock.cagr_3y_premium,
        fair_price_core=stock.fair_price_core,
        fair_3y_premium=fair_3y,
        live_price=live_price,
        updown_3y_pct=updown_3y,
        updown_core_pct=updown_core,
        ratio=ratio,
        triggered=False,  # filled in by evaluate()
    )


def evaluate(
    stocks: list[Stock],
    live_prices: dict[str, Optional[float]],
    last_triggered: dict[str, bool],
    ratio_threshold: float,
) -> tuple[list[Snapshot], list[Snapshot], dict[str, bool]]:
    """
    Returns:
        snapshots:        all stocks with computed values (for diagnostics)
        new_alerts:       snapshots whose state flipped not-triggered -> triggered
        updated_state:    new last_triggered dict to persist
    """
    snapshots: list[Snapshot] = []
    new_alerts: list[Snapshot] = []
    updated = dict(last_triggered)

    for s in stocks:
        price = live_prices.get(s.ticker)
        if price is None or price <= 0:
            continue
        snap = compute_snapshot(s, price)
        snap.triggered = snap.ratio >= ratio_threshold
        snapshots.append(snap)

        was_triggered = bool(updated.get(s.ticker, False))
        if snap.triggered and not was_triggered:
            new_alerts.append(snap)
        updated[s.ticker] = snap.triggered

    return snapshots, new_alerts, updated


def diff_valuations(
    new: dict[str, Stock], old: dict[str, dict]
) -> tuple[dict[str, dict], list[str]]:
    """
    Compare new parsed Stock objects to old dict-form snapshots stored in state.
    Old format: {ticker: {fair_price_premium, cagr_3y_premium, fair_price_core}}
    Returns:
      changes: ticker -> {field: (old, new)} for added/modified
      removed: list of tickers that disappeared
    """
    changes: dict[str, dict] = {}
    for t, ns in new.items():
        os = old.get(t)
        new_vals = {
            "fair_price_premium": ns.fair_price_premium,
            "cagr_3y_premium": ns.cagr_3y_premium,
            "fair_price_core": ns.fair_price_core,
        }
        if os is None:
            changes[t] = {k: (None, v) for k, v in new_vals.items()}
            continue
        diffs: dict = {}
        for k, v in new_vals.items():
            old_v = os.get(k)
            if old_v is None or abs(float(old_v) - v) > 1e-6:
                diffs[k] = (old_v, v)
        if diffs:
            changes[t] = diffs
    removed = [t for t in old if t not in new]
    return changes, removed
