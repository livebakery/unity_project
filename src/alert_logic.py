"""Compute discount levels and decide which alerts to fire (with dedupe)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Alert:
    ticker: str
    fair_value: float
    current_price: float
    discount_pct: float
    level: int  # 1, 2, or 3


def compute_level(discount_pct: float, thresholds: dict[str, float]) -> int:
    """Return highest level (1-3) the discount qualifies for; 0 if below all."""
    if discount_pct >= thresholds["level_3_pct"]:
        return 3
    if discount_pct >= thresholds["level_2_pct"]:
        return 2
    if discount_pct >= thresholds["level_1_pct"]:
        return 1
    return 0


def evaluate(
    fair_values: dict[str, float],
    current_prices: dict[str, Optional[float]],
    last_alert_levels: dict[str, int],
    thresholds: dict[str, float],
) -> tuple[list[Alert], dict[str, int]]:
    """
    Returns (new_alerts_to_fire, updated_alert_levels).

    Dedupe rule: fire only when level INCREASES vs last seen.
    If current level drops back down, update the stored level (so a later
    re-cross will fire again) but do not fire a notification.
    """
    new_alerts: list[Alert] = []
    updated = dict(last_alert_levels)

    for ticker, fair in fair_values.items():
        price = current_prices.get(ticker)
        if price is None or fair <= 0:
            continue
        discount_pct = (fair - price) / fair * 100.0
        level = compute_level(discount_pct, thresholds)
        previous = int(updated.get(ticker, 0))
        if level > previous:
            new_alerts.append(
                Alert(
                    ticker=ticker,
                    fair_value=fair,
                    current_price=price,
                    discount_pct=discount_pct,
                    level=level,
                )
            )
        updated[ticker] = level

    return new_alerts, updated


def diff_fair_values(
    new: dict[str, float], old: dict[str, float]
) -> tuple[dict[str, tuple[Optional[float], float]], list[str]]:
    """
    Return:
      changes: ticker -> (old_value or None, new_value)  for added or modified rows
      removed: tickers that disappeared from the new set
    """
    changes: dict[str, tuple[Optional[float], float]] = {}
    for t, new_v in new.items():
        old_v = old.get(t)
        if old_v is None:
            changes[t] = (None, new_v)
        elif abs(old_v - new_v) > 1e-9:
            changes[t] = (old_v, new_v)
    removed = [t for t in old if t not in new]
    return changes, removed
