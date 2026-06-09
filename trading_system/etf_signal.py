#!/usr/bin/env python3
"""
Low-monitoring ETF trend + price-behavior signal tool.

Default data source: Yahoo chart endpoint. Local CSV data can be supplied with
--data-dir for resilience when the public endpoint changes.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_REPORT_DIR = ROOT / "reports"
YAHOO_RETRIES = 3
YAHOO_RETRY_DELAY_SECONDS = 0.8


@dataclass(frozen=True)
class Bar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IntradayPoint:
    timestamp: dt.datetime
    price: float
    open: float
    high: float
    low: float
    volume: float


@dataclass
class Signal:
    symbol: str
    role: str
    date: dt.date
    close: float
    sma200: float | None
    sma50: float | None
    sma20: float | None
    momentum_63: float | None
    momentum_126: float | None
    trend_ok: bool
    structure_ok: bool
    near_support: bool
    near_resistance: bool
    breakout_hold: bool
    pullback_stand: bool
    risk_signal: bool
    risk_reasons: list[str]
    support: float | None
    resistance: float | None
    target_pct: float = 0.0
    current_pct: float | None = None
    trade_delta_pct: float | None = None
    action: str = "WATCH"
    limit_price: float | None = None
    notes: list[str] | None = None
    current_price: float | None = None
    current_time: dt.datetime | None = None
    day_change_pct: float | None = None
    ten_min_change_pct: float | None = None
    short_term: dict[str, Any] | None = None


def pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value:.2f}%"


def money(value: float | None) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value:.2f}"


def moving_average(values: list[float], days: int) -> float | None:
    if len(values) < days:
        return None
    return statistics.fmean(values[-days:])


def rate_of_change(values: list[float], days: int) -> float | None:
    if len(values) <= days:
        return None
    prior = values[-days - 1]
    if prior == 0:
        return None
    return (values[-1] / prior - 1) * 100


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def load_csv_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("Date") or not row.get("Close"):
                continue
            try:
                bars.append(
                    Bar(
                        date=parse_date(row["Date"]),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume") or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
    return sorted(bars, key=lambda x: x.date)


def yahoo_request_json(req: urllib.request.Request, symbol: str, label: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, YAHOO_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < YAHOO_RETRIES:
                time.sleep(YAHOO_RETRY_DELAY_SECONDS * attempt)
    raise RuntimeError(f"Yahoo {label} request failed for {symbol} after {YAHOO_RETRIES} attempts: {last_error}")


def fetch_yahoo_bars(symbol: str, years: int = 3) -> list[Bar]:
    query = urllib.parse.urlencode(
        {
            "range": f"{years}y",
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ETFSignalTool/1.0",
            "Accept": "application/json",
        },
    )
    payload = yahoo_request_json(req, symbol, "daily")

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Yahoo chart error for {symbol}: {error}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No chart data returned for {symbol}")

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[Bar] = []
    for i, ts in enumerate(timestamps):
        try:
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            v = volumes[i] if i < len(volumes) else 0
        except IndexError:
            continue
        if o is None or h is None or l is None or c is None:
            continue
        bars.append(
            Bar(
                date=dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date(),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=float(v or 0),
            )
        )
    return sorted(bars, key=lambda x: x.date)


def fetch_yahoo_intraday(symbol: str, range_value: str = "5d", interval: str = "5m") -> list[IntradayPoint]:
    query = urllib.parse.urlencode(
        {
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ETFSignalTool/1.0",
            "Accept": "application/json",
        },
    )
    payload = yahoo_request_json(req, symbol, "intraday")

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Yahoo intraday chart error for {symbol}: {error}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No intraday chart data returned for {symbol}")

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    points: list[IntradayPoint] = []
    for i, ts in enumerate(timestamps):
        try:
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            v = volumes[i] if i < len(volumes) else 0
        except IndexError:
            continue
        if o is None or h is None or l is None or c is None:
            continue
        points.append(
            IntradayPoint(
                timestamp=dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc),
                price=float(c),
                open=float(o),
                high=float(h),
                low=float(l),
                volume=float(v or 0),
            )
        )
    return sorted(points, key=lambda x: x.timestamp)


def get_bars(symbol: str, data_dir: Path | None) -> list[Bar]:
    if data_dir:
        csv_path = data_dir / f"{symbol}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing local data file: {csv_path}")
        return load_csv_bars(csv_path)
    return fetch_yahoo_bars(symbol)


def safe_max(values: list[float]) -> float | None:
    return max(values) if values else None


def safe_min(values: list[float]) -> float | None:
    return min(values) if values else None


def is_recent_breakout_hold(bars: list[Bar], window: int, hold_days: int, buffer_pct: float, fail_pct: float) -> tuple[bool, bool, float | None]:
    if len(bars) < window + hold_days + 2:
        return False, False, None

    breakout_level = None
    breakout_index = None
    start = max(window, len(bars) - hold_days - 1)
    for idx in range(start, len(bars)):
        prior_high = safe_max([b.high for b in bars[idx - window : idx]])
        if prior_high is None:
            continue
        if bars[idx].close > prior_high * (1 + buffer_pct / 100):
            breakout_level = prior_high
            breakout_index = idx

    if breakout_level is None or breakout_index is None:
        return False, False, None

    latest_close = bars[-1].close
    hold = latest_close >= breakout_level * (1 - fail_pct / 100)
    failed = latest_close < breakout_level * (1 - fail_pct / 100)
    return hold, failed, breakout_level


def short_term_rules(config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "timeframe_days": [2, 14],
        "min_avg_dollar_volume_20": 50_000_000,
        "sma20_flat_slope_pct_3d": -0.2,
        "breakout_window_days": 14,
        "pullback_lookback_days": 5,
        "near_support_pct": 1.0,
        "breakout_buffer_pct": 0.2,
        "volume_multiplier": 1.2,
        "stop_buffer_pct": 0.2,
        "max_stop_distance_pct": 4.0,
        "min_risk_reward": 1.8,
        "second_target_r": 2.0,
        "risk_per_trade_pct": 1.0,
        "weak_momentum_5d_pct": -2.0,
    }
    defaults.update(config.get("short_term") or {})
    return defaults


def percent_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return (current / prior - 1) * 100


def average_dollar_volume(bars: list[Bar], days: int) -> float | None:
    if len(bars) < days:
        return None
    values = [bar.close * bar.volume for bar in bars[-days:] if bar.close > 0 and bar.volume is not None]
    return statistics.fmean(values) if values else None


def build_short_term_analysis(
    symbol: str,
    role: str,
    bars: list[Bar],
    config: dict[str, Any],
    sma20: float | None,
    risk_reasons: list[str],
    failed_breakout: bool,
) -> dict[str, Any]:
    rules = short_term_rules(config)
    latest = bars[-1]
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]
    entry_price = latest.close
    lookback = int(rules["pullback_lookback_days"])
    breakout_window = int(rules["breakout_window_days"])

    avg_volume20 = statistics.fmean([v for v in volumes[-20:] if v is not None]) if len(volumes) >= 20 else None
    avg_dollar_volume20 = average_dollar_volume(bars, 20)
    prior_sma20 = statistics.fmean(closes[-23:-3]) if len(closes) >= 23 else None
    sma20_slope_pct_3d = percent_change(sma20, prior_sma20)
    recent_low = safe_min(lows[-lookback:])
    prior_low = safe_min(lows[-lookback - 1 : -1])
    platform_low = safe_min(lows[-breakout_window - 1 : -1])
    breakout_level = safe_max(highs[-breakout_window - 1 : -1])
    prior_target_high = safe_max(highs[-breakout_window * 2 - 1 : -breakout_window - 1]) if len(highs) >= breakout_window * 2 + 1 else None

    support_candidates = [
        value
        for value in [sma20, prior_low, platform_low]
        if value is not None and value > 0 and value <= entry_price
    ]
    support_base = max(support_candidates) if support_candidates else None
    recent_touch_support = bool(
        support_base
        and any(abs(bar.low - support_base) / support_base * 100 <= float(rules["near_support_pct"]) for bar in bars[-lookback:])
    )
    pullback_setup = bool(
        support_base
        and recent_touch_support
        and latest.close > latest.open
        and sma20 is not None
        and latest.close > sma20
    )
    breakout_setup = bool(
        breakout_level
        and latest.close > breakout_level
        and (
            (avg_volume20 is not None and latest.volume >= avg_volume20 * float(rules["volume_multiplier"]))
            or latest.close >= breakout_level * (1 + float(rules["breakout_buffer_pct"]) / 100)
        )
    )

    stop_base = platform_low if breakout_setup and platform_low else support_base
    if stop_base is None and sma20 is not None and sma20 <= entry_price:
        stop_base = sma20
    stop_price = stop_base * (1 - float(rules["stop_buffer_pct"]) / 100) if stop_base else None
    risk_per_share = entry_price - stop_price if stop_price is not None else None
    stop_distance_pct = risk_per_share / entry_price * 100 if risk_per_share and risk_per_share > 0 else None

    target_candidates = [
        value
        for value in [breakout_level, prior_target_high]
        if value is not None and value > entry_price
    ]
    if target_candidates:
        target_price = min(target_candidates)
        target_source = "technical_resistance"
    elif risk_per_share and risk_per_share > 0:
        target_price = entry_price + risk_per_share * float(rules["min_risk_reward"])
        target_source = "risk_reward"
    else:
        target_price = None
        target_source = None
    target2_price = entry_price + risk_per_share * float(rules["second_target_r"]) if risk_per_share and risk_per_share > 0 else None
    risk_reward = (target_price - entry_price) / risk_per_share if target_price and risk_per_share and risk_per_share > 0 else None

    equity = config.get("account", {}).get("equity")
    max_position_value = None
    if equity not in (None, 0) and stop_distance_pct and stop_distance_pct > 0:
        max_position_value = float(equity) * float(rules["risk_per_trade_pct"]) / 100 / (stop_distance_pct / 100)

    momentum5 = rate_of_change(closes, 5)
    sell_reasons: list[str] = []
    if stop_price is not None and latest.close < stop_price:
        sell_reasons.append("跌破短线止损位")
    if sma20 is not None and latest.close < sma20:
        sell_reasons.append("跌破 SMA20")
    if prior_low is not None and latest.close < prior_low:
        sell_reasons.append("跌破近 5 日低点")
    if failed_breakout:
        sell_reasons.append("突破失败")
    if momentum5 is not None and momentum5 <= float(rules["weak_momentum_5d_pct"]):
        sell_reasons.append("5 日动量明显转弱")

    reject_reasons: list[str] = []
    asset_eligible = role != "cash"
    liquidity_ok = bool(avg_dollar_volume20 is not None and avg_dollar_volume20 >= float(rules["min_avg_dollar_volume_20"]))
    own_risk_ok = not risk_reasons
    price_above_sma20 = bool(sma20 is not None and latest.close > sma20)
    sma20_flat_or_up = bool(sma20_slope_pct_3d is not None and sma20_slope_pct_3d >= float(rules["sma20_flat_slope_pct_3d"]))
    stop_distance_ok = bool(stop_distance_pct is not None and stop_distance_pct <= float(rules["max_stop_distance_pct"]))
    risk_reward_ok = bool(risk_reward is not None and risk_reward >= float(rules["min_risk_reward"]))
    trigger = "pullback" if pullback_setup else "breakout" if breakout_setup else None

    checks = [
        (asset_eligible, "现金类资产不参与短线买入"),
        (liquidity_ok, "20 日均成交额低于流动性门槛"),
        (own_risk_ok, "标的自身存在明确风险信号"),
        (price_above_sma20, "价格未站上 SMA20"),
        (sma20_flat_or_up, "SMA20 未走平或上行"),
        (pullback_setup or breakout_setup, "未触发回踩站稳或有效突破"),
        (stop_price is not None, "缺少可用技术止损位"),
        (stop_distance_ok, "止损距离过远"),
        (risk_reward_ok, "风险收益比低于 1:1.8"),
    ]
    for ok, reason in checks:
        if not ok:
            reject_reasons.append(reason)

    return {
        "timeframe": f"{rules['timeframe_days'][0]}-{rules['timeframe_days'][1]}D",
        "asset_eligible": asset_eligible,
        "liquidity_ok": liquidity_ok,
        "avg_dollar_volume_20": avg_dollar_volume20,
        "own_risk_ok": own_risk_ok,
        "price_above_sma20": price_above_sma20,
        "sma20_slope_pct_3d": sma20_slope_pct_3d,
        "sma20_flat_or_up": sma20_flat_or_up,
        "pullback_setup": pullback_setup,
        "breakout_setup": breakout_setup,
        "trigger": trigger,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_distance_pct": stop_distance_pct,
        "target_price": target_price,
        "target2_price": target2_price,
        "target_source": target_source,
        "risk_reward": risk_reward,
        "risk_per_trade_pct": float(rules["risk_per_trade_pct"]),
        "max_position_value": max_position_value,
        "account_equity_configured": equity is not None,
        "recent_low": recent_low,
        "breakout_level": breakout_level,
        "support_base": support_base,
        "momentum_5_pct": momentum5,
        "stop_distance_ok": stop_distance_ok,
        "risk_reward_ok": risk_reward_ok,
        "sell_reasons": sell_reasons,
        "sell_signal": bool(sell_reasons),
        "market_ok": None,
        "industry_risk_status": "not_connected",
        "industry_risk_note": "行业风险数据未接入",
        "buy_signal": False,
        "reject_reasons": reject_reasons,
    }


def finalize_short_term_signals(signals: dict[str, Signal], config: dict[str, Any]) -> None:
    market_symbols = config.get("universe", {}).get("market_filters", [])
    market_filters = [signals[symbol] for symbol in market_symbols if symbol in signals]
    market_ok = bool(market_filters) and all(signal.trend_ok and not signal.risk_signal for signal in market_filters)

    for signal in signals.values():
        if not signal.short_term:
            continue
        short_term = signal.short_term
        short_term["market_ok"] = market_ok
        if not market_ok and "大盘代理 SPY/QQQ 存在风险或数据缺失" not in short_term["reject_reasons"]:
            short_term["reject_reasons"].append("大盘代理 SPY/QQQ 存在风险或数据缺失")
        preconditions_ok = all(
            [
                short_term["asset_eligible"],
                short_term["liquidity_ok"],
                short_term["own_risk_ok"],
                short_term["price_above_sma20"],
                short_term["sma20_flat_or_up"],
                market_ok,
            ]
        )
        short_term["buy_signal"] = bool(
            preconditions_ok
            and (short_term["pullback_setup"] or short_term["breakout_setup"])
            and short_term["stop_distance_ok"]
            and short_term["risk_reward_ok"]
        )


def analyze_symbol(symbol: str, role: str, bars: list[Bar], config: dict[str, Any]) -> Signal:
    rules = config["rules"]
    behavior = config["price_behavior"]
    min_bars = max(rules["trend_sma_days"], behavior["breakout_window_days"] + behavior["breakout_hold_days"] + 2)
    if len(bars) < min_bars:
        raise RuntimeError(f"{symbol} needs at least {min_bars} daily bars, got {len(bars)}")

    latest = bars[-1]
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]

    sma200 = moving_average(closes, rules["trend_sma_days"])
    sma50 = moving_average(closes, rules["support_sma_days"])
    sma20 = moving_average(closes, rules["short_sma_days"])
    mom63 = rate_of_change(closes, rules["short_momentum_days"])
    mom126 = rate_of_change(closes, rules["momentum_days"])
    trend_ok = bool(sma200 is not None and latest.close > sma200)

    swing = behavior["swing_window_days"]
    recent_high = safe_max(highs[-swing:])
    prior_high = safe_max(highs[-2 * swing : -swing])
    recent_low = safe_min(lows[-swing:])
    prior_low = safe_min(lows[-2 * swing : -swing])
    structure_ok = bool(
        recent_high is not None
        and prior_high is not None
        and recent_low is not None
        and prior_low is not None
        and recent_high > prior_high
        and recent_low > prior_low
    )

    prior_swing_low = safe_min(lows[-swing - 1 : -1])
    prior_breakout_high = safe_max(highs[-behavior["breakout_window_days"] - 1 : -1])
    support_candidates = [x for x in [prior_swing_low, sma50, sma200] if x is not None and x > 0]
    support = min(support_candidates, key=lambda x: abs(latest.close - x)) if support_candidates else None
    resistance = prior_breakout_high

    near_support = bool(
        support is not None
        and latest.close >= support
        and (latest.close - support) / latest.close * 100 <= behavior["near_support_pct"]
    )
    near_resistance = bool(
        resistance is not None
        and latest.close <= resistance
        and (resistance - latest.close) / latest.close * 100 <= behavior["near_resistance_pct"]
    )

    breakout_hold, failed_breakout, breakout_level = is_recent_breakout_hold(
        bars,
        behavior["breakout_window_days"],
        behavior["breakout_hold_days"],
        behavior["breakout_buffer_pct"],
        behavior["failed_breakout_pct"],
    )
    if breakout_level is not None:
        resistance = breakout_level

    recent_touch_support = False
    if support is not None:
        recent_touch_support = any(
            abs(b.low - support) / support * 100 <= behavior["near_support_pct"]
            for b in bars[-5:]
            if support > 0
        )
    pullback_stand = bool(
        trend_ok
        and recent_touch_support
        and sma20 is not None
        and latest.close > sma20
        and latest.close > latest.open
    )

    avg_volume20 = statistics.fmean([v for v in volumes[-20:] if v is not None]) if len(volumes) >= 20 else 0
    candle_range = max(latest.high - latest.low, 0.0001)
    body_ratio = abs(latest.close - latest.open) / candle_range
    long_bearish = bool(
        latest.close < latest.open
        and body_ratio >= behavior["long_body_ratio"]
        and avg_volume20 > 0
        and latest.volume >= avg_volume20 * behavior["bearish_volume_multiplier"]
    )
    broke_swing_low = bool(prior_swing_low is not None and latest.close < prior_swing_low)
    broke_sma200 = bool(sma200 is not None and latest.close < sma200)

    risk_reasons: list[str] = []
    if role != "cash":
        if broke_sma200:
            risk_reasons.append("close_below_sma200")
        if broke_swing_low:
            risk_reasons.append("close_below_swing_low")
        if failed_breakout:
            risk_reasons.append("failed_breakout")
        if long_bearish:
            risk_reasons.append("long_bearish_volume")

    notes: list[str] = []
    if role == "cash":
        notes.append("cash_parking")
        trend_ok = True
        structure_ok = True
        near_support = False
        near_resistance = False
        breakout_hold = False
        pullback_stand = False
    elif trend_ok:
        notes.append("trend_ok")
    if role != "cash" and structure_ok:
        notes.append("higher_high_higher_low")
    if role != "cash" and breakout_hold:
        notes.append("breakout_hold")
    if role != "cash" and pullback_stand:
        notes.append("pullback_stand")
    if role != "cash" and near_support:
        notes.append("near_support")
    if role != "cash" and near_resistance and not breakout_hold:
        notes.append("near_resistance")

    short_term = build_short_term_analysis(symbol, role, bars, config, sma20, risk_reasons, failed_breakout)

    return Signal(
        symbol=symbol,
        role=role,
        date=latest.date,
        close=latest.close,
        sma200=sma200,
        sma50=sma50,
        sma20=sma20,
        momentum_63=mom63,
        momentum_126=mom126,
        trend_ok=trend_ok,
        structure_ok=structure_ok,
        near_support=near_support,
        near_resistance=near_resistance,
        breakout_hold=breakout_hold,
        pullback_stand=pullback_stand,
        risk_signal=bool(risk_reasons),
        risk_reasons=risk_reasons,
        support=support,
        resistance=resistance,
        notes=notes,
        short_term=short_term,
    )


def account_drawdown(config: dict[str, Any]) -> float | None:
    account = config["account"]
    equity = account.get("equity")
    high_watermark = account.get("high_watermark")
    if equity is None or high_watermark in (None, 0):
        return None
    return max(0.0, (float(high_watermark) - float(equity)) / float(high_watermark) * 100)


def role_for_symbol(symbol: str, config: dict[str, Any]) -> str:
    universe = config["universe"]
    if symbol in universe.get("risk_assets", []):
        return "risk"
    if symbol in universe.get("defensive_assets", []):
        return "defensive"
    if symbol in universe.get("stock_assets", []):
        return "stock"
    if symbol in universe.get("cash_assets", []):
        return "cash"
    return "cash"


def price_behavior_allows_entry(signal: Signal) -> bool:
    if signal.risk_signal:
        return False
    if signal.near_resistance and not signal.breakout_hold:
        return False
    return signal.structure_ok or signal.breakout_hold or signal.pullback_stand


def build_targets(signals: dict[str, Signal], config: dict[str, Any]) -> tuple[dict[str, float], str, float | None]:
    rules = config["rules"]
    universe = config["universe"]
    cash_symbol = config["account"]["cash_symbol"]
    drawdown = account_drawdown(config)

    targets = {symbol: 0.0 for symbol in signals}
    market_filters = [signals[s] for s in universe["market_filters"] if s in signals]
    market_ok = bool(market_filters) and all(s.trend_ok and not s.risk_signal for s in market_filters)

    if drawdown is not None and drawdown >= rules["drawdown_cash_pct"]:
        targets[cash_symbol] = 100.0
        return targets, "CASH_ONLY_DRAWDOWN_12", drawdown

    risk_candidates = [
        s
        for s in signals.values()
        if s.role == "risk" and s.trend_ok and price_behavior_allows_entry(s)
    ]
    defensive_candidates = [
        s
        for s in signals.values()
        if s.role == "defensive" and s.trend_ok and not s.risk_signal
    ]
    risk_candidates.sort(key=lambda s: (s.momentum_126 if s.momentum_126 is not None else -999), reverse=True)
    defensive_candidates.sort(key=lambda s: (s.momentum_126 if s.momentum_126 is not None else -999), reverse=True)

    regime = "RISK_ON" if market_ok else "RISK_OFF"
    if market_ok:
        for signal in risk_candidates[: rules["risk_slots"]]:
            targets[signal.symbol] = float(rules["risk_slot_weight_pct"])
        if defensive_candidates:
            targets[defensive_candidates[0].symbol] = float(rules["defensive_weight_pct"])
    else:
        if defensive_candidates:
            targets[defensive_candidates[0].symbol] = float(rules["risk_off_defensive_weight_pct"])

    if drawdown is not None and drawdown >= rules["drawdown_reduce_pct"]:
        regime = "REDUCED_RISK_DRAWDOWN_8"
        for symbol, signal in signals.items():
            if signal.role == "risk":
                released = targets[symbol] * 0.5
                targets[symbol] -= released
                targets[cash_symbol] = targets.get(cash_symbol, 0.0) + released

    used = sum(targets.values())
    targets[cash_symbol] = targets.get(cash_symbol, 0.0) + max(0.0, 100.0 - used)
    return targets, regime, drawdown


def add_trade_instructions(signals: dict[str, Signal], targets: dict[str, float], config: dict[str, Any]) -> None:
    holdings = config["account"].get("holdings_pct") or {}
    threshold = float(config["rules"]["rebalance_threshold_pct"])
    execution = config["execution"]

    for symbol, signal in signals.items():
        target = round(targets.get(symbol, 0.0), 2)
        current_raw = holdings.get(symbol)
        current = float(current_raw) if current_raw is not None else None
        signal.target_pct = target
        signal.current_pct = current
        signal.trade_delta_pct = None if current is None else round(target - current, 2)

        if current is None:
            signal.action = "SET_TARGET" if target > 0 else "WATCH"
            continue
        if abs(target - current) < threshold:
            signal.action = "HOLD"
            continue
        if target > current:
            signal.action = "BUY_LIMIT"
            signal.limit_price = signal.close * (1 + execution["buy_limit_buffer_pct"] / 100)
        elif target < current:
            signal.action = "SELL_LIMIT"
            signal.limit_price = signal.close * (1 - execution["sell_limit_buffer_pct"] / 100)


def add_intraday_observations(signals: dict[str, Signal]) -> dict[str, str]:
    errors: dict[str, str] = {}

    def fetch(symbol: str) -> tuple[str, list[IntradayPoint]]:
        return symbol, fetch_yahoo_intraday(symbol)

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(signals)))) as executor:
        futures = {executor.submit(fetch, symbol): symbol for symbol in signals}
        for future in as_completed(futures):
            symbol = futures[future]
            signal = signals[symbol]
            try:
                _, points = future.result()
            except Exception as exc:
                errors[symbol] = str(exc)
                continue
            if not points:
                errors[symbol] = "No intraday points returned"
                continue

            latest = points[-1]
            same_day = [p for p in points if p.timestamp.date() == latest.timestamp.date()]
            day_open = same_day[0].open if same_day else None
            signal.current_price = latest.price
            signal.current_time = latest.timestamp
            if day_open:
                signal.day_change_pct = (latest.price / day_open - 1) * 100
            if len(points) >= 3:
                signal.ten_min_change_pct = (latest.price / points[-3].price - 1) * 100
    return errors


def add_intraday_observations_sequential(signals: dict[str, Signal]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for symbol, signal in signals.items():
        try:
            points = fetch_yahoo_intraday(symbol)
        except Exception as exc:
            errors[symbol] = str(exc)
            continue
        if not points:
            errors[symbol] = "No intraday points returned"
            continue

        latest = points[-1]
        same_day = [p for p in points if p.timestamp.date() == latest.timestamp.date()]
        day_open = same_day[0].open if same_day else None
        signal.current_price = latest.price
        signal.current_time = latest.timestamp
        if day_open:
            signal.day_change_pct = (latest.price / day_open - 1) * 100
        if len(points) >= 3:
            signal.ten_min_change_pct = (latest.price / points[-3].price - 1) * 100
    return errors


def signal_to_dict(signal: Signal) -> dict[str, Any]:
    return {
        "date": signal.date.isoformat(),
        "symbol": signal.symbol,
        "role": signal.role,
        "close": signal.close,
        "sma200": signal.sma200,
        "sma50": signal.sma50,
        "sma20": signal.sma20,
        "trend_ok": signal.trend_ok,
        "structure_ok": signal.structure_ok,
        "near_support": signal.near_support,
        "near_resistance": signal.near_resistance,
        "breakout_hold": signal.breakout_hold,
        "pullback_stand": signal.pullback_stand,
        "risk_signal": signal.risk_signal,
        "risk_reasons": signal.risk_reasons,
        "momentum_63_pct": signal.momentum_63,
        "momentum_126_pct": signal.momentum_126,
        "support": signal.support,
        "resistance": signal.resistance,
        "target_pct": signal.target_pct,
        "current_pct": signal.current_pct,
        "trade_delta_pct": signal.trade_delta_pct,
        "action": signal.action,
        "limit_price": signal.limit_price,
        "notes": signal.notes or [],
        "current_price": signal.current_price,
        "current_time": signal.current_time.isoformat() if signal.current_time else None,
        "day_change_pct": signal.day_change_pct,
        "ten_min_change_pct": signal.ten_min_change_pct,
        "short_term": signal.short_term,
    }


def generate_signal_snapshot(
    config_path: Path = DEFAULT_CONFIG,
    report_dir: Path = DEFAULT_REPORT_DIR,
    data_dir: Path | None = None,
    equity: float | None = None,
    high_watermark: float | None = None,
    include_intraday: bool = True,
    write_outputs: bool = True,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config_override if config_override is not None else load_config(config_path)
    symbols = sorted(
        set(
            config["universe"]["risk_assets"]
            + config["universe"]["defensive_assets"]
            + config["universe"]["cash_assets"]
            + config["universe"].get("stock_assets", [])
        )
    )
    if equity is not None:
        config["account"]["equity"] = equity
    if high_watermark is not None:
        config["account"]["high_watermark"] = high_watermark

    signals: dict[str, Signal] = {}
    data_errors: dict[str, str] = {}

    def analyze_one(symbol: str) -> tuple[str, Signal]:
        bars = get_bars(symbol, data_dir)
        role = role_for_symbol(symbol, config)
        return symbol, analyze_symbol(symbol, role, bars, config)

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(symbols)))) as executor:
        futures = {executor.submit(analyze_one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result_symbol, signal = future.result()
                signals[result_symbol] = signal
            except Exception as exc:
                data_errors[symbol] = str(exc)

    if not signals:
        raise RuntimeError("No signal data could be generated")

    targets, regime, drawdown = build_targets(signals, config)
    add_trade_instructions(signals, targets, config)
    finalize_short_term_signals(signals, config)
    intraday_errors = add_intraday_observations(signals) if include_intraday else {}

    if write_outputs:
        write_csv(signals, report_dir / "latest_signals.csv")
        write_markdown(signals, report_dir / "latest_report.md", regime, drawdown)

    latest_date = max(s.date for s in signals.values())
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "latest_daily_date": latest_date.isoformat(),
        "regime": regime,
        "drawdown_pct": drawdown,
        "order_rule": "regular-session limit orders only; no market orders",
        "symbols": [signal_to_dict(signals[s]) for s in sorted(signals, key=lambda x: (signals[x].role, x))],
        "errors": {
            "daily": data_errors,
            "intraday": intraday_errors,
        },
        "report_paths": {
            "csv": str((report_dir / "latest_signals.csv").resolve()),
            "markdown": str((report_dir / "latest_report.md").resolve()),
        },
    }


def write_csv(signals: dict[str, Signal], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date",
        "symbol",
        "role",
        "close",
        "sma200",
        "trend_ok",
        "structure_ok",
        "near_support",
        "near_resistance",
        "breakout_hold",
        "pullback_stand",
        "risk_signal",
        "risk_reasons",
        "momentum_63_pct",
        "momentum_126_pct",
        "support",
        "resistance",
        "target_pct",
        "current_pct",
        "trade_delta_pct",
        "action",
        "limit_price",
        "notes",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for signal in sorted(signals.values(), key=lambda s: (s.role, s.symbol)):
            writer.writerow(
                {
                    "date": signal.date.isoformat(),
                    "symbol": signal.symbol,
                    "role": signal.role,
                    "close": money(signal.close),
                    "sma200": money(signal.sma200),
                    "trend_ok": signal.trend_ok,
                    "structure_ok": signal.structure_ok,
                    "near_support": signal.near_support,
                    "near_resistance": signal.near_resistance,
                    "breakout_hold": signal.breakout_hold,
                    "pullback_stand": signal.pullback_stand,
                    "risk_signal": signal.risk_signal,
                    "risk_reasons": ";".join(signal.risk_reasons),
                    "momentum_63_pct": pct(signal.momentum_63),
                    "momentum_126_pct": pct(signal.momentum_126),
                    "support": money(signal.support),
                    "resistance": money(signal.resistance),
                    "target_pct": pct(signal.target_pct),
                    "current_pct": pct(signal.current_pct),
                    "trade_delta_pct": pct(signal.trade_delta_pct),
                    "action": signal.action,
                    "limit_price": money(signal.limit_price),
                    "notes": ";".join(signal.notes or []),
                }
            )


def write_markdown(signals: dict[str, Signal], output_path: Path, regime: str, drawdown: float | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    latest_date = max(s.date for s in signals.values())
    lines = [
        "# ETF Daily Signal Report",
        "",
        f"- Date: {latest_date.isoformat()}",
        f"- Regime: {regime}",
        f"- Account drawdown: {pct(drawdown) if drawdown is not None else 'not configured'}",
        "- Order rule: regular-session limit orders only; no market orders.",
        "",
        "## Targets",
        "",
        "| Symbol | Role | Close | Trend | Price behavior | Risk | Target | Current | Action | Limit |",
        "|---|---|---:|---|---|---|---:|---:|---|---:|",
    ]
    for signal in sorted(signals.values(), key=lambda s: (s.role, s.symbol)):
        behavior = ",".join(signal.notes or []) or "none"
        risk = ",".join(signal.risk_reasons) if signal.risk_reasons else "none"
        lines.append(
            "| {symbol} | {role} | {close} | {trend} | {behavior} | {risk} | {target} | {current} | {action} | {limit} |".format(
                symbol=signal.symbol,
                role=signal.role,
                close=money(signal.close),
                trend="OK" if signal.trend_ok else "NO",
                behavior=behavior,
                risk=risk,
                target=pct(signal.target_pct),
                current=pct(signal.current_pct),
                action=signal.action,
                limit=money(signal.limit_price),
            )
        )

    lines.extend(
        [
            "",
            "## 10-Minute Checklist",
            "",
            "- Trend: risk ETFs must close above the 200-day SMA.",
            "- Structure: prefer higher highs and higher lows, breakout holds, or pullback-then-stand patterns.",
            "- Location: avoid buying close to resistance unless the breakout is holding.",
            "- Risk: reduce or exit on close below 200-day SMA, swing-low break, failed breakout, or long bearish volume candle.",
            "- Account: 8% drawdown halves risk allocations; 12% drawdown moves to SGOV/cash.",
            "",
            "## Review Questions",
            "",
            "- Did the trend allow this trade?",
            "- Was the price location reasonable?",
            "- Was the exit handled by rule?",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve() if args.data_dir else None
    snapshot = generate_signal_snapshot(
        config_path=args.config,
        report_dir=Path(args.report_dir),
        data_dir=data_dir,
        equity=args.equity,
        high_watermark=args.high_watermark,
        include_intraday=not args.no_intraday,
        write_outputs=True,
    )

    print(f"Regime: {snapshot['regime']}")
    print(f"CSV: {snapshot['report_paths']['csv']}")
    print(f"Report: {snapshot['report_paths']['markdown']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF trend + price-behavior signal tool")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to config.json")
    parser.add_argument("--data-dir", type=Path, default=None, help="Optional directory containing SYMBOL.csv files")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Output report directory")
    parser.add_argument("--equity", type=float, default=None, help="Override account equity")
    parser.add_argument("--high-watermark", type=float, default=None, help="Override account high watermark")
    parser.add_argument("--no-intraday", action="store_true", help="Skip 5-minute observation data")
    return parser


if __name__ == "__main__":
    try:
        raise SystemExit(run(build_parser().parse_args()))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
