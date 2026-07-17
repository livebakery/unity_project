"""Weekly portfolio snapshot orchestrator.

Every Friday 16:50 ICT (or on manual dispatch):
  1. Open the portfolio spreadsheet.
  2. Pick the source tab (latest DDMMYYYY-named worksheet).
  3. If a tab named after TODAY already exists, exit cleanly.
  4. Duplicate the source tab and name it after today (DDMMYYYY).
  5. Extract unique tickers, fetch live prices from yfinance.
  6. Update market-price + derived cells (total_market, %U.PL) in place.
  7. Send a Telegram summary (total value, delta vs. source tab).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src import price_fetcher, sheets_ops, telegram_notify


log = logging.getLogger("portfolio_snapshot")

ICT = timezone(timedelta(hours=7))


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    cfg_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    sheet_id = os.environ.get("SHEET_ID") or config.get("sheet_id")
    if not sheet_id:
        log.error("SHEET_ID env var (or sheet_id in config) is required.")
        return 2

    columns = config["columns"]
    tab_format = config.get("tab_name_format", "%d%m%Y")
    ticker_suffix = config.get("ticker_suffix", ".BK")
    strategy = config.get("source_tab_strategy", "latest_dated")

    now_ict = datetime.now(tz=ICT)
    weekend_skip = bool(config.get("weekend_skip", True))
    force_run = os.environ.get("FORCE_RUN") == "1"
    if weekend_skip and not force_run and now_ict.weekday() >= 5:
        log.info("Weekend (%s), skipping snapshot.", now_ict.strftime("%A"))
        return 0

    today_tab = now_ict.strftime(tab_format)
    log.info("Target tab: %s (ICT %s)", today_tab, now_ict.isoformat())

    # 1. Open spreadsheet
    try:
        ss = sheets_ops.open_spreadsheet(sheet_id)
    except Exception as e:
        log.error("Failed to open spreadsheet: %s", e)
        _try_notify(f"⚠️ Portfolio: เปิด Google Sheet ไม่ได้\n`{e}`")
        return 1

    log.info("Opened spreadsheet: %s", ss.title)

    # 2. Skip if today's tab already exists (idempotent re-runs)
    existing = {ws.title for ws in ss.worksheets()}
    if today_tab in existing:
        log.info("Tab %r already exists; skipping.", today_tab)
        return 0

    # 3. Pick source tab
    source_ws = sheets_ops.pick_source_tab(ss, strategy=strategy)
    log.info("Source tab: %r", source_ws.title)

    # 4. Extract tickers from source
    tickers = sheets_ops.extract_tickers(source_ws, columns["ticker"])
    log.info("Tickers in portfolio: %s", tickers)
    if not tickers:
        _try_notify("⚠️ Portfolio: ไม่พบ ticker ใน source tab")
        return 1

    # 5. Fetch live prices
    prices = price_fetcher.fetch_prices(tickers, suffix=ticker_suffix)
    missing_prices = [t for t, p in prices.items() if p is None]
    if missing_prices:
        log.warning("Missing prices for: %s", ", ".join(missing_prices))

    if all(p is None for p in prices.values()):
        _try_notify("⚠️ Portfolio: ดึงราคาไม่ได้เลย (yfinance ล่มหรือ ticker ผิด?)")
        return 1

    # 6. Duplicate source → today's tab
    try:
        new_ws = sheets_ops.duplicate_tab(ss, source_ws, today_tab)
    except Exception as e:
        log.error("Failed to duplicate tab: %s", e)
        _try_notify(f"⚠️ Portfolio: duplicate tab ไม่ได้\n`{e}`")
        return 1

    # 7. Apply new prices
    prices_for_apply = {t: p for t, p in prices.items() if p is not None}
    try:
        rows_updated, missing_in_prices = sheets_ops.apply_prices(
            new_ws, prices_for_apply, columns
        )
    except Exception as e:
        log.error("Failed to apply prices: %s", e)
        _try_notify(f"⚠️ Portfolio: apply prices ไม่ได้\n`{e}`")
        return 1

    log.info("Applied prices to %d rows", rows_updated)

    # 8. Compute portfolio totals (from newly written cells)
    _, new_total_market = sheets_ops.portfolio_totals(new_ws, columns)
    _, old_total_market = sheets_ops.portfolio_totals(source_ws, columns)

    # 9. Send Telegram summary
    msg = _format_summary(
        today_tab=today_tab,
        source_tab=source_ws.title,
        new_total=new_total_market,
        old_total=old_total_market,
        prices=prices,
        tickers=tickers,
        missing_prices=missing_prices,
        rows_updated=rows_updated,
    )
    _try_notify(msg)

    log.info("Done.")
    return 0


def _format_summary(
    today_tab: str,
    source_tab: str,
    new_total: float,
    old_total: float,
    prices: dict[str, float],
    tickers: list[str],
    missing_prices: list[str],
    rows_updated: int,
) -> str:
    delta = new_total - old_total
    delta_pct = (delta / old_total * 100.0) if old_total > 0 else 0.0
    arrow = "🟢" if delta > 0 else ("🔴" if delta < 0 else "⚪")

    lines = [
        f"📊 *Portfolio Snapshot — `{today_tab}`*",
        f"(source: `{source_tab}`)",
        "",
        f"มูลค่าตลาดรวม: *{new_total:,.0f} บาท*",
        f"{arrow} เทียบ tab ก่อน: {delta:+,.0f} ({delta_pct:+.2f}%)",
        f"อัพเดท {rows_updated} rows",
        "",
        "*ราคาปิดวันนี้:*",
    ]
    for t in tickers:
        p = prices.get(t)
        if p is None:
            lines.append(f"  • `{t}`: ⚠️ ไม่มีราคา")
        else:
            lines.append(f"  • `{t}`: {p:,.2f}")

    if missing_prices:
        lines.append("")
        lines.append(f"⚠️ ราคาไม่ได้: {', '.join(missing_prices)}")

    return "\n".join(lines)


def _try_notify(text: str) -> None:
    try:
        telegram_notify.send(text)
    except Exception as e:
        log.error("Telegram send failed: %s", e)


if __name__ == "__main__":
    sys.exit(run())
