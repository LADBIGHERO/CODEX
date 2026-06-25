from __future__ import annotations

import argparse
import datetime as dt
import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
INITIAL_CAPITAL = 100_000.0
TRADING_DAYS_PER_YEAR = 252
TRANSACTION_COST_RATE = 0.0014

SYMBOL_FILES = {
    "QQQ_PROXY": ROOT / "outputs" / "yahoo_USTEC_NDX_1d_19950101_20260615.csv",
    "VOO_PROXY": ROOT / "outputs" / "yahoo_US500_GSPC_1d_19950101_20260615.csv",
}

SYMBOL_LABELS = {
    "QQQ_PROXY": "QQQ proxy: USTEC / Nasdaq 100 index",
    "VOO_PROXY": "VOO proxy: US500 / S&P 500 index",
}

PERIODS = {
    "全样本": (None, None),
    "2000-2002 科技泡沫熊市": ("2000-01-01", "2002-12-31"),
    "2008 金融危机": ("2008-01-01", "2008-12-31"),
    "2020 暴跌反弹": ("2020-02-19", "2020-12-31"),
    "2022 加息慢熊": ("2022-01-01", "2022-12-31"),
    "2023-2025 牛市": ("2023-01-01", "2025-12-31"),
}

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class StrategyParams:
    swing_n: int = 2
    breakout_close_position: float = 0.75
    pullback_zone: float = 0.01
    pullback_max_days: int = 20
    confirmation_close_position: float = 0.70
    min_risk_pct: float = 0.01
    max_risk_pct: float = 0.08
    tp1_r: float = 2.0
    tp2_r: float = 3.0
    time_exit_days: int = 60
    time_exit_min_profit_r: float = 1.0

    @property
    def label(self) -> str:
        return (
            f"最小阻力趋势突破回踩：swing={self.swing_n}, "
            f"突破收盘位>={self.breakout_close_position:.0%}, "
            f"回踩区=突破位±{self.pullback_zone:.1%}, "
            f"站稳收盘位>={self.confirmation_close_position:.0%}, "
            f"TP={self.tp1_r:g}R/卖50% + {self.tp2_r:g}R/再卖25%"
        )


DEFAULT_PARAMS = StrategyParams()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimum-resistance breakout-pullback strategy on local proxies.")
    parser.add_argument("--symbols", default="QQQ_PROXY,VOO_PROXY", help="Comma-separated symbols.")
    return parser.parse_args()


def load_ohlc(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    columns = {str(column).lower(): column for column in raw.columns}
    if "date" not in columns:
        raise ValueError(f"{path} missing Date column")
    required = ["open", "high", "low", "close"]
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(f"{path} missing columns: {', '.join(missing)}")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[columns["date"]], errors="coerce"),
            "open": pd.to_numeric(raw[columns["open"]], errors="coerce"),
            "high": pd.to_numeric(raw[columns["high"]], errors="coerce"),
            "low": pd.to_numeric(raw[columns["low"]], errors="coerce"),
            "close": pd.to_numeric(raw[columns["close"]], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    return add_indicators(frame)


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["previous_close"] = data["close"].shift(1)
    data["sma50"] = data["close"].rolling(50, min_periods=50).mean()
    data["sma200"] = data["close"].rolling(200, min_periods=200).mean()
    data["sma200_slope20"] = data["sma200"] / data["sma200"].shift(20) - 1.0
    data["mom63"] = data["close"] / data["close"].shift(63) - 1.0
    data["prior_20_low"] = data["low"].shift(1).rolling(20, min_periods=20).min()
    return data


def confirmed_swing_events(frame: pd.DataFrame, swing_n: int) -> dict[int, list[dict[str, Any]]]:
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    events: dict[int, list[dict[str, Any]]] = {}
    if len(frame) < swing_n * 2 + 1:
        return events
    for center in range(swing_n, len(frame) - swing_n):
        high = highs[center]
        low = lows[center]
        if high > np.max(highs[center - swing_n : center]) and high > np.max(highs[center + 1 : center + swing_n + 1]):
            confirm_idx = center + swing_n
            events.setdefault(confirm_idx, []).append(
                {"type": "high", "center_idx": center, "confirm_idx": confirm_idx, "date": frame.at[center, "date"], "value": high}
            )
        if low < np.min(lows[center - swing_n : center]) and low < np.min(lows[center + 1 : center + swing_n + 1]):
            confirm_idx = center + swing_n
            events.setdefault(confirm_idx, []).append(
                {"type": "low", "center_idx": center, "confirm_idx": confirm_idx, "date": frame.at[center, "date"], "value": low}
            )
    return events


def close_position(high: float, low: float, close: float) -> float | None:
    if high == low:
        return None
    return (close - low) / (high - low)


def market_filter(row: pd.Series) -> bool:
    values = [row["sma200"], row["sma200_slope20"], row["sma50"], row["mom63"]]
    if any(not math.isfinite(float(value)) for value in values):
        return False
    return (
        float(row["close"]) > float(row["sma200"])
        and float(row["sma200_slope20"]) > 0.0
        and float(row["close"]) > float(row["sma50"])
        and float(row["mom63"]) > 0.0
    )


def rising_structure(known_highs: list[dict[str, Any]], known_lows: list[dict[str, Any]]) -> bool:
    if len(known_highs) < 2 or len(known_lows) < 2:
        return False
    return known_highs[-1]["value"] > known_highs[-2]["value"] and known_lows[-1]["value"] > known_lows[-2]["value"]


def buy_all(cash: float, price: float) -> tuple[float, float, float]:
    units = cash / (price * (1.0 + TRANSACTION_COST_RATE))
    cost = cash - units * price
    return units, 0.0, cost


def sell_units(units: float, price: float) -> tuple[float, float]:
    gross = units * price
    cost = gross * TRANSACTION_COST_RATE
    return gross - cost, cost


def run_buy_hold(frame: pd.DataFrame) -> pd.DataFrame:
    first_open = float(frame.iloc[0]["open"])
    units = INITIAL_CAPITAL / (first_open * (1.0 + TRANSACTION_COST_RATE))
    return pd.DataFrame({"date": frame["date"], "buy_hold_equity": units * frame["close"].astype(float)})


def run_strategy(symbol: str, frame: pd.DataFrame, params: StrategyParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    swing_events = confirmed_swing_events(frame, params.swing_n)
    known_highs: list[dict[str, Any]] = []
    known_lows: list[dict[str, Any]] = []
    cash = INITIAL_CAPITAL
    units = 0.0
    original_units = 0.0
    position: dict[str, Any] | None = None
    setup: dict[str, Any] | None = None
    pending_order: dict[str, Any] | None = None
    ledger: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []

    for idx, row in frame.iterrows():
        date = row["date"]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if pending_order is not None:
            if pending_order["side"] == "buy" and position is None:
                initial_stop = float(pending_order["initial_stop"])
                risk = open_price - initial_stop
                risk_ratio = risk / open_price if open_price > 0 else math.nan
                if risk > 0 and params.min_risk_pct <= risk_ratio <= params.max_risk_pct:
                    entry_cash = cash
                    units, cash, entry_cost = buy_all(cash, open_price)
                    original_units = units
                    position = {
                        **pending_order["setup"],
                        "entry_signal_date": pending_order["entry_signal_date"],
                        "entry_idx": idx,
                        "entry_date": date,
                        "entry_price": open_price,
                        "initial_stop": initial_stop,
                        "R": risk,
                        "entry_cash": entry_cash,
                        "entry_cost": entry_cost,
                        "below_breakout_streak": 0,
                        "tp1_done": False,
                        "tp2_done": False,
                        "max_high": open_price,
                        "min_low": open_price,
                        "exit_costs": 0.0,
                        "realized_cash": 0.0,
                    }
                    fills.append({"symbol": symbol, "date": date, "action": "BUY", "price": open_price, "units": units, "cost": entry_cost})
                setup = None
            elif pending_order["side"] == "sell" and position is not None:
                sell_fraction = pending_order["fraction"]
                sell_qty = units if sell_fraction >= 0.999 else min(units, original_units * sell_fraction)
                proceeds, exit_cost = sell_units(sell_qty, open_price)
                units -= sell_qty
                cash += proceeds
                position["exit_costs"] += exit_cost
                position["realized_cash"] += proceeds
                fills.append(
                    {
                        "symbol": symbol,
                        "date": date,
                        "action": "SELL",
                        "reason": pending_order["exit_reason"],
                        "price": open_price,
                        "units": sell_qty,
                        "cost": exit_cost,
                    }
                )
                if units <= original_units * 0.001 or pending_order["close_trade"]:
                    final_cash = cash
                    trade_return = final_cash / float(position["entry_cash"]) - 1.0
                    trades.append(
                        {
                            "symbol": symbol,
                            "breakout_date": position["breakout_date"],
                            "breakout_price": position["breakout_price"],
                            "last_swing_high": position["last_swing_high"],
                            "last_swing_low": position["last_swing_low"],
                            "pullback_date": position["pullback_date"],
                            "pullback_low": position["pullback_low_at_entry"],
                            "confirmation_date": position["confirmation_date"],
                            "entry_date": position["entry_date"],
                            "entry_price": position["entry_price"],
                            "initial_stop": position["initial_stop"],
                            "R": position["R"],
                            "exit_signal_date": pending_order["exit_signal_date"],
                            "exit_date": date,
                            "exit_price": open_price,
                            "exit_reason": pending_order["exit_reason"],
                            "holding_days": idx - int(position["entry_idx"]),
                            "trade_return": trade_return,
                            "trade_R_multiple": (open_price - float(position["entry_price"])) / float(position["R"]),
                            "max_favorable_excursion": float(position["max_high"]) / float(position["entry_price"]) - 1.0,
                            "max_adverse_excursion": float(position["min_low"]) / float(position["entry_price"]) - 1.0,
                            "entry_cost": position["entry_cost"],
                            "exit_cost": position["exit_costs"],
                        }
                    )
                    units = 0.0
                    original_units = 0.0
                    position = None
                    setup = None
            pending_order = None

        new_low_break_events: list[dict[str, Any]] = []
        for event in swing_events.get(idx, []):
            if event["type"] == "high":
                known_highs.append(event)
            else:
                if known_lows and event["value"] < known_lows[-1]["value"]:
                    new_low_break_events.append(event)
                known_lows.append(event)

        if position is not None:
            position["max_high"] = max(float(position["max_high"]), high)
            position["min_low"] = min(float(position["min_low"]), low)

            exit_reason: str | None = None
            exit_fraction = 1.0
            close_trade = True
            holding_days_at_close = idx - int(position["entry_idx"]) + 1
            entry_price = float(position["entry_price"])
            risk = float(position["R"])

            if close < float(position["initial_stop"]):
                exit_reason = "结构止损"
            elif holding_days_at_close <= 5:
                if close < float(position["last_swing_high"]):
                    position["below_breakout_streak"] += 1
                else:
                    position["below_breakout_streak"] = 0
                if position["below_breakout_streak"] >= 2:
                    exit_reason = "假突破失败"
            if exit_reason is None:
                broke_after_entry = any(event["center_idx"] >= int(position["entry_idx"]) for event in new_low_break_events)
                if broke_after_entry:
                    exit_reason = "结构破坏"
            if exit_reason is None and not bool(position["tp1_done"]) and close >= entry_price + params.tp1_r * risk:
                exit_reason = f"{params.tp1_r:g}R止盈50%"
                exit_fraction = 0.50
                close_trade = False
                position["tp1_done"] = True
            elif exit_reason is None and bool(position["tp1_done"]) and not bool(position["tp2_done"]) and close >= entry_price + params.tp2_r * risk:
                exit_reason = f"{params.tp2_r:g}R止盈25%"
                exit_fraction = 0.25
                close_trade = False
                position["tp2_done"] = True
            elif exit_reason is None and bool(position["tp1_done"]):
                prior_20_low = float(row["prior_20_low"]) if math.isfinite(float(row["prior_20_low"])) else math.nan
                if math.isfinite(prior_20_low) and close < prior_20_low:
                    exit_reason = "剩余仓位20日低点跟踪退出"
            if exit_reason is None and holding_days_at_close >= params.time_exit_days and close < entry_price + params.time_exit_min_profit_r * risk:
                exit_reason = "60日不足1R退出"

            if exit_reason is not None and idx + 1 < len(frame):
                pending_order = {
                    "side": "sell",
                    "exit_signal_date": date,
                    "exit_reason": exit_reason,
                    "fraction": exit_fraction,
                    "close_trade": close_trade,
                }

        if position is None and pending_order is None:
            if setup is not None:
                if setup["state"] == "waiting_pullback":
                    if idx - int(setup["breakout_idx"]) > params.pullback_max_days or close < float(setup["last_swing_low"]):
                        setup = None
                    else:
                        setup["pullback_low"] = min(float(setup["pullback_low"]), low)
                        if low <= float(setup["pullback_zone_high"]) and close >= float(setup["pullback_zone_low"]):
                            setup["state"] = "waiting_confirmation"
                            setup["pullback_date"] = date
                elif setup["state"] == "waiting_confirmation":
                    if close < float(setup["last_swing_low"]):
                        setup = None
                    else:
                        previous_pullback_low = float(setup["pullback_low"])
                        cp = close_position(high, low, close)
                        confirmed = (
                            cp is not None
                            and close > open_price
                            and math.isfinite(float(row["previous_close"]))
                            and close > float(row["previous_close"])
                            and cp >= params.confirmation_close_position
                            and low >= previous_pullback_low
                            and close >= float(setup["pullback_zone_low"])
                        )
                        setup["pullback_low"] = min(previous_pullback_low, low)
                        if confirmed and idx + 1 < len(frame):
                            pending_order = {
                                "side": "buy",
                                "entry_signal_date": date,
                                "initial_stop": setup["pullback_low"],
                                "setup": {
                                    "breakout_date": setup["breakout_date"],
                                    "breakout_price": setup["breakout_price"],
                                    "last_swing_high": setup["last_swing_high"],
                                    "last_swing_low": setup["last_swing_low"],
                                    "pullback_date": setup["pullback_date"],
                                    "pullback_low_at_entry": setup["pullback_low"],
                                    "confirmation_date": date,
                                },
                            }
                            setup = None

            if setup is None and pending_order is None and market_filter(row) and rising_structure(known_highs, known_lows):
                last_high = known_highs[-1]
                last_low = known_lows[-1]
                cp = close_position(high, low, close)
                if cp is not None and close > float(last_high["value"]) and close > open_price and cp >= params.breakout_close_position:
                    swing_high = float(last_high["value"])
                    setup = {
                        "state": "waiting_pullback",
                        "breakout_idx": idx,
                        "breakout_date": date,
                        "breakout_price": close,
                        "last_swing_high": swing_high,
                        "last_swing_low": float(last_low["value"]),
                        "pullback_zone_high": swing_high * (1.0 + params.pullback_zone),
                        "pullback_zone_low": swing_high * (1.0 - params.pullback_zone),
                        "pullback_low": math.inf,
                        "pullback_date": pd.NaT,
                    }

        ledger.append(
            {
                "date": date,
                "strategy_equity": cash + units * close,
                "cash": cash,
                "asset_value": units * close,
                "position": 1 if units > 0 else 0,
            }
        )

    if units > 0 and position is not None:
        last = frame.iloc[-1]
        proceeds, exit_cost = sell_units(units, float(last["close"]))
        cash += proceeds
        position["exit_costs"] += exit_cost
        trades.append(
            {
                "symbol": symbol,
                "breakout_date": position["breakout_date"],
                "breakout_price": position["breakout_price"],
                "last_swing_high": position["last_swing_high"],
                "last_swing_low": position["last_swing_low"],
                "pullback_date": position["pullback_date"],
                "pullback_low": position["pullback_low_at_entry"],
                "confirmation_date": position["confirmation_date"],
                "entry_date": position["entry_date"],
                "entry_price": position["entry_price"],
                "initial_stop": position["initial_stop"],
                "R": position["R"],
                "exit_signal_date": last["date"],
                "exit_date": last["date"],
                "exit_price": float(last["close"]),
                "exit_reason": "样本结束",
                "holding_days": len(frame) - int(position["entry_idx"]),
                "trade_return": cash / float(position["entry_cash"]) - 1.0,
                "trade_R_multiple": (float(last["close"]) - float(position["entry_price"])) / float(position["R"]),
                "max_favorable_excursion": float(position["max_high"]) / float(position["entry_price"]) - 1.0,
                "max_adverse_excursion": float(position["min_low"]) / float(position["entry_price"]) - 1.0,
                "entry_cost": position["entry_cost"],
                "exit_cost": position["exit_costs"],
            }
        )
        ledger[-1]["strategy_equity"] = cash
        ledger[-1]["cash"] = cash
        ledger[-1]["asset_value"] = 0.0
        ledger[-1]["position"] = 0

    return pd.DataFrame(ledger), pd.DataFrame(trades)


def years_between(dates: pd.Series) -> float:
    if len(dates) < 2:
        return 0.0
    return max((pd.to_datetime(dates.iloc[-1]) - pd.to_datetime(dates.iloc[0])).days / 365.25, 1 / 365.25)


def max_drawdown_pct(values: pd.Series) -> float:
    return float((values / values.cummax() - 1.0).min() * 100.0)


def yearly_returns(curve: pd.DataFrame, column: str) -> pd.Series:
    data = curve[["date", column]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.set_index("date").sort_index()
    year_end = data[column].resample("YE").last().dropna()
    if year_end.empty:
        return pd.Series(dtype=float)
    returns = year_end.pct_change()
    returns.loc[year_end.index[0]] = year_end.iloc[0] / float(data[column].iloc[0]) - 1.0
    returns.index = returns.index.year
    return returns.sort_index()


def summary_metrics(curve: pd.DataFrame, column: str, trades: pd.DataFrame | None = None) -> dict[str, Any]:
    equity = curve[column].astype(float)
    daily_returns = equity.pct_change().fillna(0.0)
    years = years_between(curve["date"])
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if years > 0 else math.nan
    max_dd = max_drawdown_pct(equity)
    volatility = daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (
        daily_returns.mean() * TRADING_DAYS_PER_YEAR / (daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR))
        if daily_returns.std(ddof=0) > 0
        else math.nan
    )
    calmar = cagr * 100.0 / abs(max_dd) if max_dd < 0 else math.nan
    annual = yearly_returns(curve, column)
    result = {
        "final_equity": equity.iloc[-1],
        "cumulative_return_pct": (equity.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0,
        "CAGR_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd,
        "volatility_pct": volatility * 100.0,
        "Sharpe": sharpe,
        "Calmar": calmar,
        "best_year": annual.idxmax() if not annual.empty else "",
        "best_year_return_pct": annual.max() * 100.0 if not annual.empty else math.nan,
        "worst_year": annual.idxmin() if not annual.empty else "",
        "worst_year_return_pct": annual.min() * 100.0 if not annual.empty else math.nan,
    }
    if trades is not None:
        returns = trades["trade_return"].astype(float) if not trades.empty else pd.Series(dtype=float)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        max_loss_streak = 0
        current = 0
        for value in returns:
            if value < 0:
                current += 1
                max_loss_streak = max(max_loss_streak, current)
            else:
                current = 0
        result.update(
            {
                "trade_count": int(len(returns)),
                "win_rate_pct": len(wins) / len(returns) * 100.0 if len(returns) else math.nan,
                "average_win_pct": wins.mean() * 100.0 if len(wins) else math.nan,
                "average_loss_pct": losses.mean() * 100.0 if len(losses) else math.nan,
                "profit_factor": wins.sum() / abs(losses.sum()) if abs(losses.sum()) > 0 else math.nan,
                "average_holding_days": trades["holding_days"].mean() if not trades.empty else math.nan,
                "max_consecutive_losses": max_loss_streak,
                "time_in_market_pct": curve["position"].mean() * 100.0 if "position" in curve else math.nan,
            }
        )
    return result


def period_return(curve: pd.DataFrame, column: str, start: str | None, end: str | None) -> float:
    data = curve.copy()
    data["date"] = pd.to_datetime(data["date"])
    if start:
        data = data[data["date"] >= pd.Timestamp(start)]
    if end:
        data = data[data["date"] <= pd.Timestamp(end)]
    if len(data) < 2:
        return math.nan
    return float((data[column].iloc[-1] / data[column].iloc[0] - 1.0) * 100.0)


def pct_axis() -> FuncFormatter:
    return FuncFormatter(lambda value, _: f"{value:.0f}%")


def plot_curves(curves: dict[str, pd.DataFrame], charts_dir: Path) -> None:
    fig, axes = plt.subplots(len(curves), 2, figsize=(15, 4.2 * len(curves)), squeeze=False)
    for row_idx, (symbol, curve) in enumerate(curves.items()):
        ret_strategy = curve["strategy_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        ret_bh = curve["buy_hold_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        ax = axes[row_idx][0]
        ax.plot(curve["date"], ret_strategy, label="策略", color="#2563eb", linewidth=1.4)
        ax.plot(curve["date"], ret_bh, label="买入持有", color="#94a3b8", linewidth=1.2)
        ax.set_title(f"{symbol} 收益曲线", loc="left", fontweight="bold")
        ax.yaxis.set_major_formatter(pct_axis())
        ax.grid(True, color="#e5e7eb")
        ax.legend()

        dd_strategy = curve["strategy_equity"] / curve["strategy_equity"].cummax() * 100.0 - 100.0
        dd_bh = curve["buy_hold_equity"] / curve["buy_hold_equity"].cummax() * 100.0 - 100.0
        ax = axes[row_idx][1]
        ax.plot(curve["date"], dd_strategy, label="策略", color="#dc2626", linewidth=1.2)
        ax.plot(curve["date"], dd_bh, label="买入持有", color="#64748b", linewidth=1.1)
        ax.set_title(f"{symbol} 回撤曲线", loc="left", fontweight="bold")
        ax.yaxis.set_major_formatter(pct_axis())
        ax.grid(True, color="#e5e7eb")
        ax.legend()
    fig.tight_layout()
    fig.savefig(charts_dir / "equity_and_drawdown_curves.png", dpi=160)
    plt.close(fig)


def table_html(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "<p class='muted'>无数据</p>"
    data = frame.head(max_rows).copy() if max_rows else frame.copy()
    return data.to_html(index=False, escape=True, classes="data-table", border=0)


def build_report(output_dir: Path, manifest: pd.DataFrame, summary: pd.DataFrame, periods: pd.DataFrame, trades: pd.DataFrame) -> None:
    css = """
    body { margin:0; background:#f1f5f9; color:#0f172a; font-family:"Microsoft YaHei","Segoe UI",sans-serif; }
    header { padding:28px 40px; background:#0f172a; color:#fff; }
    header h1 { margin:0 0 8px; font-size:28px; }
    header p { margin:0; color:#cbd5e1; }
    main { padding:28px 40px 60px; }
    section { background:#fff; border:1px solid #dbe4ef; border-radius:8px; margin:0 0 22px; overflow:hidden; }
    h2 { margin:0; padding:15px 18px; border-bottom:1px solid #e2e8f0; font-size:19px; }
    .content { padding:18px; }
    .note { background:#f8fafc; border-left:4px solid #2563eb; padding:12px 14px; margin-bottom:12px; }
    .chart { width:100%; max-width:1500px; display:block; margin:auto; border:1px solid #e2e8f0; border-radius:6px; }
    .scroll { overflow:auto; max-height:560px; }
    .data-table { border-collapse:collapse; width:100%; font-size:13px; }
    .data-table th { background:#f8fafc; text-align:left; color:#334155; }
    .data-table th, .data-table td { border-bottom:1px solid #e2e8f0; padding:8px 9px; white-space:nowrap; }
    .muted { color:#64748b; }
    """
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>最小阻力趋势突破回踩策略报告</title><style>{css}</style></head>
<body>
<header>
  <h1>最小阻力趋势突破回踩策略：QQQ / VOO 本地代理回测</h1>
  <p>使用本地 USTEC/^NDX 代理 QQQ，US500/^GSPC 代理 VOO。信号收盘后生成，次日开盘成交；每次成交成本 {TRANSACTION_COST_RATE:.2%}。</p>
</header>
<main>
  <section><h2>策略口径</h2><div class="content">
    <p class="note">{html.escape(DEFAULT_PARAMS.label)}</p>
    <p>单品种模式：有信号时 100% 买入当前代理品种；达到 2R 卖出 50%，达到 3R 再卖出 25%，剩余仓位用 20 日低点、结构破坏、止损或时间规则退出。不做空、不加杠杆、不轮动。</p>
  </div></section>
  <section><h2>数据清单</h2><div class="content scroll">{table_html(manifest)}</div></section>
  <section><h2>核心结果</h2><div class="content scroll">{table_html(summary)}</div></section>
  <section><h2>折线图</h2><div class="content"><img class="chart" src="charts/equity_and_drawdown_curves.png" alt="收益与回撤曲线"></div></section>
  <section><h2>阶段表现</h2><div class="content scroll">{table_html(periods)}</div></section>
  <section><h2>交易日志</h2><div class="content scroll">{table_html(trades, 200)}</div></section>
</main>
</body></html>
"""
    (output_dir / "backtest_report.html").write_text(html_text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()]
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    all_trades: list[pd.DataFrame] = []
    curves: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        path = SYMBOL_FILES[symbol]
        frame = load_ohlc(path)
        manifest_rows.append(
            {
                "symbol": symbol,
                "label": SYMBOL_LABELS[symbol],
                "path": str(path),
                "data_start_date": frame["date"].iloc[0].strftime("%Y-%m-%d"),
                "data_end_date": frame["date"].iloc[-1].strftime("%Y-%m-%d"),
                "data_rows": len(frame),
                "adjusted_price_used": "No, local index proxy OHLC",
            }
        )
        buy_hold = run_buy_hold(frame)
        strategy_curve, trades = run_strategy(symbol, frame, DEFAULT_PARAMS)
        merged = strategy_curve.merge(buy_hold, on="date", how="left")
        curves[symbol] = merged
        if not trades.empty:
            all_trades.append(trades)

        strategy_metrics = summary_metrics(strategy_curve, "strategy_equity", trades)
        buy_hold_metrics = summary_metrics(buy_hold.rename(columns={"buy_hold_equity": "strategy_equity"}), "strategy_equity")
        summary_rows.append(
            {
                "symbol": symbol,
                "proxy_for": "QQQ" if symbol == "QQQ_PROXY" else "VOO",
                **strategy_metrics,
                "buy_hold_cumulative_return_pct": buy_hold_metrics["cumulative_return_pct"],
                "buy_hold_CAGR_pct": buy_hold_metrics["CAGR_pct"],
                "buy_hold_max_drawdown_pct": buy_hold_metrics["max_drawdown_pct"],
                "buy_hold_Calmar": buy_hold_metrics["Calmar"],
                "strategy_minus_buy_hold_CAGR_pct": strategy_metrics["CAGR_pct"] - buy_hold_metrics["CAGR_pct"],
                "strategy_minus_buy_hold_max_drawdown_pct": strategy_metrics["max_drawdown_pct"] - buy_hold_metrics["max_drawdown_pct"],
                "strategy_minus_buy_hold_Calmar": strategy_metrics["Calmar"] - buy_hold_metrics["Calmar"],
            }
        )
        for period_name, (start, end) in PERIODS.items():
            period_rows.append(
                {
                    "symbol": symbol,
                    "period": period_name,
                    "strategy_return_pct": period_return(strategy_curve, "strategy_equity", start, end),
                    "buy_hold_return_pct": period_return(buy_hold, "buy_hold_equity", start, end),
                }
            )
        print(f"{symbol}: rows={len(frame)}, trades={len(trades)}")

    manifest = pd.DataFrame(manifest_rows)
    summary = pd.DataFrame(summary_rows)
    periods = pd.DataFrame(period_rows)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    avg_adv = summary["strategy_minus_buy_hold_CAGR_pct"].mean() if not summary.empty else math.nan
    output_dir = REPORTS / f"min-resistance-breakout-pullback_qqq-voo-proxy_{timestamp}_avgadv-{avg_adv:.2f}"
    charts_dir = output_dir / "charts"
    tables_dir = output_dir / "tables"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    plot_curves(curves, charts_dir)
    equity_frames = []
    for symbol, curve in curves.items():
        data = curve.copy()
        data.insert(0, "symbol", symbol)
        equity_frames.append(data)
    pd.concat(equity_frames, ignore_index=True).to_csv(tables_dir / "equity_curves.csv", index=False, encoding="utf-8-sig")
    manifest.to_csv(tables_dir / "input_manifest.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(tables_dir / "symbol_summary.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(tables_dir / "period_performance.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(tables_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
    build_report(output_dir, manifest, summary, periods, trades)
    print(f"HTML report: {output_dir / 'backtest_report.html'}")
    print(f"PNG charts: {charts_dir}")
    print(f"CSV tables: {tables_dir}")


if __name__ == "__main__":
    main()
