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

    # 1b. Optional: rename any date-parseable tabs to the canonical format
    #     (e.g. legacy '17072026' → '17/07/2026'). Triggered by env var.
    if os.environ.get("RENAME_LEGACY") == "1":
        renamed = 0
        for ws in ss.worksheets():
            d = sheets_ops._parse_dated_tab(ws.title)
            if d is None:
                continue
            canonical = d.strftime(tab_format)
            if ws.title != canonical:
                log.info("Renaming %r → %r", ws.title, canonical)
                ws.update_title(canonical)
                renamed += 1
        log.info("Legacy rename complete: %d tabs renamed.", renamed)
        _try_notify(
            f"🔧 Portfolio: normalized {renamed} tab name(s) to `{tab_format}` format"
        )
        return 0

    # 2. Skip if today's tab already exists (idempotent re-runs). Match by
    #    parsed date so slashed and un-slashed formats are treated as one.
    #    RECOMPUTE_ONLY overrides the skip: reuse the existing tab instead of
    #    duplicating a new one, and resend a corrected summary. Added
    #    2026-08-05 after portfolio_totals() double-counted a second
    #    (breakdown-only) table and sent a wrong total to Telegram.
    recompute_only = os.environ.get("RECOMPUTE_ONLY") == "1"
    existing_match = sheets_ops.find_tab_for_date(ss, now_ict)
    reuse_existing_tab = False
    if existing_match is not None:
        if not recompute_only:
            log.info("Tab for today already exists as %r; skipping.", existing_match)
            return 0
        log.info("RECOMPUTE_ONLY set — reusing existing tab %r.", existing_match)
        reuse_existing_tab = True
        today_tab = existing_match

    # 3. Pick source tab (excluding today's own tab, so a recompute run
    #    doesn't pick itself as the comparison baseline).
    source_ws = sheets_ops.pick_source_tab(
        ss, strategy=strategy, exclude_title=today_tab if reuse_existing_tab else None
    )
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

    # 6. Duplicate source → today's tab (or reuse it, when recomputing)
    if reuse_existing_tab:
        new_ws = next(ws for ws in ss.worksheets() if ws.title == today_tab)
        log.info("Reusing existing tab %r (no duplicate).", today_tab)
    else:
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
    if reuse_existing_tab:
        msg = (
            "🔧 *แก้ไขยอดที่ส่งผิดก่อนหน้านี้* — บั๊กใน portfolio_totals() "
            "นับตารางย่อย (breakdown เฉพาะกลุ่ม Growth) ซ้ำเข้าไปด้วย "
            "ยอดที่ถูกต้องคือด้านล่างนี้\n\n" + msg
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
