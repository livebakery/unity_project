"""Orchestrator: read VI valuation sheet, compute live ratio, alert on Telegram.

Buy signal:
    fair_3y_premium = fair_price_premium * (1 + cagr_3y/100)**3
    updown_3y       = (fair_3y_premium - live_price) / live_price * 100
    updown_core     = (fair_price_core - live_price) / live_price * 100
    ratio           = |updown_3y| / |updown_core|
Alert when ratio >= ratio_threshold (default 10).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import yaml

from src import alert_logic, drive_watcher, parser, price_fetcher, sheets_client, state, telegram_notify


log = logging.getLogger("stock_alert")

ICT = timezone(timedelta(hours=7))


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def is_market_open(now_ict: datetime, hours_cfg: dict) -> bool:
    if now_ict.weekday() >= 5:
        return False
    t = now_ict.time()
    morning = hours_cfg["morning"]
    afternoon = hours_cfg["afternoon"]
    return (
        _hhmm(morning["start"]) <= t <= _hhmm(morning["end"])
        or _hhmm(afternoon["start"]) <= t <= _hhmm(afternoon["end"])
    )


def format_update_message(changes: dict[str, dict], removed: list[str]) -> str:
    lines = ["📊 *พี่เซียนอัพเดทไฟล์ประเมินมูลค่าหุ้น*", ""]
    pretty = {
        "fair_price_premium": "Fair Price [Premium]",
        "cagr_3y_premium": "3Y CAGR [Premium]",
        "fair_price_core": "Fair Price [Core]",
    }
    if changes:
        for ticker in sorted(changes):
            lines.append(f"*{ticker}*")
            for field, (old_v, new_v) in changes[ticker].items():
                label = pretty.get(field, field)
                if old_v is None:
                    lines.append(f"  • {label}: ใหม่ → {new_v:,.2f}")
                else:
                    arrow = "↑" if new_v > old_v else "↓"
                    lines.append(f"  • {label}: {old_v:,.2f} → {new_v:,.2f} {arrow}")
            lines.append("")
    if removed:
        lines.append("*ลบออกจาก watchlist:*")
        for t in sorted(removed):
            lines.append(f"• {t}")
    return "\n".join(lines).strip()


def format_alert_message(snap: alert_logic.Snapshot, threshold: float) -> str:
    return (
        f"🚨 *สัญญาณซื้อ — `{snap.ticker}`*\n"
        f"ratio = `{snap.ratio:.2f}` (≥ {threshold:.0f})\n"
        f"\n"
        f"ราคาตลาด: {snap.live_price:,.2f}\n"
        f"Fair Price [Premium] (1Y): {snap.fair_price_premium:,.2f}\n"
        f"3Y CAGR: {snap.cagr_3y_premium:.2f}%\n"
        f"→ Fair Price 3Y: {snap.fair_3y_premium:,.2f}\n"
        f"Fair Price [Core]: {snap.fair_price_core:,.2f}\n"
        f"\n"
        f"Up/Down 3Y [Premium]: {snap.updown_3y_pct:+.2f}%\n"
        f"Up/Down [Core]: {snap.updown_core_pct:+.2f}%"
    )


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    cfg_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        log.error("SHEET_ID env var is not set")
        return 2

    now_ict = datetime.now(tz=ICT)
    skip_market_check = os.environ.get("FORCE_RUN") == "1"
    if not skip_market_check and not is_market_open(now_ict, config["market_hours_ict"]):
        log.info("Market closed (now=%s ICT); exiting.",
                 now_ict.strftime("%Y-%m-%d %H:%M %a"))
        return 0

    watchlist: list[str] = config.get("watchlist") or []
    if not watchlist:
        log.error("watchlist is empty in config.yaml")
        return 2
    threshold = float(config.get("ratio_threshold", 10.0))

    st = state.load()

    # 1. Drive modifiedTime poll
    sheet_updated = False
    try:
        modified_time = drive_watcher.get_modified_time(sheet_id)
        if st["last_modified_time"] != modified_time:
            sheet_updated = st["last_modified_time"] is not None
            st["last_modified_time"] = modified_time
    except Exception as e:
        log.warning("Drive metadata fetch failed: %s", e)

    # 2. Read sheet + parse
    try:
        rows = sheets_client.read_sheet(sheet_id, config.get("worksheet_name"))
    except Exception as e:
        log.error("Failed to read sheet: %s", e)
        try:
            telegram_notify.send(f"⚠️ ไม่สามารถอ่าน Google Sheet ได้: `{e}`")
        except Exception:
            pass
        return 1

    pr = parser.parse(rows, watchlist=watchlist)
    if pr.error:
        log.error("Parse error: %s", pr.error)
        try:
            telegram_notify.send(
                "⚠️ Parser อ่าน sheet ไม่ได้ — โครงสร้างอาจเปลี่ยน\n"
                f"`{pr.error}`"
            )
        except Exception:
            pass
        return 1

    found_tickers = {s.ticker for s in pr.stocks}
    missing_watchlist = [t.upper() for t in watchlist if t.upper() not in found_tickers]
    if missing_watchlist:
        log.warning("Watchlist tickers not found in sheet: %s", missing_watchlist)
    log.info("Parsed %d stocks (header row %d, columns %s)",
             len(pr.stocks), pr.header_row_index, pr.columns)

    new_vals = {s.ticker: s for s in pr.stocks}
    last_state_vals: dict[str, dict] = st.get("last_valuations", {})

    # 3. Notify on sheet update
    if sheet_updated:
        changes, removed = alert_logic.diff_valuations(new_vals, last_state_vals)
        if changes or removed:
            try:
                telegram_notify.send(format_update_message(changes, removed))
            except Exception as e:
                log.error("Failed to send update message: %s", e)
            # reset triggered state for changed tickers so a fresh signal fires
            for t in changes:
                st["last_triggered"][t] = False
            for t in removed:
                st["last_triggered"].pop(t, None)

    st["last_valuations"] = {
        t: {
            "fair_price_premium": s.fair_price_premium,
            "cagr_3y_premium": s.cagr_3y_premium,
            "fair_price_core": s.fair_price_core,
        }
        for t, s in new_vals.items()
    }

    # 4. Fetch live prices
    tickers = list(new_vals)
    prices = price_fetcher.fetch_prices(tickers, suffix=config.get("ticker_suffix", ".BK"))
    missing = [t for t, p in prices.items() if p is None]
    if missing:
        log.warning("No price for: %s", ", ".join(missing))

    # 5. Evaluate
    snapshots, new_alerts, updated = alert_logic.evaluate(
        stocks=pr.stocks,
        live_prices=prices,
        last_triggered={t: bool(v) for t, v in st.get("last_triggered", {}).items()},
        ratio_threshold=threshold,
    )
    st["last_triggered"] = updated

    for snap in snapshots:
        log.info("%s: live=%.2f fair3Y=%.2f core=%.2f UD3Y=%+.2f%% UDcore=%+.2f%% ratio=%.2f%s",
                 snap.ticker, snap.live_price, snap.fair_3y_premium, snap.fair_price_core,
                 snap.updown_3y_pct, snap.updown_core_pct, snap.ratio,
                 " [TRIGGERED]" if snap.triggered else "")

    # 6. Send alerts
    for snap in new_alerts:
        try:
            telegram_notify.send(format_alert_message(snap, threshold))
            log.info("Alert sent: %s", snap.ticker)
        except Exception as e:
            log.error("Failed to send alert for %s: %s", snap.ticker, e)

    state.save(st)
    log.info("Done. %d new alerts.", len(new_alerts))
    return 0


if __name__ == "__main__":
    sys.exit(run())
