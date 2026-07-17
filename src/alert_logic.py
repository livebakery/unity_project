"""Compute live ratio (Up/Down 3Y Premium / Up/Down Core) and dedupe alerts.

For each watchlist ticker:
    fair_3y_premium = fair_price_premium * (1 + cagr_3y/100) ** 3
    updown_3y       = (fair_3y_premium - live_price) / live_price * 100
    updown_core     = (fair_price_core - live_price) / live_price * 100
    ratio           = abs(updown_3y) / abs(updown_core)

Multi-tier alerts (all measured against the main ratio_threshold T):
    tier 1: ratio >= T * (1 - 0.15)   -> 🟡 watch  (15% below buy)
    tier 2: ratio >= T * (1 - 0.10)   -> 🟠 warm   (10% below buy)
    tier 3: ratio >= T                -> 🔴 buy    (mentor-confirmed signal)

Dedupe: alert fires only when the ticker's tier INCREASES from one run to
the next. When the ratio drops back down, the stored tier follows it
downward so the next upward crossing fires again.
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
    tier: int                       # 0/1/2/3 — filled by evaluate()


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
        tier=0,
    )


def tier_thresholds(ratio_threshold: float, warnings_pct: list[float]) -> list[float]:
    """Return tier thresholds in ASCENDING order: [warn1, warn2, ..., main].

    warnings_pct is a list of "% below main" values (e.g. [15, 10] → main*0.85,
    main*0.90). Duplicates and out-of-range entries are silently filtered.
    """
    tiers: list[float] = []
    for pct in warnings_pct:
        if pct is None:
            continue
        try:
            f = float(pct)
        except (TypeError, ValueError):
            continue
        if f <= 0 or f >= 100:
            continue
        tiers.append(ratio_threshold * (1.0 - f / 100.0))
    tiers.append(ratio_threshold)
    tiers = sorted(set(round(t, 6) for t in tiers))
    return tiers


def compute_tier(ratio: float, tiers: list[float]) -> int:
    """Return highest tier index (1-based) whose threshold is met, or 0."""
    tier = 0
    for i, t in enumerate(tiers, start=1):
        if ratio >= t:
            tier = i
    return tier


def evaluate(
    stocks: list[Stock],
    live_prices: dict[str, Optional[float]],
    last_tier: dict[str, int],
    tiers: list[float],
    ticker_configs: Optional[dict[str, dict]] = None,
    last_sell_alerted: Optional[dict[str, bool]] = None,
) -> tuple[list[Snapshot], list[Snapshot], list[Snapshot], dict[str, int], dict[str, bool]]:
    """
    Returns:
        snapshots:            all stocks with computed values + current tier
        new_buy_alerts:       snapshots whose buy tier increased since last run
                              (only for tickers with buy_ratio_enabled=true)
        new_sell_alerts:      snapshots that crossed sell_target upward this run
        updated_tier:         new last_tier dict to persist
        updated_sell:         new last_sell_alerted dict to persist
    """
    ticker_configs = ticker_configs or {}
    snapshots: list[Snapshot] = []
    new_buy_alerts: list[Snapshot] = []
    new_sell_alerts: list[Snapshot] = []
    updated_tier: dict[str, int] = {t: int(v) for t, v in last_tier.items()}
    updated_sell: dict[str, bool] = dict(last_sell_alerted or {})

    for s in stocks:
        price = live_prices.get(s.ticker)
        if price is None or price <= 0:
            continue
        snap = compute_snapshot(s, price)
        cfg = ticker_configs.get(s.ticker, {})
        buy_enabled = bool(cfg.get("buy_ratio_enabled", True))
        sell_target = cfg.get("sell_target")

        if buy_enabled:
            snap.tier = compute_tier(snap.ratio, tiers)
            was_tier = int(updated_tier.get(s.ticker, 0))
            if snap.tier > was_tier:
                new_buy_alerts.append(snap)
            updated_tier[s.ticker] = snap.tier
        else:
            snap.tier = 0
            updated_tier[s.ticker] = 0

        if sell_target is not None:
            try:
                target = float(sell_target)
            except (TypeError, ValueError):
                target = None
            if target is not None:
                at_target = snap.live_price >= target
                was_at_target = bool(updated_sell.get(s.ticker, False))
                if at_target and not was_at_target:
                    new_sell_alerts.append(snap)
                updated_sell[s.ticker] = at_target

        snapshots.append(snap)

    return snapshots, new_buy_alerts, new_sell_alerts, updated_tier, updated_sell


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
