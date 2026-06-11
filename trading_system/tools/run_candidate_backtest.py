"""Run the current candidate ETF/stock strategy as a local experiment.

This is an offline lab script. It reuses cached daily history, writes a full
backtest JSON with trades and equity curve, refreshes latest/top run indexes,
and generates the standalone HTML report. It does not modify the dashboard,
server, signal engine, or production config.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools.backtest_lab import (  # noqa: E402
    ETF_SYMBOLS,
    SECTOR_MAP,
    STOCK_SYMBOLS,
    build_scenario,
    ensure_daily_history,
    save_run_summary,
    summarize_result,
)
from tools.generate_backtest_report import generate as generate_report  # noqa: E402


ETF_WEIGHT = 0.60
STOCK_WEIGHT = 0.40
MAX_STOCK_NAMES = 6
MAX_RUNNER_NAMES = 4
BASE_TOTAL_PCT = 6.0
ADD1_TOTAL_PCT = 4.0
ADD2_TOTAL_PCT = 5.0
MAX_SINGLE_TOTAL_PCT = 15.0
NORMAL_MAX_HOLD_DAYS = 14
RUNNER_MAX_HOLD_DAYS = 60
SLIPPAGE_PCT = 0.1


def clean_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def make_pool(symbols: list[str], asset_type: str) -> dict[str, Any]:
    return {
        "version": 1,
        "groups": [{"id": asset_type, "name": asset_type, "symbols": symbols}],
        "instruments": {
            symbol: {"symbol": symbol, "type": asset_type, "assetType": asset_type, "active": True}
            for symbol in symbols
        },
    }


def build_etf_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(base_config)
    config["universe"]["risk_assets"] = ["SPY", "QQQ"]
    config["universe"]["defensive_assets"] = ["GLD", "TLT"]
    config["universe"]["stock_assets"] = []
    config["universe"]["cash_assets"] = []
    config["universe"]["market_filters"] = ["SPY", "QQQ"]
    short = config.setdefault("short_term", {})
    short["timeframe_days"] = [2, 14]
    short["base_position_pct"] = 50.0
    short["max_single_position_pct"] = 50.0
    short["theme_max_position_pct"] = 100.0
    short["risk_per_trade_pct"] = 1.0 / ETF_WEIGHT
    short["max_open_risk_pct"] = 8.0 / ETF_WEIGHT
    short["max_holding_days"] = 9999
    short["loss_streak_pause_days"] = 1
    short["trend_runner_enabled"] = False
    for symbol in ETF_SYMBOLS:
        config.setdefault("theme_risk", {}).setdefault("theme_map", {})[symbol] = "etf_core"
    return config


def build_stock_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(base_config)
    config["universe"]["risk_assets"] = []
    config["universe"]["defensive_assets"] = []
    config["universe"]["stock_assets"] = STOCK_SYMBOLS
    config["universe"]["cash_assets"] = []
    config["universe"]["market_filters"] = ["SPY", "QQQ"]
    short = config.setdefault("short_term", {})
    short["max_holding_days"] = NORMAL_MAX_HOLD_DAYS
    short["trend_runner_enabled"] = True
    for symbol, theme in SECTOR_MAP.items():
        config.setdefault("theme_risk", {}).setdefault("theme_map", {})[symbol] = theme
    return config


def load_histories(symbols: list[str], start_date: dt.date, end_date: dt.date) -> dict[str, list[dict[str, object]]]:
    return {symbol: server.load_backtest_history_entries(symbol, "1d", start_date, end_date) for symbol in symbols}


def bars_before(
    symbol: str,
    current_time: dt.datetime,
    bar_by_symbol_time: dict[str, dict[dt.datetime, Any]],
    limit: int,
) -> list[Any]:
    table = bar_by_symbol_time.get(symbol, {})
    times = [item_time for item_time in table if item_time <= current_time]
    times.sort()
    return [table[item_time] for item_time in times[-limit:]]


def pct_change(values: list[float], days: int) -> float | None:
    if len(values) <= days:
        return None
    prior = values[-days - 1]
    if prior <= 0:
        return None
    return (values[-1] / prior - 1) * 100


def avg_dollar_volume(bars: list[Any], days: int = 20) -> float:
    sample = bars[-days:]
    if not sample:
        return 0.0
    return statistics.fmean([bar.close * clean_float(bar.volume) for bar in sample if bar.close > 0])


def drawdown_from_high(bars: list[Any], days: int = 63) -> float:
    sample = bars[-days:]
    if not sample:
        return 0.0
    high = max(bar.close for bar in sample)
    if high <= 0:
        return 0.0
    return (sample[-1].close / high - 1) * 100


def relative_strength_stats(
    symbol: str,
    current_time: dt.datetime,
    bar_by_symbol_time: dict[str, dict[dt.datetime, Any]],
) -> dict[str, float | bool]:
    symbol_bars = bars_before(symbol, current_time, bar_by_symbol_time, 90)
    spy_bars = bars_before("SPY", current_time, bar_by_symbol_time, 90)
    if len(symbol_bars) < 22 or len(spy_bars) < 22:
        return {"rel20": 0.0, "rel63": 0.0, "rel_new_high_63": False, "rel_improving_20": False}
    count = min(len(symbol_bars), len(spy_bars))
    ratios = [
        symbol_bars[-count + idx].close / spy_bars[-count + idx].close
        for idx in range(count)
        if spy_bars[-count + idx].close > 0
    ]
    if len(ratios) < 22:
        return {"rel20": 0.0, "rel63": 0.0, "rel_new_high_63": False, "rel_improving_20": False}
    rel20 = (ratios[-1] / ratios[-21] - 1) * 100 if ratios[-21] > 0 else 0.0
    rel63 = (ratios[-1] / ratios[-64] - 1) * 100 if len(ratios) >= 64 and ratios[-64] > 0 else rel20
    rel_new_high_63 = ratios[-1] >= max(ratios[-63:])
    rel_improving_20 = ratios[-1] > ratios[-6] if len(ratios) >= 6 else rel20 > 0
    return {
        "rel20": rel20,
        "rel63": rel63,
        "rel_new_high_63": rel_new_high_63,
        "rel_improving_20": rel_improving_20,
    }


def momentum_improving(symbol: str, current_time: dt.datetime, bar_by_symbol_time: dict[str, dict[dt.datetime, Any]]) -> bool:
    bars = bars_before(symbol, current_time, bar_by_symbol_time, 35)
    if len(bars) < 27:
        return False
    closes = [bar.close for bar in bars]
    now = pct_change(closes, 20)
    prior = pct_change(closes[:-5], 20)
    return bool(now is not None and prior is not None and now > 0 and now >= prior)


def rank_score(
    symbol: str,
    current_time: dt.datetime,
    item: dict[str, Any],
    bar_by_symbol_time: dict[str, dict[dt.datetime, Any]],
) -> float:
    short = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
    bars = bars_before(symbol, current_time, bar_by_symbol_time, 90)
    rel = relative_strength_stats(symbol, current_time, bar_by_symbol_time)
    momentum20 = clean_float(short.get("momentum_20_pct"))
    momentum63 = clean_float(item.get("momentum_63_pct"))
    dollar_volume = avg_dollar_volume(bars, 20)
    liquidity_score = math.log10(max(1.0, dollar_volume)) - 7.0
    drawdown_quality = drawdown_from_high(bars, 63)
    return (
        clean_float(rel.get("rel63")) * 1.2
        + clean_float(rel.get("rel20")) * 0.9
        + momentum20 * 0.8
        + momentum63 * 0.35
        + liquidity_score * 3.0
        + drawdown_quality * 0.45
    )


def stock_equity(cash: float, positions: dict[str, dict[str, Any]], prices: dict[str, float]) -> float:
    return cash + sum(position_value(position, prices) for position in positions.values())


def position_value(position: dict[str, Any], prices: dict[str, float]) -> float:
    price = prices.get(str(position["symbol"])) or clean_float(position.get("lastPrice")) or clean_float(position.get("avgPrice"))
    return clean_float(position.get("quantity")) * price


def runner_count(positions: dict[str, dict[str, Any]]) -> int:
    return sum(1 for position in positions.values() if position.get("runnerActive"))


def is_strong_stock(
    symbol: str,
    current_time: dt.datetime,
    item: dict[str, Any],
    position: dict[str, Any] | None,
    bar_by_symbol_time: dict[str, dict[dt.datetime, Any]],
) -> bool:
    short = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
    rel = relative_strength_stats(symbol, current_time, bar_by_symbol_time)
    close = clean_float(item.get("close") or item.get("current_price"))
    sma20 = clean_float(short.get("sma20"))
    momentum20 = clean_float(short.get("momentum_20_pct"))
    return bool(
        close > 0
        and sma20 > 0
        and close > sma20
        and short.get("price_above_sma20")
        and short.get("sma20_flat_or_up")
        and momentum20 > 0
        and momentum_improving(symbol, current_time, bar_by_symbol_time)
        and (rel.get("rel_new_high_63") or (clean_float(rel.get("rel20")) > 0 and clean_float(rel.get("rel63")) > 0))
        and not item.get("near_resistance")
        and not short.get("sell_signal")
        and (position is None or close > clean_float(position.get("avgPrice")))
    )


def record_trade(
    trades: list[dict[str, Any]],
    *,
    time_value: dt.datetime,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    reason: str,
    entry_type: str = "unknown",
    pnl: float | None = None,
    realized_r: float | None = None,
    stop_price: float | None = None,
    bucket: str = "stock",
) -> None:
    trades.append(
        {
            "time": time_value.isoformat(),
            "date": time_value.date().isoformat(),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "valueUsdt": quantity * price,
            "realizedPnlUsdt": pnl,
            "realizedR": realized_r,
            "reason": reason,
            "entryType": entry_type,
            "stopPrice": stop_price,
            "bucket": bucket,
        }
    )


def buy_position(
    *,
    trades: list[dict[str, Any]],
    positions: dict[str, dict[str, Any]],
    cash: float,
    symbol: str,
    value: float,
    price: float,
    time_value: dt.datetime,
    item: dict[str, Any],
    stage: int,
    reason: str,
    current_index: int,
) -> float:
    short = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
    value = min(value, cash)
    if value <= 0:
        return cash
    quantity = value / price
    stop_price = clean_float(short.get("stop_price"))
    if symbol in positions:
        position = positions[symbol]
        old_cost = clean_float(position.get("avgPrice")) * clean_float(position.get("quantity"))
        new_quantity = clean_float(position.get("quantity")) + quantity
        position["quantity"] = new_quantity
        position["avgPrice"] = (old_cost + value) / new_quantity
        position["stage"] = max(int(position.get("stage") or 1), stage)
        position["lastPrice"] = price
        if stop_price > 0:
            position["stopPrice"] = max(clean_float(position.get("stopPrice")), stop_price)
        position["trendRunner"] = bool(position.get("trendRunner") or short.get("trend_runner"))
    else:
        positions[symbol] = {
            "symbol": symbol,
            "quantity": quantity,
            "initialQuantity": quantity,
            "avgPrice": price,
            "entryPrice": price,
            "lastPrice": price,
            "openedIndex": current_index,
            "stage": stage,
            "stopPrice": stop_price,
            "target1Price": clean_float(short.get("target1_price")),
            "target2Price": clean_float(short.get("target2_price")),
            "partialTaken": False,
            "target2Taken": False,
            "runnerActive": False,
            "trendRunner": bool(short.get("trend_runner")),
            "entryType": str(short.get("entry_type") or short.get("trigger") or "unknown"),
            "lastAtr": clean_float(short.get("atr")),
            "lastSma20": clean_float(short.get("sma20")),
        }
    record_trade(
        trades,
        time_value=time_value,
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        price=price,
        reason=reason,
        entry_type=str(short.get("entry_type") or short.get("trigger") or "unknown"),
        stop_price=stop_price,
    )
    return cash - value


def close_position(
    *,
    trades: list[dict[str, Any]],
    positions: dict[str, dict[str, Any]],
    cash: float,
    symbol: str,
    quantity: float,
    price: float,
    time_value: dt.datetime,
    reason: str,
) -> float:
    position = positions.get(symbol)
    if not position:
        return cash
    quantity = min(quantity, clean_float(position.get("quantity")))
    if quantity <= 0:
        return cash
    avg_price = clean_float(position.get("avgPrice"))
    risk = abs(avg_price - clean_float(position.get("stopPrice"))) * quantity
    pnl = (price - avg_price) * quantity
    realized_r = pnl / risk if risk > 0 else None
    record_trade(
        trades,
        time_value=time_value,
        symbol=symbol,
        side="SELL",
        quantity=quantity,
        price=price,
        reason=reason,
        entry_type=str(position.get("entryType") or "unknown"),
        pnl=pnl,
        realized_r=realized_r,
        stop_price=clean_float(position.get("stopPrice")),
    )
    cash += quantity * price
    position["quantity"] = clean_float(position.get("quantity")) - quantity
    if position["quantity"] <= 1e-9:
        positions.pop(symbol, None)
    return cash


def run_stock_bucket(
    *,
    config: dict[str, Any],
    start_date: dt.date,
    end_date: dt.date,
    initial_cash: float,
) -> dict[str, Any]:
    symbols = sorted(set(STOCK_SYMBOLS + ["SPY", "QQQ"]))
    histories = load_histories(symbols, start_date, end_date)
    bar_by_symbol_time = {
        symbol: {server.backtest_entry_time(entry): server.backtest_entry_bar(entry) for entry in entries}
        for symbol, entries in histories.items()
    }
    symbol_times = {symbol: sorted(table) for symbol, table in bar_by_symbol_time.items()}
    timeline = sorted(
        {
            item_time
            for table in bar_by_symbol_time.values()
            for item_time in table
            if start_date <= item_time.date() <= end_date
        }
    )

    def next_time(symbol: str, current_time: dt.datetime) -> dt.datetime | None:
        for item_time in symbol_times.get(symbol, []):
            if item_time > current_time:
                return item_time
        return None

    cash = initial_cash
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    pending_orders: list[dict[str, Any]] = []
    prices: dict[str, float] = {}
    high_watermark = initial_cash
    max_names = {"count": 0, "date": None, "symbols": []}

    for current_index, current_time in enumerate(timeline):
        current_bars = {
            symbol: table[current_time]
            for symbol, table in bar_by_symbol_time.items()
            if current_time in table
        }
        for symbol, bar in current_bars.items():
            prices[symbol] = bar.close
            if symbol in positions:
                positions[symbol]["lastPrice"] = bar.close

        for order in list(pending_orders):
            if order["time"] > current_time:
                continue
            symbol = str(order["symbol"])
            bar = current_bars.get(symbol)
            if not bar:
                pending_orders.remove(order)
                continue
            order_type = str(order["type"])
            if order_type == "sell" and symbol in positions:
                cash = close_position(
                    trades=trades,
                    positions=positions,
                    cash=cash,
                    symbol=symbol,
                    quantity=clean_float(positions[symbol].get("quantity")),
                    price=bar.open,
                    time_value=current_time,
                    reason=str(order.get("reason") or "signal_exit"),
                )
                pending_orders.remove(order)
                continue
            if order_type in {"base", "add1", "add2"}:
                item = order.get("item") if isinstance(order.get("item"), dict) else {}
                equity = stock_equity(cash, positions, prices)
                current_value = position_value(positions[symbol], prices) if symbol in positions else 0.0
                max_value = equity * (MAX_SINGLE_TOTAL_PCT / 100 / STOCK_WEIGHT)
                if order_type == "base":
                    value = equity * (BASE_TOTAL_PCT / 100 / STOCK_WEIGHT)
                    can_buy = symbol not in positions and len(positions) < MAX_STOCK_NAMES and value <= cash
                    reason = "base_6pct_ranked"
                    stage = 1
                elif order_type == "add1":
                    value = min(equity * (ADD1_TOTAL_PCT / 100 / STOCK_WEIGHT), max_value - current_value)
                    can_buy = symbol in positions and value >= equity * (ADD1_TOTAL_PCT / 100 / STOCK_WEIGHT) * 0.98
                    reason = "add1_4pct_strong"
                    stage = 2
                else:
                    value = min(equity * (ADD2_TOTAL_PCT / 100 / STOCK_WEIGHT), max_value - current_value)
                    can_buy = symbol in positions and value >= equity * (ADD2_TOTAL_PCT / 100 / STOCK_WEIGHT) * 0.98
                    reason = "add2_5pct_strong"
                    stage = 3
                if can_buy and value <= cash:
                    cash = buy_position(
                        trades=trades,
                        positions=positions,
                        cash=cash,
                        symbol=symbol,
                        value=value,
                        price=bar.open,
                        time_value=current_time,
                        item=item,
                        stage=stage,
                        reason=reason,
                        current_index=current_index,
                    )
                pending_orders.remove(order)

        snapshot, items = server.backtest_snapshot_at(
            current_time=current_time,
            histories=histories,
            config=config,
            symbols=symbols,
        )

        for symbol, position in list(positions.items()):
            bar = current_bars.get(symbol)
            item = items.get(symbol) if items else None
            short = item.get("short_term") if isinstance(item, dict) and isinstance(item.get("short_term"), dict) else {}
            if not bar:
                continue
            if short:
                atr = clean_float(short.get("atr"))
                sma20 = clean_float(short.get("sma20"))
                if atr > 0:
                    position["lastAtr"] = atr
                if sma20 > 0:
                    position["lastSma20"] = sma20
                if position.get("runnerActive"):
                    trail_candidates = [
                        clean_float(position.get("stopPrice")),
                        clean_float(position.get("entryPrice")),
                    ]
                    if sma20 > 0:
                        trail_candidates.append(sma20)
                    if atr > 0:
                        trail_candidates.append(bar.close - 2.5 * atr)
                    position["stopPrice"] = max(value for value in trail_candidates if value > 0)

            stop = clean_float(position.get("stopPrice"))
            target1 = clean_float(position.get("target1Price"))
            target2 = clean_float(position.get("target2Price"))
            if stop > 0 and bar.low <= stop:
                exit_price = min(bar.open, stop * (1 - SLIPPAGE_PCT / 100)) if bar.open < stop else stop * (1 - SLIPPAGE_PCT / 100)
                cash = close_position(
                    trades=trades,
                    positions=positions,
                    cash=cash,
                    symbol=symbol,
                    quantity=clean_float(position.get("quantity")),
                    price=exit_price,
                    time_value=current_time,
                    reason="hard_stop",
                )
                continue

            strong = bool(item and is_strong_stock(symbol, current_time, item, position, bar_by_symbol_time))
            can_runner = strong and (position.get("runnerActive") or runner_count(positions) < MAX_RUNNER_NAMES)
            if target2 > 0 and bar.high >= target2 and not position.get("target2Taken"):
                sell_pct = 0.15 if can_runner else 0.30
                cash = close_position(
                    trades=trades,
                    positions=positions,
                    cash=cash,
                    symbol=symbol,
                    quantity=clean_float(position.get("quantity")) * sell_pct,
                    price=max(bar.open, target2),
                    time_value=current_time,
                    reason="target2_sell_15pct_runner" if can_runner else "target2_sell_30pct",
                )
                if symbol in positions:
                    positions[symbol]["target2Taken"] = True
                    positions[symbol]["partialTaken"] = True
                    positions[symbol]["runnerActive"] = bool(can_runner)
                    positions[symbol]["stopPrice"] = max(clean_float(positions[symbol].get("stopPrice")), clean_float(positions[symbol].get("entryPrice")))
                continue
            if target1 > 0 and bar.high >= target1 and not position.get("partialTaken"):
                sell_pct = 0.15 if can_runner else 0.30
                cash = close_position(
                    trades=trades,
                    positions=positions,
                    cash=cash,
                    symbol=symbol,
                    quantity=clean_float(position.get("quantity")) * sell_pct,
                    price=max(bar.open, target1),
                    time_value=current_time,
                    reason="target1_sell_15pct_runner" if can_runner else "target1_sell_30pct",
                )
                if symbol in positions:
                    positions[symbol]["partialTaken"] = True
                    positions[symbol]["runnerActive"] = bool(can_runner)
                    positions[symbol]["stopPrice"] = max(clean_float(positions[symbol].get("stopPrice")), clean_float(positions[symbol].get("entryPrice")))

        if items:
            for symbol, position in list(positions.items()):
                item = items.get(symbol)
                if not item:
                    continue
                short = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
                execute_time = next_time(symbol, current_time)
                if execute_time is None:
                    continue
                holding_days = current_index - int(position.get("openedIndex") or current_index)
                strong = is_strong_stock(symbol, current_time, item, position, bar_by_symbol_time)
                if short.get("sell_signal"):
                    pending_orders.append({"time": execute_time, "symbol": symbol, "type": "sell", "reason": "signal_exit"})
                    continue
                if position.get("runnerActive") and holding_days >= RUNNER_MAX_HOLD_DAYS:
                    pending_orders.append({"time": execute_time, "symbol": symbol, "type": "sell", "reason": "runner_time_60d"})
                    continue
                if not position.get("runnerActive") and holding_days >= NORMAL_MAX_HOLD_DAYS:
                    pending_orders.append({"time": execute_time, "symbol": symbol, "type": "sell", "reason": "normal_time_14d"})
                    continue
                if strong and not any(order.get("symbol") == symbol and order.get("type") in {"add1", "add2"} for order in pending_orders):
                    if int(position.get("stage") or 1) == 1:
                        pending_orders.append({"time": execute_time, "symbol": symbol, "type": "add1", "item": item})
                    elif int(position.get("stage") or 1) == 2 and clean_float(short.get("momentum_20_pct")) >= 3.0:
                        pending_orders.append({"time": execute_time, "symbol": symbol, "type": "add2", "item": item})

            open_slots = MAX_STOCK_NAMES - len(positions) - sum(1 for order in pending_orders if order.get("type") == "base")
            if open_slots > 0:
                candidates: list[tuple[float, str, dict[str, Any]]] = []
                for symbol in STOCK_SYMBOLS:
                    if symbol in positions:
                        continue
                    item = items.get(symbol)
                    if not item:
                        continue
                    short = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
                    if not short.get("buy_signal"):
                        continue
                    score = rank_score(symbol, current_time, item, bar_by_symbol_time)
                    candidates.append((score, symbol, item))
                for _, symbol, item in sorted(candidates, reverse=True)[:open_slots]:
                    execute_time = next_time(symbol, current_time)
                    if execute_time is not None:
                        pending_orders.append({"time": execute_time, "symbol": symbol, "type": "base", "item": item})

        equity = stock_equity(cash, positions, prices)
        position_value_now = sum(position_value(position, prices) for position in positions.values())
        high_watermark = max(high_watermark, equity)
        equity_curve.append(
            {
                "time": current_time.isoformat(),
                "date": current_time.date().isoformat(),
                "equityUsdt": equity,
                "cashUsdt": cash,
                "positionValueUsdt": position_value_now,
                "drawdownPct": (high_watermark - equity) / high_watermark * 100 if high_watermark > 0 else 0.0,
            }
        )
        if len(positions) > max_names["count"]:
            max_names = {"count": len(positions), "date": current_time.date().isoformat(), "symbols": sorted(positions)}

    summary = build_summary(initial_cash, equity_curve, trades)
    summary["maxStockNames"] = max_names
    summary["runnerNameLimit"] = MAX_RUNNER_NAMES
    return {
        "status": "completed",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "interval": "1d",
        "summary": summary,
        "equityCurve": equity_curve,
        "trades": trades,
    }


def build_summary(initial_cash: float, equity_curve: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    final_equity = clean_float(equity_curve[-1].get("equityUsdt")) if equity_curve else initial_cash
    returns = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        prev_equity = clean_float(previous.get("equityUsdt"))
        curr_equity = clean_float(current.get("equityUsdt"))
        if prev_equity > 0:
            returns.append(curr_equity / prev_equity - 1)
    max_drawdown = max((clean_float(row.get("drawdownPct")) for row in equity_curve), default=0.0)
    sharpe = 0.0
    if len(returns) > 1:
        stdev = statistics.stdev(returns)
        if stdev > 0:
            sharpe = statistics.fmean(returns) / stdev * math.sqrt(252)
    sells = [trade for trade in trades if trade.get("side") == "SELL"]
    wins = [trade for trade in sells if clean_float(trade.get("realizedPnlUsdt")) > 0]
    losses = [trade for trade in sells if clean_float(trade.get("realizedPnlUsdt")) < 0]
    gross_profit = sum(clean_float(trade.get("realizedPnlUsdt")) for trade in wins)
    gross_loss = abs(sum(clean_float(trade.get("realizedPnlUsdt")) for trade in losses))
    r_values = [clean_float(trade.get("realizedR")) for trade in sells if trade.get("realizedR") is not None]
    return {
        "initialCashUsdt": initial_cash,
        "finalEquityUsdt": final_equity,
        "totalReturnPct": (final_equity / initial_cash - 1) * 100 if initial_cash > 0 else 0.0,
        "annualReturnPct": ((final_equity / initial_cash) ** (252 / len(equity_curve)) - 1) * 100 if equity_curve and final_equity > 0 else 0.0,
        "maxDrawdownPct": max_drawdown,
        "sharpe": sharpe,
        "tradeCount": len(trades),
        "closedTradeCount": len(sells),
        "winRatePct": len(wins) / len(sells) * 100 if sells else None,
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else None,
        "averageR": statistics.fmean(r_values) if r_values else None,
    }


def curve_by_date(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output = {}
    for row in result.get("equityCurve") or []:
        date_value = str(row.get("date") or row.get("time") or "")[:10]
        if date_value:
            output[date_value] = row
    return output


def combine_results(
    *,
    initial_cash: float,
    etf_result: dict[str, Any],
    stock_result: dict[str, Any],
    start_date: dt.date,
    end_date: dt.date,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    etf_curve = curve_by_date(etf_result)
    stock_curve = curve_by_date(stock_result)
    dates = sorted(set(etf_curve) & set(stock_curve))
    combined_curve = []
    high_watermark = initial_cash
    returns = []
    previous_equity = None
    for date_text in dates:
        etf_row = etf_curve[date_text]
        stock_row = stock_curve[date_text]
        equity = clean_float(etf_row.get("equityUsdt")) + clean_float(stock_row.get("equityUsdt"))
        cash = clean_float(etf_row.get("cashUsdt")) + clean_float(stock_row.get("cashUsdt"))
        position_value_now = clean_float(etf_row.get("positionValueUsdt")) + clean_float(stock_row.get("positionValueUsdt"))
        high_watermark = max(high_watermark, equity)
        if previous_equity and previous_equity > 0:
            returns.append(equity / previous_equity - 1)
        previous_equity = equity
        combined_curve.append(
            {
                "time": f"{date_text}T00:00:00+00:00",
                "date": date_text,
                "equityUsdt": equity,
                "cashUsdt": cash,
                "positionValueUsdt": position_value_now,
                "drawdownPct": (high_watermark - equity) / high_watermark * 100 if high_watermark > 0 else 0.0,
            }
        )

    final_equity = clean_float(combined_curve[-1].get("equityUsdt")) if combined_curve else initial_cash
    max_drawdown = max((clean_float(row.get("drawdownPct")) for row in combined_curve), default=0.0)
    sharpe = 0.0
    if len(returns) > 1:
        stdev = statistics.stdev(returns)
        if stdev > 0:
            sharpe = statistics.fmean(returns) / stdev * math.sqrt(252)
    exposures = [
        clean_float(row.get("positionValueUsdt")) / clean_float(row.get("equityUsdt")) * 100
        for row in combined_curve
        if clean_float(row.get("equityUsdt")) > 0
    ]
    spy_entries = server.load_backtest_history_entries("SPY", "1d", start_date, end_date)
    spy_entries = [entry for entry in spy_entries if start_date <= server.backtest_entry_time(entry).date() <= end_date]
    benchmark_return = None
    if spy_entries:
        first = server.backtest_entry_bar(spy_entries[0]).close
        last = server.backtest_entry_bar(spy_entries[-1]).close
        benchmark_return = (last / first - 1) * 100 if first > 0 else None
    combined_summary = {
        "initialCashUsdt": initial_cash,
        "finalEquityUsdt": final_equity,
        "totalReturnPct": (final_equity / initial_cash - 1) * 100 if initial_cash > 0 else 0.0,
        "annualReturnPct": ((final_equity / initial_cash) ** (252 / len(combined_curve)) - 1) * 100 if combined_curve and final_equity > 0 else 0.0,
        "maxDrawdownPct": max_drawdown,
        "sharpe": sharpe,
        "benchmarkReturnPct": benchmark_return,
        "excessReturnPct": (final_equity / initial_cash - 1) * 100 - benchmark_return if benchmark_return is not None else None,
        "avgExposurePct": statistics.fmean(exposures) if exposures else None,
        "medianExposurePct": statistics.median(exposures) if exposures else None,
        "maxExposurePct": max(exposures) if exposures else None,
        "zeroExposurePct": (sum(1 for value in exposures if value < 0.01) / len(exposures) * 100) if exposures else None,
        "periods": len(combined_curve),
    }
    return combined_summary, combined_curve


def run_candidate(start_date: dt.date, end_date: dt.date, initial_cash: float, refresh_history: bool) -> dict[str, Any]:
    symbols = sorted(set(ETF_SYMBOLS + STOCK_SYMBOLS + ["SPY", "QQQ"]))
    cache_report = ensure_daily_history(symbols, start_date, end_date, refresh_history)
    base_config, _ = build_scenario("etf-stock-6040")
    server.MAX_BACKTEST_TRADES = 999999
    etf_result = server.run_strategy_backtest(
        config=build_etf_config(base_config),
        asset_pool=make_pool(ETF_SYMBOLS, "etf"),
        start_date=start_date,
        end_date=end_date,
        interval="1d",
        initial_cash=initial_cash * ETF_WEIGHT,
        requested_symbols=ETF_SYMBOLS,
    )
    stock_result = run_stock_bucket(
        config=build_stock_config(base_config),
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash * STOCK_WEIGHT,
    )
    combined, equity_curve = combine_results(
        initial_cash=initial_cash,
        etf_result=etf_result,
        stock_result=stock_result,
        start_date=start_date,
        end_date=end_date,
    )
    trades = []
    for trade in etf_result.get("trades") or []:
        if isinstance(trade, dict):
            copied = dict(trade)
            copied["bucket"] = "etf"
            trades.append(copied)
    for trade in stock_result.get("trades") or []:
        if isinstance(trade, dict):
            trades.append(dict(trade))
    trades.sort(key=lambda trade: str(trade.get("time") or trade.get("date") or ""))
    return {
        "ok": etf_result.get("status") == "completed" and stock_result.get("status") == "completed",
        "scenario": "candidate-ranked6040-strict-add-runner4",
        "rules": {
            "etf": {
                "weightPct": 60,
                "symbols": ETF_SYMBOLS,
                "interval": "1d",
                "maxHoldingDays": "disabled",
                "singleSymbolCapPctOfTotal": 30,
            },
            "stock": {
                "weightPct": 40,
                "symbols": STOCK_SYMBOLS,
                "basePctOfTotal": BASE_TOTAL_PCT,
                "add1PctOfTotal": ADD1_TOTAL_PCT,
                "add2PctOfTotal": ADD2_TOTAL_PCT,
                "singleSymbolCapPctOfTotal": MAX_SINGLE_TOTAL_PCT,
                "maxSimultaneousNames": MAX_STOCK_NAMES,
                "ranking": "relative SPY strength + 20/63d momentum + dollar volume + drawdown quality",
                "strictAdd": "above SMA20, relative strength new/high improving, improving positive 20d momentum, no resistance/sell signal",
                "runnerLimit": MAX_RUNNER_NAMES,
                "runnerTargetSellPct": 15,
                "normalTargetSellPct": 30,
                "normalMaxHoldingDays": NORMAL_MAX_HOLD_DAYS,
                "strongMaxHoldingDays": RUNNER_MAX_HOLD_DAYS,
            },
        },
        "historyCache": {
            "cached": sum(1 for row in cache_report if row["status"] == "cached"),
            "fetched": sum(1 for row in cache_report if row["status"] == "fetched"),
            "symbols": symbols,
        },
        "combined": combined,
        "summary": combined,
        "equityCurve": equity_curve,
        "trades": trades,
        "etfBucket": summarize_result(etf_result),
        "stockBucket": {
            "status": stock_result.get("status"),
            "summary": stock_result.get("summary"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run current candidate ETF/stock backtest and generate report.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2020-12-31")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument("--report-output", default=str(ROOT / "reports" / "backtest_analysis.html"))
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start[:10])
    end_date = dt.date.fromisoformat(args.end[:10])
    payload = run_candidate(start_date, end_date, args.initial_cash, args.refresh_history)
    saved_path = save_run_summary(payload)
    payload["savedSummaryPath"] = str(saved_path)
    saved_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(saved_path, args.initial_cash, Path(args.report_output))
    print(json.dumps({"ok": payload["ok"], "savedSummaryPath": str(saved_path), "combined": payload["combined"]}, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
