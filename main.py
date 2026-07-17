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
from typing import Optional

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


TIER_META = {
    1: {"emoji": "🟡", "label": "watch", "th": "เริ่มน่าสน (15% จาก buy)"},
    2: {"emoji": "🟠", "label": "warm",  "th": "ใกล้แล้ว (10% จาก buy)"},
    3: {"emoji": "🔴", "label": "buy",   "th": "สัญญาณซื้อ (เซียนรับรอง)"},
}


def format_alert_message(
    snap: alert_logic.Snapshot, tiers: list[float], threshold: float
) -> str:
    meta = TIER_META.get(snap.tier, TIER_META[3])
    tier_threshold = tiers[snap.tier - 1] if 1 <= snap.tier <= len(tiers) else threshold
    if snap.tier >= 3:
        headline = f"{meta['emoji']} *สัญญาณซื้อ — `{snap.ticker}`*"
    else:
        headline = (
            f"{meta['emoji']} *{snap.ticker}* — {meta['th']}\n"
            f"_(tier {snap.tier}/3, ยังไม่ใช่สัญญาณซื้อเต็ม)_"
        )
    return (
        f"{headline}\n"
        f"ratio = `{snap.ratio:.2f}` (≥ {tier_threshold:.2f})\n"
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


def format_sell_alert_message(
    snap: alert_logic.Snapshot, sell_target: float
) -> str:
    pct_above = (snap.live_price - sell_target) / sell_target * 100.0
    return (
        f"💰 *ราคาแตะเป้าขาย — `{snap.ticker}`*\n"
        f"ราคาตลาด: {snap.live_price:,.2f}  (เป้า {sell_target:,.2f}, "
        f"เหนือเป้า {pct_above:+.2f}%)\n"
        f"\n"
        f"Fair Price [Premium] (1Y): {snap.fair_price_premium:,.2f}\n"
        f"Fair Price 3Y: {snap.fair_3y_premium:,.2f}\n"
        f"Fair Price [Core]: {snap.fair_price_core:,.2f}"
    )


def _normalize_watchlist(raw) -> tuple[list[str], dict[str, dict]]:
    """Accept either legacy list-of-strings or new dict-of-configs.

    Returns (ticker_list, per_ticker_config) with tickers upper-cased.
    """
    tickers: list[str] = []
    configs: dict[str, dict] = {}
    if isinstance(raw, dict):
        for t, cfg in raw.items():
            key = str(t).upper()
            tickers.append(key)
            configs[key] = dict(cfg) if isinstance(cfg, dict) else {}
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                # entries like {ticker: DOHOME, sell_target: 4.20}
                key = str(item.get("ticker") or "").upper()
                if not key:
                    continue
                tickers.append(key)
                configs[key] = {k: v for k, v in item.items() if k != "ticker"}
            else:
                key = str(item).upper()
                tickers.append(key)
                configs[key] = {}
    return tickers, configs


def format_heartbeat(
    snapshots: list[alert_logic.Snapshot],
    missing_prices: list[str],
    threshold: float,
    last_modified: Optional[str],
    now_ict: datetime,
) -> str:
    lines = [f"📍 *EOD {now_ict.strftime('%d %b %Y')}* — ระบบทำงานปกติ", ""]
    if snapshots:
        for snap in snapshots:
            tag = f" {TIER_META[snap.tier]['emoji']}" if snap.tier > 0 else ""
            lines.append(
                f"`{snap.ticker}` @ {snap.live_price:,.2f} — "
                f"ratio={snap.ratio:.2f}{tag}"
            )
            lines.append(
                f"  UD3Y {snap.updown_3y_pct:+.1f}% / "
                f"UDcore {snap.updown_core_pct:+.1f}% / "
                f"fair3Y {snap.fair_3y_premium:,.2f}"
            )
    else:
        lines.append("_ไม่มี snapshot (ดูราคาไม่ได้?)_")
    if missing_prices:
        lines.append("")
        lines.append(f"⚠️ ราคาไม่มี: {', '.join(missing_prices)}")
    if last_modified:
        lines.append("")
        lines.append(f"sheet last update: `{last_modified}`")
    return "\n".join(lines)


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
    heartbeat_only = os.environ.get("HEARTBEAT_ONLY") == "1"
    skip_market_check = os.environ.get("FORCE_RUN") == "1" or heartbeat_only
    if not skip_market_check and not is_market_open(now_ict, config["market_hours_ict"]):
        log.info("Market closed (now=%s ICT); exiting.",
                 now_ict.strftime("%Y-%m-%d %H:%M %a"))
        return 0

    watchlist_raw = config.get("watchlist") or []
    watchlist, ticker_configs = _normalize_watchlist(watchlist_raw)
    if not watchlist:
        log.error("watchlist is empty in config.yaml")
        return 2
    threshold = float(config.get("ratio_threshold", 10.0))
    warnings_pct = config.get("ratio_tier_warnings_pct") or []
    tiers = alert_logic.tier_thresholds(threshold, warnings_pct)
    log.info("Tier thresholds: %s (ratio_threshold=%.2f)", tiers, threshold)
    log.info("Watchlist: %s", ticker_configs)

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

    # 3. Notify on sheet update (suppressed in heartbeat mode — we only want
    #    one message per heartbeat run regardless of mentor activity).
    if sheet_updated and not heartbeat_only:
        changes, removed = alert_logic.diff_valuations(new_vals, last_state_vals)
        if changes or removed:
            try:
                telegram_notify.send(format_update_message(changes, removed))
            except Exception as e:
                log.error("Failed to send update message: %s", e)
            # Reset tier state for changed tickers so the new valuation can
            # fire fresh tier-crossing alerts.
            for t in changes:
                st["last_tier"][t] = 0
            for t in removed:
                st["last_tier"].pop(t, None)

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
    snapshots, new_buy_alerts, new_sell_alerts, updated_tier, updated_sell = alert_logic.evaluate(
        stocks=pr.stocks,
        live_prices=prices,
        last_tier={t: int(v) for t, v in st.get("last_tier", {}).items()},
        tiers=tiers,
        ticker_configs=ticker_configs,
        last_sell_alerted={t: bool(v) for t, v in st.get("last_sell_alerted", {}).items()},
    )

    for snap in snapshots:
        cfg = ticker_configs.get(snap.ticker, {})
        sell_target = cfg.get("sell_target")
        sell_str = f" sell_target={sell_target}" if sell_target is not None else ""
        buy_enabled = bool(cfg.get("buy_ratio_enabled", True))
        log.info(
            "%s: live=%.2f fair3Y=%.2f core=%.2f UD3Y=%+.2f%% UDcore=%+.2f%% "
            "ratio=%.2f tier=%d buy=%s%s",
            snap.ticker, snap.live_price, snap.fair_3y_premium, snap.fair_price_core,
            snap.updown_3y_pct, snap.updown_core_pct, snap.ratio, snap.tier,
            buy_enabled, sell_str,
        )

    # Heartbeat mode: send EOD summary, dedup so multiple cron triggers per day
    # only fire once. GitHub Actions cron is best-effort and drops runs, so
    # heartbeat.yml schedules 3 near-identical times — dedup here keeps the
    # user from seeing 2-3 identical heartbeats on days when all three fire.
    if heartbeat_only:
        today = now_ict.strftime("%Y-%m-%d")
        # Re-read state from disk so we don't accidentally save the fresh
        # last_modified_time from step 1 (that would suppress the next
        # mentor-edit diff message). Only persist the dedup field.
        st_save = state.load()
        if st_save.get("last_heartbeat_date") == today:
            log.info("Heartbeat already sent today (%s); skipping duplicate.", today)
            return 0
        msg = format_heartbeat(snapshots, missing, threshold,
                               st.get("last_modified_time"), now_ict)
        try:
            telegram_notify.send(msg)
            log.info("Heartbeat sent.")
        except Exception as e:
            log.error("Failed to send heartbeat: %s", e)
            return 1
        st_save["last_heartbeat_date"] = today
        state.save(st_save)
        return 0

    st["last_tier"] = updated_tier
    st["last_sell_alerted"] = updated_sell

    # 6. Send alerts (one per ticker per tier-up transition)
    for snap in new_buy_alerts:
        try:
            telegram_notify.send(format_alert_message(snap, tiers, threshold))
            log.info("Buy alert sent: %s (tier %d)", snap.ticker, snap.tier)
        except Exception as e:
            log.error("Failed to send buy alert for %s: %s", snap.ticker, e)

    # 7. Send sell alerts (price crossed sell_target upward)
    for snap in new_sell_alerts:
        cfg = ticker_configs.get(snap.ticker, {})
        try:
            target = float(cfg["sell_target"])
            telegram_notify.send(format_sell_alert_message(snap, target))
            log.info("Sell alert sent: %s @ %.2f (target %.2f)",
                     snap.ticker, snap.live_price, target)
        except Exception as e:
            log.error("Failed to send sell alert for %s: %s", snap.ticker, e)

    state.save(st)
    log.info("Done. %d buy + %d sell alerts.",
             len(new_buy_alerts), len(new_sell_alerts))
    return 0


if __name__ == "__main__":
    sys.exit(run())
