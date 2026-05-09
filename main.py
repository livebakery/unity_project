"""Orchestrator: read sheet, fetch prices, compare to fair values, alert on Telegram."""
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
    if now_ict.weekday() >= 5:  # Sat=5, Sun=6
        return False
    t = now_ict.time()
    morning = hours_cfg["morning"]
    afternoon = hours_cfg["afternoon"]
    in_morning = _hhmm(morning["start"]) <= t <= _hhmm(morning["end"])
    in_afternoon = _hhmm(afternoon["start"]) <= t <= _hhmm(afternoon["end"])
    return in_morning or in_afternoon


def format_update_message(
    changes: dict[str, tuple[float | None, float]], removed: list[str]
) -> str:
    lines = ["📊 *พี่เซียนอัพเดทไฟล์ประเมินมูลค่าหุ้น*", ""]
    if changes:
        lines.append("*เปลี่ยนแปลง / เพิ่มใหม่:*")
        for ticker in sorted(changes):
            old_v, new_v = changes[ticker]
            if old_v is None:
                lines.append(f"• `{ticker}`: ใหม่ → {new_v:,.2f}")
            else:
                arrow = "↑" if new_v > old_v else "↓"
                pct = (new_v - old_v) / old_v * 100.0 if old_v else 0.0
                lines.append(
                    f"• `{ticker}`: {old_v:,.2f} → {new_v:,.2f} {arrow} ({pct:+.1f}%)"
                )
    if removed:
        lines.append("")
        lines.append("*ลบ:*")
        for ticker in sorted(removed):
            lines.append(f"• `{ticker}`")
    return "\n".join(lines)


def format_alert_message(alert: alert_logic.Alert) -> str:
    level_label = {
        1: "🟡 *Level 1* — ราคาแตะ Fair Value",
        2: "🟠 *Level 2* — ส่วนลด ≥ 10%",
        3: "🔴 *Level 3* — ส่วนลด ≥ 15% (Deep Value)",
    }[alert.level]
    return (
        f"{level_label}\n"
        f"`{alert.ticker}`\n"
        f"Fair value: {alert.fair_value:,.2f}\n"
        f"Current:    {alert.current_price:,.2f}\n"
        f"ส่วนลด:     {alert.discount_pct:+.2f}%"
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
        log.info("Market closed (now=%s ICT); exiting.", now_ict.strftime("%Y-%m-%d %H:%M %a"))
        return 0

    st = state.load()

    # 1. Detect Drive file change
    sheet_updated = False
    try:
        modified_time = drive_watcher.get_modified_time(sheet_id)
        if st["last_modified_time"] != modified_time:
            sheet_updated = st["last_modified_time"] is not None  # don't fire on first run
            st["last_modified_time"] = modified_time
    except Exception as e:
        log.warning("Drive metadata fetch failed: %s", e)

    # 2. Read sheet + parse fair values
    try:
        rows = sheets_client.read_sheet(sheet_id, config.get("worksheet_name"))
    except Exception as e:
        log.error("Failed to read sheet: %s", e)
        try:
            telegram_notify.send(f"⚠️ ไม่สามารถอ่าน Google Sheet ได้: `{e}`")
        except Exception:
            pass
        return 1

    parse_result = parser.parse(rows, config["header_keywords"])
    if parse_result.error:
        log.error("Parse error: %s", parse_result.error)
        try:
            telegram_notify.send(
                f"⚠️ Parser อ่าน sheet ไม่ได้ — โครงสร้างอาจเปลี่ยน\n"
                f"`{parse_result.error}`"
            )
        except Exception:
            pass
        return 1

    new_fair = {s.ticker: s.fair_value for s in parse_result.stocks}
    log.info("Parsed %d stocks (header row %d, ticker col %d, fair col %d)",
             len(new_fair), parse_result.header_row_index,
             parse_result.ticker_col, parse_result.fair_col)

    old_fair = {k: float(v) for k, v in st["last_fair_values"].items()}

    # 3. Notify on sheet update + reset alert levels for changed tickers
    if sheet_updated:
        changes, removed = alert_logic.diff_fair_values(new_fair, old_fair)
        if changes or removed:
            try:
                telegram_notify.send(format_update_message(changes, removed))
            except Exception as e:
                log.error("Failed to send update message: %s", e)
            for ticker in changes:
                st["last_alert_levels"][ticker] = 0
            for ticker in removed:
                st["last_alert_levels"].pop(ticker, None)

    st["last_fair_values"] = new_fair

    # 4. Fetch market prices
    tickers = list(new_fair.keys())
    prices = price_fetcher.fetch_prices(tickers, suffix=config.get("ticker_suffix", ".BK"))
    missing = [t for t, p in prices.items() if p is None]
    if missing:
        log.warning("No price for: %s", ", ".join(missing))

    # 5. Compute alerts (with dedupe via last_alert_levels)
    alerts, updated_levels = alert_logic.evaluate(
        fair_values=new_fair,
        current_prices=prices,
        last_alert_levels={k: int(v) for k, v in st["last_alert_levels"].items()},
        thresholds=config["thresholds"],
    )
    st["last_alert_levels"] = updated_levels

    # 6. Send alerts
    for a in alerts:
        try:
            telegram_notify.send(format_alert_message(a))
            log.info("Alert sent: %s level=%d discount=%.2f%%", a.ticker, a.level, a.discount_pct)
        except Exception as e:
            log.error("Failed to send alert for %s: %s", a.ticker, e)

    # 7. Persist state
    state.save(st)
    log.info("Done. %d alerts fired.", len(alerts))
    return 0


if __name__ == "__main__":
    sys.exit(run())
