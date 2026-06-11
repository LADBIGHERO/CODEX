"""Standalone ETF + stock strategy backtest and report generator.

This script is intentionally separate from the dashboard runtime. It reads or
refreshes cached OHLCV data, runs the candidate v2.1 strategy with explicit
position/risk rules, and writes complete trades, fills, equity curve, charts,
summary tables, and a standalone HTML report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tools.backtest_lab import (  # noqa: E402
    ETF_SYMBOLS,
    SECTOR_MAP,
    STOCK_SYMBOLS,
    ensure_daily_history,
    history_path,
    read_cached_bars,
    save_run_summary,
)


SLIPPAGE_PCT = 0.001
FEE_PCT = 0.0002
ETF_SLEEVE_LIMIT = 0.60
ETF_CORE_LIMIT = 0.45
ETF_TACTICAL_LIMIT = 0.15
STOCK_SLEEVE_NORMAL = 0.40
STOCK_SLEEVE_CAUTION = 0.25
STOCK_SLEEVE_DEFENSIVE = 0.10
TOTAL_POSITION_LIMIT = 1.00
SINGLE_ETF_LIMIT = 0.30
SINGLE_STOCK_LIMIT = 0.15
SECTOR_LIMIT = 0.20
THEME_LIMIT = 0.25
QQQ_TOP10_STOCK_LIMIT = 0.20
QQQ_TECH_OVERLAP_LIMIT = 0.50
BASE_STOCK_PCT = 0.06
ADD1_STOCK_PCT = 0.04
ADD2_STOCK_PCT = 0.05
MIN_BASE_PCT = 0.03
MIN_ADD_PCT = 0.02
MAX_STOCK_NAMES = 6
MAX_RUNNER_NAMES = 4
NORMAL_OPEN_RISK_LIMIT = 0.08
CAUTION_OPEN_RISK_LIMIT = 0.04
DEFENSIVE_OPEN_RISK_LIMIT = 0.02
NORMAL_INITIAL_RISK_LIMIT = 0.008
NORMAL_POSITION_RISK_LIMIT = 0.012
MAX_STOCK_STOP_DISTANCE_PCT = 0.08
CAUTION_INITIAL_RISK_LIMIT = 0.004
CAUTION_POSITION_RISK_LIMIT = 0.006


def pct(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return value * 100


def clean_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def nearest_next_date(dates: list[dt.date], index: int) -> dt.date | None:
    return dates[index + 1] if index + 1 < len(dates) else None


def percentile_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average").fillna(0.0)


def holding_bucket(days: int | float | None) -> str:
    value = clean_float(days, -1)
    if value <= 2:
        return "1-2d"
    if value <= 5:
        return "3-5d"
    if value <= 10:
        return "6-10d"
    if value <= 15:
        return "11-15d"
    return "15d+"


def r_bucket(value: float | None) -> str:
    number = clean_float(value, math.nan)
    if not math.isfinite(number):
        return "N/A"
    if number <= -1:
        return "<= -1R"
    if number <= 0:
        return "-1R to 0"
    if number <= 1:
        return "0 to 1R"
    if number <= 2:
        return "1R to 2R"
    if number <= 3:
        return "2R to 3R"
    return "> 3R"


@dataclass
class Fill:
    fill_id: int
    position_id: str
    date: str
    symbol: str
    action: str
    price: float
    shares: float
    position_pct_change: float
    cash_change: float
    reason: str
    market_regime: str


@dataclass
class Position:
    position_id: str
    symbol: str
    sleeve: str
    shares: float
    avg_entry_price: float
    base_entry_price: float
    opened_date: dt.date
    signal_date: dt.date
    sector: str = "unknown"
    theme: str = "unknown"
    entry_type: str = "unknown"
    initial_stop: float = 0.0
    effective_stop: float = 0.0
    trailing_stop: float = 0.0
    base_r: float = 0.0
    base_position_value: float = 0.0
    tp1_done: bool = False
    tp2_done: bool = False
    is_runner: bool = False
    add_count: int = 0
    last_add_price: float = 0.0
    out_of_rank_weeks: int = 0
    peak_price: float = 0.0
    is_chase_trade: bool = False
    entry_signal_close: float = 0.0
    entry_signal_high: float = 0.0
    entry_atr20: float = 0.0
    realized_pnl: float = 0.0
    realized_value: float = 0.0
    realized_shares: float = 0.0
    fills: list[Fill] = field(default_factory=list)

    def market_value(self, price: float) -> float:
        return self.shares * price

    def open_risk_pct(self, equity: float, price: float) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        risk_per_share = max(price - self.effective_stop, 0.0)
        return self.shares * risk_per_share / equity


@dataclass
class PendingOrder:
    execute_date: dt.date
    signal_date: dt.date
    symbol: str
    action: str
    sleeve: str
    reason: str
    target_pct: float = 0.0
    sell_fraction: float = 1.0
    add_level: int = 0
    stop_price: float | None = None


class StrategyBacktester:
    def __init__(
        self,
        *,
        start_date: dt.date,
        end_date: dt.date,
        initial_capital: float,
        output_dir: Path,
        refresh_history: bool,
        stock_sleeve_normal_pct: float = STOCK_SLEEVE_NORMAL,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.output_dir = output_dir
        self.refresh_history = refresh_history
        self.stock_sleeve_normal_pct = stock_sleeve_normal_pct
        self.symbols = sorted(set(ETF_SYMBOLS + STOCK_SYMBOLS + ["SPY", "QQQ"]))
        self.data: dict[str, pd.DataFrame] = {}
        self.dates: list[dt.date] = []
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.pending_orders: list[PendingOrder] = []
        self.fills: list[Fill] = []
        self.trade_rows: list[dict[str, Any]] = []
        self.equity_rows: list[dict[str, Any]] = []
        self.quality_warnings: list[str] = []
        self.position_counter = 0
        self.fill_counter = 0
        self.high_watermark = initial_capital
        self.qqq_top10_unavailable = True
        self.earnings_unreliable = True
        self.survivorship_bias_risk = True

    def prepare_data(self) -> None:
        cache_report = ensure_daily_history(self.symbols, self.start_date, self.end_date, self.refresh_history)
        fetched = [row["symbol"] for row in cache_report if row.get("status") == "fetched"]
        if fetched:
            self.quality_warnings.append(f"History refreshed for {len(fetched)} symbols: {', '.join(fetched[:12])}")

        frames: dict[str, pd.DataFrame] = {}
        warmup_start = self.start_date - dt.timedelta(days=460)
        for symbol in self.symbols:
            bars = read_cached_bars(history_path(symbol, "1d"))
            rows = [
                {
                    "date": bar.date,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
                for bar in bars
                if warmup_start <= bar.date <= self.end_date
            ]
            if not rows:
                self.quality_warnings.append(f"No OHLCV data for {symbol}")
                continue
            frame = pd.DataFrame(rows).sort_values("date").set_index("date")
            frames[symbol] = self.add_indicators(symbol, frame)

        if "SPY" not in frames or "QQQ" not in frames:
            raise RuntimeError("SPY and QQQ history are required for market regime and relative strength.")

        spy = frames["SPY"]["close"]
        for symbol, frame in list(frames.items()):
            aligned = frame.join(spy.rename("spy_close"), how="left")
            aligned["rs_ratio"] = aligned["close"] / aligned["spy_close"]
            aligned["rs20"] = aligned["rs_ratio"] / aligned["rs_ratio"].shift(20) - 1
            aligned["rs63"] = aligned["rs_ratio"] / aligned["rs_ratio"].shift(63) - 1
            aligned["rs20_5d_ago"] = aligned["rs20"].shift(5)
            aligned["rs63_q95_63"] = aligned["rs63"].rolling(63, min_periods=20).quantile(0.95)
            frames[symbol] = aligned

        self.data = frames
        date_sets = [set(frame.loc[self.start_date : self.end_date].index) for frame in frames.values()]
        all_dates = sorted(set.union(*date_sets)) if date_sets else []
        self.dates = [value for value in all_dates if self.start_date <= value <= self.end_date]
        if not self.dates:
            raise RuntimeError("No usable trading dates in requested range.")

    @staticmethod
    def add_indicators(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["sma20"] = out["close"].rolling(20, min_periods=10).mean()
        out["sma50"] = out["close"].rolling(50, min_periods=20).mean()
        out["sma200"] = out["close"].rolling(200, min_periods=100).mean()
        out["sma20_5d_ago"] = out["sma20"].shift(5)
        high_low = out["high"] - out["low"]
        high_close = (out["high"] - out["close"].shift(1)).abs()
        low_close = (out["low"] - out["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        out["atr20"] = tr.rolling(20, min_periods=10).mean()
        out["mom20"] = out["close"] / out["close"].shift(20) - 1
        out["mom63"] = out["close"] / out["close"].shift(63) - 1
        out["mom126"] = out["close"] / out["close"].shift(126) - 1
        out["mom20_5d_ago"] = out["mom20"].shift(5)
        out["high63"] = out["close"].rolling(63, min_periods=20).max()
        out["low10"] = out["low"].rolling(10, min_periods=5).min()
        out["low5"] = out["low"].rolling(5, min_periods=3).min()
        out["adv20"] = (out["close"] * out["volume"]).rolling(20, min_periods=10).mean()
        out["trend_score"] = 0.6 * out["mom63"] + 0.4 * out["mom126"]
        return out

    def row(self, symbol: str, date_value: dt.date) -> pd.Series | None:
        frame = self.data.get(symbol)
        if frame is None or date_value not in frame.index:
            return None
        row = frame.loc[date_value]
        return row if isinstance(row, pd.Series) else row.iloc[-1]

    def close_price(self, symbol: str, date_value: dt.date) -> float:
        row = self.row(symbol, date_value)
        return clean_float(row.get("close")) if row is not None else 0.0

    def open_price(self, symbol: str, date_value: dt.date) -> float:
        row = self.row(symbol, date_value)
        return clean_float(row.get("open")) if row is not None else 0.0

    def current_equity(self, date_value: dt.date) -> float:
        value = self.cash
        for position in self.positions.values():
            price = self.close_price(position.symbol, date_value)
            if price <= 0:
                price = position.avg_entry_price
            value += position.market_value(price)
        return value

    def sleeve_pct(self, date_value: dt.date, sleeve_prefix: str) -> float:
        equity = self.current_equity(date_value)
        if equity <= 0:
            return 0.0
        total = 0.0
        for position in self.positions.values():
            if position.sleeve.startswith(sleeve_prefix):
                total += position.market_value(self.close_price(position.symbol, date_value))
        return total / equity

    def symbol_pct(self, date_value: dt.date, symbol: str) -> float:
        equity = self.current_equity(date_value)
        if equity <= 0:
            return 0.0
        total = sum(
            position.market_value(self.close_price(position.symbol, date_value))
            for position in self.positions.values()
            if position.symbol == symbol
        )
        return total / equity

    def stock_open_risk_pct(self, date_value: dt.date) -> float:
        equity = self.current_equity(date_value)
        return sum(
            position.open_risk_pct(equity, self.close_price(position.symbol, date_value))
            for position in self.positions.values()
            if position.sleeve == "stock"
        )

    def market_regime(self, date_value: dt.date) -> str:
        spy = self.row("SPY", date_value)
        qqq = self.row("QQQ", date_value)
        if spy is None or qqq is None:
            return "defensive"
        spy_ok = clean_float(spy.get("close")) > clean_float(spy.get("sma200"))
        qqq_ok = clean_float(qqq.get("close")) > clean_float(qqq.get("sma200"))
        if spy_ok and qqq_ok:
            return "normal"
        if spy_ok or qqq_ok:
            return "caution"
        return "defensive"

    def regime_rules(self, regime: str) -> dict[str, float]:
        if regime == "normal":
            return {
                "new_mult": 1.0,
                "add1_mult": 1.0,
                "add2_mult": 1.0,
                "stock_limit": self.stock_sleeve_normal_pct,
                "open_risk_limit": NORMAL_OPEN_RISK_LIMIT,
                "initial_risk_limit": NORMAL_INITIAL_RISK_LIMIT,
                "position_risk_limit": NORMAL_POSITION_RISK_LIMIT,
            }
        if regime == "caution":
            return {
                "new_mult": 0.5,
                "add1_mult": 0.5,
                "add2_mult": 0.0,
                "stock_limit": STOCK_SLEEVE_CAUTION,
                "open_risk_limit": CAUTION_OPEN_RISK_LIMIT,
                "initial_risk_limit": CAUTION_INITIAL_RISK_LIMIT,
                "position_risk_limit": CAUTION_POSITION_RISK_LIMIT,
            }
        return {
            "new_mult": 0.0,
            "add1_mult": 0.0,
            "add2_mult": 0.0,
            "stock_limit": STOCK_SLEEVE_DEFENSIVE,
            "open_risk_limit": DEFENSIVE_OPEN_RISK_LIMIT,
            "initial_risk_limit": 0.0,
            "position_risk_limit": 0.0,
        }

    def run(self) -> dict[str, Any]:
        self.prepare_data()
        for index, date_value in enumerate(self.dates):
            regime = self.market_regime(date_value)
            self.execute_pending_orders(date_value, regime)
            self.execute_intraday_stops(date_value, regime)
            self.update_runner_trails(date_value)
            next_date = nearest_next_date(self.dates, index)
            if next_date is not None:
                self.schedule_close_signals(date_value, next_date, regime)
            self.record_equity(date_value, regime)

        if self.positions:
            final_date = self.dates[-1]
            regime = self.market_regime(final_date)
            for position_id in list(self.positions):
                self.close_position(
                    position_id=position_id,
                    date_value=final_date,
                    price=self.close_price(self.positions[position_id].symbol, final_date) * (1 - SLIPPAGE_PCT) * (1 - FEE_PCT),
                    reason="end_of_backtest",
                    market_regime=regime,
                    sell_fraction=1.0,
                )
            self.record_equity(final_date, regime)

        return self.build_payload()

    def execute_pending_orders(self, date_value: dt.date, regime: str) -> None:
        due = [order for order in self.pending_orders if order.execute_date == date_value]
        self.pending_orders = [order for order in self.pending_orders if order.execute_date != date_value]
        priority = {"sell": 0, "reduce": 1, "buy": 2, "add": 3}
        for order in sorted(due, key=lambda item: priority.get(item.action, 9)):
            raw_open = self.open_price(order.symbol, date_value)
            if raw_open <= 0:
                self.quality_warnings.append(f"Missing next_open for {order.symbol} on {date_value}; skipped {order.action}")
                continue
            if order.action in {"sell", "reduce"}:
                position_id = self.find_position_id(order.symbol, order.sleeve)
                if position_id is None:
                    continue
                position = self.positions[position_id]
                price = raw_open * (1 - SLIPPAGE_PCT) * (1 - FEE_PCT)
                reason = self.pending_exit_reason(position, raw_open, order.reason)
                self.close_position(
                    position_id=position_id,
                    date_value=date_value,
                    price=price,
                    reason=reason,
                    market_regime=regime,
                    sell_fraction=order.sell_fraction,
                    exit_signal_date=order.signal_date,
                )
            elif order.action == "buy":
                self.open_position(order, date_value, raw_open, regime)
            elif order.action == "add":
                self.add_to_position(order, date_value, raw_open, regime)

    def execute_intraday_stops(self, date_value: dt.date, regime: str) -> None:
        for position_id, position in list(self.positions.items()):
            if position.sleeve not in {"stock", "etf_tactical"}:
                continue
            row = self.row(position.symbol, date_value)
            if row is None:
                continue
            low = clean_float(row.get("low"))
            raw_open = clean_float(row.get("open"))
            stop = position.trailing_stop if position.is_runner else position.effective_stop
            if stop <= 0 or low > stop:
                continue
            raw_exit = raw_open if raw_open <= stop else stop
            price = raw_exit * (1 - SLIPPAGE_PCT) * (1 - FEE_PCT)
            self.close_position(
                position_id=position_id,
                date_value=date_value,
                price=price,
                reason=self.stop_reason(position, raw_open),
                market_regime=regime,
                sell_fraction=1.0,
                exit_signal_date=date_value,
            )

    def open_position(self, order: PendingOrder, date_value: dt.date, raw_open: float, regime: str) -> None:
        if order.sleeve == "stock" and len([p for p in self.positions.values() if p.sleeve == "stock"]) >= MAX_STOCK_NAMES:
            return
        if self.find_position_id(order.symbol, order.sleeve) is not None:
            return
        price = raw_open * (1 + SLIPPAGE_PCT) * (1 + FEE_PCT)
        if price <= 0:
            return
        target_pct = self.execution_capped_target_pct(order, date_value, price, regime)
        if order.sleeve == "stock" and target_pct < MIN_BASE_PCT:
            return
        if order.sleeve != "stock" and target_pct < 0.005:
            return
        equity = self.current_equity(date_value)
        value = min(equity * target_pct, self.cash)
        if value <= 0:
            return
        shares = value / price
        self.cash -= value
        self.position_counter += 1
        position_id = f"P{self.position_counter:06d}"
        sector = SECTOR_MAP.get(order.symbol, "unknown")
        stop_price = clean_float(order.stop_price)
        is_chase_trade = False
        entry_signal_close = 0.0
        entry_signal_high = 0.0
        entry_atr20 = 0.0
        if order.sleeve == "etf_tactical":
            signal_row = self.row(order.symbol, order.signal_date)
            if signal_row is not None:
                is_chase_trade = self.is_tactical_chase(signal_row)
                entry_signal_close = clean_float(signal_row.get("close"))
                entry_signal_high = clean_float(signal_row.get("high"))
                entry_atr20 = clean_float(signal_row.get("atr20"))
                stop_price = self.tactical_initial_stop(signal_row, price, is_chase_trade)
        position = Position(
            position_id=position_id,
            symbol=order.symbol,
            sleeve=order.sleeve,
            shares=shares,
            avg_entry_price=price,
            base_entry_price=price,
            opened_date=date_value,
            signal_date=order.signal_date,
            sector=sector,
            theme=sector,
            entry_type="pullback" if order.sleeve == "stock" else order.sleeve,
            initial_stop=stop_price,
            effective_stop=stop_price,
            trailing_stop=stop_price,
            base_r=max(price - stop_price, 0.0),
            base_position_value=value,
            last_add_price=price,
            peak_price=price,
            is_chase_trade=is_chase_trade,
            entry_signal_close=entry_signal_close,
            entry_signal_high=entry_signal_high,
            entry_atr20=entry_atr20,
        )
        fill = self.make_fill(position, date_value, "BUY", price, shares, value / equity if equity > 0 else 0.0, -value, order.reason, regime)
        position.fills.append(fill)
        self.fills.append(fill)
        self.positions[position_id] = position

    @staticmethod
    def is_tactical_chase(row: pd.Series) -> bool:
        close = clean_float(row.get("close"))
        high63 = clean_float(row.get("high63"))
        sma20 = clean_float(row.get("sma20"))
        atr20 = clean_float(row.get("atr20"))
        if close <= 0:
            return False
        return bool(
            (high63 > 0 and close >= high63 * 0.98)
            or (sma20 > 0 and atr20 > 0 and close > sma20 + 3.0 * atr20)
            or (sma20 > 0 and close / sma20 - 1 > 0.08)
        )

    @staticmethod
    def tactical_initial_stop(row: pd.Series, entry_price: float, is_chase_trade: bool) -> float:
        atr20 = clean_float(row.get("atr20"))
        if entry_price <= 0 or atr20 <= 0:
            return 0.0
        if is_chase_trade:
            return max(
                entry_price - 1.2 * atr20,
                clean_float(row.get("low")) - 0.2 * atr20,
                entry_price * 0.97,
            )
        return max(
            entry_price - 2.0 * atr20,
            clean_float(row.get("low5")) - 0.5 * atr20,
            entry_price * 0.96,
        )

    @staticmethod
    def stop_reason(position: Position, raw_open: float | None = None) -> str:
        stop = position.trailing_stop if position.is_runner else position.effective_stop
        is_gap = raw_open is not None and stop > 0 and raw_open <= stop
        if position.is_runner:
            return "runner_gap_stop" if is_gap else "runner_trailing_stop"
        if position.sleeve == "etf_tactical":
            return "etf_tactical_gap_stop" if is_gap else "etf_tactical_stop"
        return "gap_stop_loss" if is_gap else "stop_loss"

    def pending_exit_reason(self, position: Position, raw_open: float, fallback: str) -> str:
        if position.sleeve not in {"stock", "etf_tactical"}:
            return fallback
        stop = position.trailing_stop if position.is_runner else position.effective_stop
        if stop > 0 and raw_open <= stop:
            return self.stop_reason(position, raw_open)
        return fallback

    def add_to_position(self, order: PendingOrder, date_value: dt.date, raw_open: float, regime: str) -> None:
        position_id = self.find_position_id(order.symbol, "stock")
        if position_id is None:
            return
        position = self.positions[position_id]
        price = raw_open * (1 + SLIPPAGE_PCT) * (1 + FEE_PCT)
        if price <= 0:
            return
        equity = self.current_equity(date_value)
        target_pct = self.allowed_stock_add_pct(position, date_value, price, order.add_level, regime)
        if target_pct < MIN_ADD_PCT:
            return
        value = min(equity * target_pct, self.cash)
        if value <= 0:
            return
        new_shares = value / price
        old_value = position.shares * position.avg_entry_price
        position.shares += new_shares
        position.avg_entry_price = (old_value + value) / position.shares
        position.add_count = max(position.add_count, order.add_level)
        position.last_add_price = price
        if order.add_level == 1:
            position.effective_stop = max(position.initial_stop, position.base_entry_price)
        else:
            row = self.row(position.symbol, date_value)
            position.effective_stop = max(position.initial_stop, position.base_entry_price, clean_float(row.get("sma20")) if row is not None else 0.0)
        self.cash -= value
        fill = self.make_fill(position, date_value, f"ADD{order.add_level}", price, new_shares, value / equity if equity > 0 else 0.0, -value, order.reason, regime)
        position.fills.append(fill)
        self.fills.append(fill)

    def execution_capped_target_pct(self, order: PendingOrder, date_value: dt.date, price: float, regime: str) -> float:
        equity = self.current_equity(date_value)
        if equity <= 0:
            return 0.0
        positions_value_pct = max(0.0, 1.0 - self.cash / equity)
        total_remaining = max(0.0, TOTAL_POSITION_LIMIT - positions_value_pct)
        if order.sleeve.startswith("etf"):
            etf_remaining = max(0.0, ETF_SLEEVE_LIMIT - self.sleeve_pct(date_value, "etf"))
            single_remaining = max(0.0, SINGLE_ETF_LIMIT - self.symbol_pct(date_value, order.symbol))
            if order.sleeve == "etf_core":
                sleeve_remaining = max(0.0, ETF_CORE_LIMIT - self.sleeve_pct(date_value, "etf_core"))
            else:
                sleeve_remaining = max(0.0, ETF_TACTICAL_LIMIT - self.sleeve_pct(date_value, "etf_tactical"))
            return min(order.target_pct, total_remaining, etf_remaining, single_remaining, sleeve_remaining)
        if order.sleeve == "stock":
            stop = clean_float(order.stop_price)
            allowed = self.allowed_stock_base_pct(order.symbol, date_value, price, stop, regime)
            return min(order.target_pct, allowed, total_remaining)
        return min(order.target_pct, total_remaining)

    def close_position(
        self,
        *,
        position_id: str,
        date_value: dt.date,
        price: float,
        reason: str,
        market_regime: str,
        sell_fraction: float,
        exit_signal_date: dt.date | None = None,
    ) -> None:
        position = self.positions.get(position_id)
        if not position or price <= 0:
            return
        shares = position.shares * min(max(sell_fraction, 0.0), 1.0)
        if shares <= 0:
            return
        gross = shares * price
        cost_basis = shares * position.avg_entry_price
        pnl_amount = gross - cost_basis
        equity = self.current_equity(date_value)
        position.shares -= shares
        position.realized_pnl += pnl_amount
        position.realized_value += gross
        position.realized_shares += shares
        self.cash += gross
        pct_change = gross / equity if equity > 0 else 0.0
        fill = self.make_fill(position, date_value, "SELL", price, shares, -pct_change, gross, reason, market_regime)
        position.fills.append(fill)
        self.fills.append(fill)

        if position.shares <= 1e-9:
            self.trade_rows.append(self.position_to_trade(position, date_value, price, reason, market_regime, exit_signal_date))
            self.positions.pop(position_id, None)

    def make_fill(
        self,
        position: Position,
        date_value: dt.date,
        action: str,
        price: float,
        shares: float,
        position_pct_change: float,
        cash_change: float,
        reason: str,
        market_regime: str,
    ) -> Fill:
        self.fill_counter += 1
        return Fill(
            fill_id=self.fill_counter,
            position_id=position.position_id,
            date=date_value.isoformat(),
            symbol=position.symbol,
            action=action,
            price=price,
            shares=shares,
            position_pct_change=position_pct_change,
            cash_change=cash_change,
            reason=reason,
            market_regime=market_regime,
        )

    def position_to_trade(
        self,
        position: Position,
        exit_date: dt.date,
        exit_price: float,
        reason: str,
        market_regime: str,
        exit_signal_date: dt.date | None,
    ) -> dict[str, Any]:
        pnl_amount = position.realized_pnl
        if position.realized_value == 0:
            pnl_amount = position.shares * (exit_price - position.avg_entry_price)
        initial_dollar_risk = position.base_position_value * position.base_r / position.base_entry_price if position.base_entry_price > 0 else 0.0
        realized_r = pnl_amount / initial_dollar_risk if initial_dollar_risk > 0 else None
        holding_days = (exit_date - position.opened_date).days
        entry_value = sum(-fill.cash_change for fill in position.fills if fill.cash_change < 0)
        pnl_pct = pnl_amount / entry_value * 100 if entry_value > 0 else 0.0
        return {
            "trade_id": f"T{len(self.trade_rows) + 1:06d}",
            "position_id": position.position_id,
            "signal_date": position.signal_date.isoformat(),
            "execution_date": position.opened_date.isoformat(),
            "exit_signal_date": (exit_signal_date or exit_date).isoformat(),
            "exit_execution_date": exit_date.isoformat(),
            "symbol": position.symbol,
            "side": "LONG",
            "sleeve": position.sleeve,
            "entry_type": position.entry_type,
            "exit_reason": reason,
            "base_entry_price": position.base_entry_price,
            "avg_entry_price": position.avg_entry_price,
            "exit_price": exit_price,
            "initial_stop": position.initial_stop,
            "effective_stop": position.effective_stop,
            "trailing_stop": position.trailing_stop,
            "base_R": position.base_r,
            "realized_R": realized_r,
            "position_pct": None,
            "risk_pct": None,
            "pnl_amount": pnl_amount,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
            "market_regime": market_regime,
            "sector": position.sector,
            "theme": position.theme,
            "is_qqq_top10": "unknown",
            "tp1_done": position.tp1_done,
            "tp2_done": position.tp2_done,
            "is_runner": position.is_runner,
            "is_chase_trade": position.is_chase_trade,
            "add_count": position.add_count,
            "add_level": position.add_count,
            "slippage_pct": SLIPPAGE_PCT * 100,
            "fee_pct": FEE_PCT * 100,
        }

    def schedule_close_signals(self, date_value: dt.date, next_date: dt.date, regime: str) -> None:
        self.schedule_etf_signals(date_value, next_date)
        self.schedule_stock_signals(date_value, next_date, regime)
        self.schedule_etf_cap_reduction(date_value, next_date)

    def schedule_etf_signals(self, date_value: dt.date, next_date: dt.date) -> None:
        is_week_check = self.is_first_trading_day_of_week(date_value)
        if is_week_check:
            targets = self.etf_core_targets(date_value)
            for position in list(self.positions.values()):
                if position.sleeve != "etf_core":
                    continue
                current_pct = self.symbol_sleeve_pct(date_value, position.symbol, "etf_core")
                target = targets.get(position.symbol, 0.0)
                row = self.row(position.symbol, date_value)
                if row is None:
                    continue
                if clean_float(row.get("close")) < clean_float(row.get("sma200")):
                    self.queue_unique(next_date, date_value, position.symbol, "sell", "etf_core", "etf_sma200_exit")
                    continue
                if clean_float(row.get("close")) < clean_float(row.get("sma50")) and clean_float(row.get("mom63")) < 0:
                    self.queue_unique(next_date, date_value, position.symbol, "reduce", "etf_core", "etf_sma50_mom_reduce", sell_fraction=0.5)
                    continue
                if target <= 0:
                    self.queue_unique(next_date, date_value, position.symbol, "sell", "etf_core", "etf_rank_exit")
                elif current_pct > target * 1.05:
                    sell_fraction = max(0.0, min(1.0, (current_pct - target) / current_pct))
                    self.queue_unique(next_date, date_value, position.symbol, "reduce", "etf_core", "etf_core_rebalance_reduce", sell_fraction=sell_fraction)
            for symbol, target in targets.items():
                current_pct = self.symbol_sleeve_pct(date_value, symbol, "etf_core")
                if target > current_pct + 0.005 and self.find_position_id(symbol, "etf_core") is None:
                    self.pending_orders.append(PendingOrder(next_date, date_value, symbol, "buy", "etf_core", "etf_core_rank_buy", target_pct=target))

        tactical_target = self.etf_tactical_target(date_value)
        for position in list(self.positions.values()):
            if position.sleeve != "etf_tactical":
                continue
            row = self.row(position.symbol, date_value)
            if row is None:
                continue
            quick_failure = self.tactical_chase_failure(position, row, date_value)
            should_exit = (
                clean_float(row.get("close")) < clean_float(row.get("sma20"))
                or clean_float(row.get("mom20")) < 0
                or quick_failure
            )
            if should_exit or position.symbol != tactical_target:
                reason = "etf_tactical_chase_failure" if quick_failure else "etf_tactical_exit"
                self.queue_unique(next_date, date_value, position.symbol, "sell", "etf_tactical", reason)
        if tactical_target and self.find_position_id(tactical_target, "etf_tactical") is None:
            current_symbol_pct = self.symbol_pct(date_value, tactical_target)
            target = min(ETF_TACTICAL_LIMIT, max(0.0, SINGLE_ETF_LIMIT - current_symbol_pct))
            if target >= 0.01:
                self.pending_orders.append(PendingOrder(next_date, date_value, tactical_target, "buy", "etf_tactical", "etf_tactical_buy", target_pct=target))

    def schedule_etf_cap_reduction(self, date_value: dt.date, next_date: dt.date) -> None:
        etf_pct = self.sleeve_pct(date_value, "etf")
        if etf_pct > ETF_SLEEVE_LIMIT + 0.005:
            excess = etf_pct - ETF_SLEEVE_LIMIT
            for position in sorted([item for item in self.positions.values() if item.sleeve.startswith("etf")], key=lambda item: item.sleeve != "etf_tactical"):
                current_pct = self.symbol_sleeve_pct(date_value, position.symbol, position.sleeve)
                if current_pct <= 0 or excess <= 0:
                    continue
                sell_fraction = min(1.0, excess / current_pct)
                self.queue_unique(next_date, date_value, position.symbol, "reduce", position.sleeve, "etf_sleeve_cap_reduce", sell_fraction=sell_fraction)
                excess -= current_pct * sell_fraction
        for symbol in ETF_SYMBOLS:
            symbol_total = self.symbol_pct(date_value, symbol)
            if symbol_total <= SINGLE_ETF_LIMIT + 0.005:
                continue
            excess = symbol_total - SINGLE_ETF_LIMIT
            for position in sorted([item for item in self.positions.values() if item.symbol == symbol and item.sleeve.startswith("etf")], key=lambda item: item.sleeve != "etf_tactical"):
                current_pct = self.symbol_sleeve_pct(date_value, position.symbol, position.sleeve)
                if current_pct <= 0 or excess <= 0:
                    continue
                sell_fraction = min(1.0, excess / current_pct)
                self.queue_unique(next_date, date_value, position.symbol, "reduce", position.sleeve, "single_etf_cap_reduce", sell_fraction=sell_fraction)
                excess -= current_pct * sell_fraction

    def etf_core_targets(self, date_value: dt.date) -> dict[str, float]:
        rows = []
        for symbol in ETF_SYMBOLS:
            row = self.row(symbol, date_value)
            if row is None:
                continue
            eligible = (
                clean_float(row.get("close")) > clean_float(row.get("sma200"))
                and clean_float(row.get("mom63")) > 0
                and clean_float(row.get("mom126")) > -0.05
            )
            rows.append((symbol, clean_float(row.get("trend_score")), eligible))
        ranked = sorted([item for item in rows if item[2]], key=lambda item: item[1], reverse=True)
        targets: dict[str, float] = {}
        sleeve_left = ETF_CORE_LIMIT
        for idx, (symbol, _, _) in enumerate(ranked[:2]):
            desired = 0.30 if idx == 0 else 0.15
            tactical_pct = self.symbol_sleeve_pct(date_value, symbol, "etf_tactical")
            target = min(desired, sleeve_left, max(0.0, SINGLE_ETF_LIMIT - tactical_pct))
            if target > 0.0:
                targets[symbol] = target
                sleeve_left -= target
        return targets

    def etf_tactical_target(self, date_value: dt.date) -> str | None:
        candidates = []
        for symbol in ETF_SYMBOLS:
            row = self.row(symbol, date_value)
            if row is None:
                continue
            if (
                clean_float(row.get("close")) > clean_float(row.get("sma20"))
                and clean_float(row.get("sma20")) >= clean_float(row.get("sma20_5d_ago"))
                and clean_float(row.get("mom20")) > 0
                and clean_float(row.get("mom20")) > clean_float(row.get("mom20_5d_ago"))
            ):
                current_symbol_pct = self.symbol_pct(date_value, symbol)
                if current_symbol_pct < SINGLE_ETF_LIMIT - 0.005:
                    candidates.append((clean_float(row.get("mom20")), symbol))
        return sorted(candidates, reverse=True)[0][1] if candidates else None

    def schedule_stock_signals(self, date_value: dt.date, next_date: dt.date, regime: str) -> None:
        rules = self.regime_rules(regime)
        for position in list(self.positions.values()):
            if position.sleeve != "stock":
                continue
            row = self.row(position.symbol, date_value)
            if row is None:
                continue
            if self.stock_sell_reason(position, row, date_value, regime):
                self.queue_unique(next_date, date_value, position.symbol, "sell", "stock", self.stock_sell_reason(position, row, date_value, regime) or "stock_exit")
                continue
            self.schedule_stock_tp_and_add(position, row, date_value, next_date, regime)

        self.schedule_market_regime_reduction(date_value, next_date, regime)

        if self.is_first_trading_day_of_week(date_value) and rules["new_mult"] > 0:
            candidates = self.stock_candidates(date_value)
            open_stock_count = len([p for p in self.positions.values() if p.sleeve == "stock"])
            queued_buys = sum(1 for order in self.pending_orders if order.action == "buy" and order.sleeve == "stock")
            slots = max(0, MAX_STOCK_NAMES - open_stock_count - queued_buys)
            for candidate in candidates[:slots]:
                symbol = str(candidate["symbol"])
                if self.find_position_id(symbol, "stock") is not None:
                    continue
                signal_row = self.row(symbol, date_value)
                next_open = self.open_price(symbol, next_date)
                if signal_row is None or next_open <= 0:
                    continue
                stop = self.initial_stop(signal_row, next_open)
                actual_pct = self.allowed_stock_base_pct(symbol, date_value, next_open, stop, regime)
                if actual_pct >= MIN_BASE_PCT:
                    self.pending_orders.append(
                        PendingOrder(next_date, date_value, symbol, "buy", "stock", "stock_base_pullback_rank_buy", target_pct=actual_pct, stop_price=stop)
                    )

    def schedule_stock_tp_and_add(self, position: Position, row: pd.Series, date_value: dt.date, next_date: dt.date, regime: str) -> None:
        close = clean_float(row.get("close"))
        tp1 = position.base_entry_price + 1.5 * position.base_r
        tp2 = position.base_entry_price + 3.0 * position.base_r
        runner_now = self.is_runner_candidate(position, row)
        if close >= tp2 and not position.tp2_done:
            if runner_now:
                position.is_runner = True
            sell_fraction = 0.15 if runner_now else 0.30
            self.queue_unique(next_date, date_value, position.symbol, "reduce", "stock", "tp2", sell_fraction=sell_fraction)
            position.tp2_done = True
            return
        if close >= tp1 and not position.tp1_done:
            if runner_now:
                position.is_runner = True
            sell_fraction = 0.10 if runner_now else 0.30
            self.queue_unique(next_date, date_value, position.symbol, "reduce", "stock", "tp1", sell_fraction=sell_fraction)
            position.tp1_done = True
            return
        if position.add_count == 0 and self.add1_signal(position, row, regime):
            self.pending_orders.append(PendingOrder(next_date, date_value, position.symbol, "add", "stock", "stock_add1", add_level=1))
        elif position.add_count == 1 and self.add2_signal(position, row, regime):
            self.pending_orders.append(PendingOrder(next_date, date_value, position.symbol, "add", "stock", "stock_add2", add_level=2))

    def stock_sell_reason(self, position: Position, row: pd.Series, date_value: dt.date, regime: str) -> str | None:
        close = clean_float(row.get("close"))
        mom20 = clean_float(row.get("mom20"))
        rs20 = clean_float(row.get("rs20"))
        holding_days = (date_value - position.opened_date).days
        if position.is_runner:
            if close < position.trailing_stop:
                return "runner_trailing_stop"
            if rs20 < 0 and close < clean_float(row.get("sma20")):
                return "runner_rs_sma_exit"
            if holding_days >= 60:
                return "runner_time_exit"
            if regime == "defensive" and not (close > position.trailing_stop and close > clean_float(row.get("sma20")) and rs20 > 0):
                return "market_regime_reduce"
            return None
        if close <= position.initial_stop:
            return "stop_loss"
        if close < clean_float(row.get("sma20")) and mom20 < 0:
            return "sma20_mom_exit"
        if rs20 < 0 and mom20 < 0:
            return "rs_mom_exit"
        if holding_days >= 14:
            return "normal_time_exit"
        if regime == "caution" and close < clean_float(row.get("sma20")) and close < position.avg_entry_price:
            return "market_regime_reduce"
        if regime == "defensive" and not (close > clean_float(row.get("sma20")) and close > position.avg_entry_price):
            return "market_regime_reduce"
        return None

    def update_runner_trails(self, date_value: dt.date) -> None:
        for position in self.positions.values():
            row = self.row(position.symbol, date_value)
            if row is None:
                continue
            close = clean_float(row.get("close"))
            position.peak_price = max(position.peak_price, close)
            if position.sleeve != "stock":
                continue
            if position.is_runner:
                trail = max(
                    position.trailing_stop,
                    clean_float(row.get("sma20")),
                    close - 2.5 * clean_float(row.get("atr20")),
                    position.base_entry_price,
                )
                position.trailing_stop = trail
                position.effective_stop = trail

    @staticmethod
    def tactical_chase_failure(position: Position, row: pd.Series, date_value: dt.date) -> bool:
        if position.sleeve != "etf_tactical" or not position.is_chase_trade:
            return False
        close = clean_float(row.get("close"))
        if position.entry_atr20 > 0 and close < position.entry_signal_close - position.entry_atr20:
            return True
        holding_days = (date_value - position.opened_date).days
        return bool(holding_days >= 3 and position.peak_price <= max(position.entry_signal_high, position.base_entry_price))

    def add1_signal(self, position: Position, row: pd.Series, regime: str) -> bool:
        if regime == "defensive":
            return False
        return bool(
            clean_float(row.get("close")) > clean_float(row.get("sma20"))
            and clean_float(row.get("sma20")) >= clean_float(row.get("sma20_5d_ago"))
            and clean_float(row.get("rs20")) > 0
            and clean_float(row.get("rs20")) > clean_float(row.get("rs20_5d_ago"))
            and clean_float(row.get("mom20")) > 0
            and clean_float(row.get("mom20")) > clean_float(row.get("mom20_5d_ago"))
            and clean_float(row.get("close")) > position.base_entry_price
        )

    def add2_signal(self, position: Position, row: pd.Series, regime: str) -> bool:
        if regime != "normal":
            return False
        return bool(
            clean_float(row.get("close")) > clean_float(row.get("sma20"))
            and clean_float(row.get("sma20")) >= clean_float(row.get("sma20_5d_ago"))
            and clean_float(row.get("rs63")) >= clean_float(row.get("rs63_q95_63"))
            and clean_float(row.get("mom20")) >= 0.05
            and clean_float(row.get("mom20")) > clean_float(row.get("mom20_5d_ago"))
            and clean_float(row.get("close")) > position.last_add_price
        )

    def is_runner_candidate(self, position: Position, row: pd.Series) -> bool:
        runner_count = sum(1 for item in self.positions.values() if item.sleeve == "stock" and item.is_runner)
        close = clean_float(row.get("close"))
        tp1 = position.base_entry_price + 1.5 * position.base_r
        return bool(
            close >= tp1
            and close > clean_float(row.get("sma20"))
            and clean_float(row.get("sma20")) >= clean_float(row.get("sma20_5d_ago"))
            and clean_float(row.get("rs63")) >= clean_float(row.get("rs63_q95_63"))
            and clean_float(row.get("mom20")) >= 0.05
            and clean_float(row.get("mom20")) > clean_float(row.get("mom20_5d_ago"))
            and (position.is_runner or runner_count < MAX_RUNNER_NAMES)
        )

    def schedule_market_regime_reduction(self, date_value: dt.date, next_date: dt.date, regime: str) -> None:
        rules = self.regime_rules(regime)
        stock_pct = self.sleeve_pct(date_value, "stock")
        if stock_pct <= rules["stock_limit"] + 0.005:
            return
        excess = stock_pct - rules["stock_limit"]
        ranked_positions = []
        for position in self.positions.values():
            if position.sleeve != "stock":
                continue
            row = self.row(position.symbol, date_value)
            if row is None:
                continue
            loss_flag = int(clean_float(row.get("close")) < position.avg_entry_price and clean_float(row.get("close")) < clean_float(row.get("sma20")))
            rs_bad = int(clean_float(row.get("rs20")) < 0)
            mom_bad = int(clean_float(row.get("mom20")) < 0)
            runner_penalty = -1 if position.is_runner else 0
            age = (date_value - position.opened_date).days
            ranked_positions.append((loss_flag, rs_bad, mom_bad, runner_penalty, age, position.symbol, position))
        for *_score, position in sorted(ranked_positions, key=lambda item: item[:-1], reverse=True):
            if excess <= 0:
                break
            current_pct = self.symbol_sleeve_pct(date_value, position.symbol, "stock")
            if current_pct <= 0:
                continue
            sell_fraction = min(1.0, excess / current_pct)
            self.queue_unique(next_date, date_value, position.symbol, "reduce", "stock", "market_regime_reduce", sell_fraction=sell_fraction)
            excess -= current_pct * sell_fraction

    def stock_candidates(self, date_value: dt.date) -> list[dict[str, Any]]:
        rows = []
        for symbol in STOCK_SYMBOLS:
            row = self.row(symbol, date_value)
            if row is None:
                continue
            valid_days = self.valid_days(symbol, date_value, 20)
            if valid_days < 18 or clean_float(row.get("close")) < 5:
                continue
            required = ["adv20", "rs20", "rs63", "mom20", "mom63", "high63", "sma20", "sma20_5d_ago"]
            if any(not math.isfinite(clean_float(row.get(key), math.nan)) for key in required):
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "adv20": clean_float(row.get("adv20")),
                    "rs20": clean_float(row.get("rs20")),
                    "rs63": clean_float(row.get("rs63")),
                    "mom20": clean_float(row.get("mom20")),
                    "mom63": clean_float(row.get("mom63")),
                    "pullback_quality": min(max(1 - abs(clean_float(row.get("close")) / clean_float(row.get("high63")) - 1) / 0.20, 0.0), 1.0)
                    if clean_float(row.get("high63")) > 0
                    else 0.0,
                }
            )
        if not rows:
            return []
        frame = pd.DataFrame(rows)
        frame = frame.sort_values("adv20", ascending=False).head(50).copy()
        frame["score"] = (
            0.30 * percentile_rank(frame["rs63"])
            + 0.20 * percentile_rank(frame["rs20"])
            + 0.20 * percentile_rank(frame["mom20"])
            + 0.15 * percentile_rank(frame["mom63"])
            + 0.10 * percentile_rank(frame["adv20"])
            + 0.05 * frame["pullback_quality"]
        )
        candidates = []
        for item in frame.sort_values("score", ascending=False).to_dict("records"):
            symbol = str(item["symbol"])
            row = self.row(symbol, date_value)
            if row is not None and self.stock_base_signal(row):
                item["sector"] = SECTOR_MAP.get(symbol, "unknown")
                candidates.append(item)
        return candidates

    @staticmethod
    def stock_base_signal(row: pd.Series) -> bool:
        close = clean_float(row.get("close"))
        high63 = clean_float(row.get("high63"))
        return bool(
            close > clean_float(row.get("sma20"))
            and clean_float(row.get("sma20")) >= clean_float(row.get("sma20_5d_ago"))
            and clean_float(row.get("mom20")) > 0
            and clean_float(row.get("rs20")) > 0
            and high63 > 0
            and close <= high63 * 0.98
            and close >= high63 * 0.80
        )

    def valid_days(self, symbol: str, date_value: dt.date, days: int) -> int:
        frame = self.data.get(symbol)
        if frame is None:
            return 0
        sample = frame.loc[:date_value].tail(days)
        return int(sample["close"].notna().sum())

    @staticmethod
    def initial_stop(row: pd.Series, actual_entry_price: float) -> float:
        signal_close = clean_float(row.get("close"))
        candidate = max(signal_close - 2.5 * clean_float(row.get("atr20")), clean_float(row.get("low10")) - 0.5 * clean_float(row.get("atr20")))
        return min(candidate, actual_entry_price * 0.97)

    def allowed_stock_base_pct(self, symbol: str, date_value: dt.date, entry_price: float, stop: float, regime: str) -> float:
        rules = self.regime_rules(regime)
        if rules["new_mult"] <= 0 or entry_price <= 0 or stop >= entry_price:
            return 0.0
        risk_per_share_pct = (entry_price - stop) / entry_price
        if risk_per_share_pct <= 0:
            return 0.0
        if risk_per_share_pct > MAX_STOCK_STOP_DISTANCE_PCT:
            return 0.0
        single_risk_allowed_pct = rules["initial_risk_limit"] / risk_per_share_pct
        remaining_total_risk = max(0.0, rules["open_risk_limit"] - self.stock_open_risk_pct(date_value))
        total_risk_allowed_pct = remaining_total_risk / risk_per_share_pct
        stock_remaining = max(0.0, rules["stock_limit"] - self.sleeve_pct(date_value, "stock"))
        single_remaining = max(0.0, SINGLE_STOCK_LIMIT - self.symbol_pct(date_value, symbol))
        sector_remaining = self.remaining_group_pct(date_value, SECTOR_MAP.get(symbol, "unknown"), "sector", SECTOR_LIMIT)
        theme_remaining = self.remaining_group_pct(date_value, SECTOR_MAP.get(symbol, "unknown"), "theme", THEME_LIMIT)
        qqq_remaining = QQQ_TOP10_STOCK_LIMIT if self.qqq_top10_unavailable else 0.0
        planned = BASE_STOCK_PCT * rules["new_mult"]
        return max(
            0.0,
            min(planned, single_risk_allowed_pct, total_risk_allowed_pct, stock_remaining, single_remaining, sector_remaining, theme_remaining, qqq_remaining),
        )

    def allowed_stock_add_pct(self, position: Position, date_value: dt.date, entry_price: float, add_level: int, regime: str) -> float:
        rules = self.regime_rules(regime)
        planned = ADD1_STOCK_PCT * rules["add1_mult"] if add_level == 1 else ADD2_STOCK_PCT * rules["add2_mult"]
        if planned <= 0 or entry_price <= 0:
            return 0.0
        if add_level == 1:
            predicted_stop = max(position.initial_stop, position.base_entry_price)
        else:
            row = self.row(position.symbol, date_value)
            predicted_stop = max(position.initial_stop, position.base_entry_price, clean_float(row.get("sma20")) if row is not None else 0.0)
        risk_per_share_pct = (entry_price - predicted_stop) / entry_price
        if risk_per_share_pct <= 0:
            return 0.0
        if risk_per_share_pct > MAX_STOCK_STOP_DISTANCE_PCT:
            return 0.0
        equity = self.current_equity(date_value)
        current_risk = position.open_risk_pct(equity, self.close_price(position.symbol, date_value))
        remaining_single_risk = max(0.0, rules["position_risk_limit"] - current_risk)
        single_risk_allowed_pct = remaining_single_risk / risk_per_share_pct
        remaining_total_risk = max(0.0, rules["open_risk_limit"] - self.stock_open_risk_pct(date_value))
        total_risk_allowed_pct = remaining_total_risk / risk_per_share_pct
        stock_remaining = max(0.0, rules["stock_limit"] - self.sleeve_pct(date_value, "stock"))
        single_remaining = max(0.0, SINGLE_STOCK_LIMIT - self.symbol_pct(date_value, position.symbol))
        sector_remaining = self.remaining_group_pct(date_value, position.sector, "sector", SECTOR_LIMIT)
        theme_remaining = self.remaining_group_pct(date_value, position.theme, "theme", THEME_LIMIT)
        qqq_remaining = QQQ_TOP10_STOCK_LIMIT if self.qqq_top10_unavailable else 0.0
        return max(
            0.0,
            min(planned, single_risk_allowed_pct, total_risk_allowed_pct, stock_remaining, single_remaining, sector_remaining, theme_remaining, qqq_remaining),
        )

    def remaining_group_pct(self, date_value: dt.date, group_value: str, field_name: str, limit: float) -> float:
        if group_value == "unknown":
            return limit
        equity = self.current_equity(date_value)
        if equity <= 0:
            return 0.0
        used = 0.0
        for position in self.positions.values():
            if position.sleeve != "stock":
                continue
            if getattr(position, field_name) == group_value:
                used += position.market_value(self.close_price(position.symbol, date_value)) / equity
        return max(0.0, limit - used)

    def symbol_sleeve_pct(self, date_value: dt.date, symbol: str, sleeve: str) -> float:
        equity = self.current_equity(date_value)
        if equity <= 0:
            return 0.0
        return sum(
            position.market_value(self.close_price(position.symbol, date_value)) / equity
            for position in self.positions.values()
            if position.symbol == symbol and position.sleeve == sleeve
        )

    def find_position_id(self, symbol: str, sleeve: str) -> str | None:
        for position_id, position in self.positions.items():
            if position.symbol == symbol and position.sleeve == sleeve:
                return position_id
        return None

    def is_first_trading_day_of_week(self, date_value: dt.date) -> bool:
        index = self.dates.index(date_value)
        if index == 0:
            return True
        previous = self.dates[index - 1]
        return date_value.isocalendar().week != previous.isocalendar().week or date_value.year != previous.year

    def queue_unique(
        self,
        execute_date: dt.date,
        signal_date: dt.date,
        symbol: str,
        action: str,
        sleeve: str,
        reason: str,
        sell_fraction: float = 1.0,
    ) -> None:
        if any(order.symbol == symbol and order.sleeve == sleeve and order.action == action and order.execute_date == execute_date for order in self.pending_orders):
            return
        self.pending_orders.append(PendingOrder(execute_date, signal_date, symbol, action, sleeve, reason, sell_fraction=sell_fraction))

    def record_equity(self, date_value: dt.date, regime: str) -> None:
        equity = self.current_equity(date_value)
        positions_value = equity - self.cash
        self.high_watermark = max(self.high_watermark, equity)
        previous_equity = self.equity_rows[-1]["equity"] if self.equity_rows else self.initial_capital
        self.equity_rows.append(
            {
                "date": date_value.isoformat(),
                "cash": self.cash,
                "equity": equity,
                "positions_value": positions_value,
                "total_position_pct": positions_value / equity * 100 if equity > 0 else 0.0,
                "etf_position_pct": self.sleeve_pct(date_value, "etf") * 100,
                "stock_position_pct": self.sleeve_pct(date_value, "stock") * 100,
                "open_risk_pct": self.stock_open_risk_pct(date_value) * 100,
                "drawdown_pct": equity / self.high_watermark * 100 - 100 if self.high_watermark > 0 else 0.0,
                "market_regime": regime,
                "daily_pnl": equity - previous_equity,
                "cumulative_pnl": equity - self.initial_capital,
            }
        )

    def build_payload(self) -> dict[str, Any]:
        summary = build_summary(self.initial_capital, self.trade_rows, self.equity_rows)
        summary.update(
            {
                "max_total_position_pct": max((row["total_position_pct"] for row in self.equity_rows), default=0.0),
                "max_stock_sleeve_pct": max((row["stock_position_pct"] for row in self.equity_rows), default=0.0),
                "max_etf_sleeve_pct": max((row["etf_position_pct"] for row in self.equity_rows), default=0.0),
                "max_open_risk_pct": max((row["open_risk_pct"] for row in self.equity_rows), default=0.0),
                "survivorship_bias_risk": self.survivorship_bias_risk,
                "earnings_filter_unreliable": self.earnings_unreliable,
                "qqq_top10_flag_unavailable": self.qqq_top10_unavailable,
            }
        )
        warnings = list(dict.fromkeys(self.quality_warnings))
        if self.survivorship_bias_risk:
            warnings.append("No point-in-time broad universe file was found; fixed candidate symbols plus dynamic OHLCV filters were used.")
        if self.earnings_unreliable:
            warnings.append("No point-in-time earnings calendar was found; earnings filters were not enforced.")
        if self.qqq_top10_unavailable:
            warnings.append("No point-in-time QQQ top-10 holdings were found; QQQ overlap limits were reported but not enforced.")
        return {
            "ok": True,
            "scenario": self.scenario_name(),
            "summary": summary,
            "trades": self.trade_rows,
            "fills": [fill.__dict__ for fill in self.fills],
            "equity_curve": self.equity_rows,
            "quality_warnings": warnings,
            "parameters": {
                "stock_sleeve_normal_pct": self.stock_sleeve_normal_pct * 100,
                "stock_sleeve_caution_pct": STOCK_SLEEVE_CAUTION * 100,
                "stock_sleeve_defensive_pct": STOCK_SLEEVE_DEFENSIVE * 100,
            },
            "rules": strategy_rules(),
        }

    def scenario_name(self) -> str:
        stock_cap = round(self.stock_sleeve_normal_pct * 100)
        if stock_cap == round(STOCK_SLEEVE_NORMAL * 100):
            return "candidate-v2.1-stop8-gap-tactical-chase-stops"
        return f"candidate-v2.1-stock-sleeve-normal-{stock_cap}-stop8-gap-tactical-chase-stops"


def build_summary(initial_capital: float, trades: list[dict[str, Any]], equity_rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_equity = clean_float(equity_rows[-1]["equity"]) if equity_rows else initial_capital
    total_pnl = final_equity - initial_capital
    trade_count = len(trades)
    wins = [row for row in trades if clean_float(row.get("pnl_amount")) > 0]
    losses = [row for row in trades if clean_float(row.get("pnl_amount")) < 0]
    gross_profit = sum(clean_float(row.get("pnl_amount")) for row in wins)
    gross_loss = abs(sum(clean_float(row.get("pnl_amount")) for row in losses))
    r_values = [clean_float(row.get("realized_R")) for row in trades if row.get("realized_R") is not None]
    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "total_return_pct": total_pnl / initial_capital * 100 if initial_capital > 0 else 0.0,
        "max_drawdown_pct": min((clean_float(row.get("drawdown_pct")) for row in equity_rows), default=0.0),
        "trade_count": trade_count,
        "win_rate": len(wins) / trade_count * 100 if trade_count else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "avg_realized_R": statistics.fmean(r_values) if r_values else None,
        "max_consecutive_losses": max_consecutive_losses(trades),
    }


def max_consecutive_losses(trades: list[dict[str, Any]]) -> int:
    streak = 0
    max_streak = 0
    for row in sorted(trades, key=lambda item: str(item.get("exit_execution_date") or "")):
        if clean_float(row.get("pnl_amount")) < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def strategy_rules() -> dict[str, Any]:
    return {
        "position_priority": [
            "total_position_limit",
            "sleeve_limit",
            "single_symbol_limit",
            "sector_theme_qqq_overlap_limit",
            "total_open_risk_limit",
            "single_trade_risk_limit",
            "signals",
        ],
        "etf": {
            "symbols": ETF_SYMBOLS,
            "sleeve_pct": 60,
            "core_pct": 45,
            "tactical_pct": 15,
            "single_etf_cap_pct": 30,
            "core_score": "0.6*mom63 + 0.4*mom126",
        },
        "stock": {
            "base_pct": 6,
            "add1_pct": 4,
            "add2_pct": 5,
            "single_stock_cap_pct": 15,
            "max_initial_stop_distance_pct": MAX_STOCK_STOP_DISTANCE_PCT * 100,
            "max_names": 6,
            "max_runner_names": 4,
            "tp1": "1.5R",
            "tp2": "3.0R",
        },
    }


def write_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    charts_dir = output_dir / "charts"
    tables_dir = output_dir / "tables"
    ensure_dir(output_dir)
    ensure_dir(charts_dir)
    ensure_dir(tables_dir)

    trades_df = pd.DataFrame(payload["trades"])
    fills_df = pd.DataFrame(payload["fills"])
    equity_df = pd.DataFrame(payload["equity_curve"])
    trades_path = output_dir / "trades.csv"
    fills_path = output_dir / "fills.csv"
    equity_path = output_dir / "equity_curve.csv"
    summary_path = output_dir / "summary.json"
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
    fills_df.to_csv(fills_path, index=False, encoding="utf-8-sig")
    equity_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    table_paths = write_tables(trades_df, equity_df, tables_dir)
    chart_paths = write_charts(trades_df, equity_df, charts_dir)
    html_path = output_dir / "backtest_report.html"
    write_html_report(payload, table_paths, chart_paths, html_path)
    return {
        "html": html_path,
        "trades": trades_path,
        "fills": fills_path,
        "equity": equity_path,
        "summary": summary_path,
        "charts": charts_dir,
        "tables": tables_dir,
    }


def write_tables(trades: pd.DataFrame, equity: pd.DataFrame, tables_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if trades.empty:
        for name in [
            "symbol_summary",
            "yearly_summary",
            "monthly_summary",
            "holding_period_summary",
            "entry_type_summary",
            "top_winners",
            "top_losers",
            "sleeve_summary",
            "add_level_summary",
            "exit_reason_summary",
            "market_regime_summary",
        ]:
            path = tables_dir / f"{name}.csv"
            pd.DataFrame().to_csv(path, index=False)
            paths[name] = path
        return paths

    frame = trades.copy()
    frame["exit_execution_date"] = pd.to_datetime(frame["exit_execution_date"], errors="coerce")
    frame["year"] = frame["exit_execution_date"].dt.year
    frame["month"] = frame["exit_execution_date"].dt.to_period("M").astype(str)
    frame["holding_bucket"] = frame["holding_days"].apply(holding_bucket)

    aggregations = {
        "pnl_amount": ["sum", "mean", "count"],
        "realized_R": "mean",
    }
    summary_specs = {
        "symbol_summary": "symbol",
        "yearly_summary": "year",
        "monthly_summary": "month",
        "holding_period_summary": "holding_bucket",
        "entry_type_summary": "entry_type",
        "sleeve_summary": "sleeve",
        "add_level_summary": "add_level",
        "exit_reason_summary": "exit_reason",
        "market_regime_summary": "market_regime",
    }
    for name, key in summary_specs.items():
        grouped = frame.groupby(key, dropna=False).agg(aggregations)
        grouped.columns = ["total_pnl", "avg_pnl", "trade_count", "avg_R"]
        wins = frame.groupby(key)["pnl_amount"].apply(lambda values: (values > 0).mean() * 100)
        grouped["win_rate"] = wins
        grouped = grouped.reset_index().sort_values("total_pnl", ascending=False)
        path = tables_dir / f"{name}.csv"
        grouped.to_csv(path, index=False, encoding="utf-8-sig")
        paths[name] = path

    winners = frame.sort_values("pnl_amount", ascending=False).head(20)
    losers = frame.sort_values("pnl_amount", ascending=True).head(20)
    paths["top_winners"] = tables_dir / "top_winners.csv"
    paths["top_losers"] = tables_dir / "top_losers.csv"
    winners.to_csv(paths["top_winners"], index=False, encoding="utf-8-sig")
    losers.to_csv(paths["top_losers"], index=False, encoding="utf-8-sig")
    return paths


def write_charts(trades: pd.DataFrame, equity: pd.DataFrame, charts_dir: Path) -> dict[str, Path]:
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.25})
    paths = {
        "equity_curve": charts_dir / "equity_curve.png",
        "drawdown_curve": charts_dir / "drawdown_curve.png",
        "symbol_pnl_rank": charts_dir / "symbol_pnl_rank.png",
        "yearly_pnl": charts_dir / "yearly_pnl.png",
        "monthly_heatmap": charts_dir / "monthly_heatmap.png",
        "rolling_20_trades_pnl": charts_dir / "rolling_20_trades_pnl.png",
        "holding_period_pnl": charts_dir / "holding_period_pnl.png",
        "entry_type_pnl": charts_dir / "entry_type_pnl.png",
        "r_distribution": charts_dir / "r_distribution.png",
    }
    equity_frame = equity.copy()
    if not equity_frame.empty:
        equity_frame["date"] = pd.to_datetime(equity_frame["date"])
        line_chart(equity_frame, "date", "equity", "Equity Curve", "Equity", paths["equity_curve"])
        line_chart(equity_frame, "date", "drawdown_pct", "Drawdown Curve", "Drawdown %", paths["drawdown_curve"])
    else:
        empty_chart(paths["equity_curve"], "No equity data")
        empty_chart(paths["drawdown_curve"], "No drawdown data")

    if trades.empty:
        for key, path in paths.items():
            if not path.exists():
                empty_chart(path, "No trade data")
        return paths

    frame = trades.copy()
    frame["exit_execution_date"] = pd.to_datetime(frame["exit_execution_date"], errors="coerce")
    frame["year"] = frame["exit_execution_date"].dt.year
    frame["month"] = frame["exit_execution_date"].dt.month
    frame["holding_bucket"] = frame["holding_days"].apply(holding_bucket)
    frame["r_bucket"] = frame["realized_R"].apply(r_bucket)

    barh(frame.groupby("symbol")["pnl_amount"].sum().sort_values(), "Symbol Net PnL", "PnL", paths["symbol_pnl_rank"])
    bar(frame.groupby("year")["pnl_amount"].sum(), "Yearly PnL", "Year", "PnL", paths["yearly_pnl"])
    monthly_heatmap(frame, paths["monthly_heatmap"])
    rolling = frame.sort_values("exit_execution_date")["pnl_amount"].rolling(20).sum().dropna()
    if not rolling.empty:
        plot_series(rolling.reset_index(drop=True), "Rolling 20 Trades PnL", "Trade Index", "Rolling PnL", paths["rolling_20_trades_pnl"])
    else:
        empty_chart(paths["rolling_20_trades_pnl"], "Not enough trades for rolling 20")
    bar(frame.groupby("holding_bucket")["pnl_amount"].sum().reindex(["1-2d", "3-5d", "6-10d", "11-15d", "15d+"]).fillna(0), "Holding Period PnL", "Holding Period", "PnL", paths["holding_period_pnl"])
    bar(frame.groupby("entry_type")["pnl_amount"].sum(), "Entry Type PnL", "Entry Type", "PnL", paths["entry_type_pnl"])
    r_order = ["<= -1R", "-1R to 0", "0 to 1R", "1R to 2R", "2R to 3R", "> 3R", "N/A"]
    bar(frame.groupby("r_bucket").size().reindex(r_order).fillna(0), "R Multiple Distribution", "R Bucket", "Trade Count", paths["r_distribution"])
    return paths


def line_chart(frame: pd.DataFrame, x_col: str, y_col: str, title: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(frame[x_col], frame[y_col], linewidth=1.8)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_series(series: pd.Series, title: str, xlabel: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(series.index, series.values, linewidth=1.8)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def bar(series: pd.Series, title: str, xlabel: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#16a34a" if value >= 0 else "#dc2626" for value in series.values]
    ax.bar([str(item) for item in series.index], series.values, color=colors)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def barh(series: pd.Series, title: str, xlabel: str, path: Path) -> None:
    fig_height = max(5, len(series) * 0.28)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    colors = ["#16a34a" if value >= 0 else "#dc2626" for value in series.values]
    ax.barh([str(item) for item in series.index], series.values, color=colors)
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Symbol")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def monthly_heatmap(frame: pd.DataFrame, path: Path) -> None:
    pivot = frame.pivot_table(index=frame["exit_execution_date"].dt.year, columns=frame["exit_execution_date"].dt.month, values="pnl_amount", aggfunc="sum").fillna(0)
    if pivot.empty:
        empty_chart(path, "No monthly trade data")
        return
    pivot = pivot.reindex(columns=range(1, 13), fill_value=0)
    fig, ax = plt.subplots(figsize=(12, max(3, 0.5 * len(pivot))))
    vmax = max(abs(pivot.values.min()), abs(pivot.values.max()), 1.0)
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_title("Monthly PnL Heatmap")
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.set_xticks(range(12), labels=[str(i) for i in range(1, 13)])
    ax.set_yticks(range(len(pivot.index)), labels=[str(i) for i in pivot.index])
    for y in range(pivot.shape[0]):
        for x in range(pivot.shape[1]):
            ax.text(x, y, f"{pivot.values[y, x]:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="PnL")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def empty_chart(path: Path, message: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.text(0.5, 0.5, message, ha="center", va="center")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_html_report(payload: dict[str, Any], table_paths: dict[str, Path], chart_paths: dict[str, Path], html_path: Path) -> None:
    summary = payload["summary"]
    cards = "".join(
        f"<div class='card'><div class='label'>{key}</div><div class='value'>{format_value(value)}</div></div>"
        for key, value in summary.items()
        if key
        in {
            "initial_capital",
            "final_equity",
            "total_pnl",
            "total_return_pct",
            "max_drawdown_pct",
            "trade_count",
            "win_rate",
            "profit_factor",
            "avg_realized_R",
            "max_consecutive_losses",
            "max_total_position_pct",
            "max_stock_sleeve_pct",
            "max_etf_sleeve_pct",
            "max_open_risk_pct",
            "survivorship_bias_risk",
            "earnings_filter_unreliable",
            "qqq_top10_flag_unavailable",
        }
    )
    chart_html = "".join(
        f"<section><h2>{key.replace('_', ' ').title()}</h2><img src='charts/{path.name}' alt='{key}'></section>"
        for key, path in chart_paths.items()
    )
    warnings = "".join(f"<li>{item}</li>" for item in payload.get("quality_warnings", []))
    tables = "".join(
        f"<li><a href='tables/{path.name}'>{path.name}</a></li>"
        for path in table_paths.values()
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Strategy Backtest Report</title>
  <style>
    body {{ font-family: Arial, 'Microsoft YaHei', sans-serif; margin: 0; background: #f6f8fb; color: #111827; }}
    header {{ padding: 28px 36px; background: #0f172a; color: #fff; }}
    main {{ padding: 24px 36px 48px; max-width: 1280px; margin: auto; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 20px 0; }}
    .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }}
    .label {{ color: #64748b; font-size: 12px; }}
    .value {{ font-size: 20px; font-weight: 700; margin-top: 6px; }}
    section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 18px 0; }}
    img {{ width: 100%; height: auto; display: block; }}
    code {{ background: #e5e7eb; padding: 2px 4px; border-radius: 4px; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <header>
    <h1>ETF + Stock Candidate v2.1 Backtest</h1>
    <p>Standalone offline report. No dashboard/server integration required.</p>
  </header>
  <main>
    <div class="cards">{cards}</div>
    <section><h2>Data Quality Warnings</h2><ul>{warnings}</ul></section>
    {chart_html}
    <section><h2>CSV Summary Tables</h2><ul>{tables}</ul></section>
  </main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")


def format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, np.integer)):
        return str(value)
    if isinstance(value, (float, np.floating)):
        return f"{float(value):,.2f}"
    return str(value)


def save_run_index(payload: dict[str, Any], output_dir: Path) -> Path:
    summary_payload = {
        "ok": payload.get("ok"),
        "scenario": payload.get("scenario"),
        "summary": {
            "totalReturnPct": payload.get("summary", {}).get("total_return_pct"),
            "finalEquityUsdt": payload.get("summary", {}).get("final_equity"),
            "maxDrawdownPct": payload.get("summary", {}).get("max_drawdown_pct"),
            "tradeCount": payload.get("summary", {}).get("trade_count"),
        },
        "combined": {"totalReturnPct": payload.get("summary", {}).get("total_return_pct")},
        "outputDir": str(output_dir),
    }
    path = save_run_summary(summary_payload)
    path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standalone candidate v2.1 strategy backtest and report.")
    parser.add_argument("--data-dir", default="data", help="Optional data directory. Local cache is auto-detected when absent.")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "strategy_backtest"))
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument(
        "--stock-sleeve-normal-pct",
        type=float,
        default=STOCK_SLEEVE_NORMAL * 100,
        help="Normal-regime stock sleeve cap as percent of account equity.",
    )
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    backtester = StrategyBacktester(
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.initial_capital,
        output_dir=output_dir,
        refresh_history=args.refresh_history,
        stock_sleeve_normal_pct=args.stock_sleeve_normal_pct / 100,
    )
    payload = backtester.run()
    paths = write_outputs(payload, output_dir)
    index_path = save_run_index(payload, output_dir)
    print(json.dumps({"ok": True, "summary": payload["summary"], "run_index": str(index_path)}, ensure_ascii=False, indent=2))
    print(f"HTML report: {paths['html']}")
    print(f"trades.csv: {paths['trades']}")
    print(f"fills.csv: {paths['fills']}")
    print(f"equity_curve.csv: {paths['equity']}")
    print(f"summary.json: {paths['summary']}")
    print(f"charts dir: {paths['charts']}")
    print(f"tables dir: {paths['tables']}")
    print("data quality warnings:")
    for warning in payload.get("quality_warnings", []):
        print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
