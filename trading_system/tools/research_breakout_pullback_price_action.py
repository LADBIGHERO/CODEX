from __future__ import annotations

import argparse
import datetime as dt
import html
import itertools
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
    "US500": ROOT / "outputs" / "yahoo_US500_GSPC_1d_19950101_20260615.csv",
    "USTEC": ROOT / "outputs" / "yahoo_USTEC_NDX_1d_19950101_20260615.csv",
    "JP225": ROOT / "outputs" / "yahoo_JP225_N225_1d_19950101_20260615.csv",
    "MidDE50": ROOT / "outputs" / "mt5_MidDE50_M30_20060614_20260614.csv",
    "TecDE30": ROOT / "outputs" / "mt5_TecDE30_M30_20060614_20260614.csv",
}

SYMBOL_SOURCE = {
    "US500": "Yahoo ^GSPC daily",
    "USTEC": "Yahoo ^NDX daily",
    "JP225": "Yahoo ^N225 daily",
    "MidDE50": "MT5 MidDE50 M30 aggregated to daily",
    "TecDE30": "MT5 TecDE30 M30 aggregated to daily",
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
    confirmation_close_position: float = 0.70
    take_profit_r: float = 2.0
    max_holding_days: int = 20
    pullback_max_days: int = 20

    @property
    def param_id(self) -> str:
        return (
            f"sw{self.swing_n}_"
            f"br{int(self.breakout_close_position * 100)}_"
            f"zone{self.pullback_zone * 100:.1f}_"
            f"cf{int(self.confirmation_close_position * 100)}_"
            f"tp{self.take_profit_r:g}R_"
            f"hold{self.max_holding_days}"
        ).replace(".", "p")

    @property
    def label(self) -> str:
        return (
            f"swing {self.swing_n} / 突破收盘位 {self.breakout_close_position:.0%} / "
            f"回踩带 ±{self.pullback_zone:.1%} / 站稳收盘位 {self.confirmation_close_position:.0%} / "
            f"{self.take_profit_r:g}R / {self.max_holding_days}日"
        )


DEFAULT_PARAMS = StrategyParams()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pure OHLC breakout-pullback price action research backtest.")
    parser.add_argument("--symbols", default=",".join(SYMBOL_FILES.keys()), help="Comma-separated symbols.")
    parser.add_argument("--skip-stability", action="store_true", help="Run only the base parameter set.")
    parser.add_argument("--full-grid-stability", action="store_true", help="Run the full Cartesian parameter grid.")
    return parser.parse_args()


def standardize_ohlc(raw: pd.DataFrame, path: Path) -> pd.DataFrame:
    columns = {str(column).lower(): column for column in raw.columns}
    if "date" in columns:
        date = pd.to_datetime(raw[columns["date"]], errors="coerce")
    elif "time_utc" in columns:
        date = pd.to_datetime(raw[columns["time_utc"]], utc=True, errors="coerce").dt.tz_convert(None)
    elif "time" in columns:
        numeric_time = pd.to_numeric(raw[columns["time"]], errors="coerce")
        date = pd.to_datetime(numeric_time, unit="s", utc=True, errors="coerce").dt.tz_convert(None)
    else:
        raise ValueError(f"{path} 缺少 date/time/time_utc 字段")

    required = ["open", "high", "low", "close"]
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(f"{path} 缺少 OHLC 字段: {', '.join(missing)}")

    frame = pd.DataFrame(
        {
            "date": date,
            "open": pd.to_numeric(raw[columns["open"]], errors="coerce"),
            "high": pd.to_numeric(raw[columns["high"]], errors="coerce"),
            "low": pd.to_numeric(raw[columns["low"]], errors="coerce"),
            "close": pd.to_numeric(raw[columns["close"]], errors="coerce"),
        }
    )
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")


def load_ohlc(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    frame = standardize_ohlc(raw, path)
    frame["session"] = frame["date"].dt.date
    daily = (
        frame.groupby("session", sort=True)
        .agg(
            date=("date", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            source_rows=("close", "size"),
        )
        .reset_index(drop=True)
    )
    daily["date"] = pd.to_datetime(daily["date"].dt.date)
    return daily.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


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
                {
                    "type": "high",
                    "center_idx": center,
                    "confirm_idx": confirm_idx,
                    "date": frame.at[center, "date"],
                    "value": high,
                }
            )
        if low < np.min(lows[center - swing_n : center]) and low < np.min(lows[center + 1 : center + swing_n + 1]):
            confirm_idx = center + swing_n
            events.setdefault(confirm_idx, []).append(
                {
                    "type": "low",
                    "center_idx": center,
                    "confirm_idx": confirm_idx,
                    "date": frame.at[center, "date"],
                    "value": low,
                }
            )
    return events


def close_position(row: pd.Series) -> float | None:
    high = float(row["high"])
    low = float(row["low"])
    if high == low:
        return None
    return (float(row["close"]) - low) / (high - low)


def is_rising_structure(known_highs: list[dict[str, Any]], known_lows: list[dict[str, Any]]) -> bool:
    if len(known_highs) < 2 or len(known_lows) < 2:
        return False
    return known_highs[-1]["value"] > known_highs[-2]["value"] and known_lows[-1]["value"] > known_lows[-2]["value"]


def execute_buy(cash: float, entry_price: float) -> tuple[float, float, float]:
    units = cash / (entry_price * (1.0 + TRANSACTION_COST_RATE))
    asset_value = units * entry_price
    cost = cash - asset_value
    return units, 0.0, cost


def execute_sell(units: float, exit_price: float) -> tuple[float, float]:
    gross = units * exit_price
    cost = gross * TRANSACTION_COST_RATE
    return gross - cost, cost


def run_buy_hold(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "buy_hold_equity"])
    first_open = float(frame.iloc[0]["open"])
    units = INITIAL_CAPITAL / (first_open * (1.0 + TRANSACTION_COST_RATE))
    equity = units * frame["close"].astype(float)
    return pd.DataFrame({"date": frame["date"], "buy_hold_equity": equity})


def run_strategy(
    symbol: str,
    frame: pd.DataFrame,
    params: StrategyParams,
    swing_events: dict[int, list[dict[str, Any]]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if swing_events is None:
        swing_events = confirmed_swing_events(frame, params.swing_n)
    dates = frame["date"].to_numpy()
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    known_highs: list[dict[str, Any]] = []
    known_lows: list[dict[str, Any]] = []
    cash = INITIAL_CAPITAL
    units = 0.0
    position: dict[str, Any] | None = None
    setup: dict[str, Any] | None = None
    pending_order: dict[str, Any] | None = None
    ledger: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for idx in range(len(frame)):
        date = dates[idx]
        open_price = float(opens[idx])
        high_price = float(highs[idx])
        low_price = float(lows[idx])
        close_price = float(closes[idx])

        if pending_order is not None:
            if pending_order["side"] == "buy" and position is None and cash > 0:
                initial_stop = float(pending_order["initial_stop"])
                risk = open_price - initial_stop
                risk_ratio = risk / open_price if open_price > 0 else math.nan
                if risk > 0 and 0.01 <= risk_ratio <= 0.10:
                    entry_cash = cash
                    units, cash, entry_cost = execute_buy(cash, open_price)
                    position = {
                        **pending_order["setup"],
                        "entry_signal_date": pending_order["entry_signal_date"],
                        "entry_idx": idx,
                        "entry_date": date,
                        "entry_price": open_price,
                        "initial_stop": initial_stop,
                        "R": risk,
                        "units": units,
                        "entry_cash": entry_cash,
                        "entry_cost": entry_cost,
                        "max_high": open_price,
                        "min_low": open_price,
                        "below_breakout_streak": 0,
                    }
                setup = None
            elif pending_order["side"] == "sell" and position is not None:
                exit_cash, exit_cost = execute_sell(units, open_price)
                trade_return = exit_cash / float(position["entry_cash"]) - 1.0
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
                        "exit_cost": exit_cost,
                    }
                )
                cash = exit_cash
                units = 0.0
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
            position["max_high"] = max(float(position["max_high"]), high_price)
            position["min_low"] = min(float(position["min_low"]), low_price)

        exit_reason: str | None = None
        if position is not None:
            holding_days_at_close = idx - int(position["entry_idx"]) + 1
            if close_price < float(position["initial_stop"]):
                exit_reason = "结构止损"
            elif holding_days_at_close <= 5:
                if close_price < float(position["last_swing_high"]):
                    position["below_breakout_streak"] += 1
                else:
                    position["below_breakout_streak"] = 0
                if position["below_breakout_streak"] >= 2:
                    exit_reason = "假突破失败"
            if exit_reason is None and close_price >= float(position["entry_price"]) + params.take_profit_r * float(position["R"]):
                exit_reason = f"{params.take_profit_r:g}R止盈"
            if exit_reason is None:
                broke_after_entry = any(event["center_idx"] >= int(position["entry_idx"]) for event in new_low_break_events)
                if broke_after_entry:
                    exit_reason = "结构破坏"
            if exit_reason is None and close_price > float(position["entry_price"]):
                cp = None if high_price == low_price else (close_price - low_price) / (high_price - low_price)
                previous_close = float(closes[idx - 1]) if idx > 0 else math.nan
                if (
                    cp is not None
                    and close_price < open_price
                    and math.isfinite(previous_close)
                    and close_price < previous_close
                    and cp <= 0.30
                ):
                    exit_reason = "反向强K"
            if exit_reason is None and holding_days_at_close >= params.max_holding_days:
                exit_reason = "时间退出"
            if exit_reason is not None:
                if idx + 1 < len(frame):
                    pending_order = {"side": "sell", "exit_signal_date": date, "exit_reason": exit_reason}
                else:
                    exit_cash, exit_cost = execute_sell(units, close_price)
                    trade_return = exit_cash / float(position["entry_cash"]) - 1.0
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
                            "exit_signal_date": date,
                            "exit_date": date,
                            "exit_price": close_price,
                            "exit_reason": f"{exit_reason}/样本结束",
                            "holding_days": holding_days_at_close,
                            "trade_return": trade_return,
                            "trade_R_multiple": (close_price - float(position["entry_price"])) / float(position["R"]),
                            "max_favorable_excursion": float(position["max_high"]) / float(position["entry_price"]) - 1.0,
                            "max_adverse_excursion": float(position["min_low"]) / float(position["entry_price"]) - 1.0,
                            "entry_cost": position["entry_cost"],
                            "exit_cost": exit_cost,
                        }
                    )
                    cash = exit_cash
                    units = 0.0
                    position = None
                    setup = None

        if position is None and pending_order is None:
            if setup is not None:
                if setup["state"] == "waiting_pullback":
                    if idx - int(setup["breakout_idx"]) > params.pullback_max_days or close_price < float(setup["last_swing_low"]):
                        setup = None
                    else:
                        setup["pullback_low"] = min(float(setup["pullback_low"]), low_price)
                        if low_price <= float(setup["pullback_zone_high"]) and close_price >= float(setup["pullback_zone_low"]):
                            setup["state"] = "waiting_confirmation"
                            setup["pullback_date"] = date
                elif setup["state"] == "waiting_confirmation":
                    if close_price < float(setup["last_swing_low"]):
                        setup = None
                    else:
                        previous_pullback_low = float(setup["pullback_low"])
                        cp = None if high_price == low_price else (close_price - low_price) / (high_price - low_price)
                        previous_close = float(closes[idx - 1]) if idx > 0 else math.nan
                        confirmed = (
                            cp is not None
                            and close_price > open_price
                            and math.isfinite(previous_close)
                            and close_price > previous_close
                            and cp >= params.confirmation_close_position
                            and low_price >= previous_pullback_low
                            and (close_price > float(setup["last_swing_high"]) or close_price >= float(setup["pullback_zone_low"]))
                        )
                        setup["pullback_low"] = min(previous_pullback_low, low_price)
                        if confirmed and idx + 1 < len(frame):
                            setup_for_trade = {
                                "breakout_date": setup["breakout_date"],
                                "breakout_price": setup["breakout_price"],
                                "last_swing_high": setup["last_swing_high"],
                                "last_swing_low": setup["last_swing_low"],
                                "pullback_date": setup["pullback_date"],
                                "pullback_low_at_entry": setup["pullback_low"],
                                "confirmation_date": date,
                            }
                            pending_order = {
                                "side": "buy",
                                "entry_signal_date": date,
                                "initial_stop": setup["pullback_low"],
                                "setup": setup_for_trade,
                            }
                            setup = None

            if setup is None and pending_order is None and is_rising_structure(known_highs, known_lows):
                last_high = known_highs[-1]
                last_low = known_lows[-1]
                cp = None if high_price == low_price else (close_price - low_price) / (high_price - low_price)
                if (
                    cp is not None
                    and close_price > float(last_high["value"])
                    and cp >= params.breakout_close_position
                    and close_price > open_price
                ):
                    swing_high = float(last_high["value"])
                    setup = {
                        "state": "waiting_pullback",
                        "breakout_idx": idx,
                        "breakout_date": date,
                        "breakout_price": close_price,
                        "last_swing_high": swing_high,
                        "last_swing_low": float(last_low["value"]),
                        "pullback_zone_high": swing_high * (1.0 + params.pullback_zone),
                        "pullback_zone_low": swing_high * (1.0 - params.pullback_zone),
                        "pullback_low": math.inf,
                        "pullback_date": pd.NaT,
                    }

        equity = cash + units * close_price
        ledger.append(
            {
                "date": date,
                "strategy_equity": equity,
                "cash": cash,
                "asset_units": units,
                "asset_value": units * close_price,
                "position": 1 if position is not None else 0,
            }
        )

    if position is not None:
        last_idx = len(frame) - 1
        exit_cash, exit_cost = execute_sell(units, float(closes[last_idx]))
        trade_return = exit_cash / float(position["entry_cash"]) - 1.0
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
                "exit_signal_date": dates[last_idx],
                "exit_date": dates[last_idx],
                "exit_price": float(closes[last_idx]),
                "exit_reason": "样本结束",
                "holding_days": len(frame) - 1 - int(position["entry_idx"]) + 1,
                "trade_return": trade_return,
                "trade_R_multiple": (float(closes[last_idx]) - float(position["entry_price"])) / float(position["R"]),
                "max_favorable_excursion": float(position["max_high"]) / float(position["entry_price"]) - 1.0,
                "max_adverse_excursion": float(position["min_low"]) / float(position["entry_price"]) - 1.0,
                "entry_cost": position["entry_cost"],
                "exit_cost": exit_cost,
            }
        )
        ledger[-1]["strategy_equity"] = exit_cash
        ledger[-1]["cash"] = exit_cash
        ledger[-1]["asset_units"] = 0.0
        ledger[-1]["asset_value"] = 0.0
        ledger[-1]["position"] = 0

    return pd.DataFrame(ledger), pd.DataFrame(trades)


def years_between(dates: pd.Series) -> float:
    if len(dates) < 2:
        return 0.0
    return max((pd.to_datetime(dates.iloc[-1]) - pd.to_datetime(dates.iloc[0])).days / 365.25, 1 / 365.25)


def max_drawdown_pct(values: pd.Series) -> float:
    if values.empty:
        return math.nan
    series = values.astype(float)
    return float((series / series.cummax() - 1.0).min() * 100.0)


def yearly_returns(curve: pd.DataFrame, equity_column: str) -> pd.Series:
    if curve.empty:
        return pd.Series(dtype=float)
    data = curve[["date", equity_column]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.set_index("date").sort_index()
    year_end = data[equity_column].resample("YE").last().dropna()
    if year_end.empty:
        return pd.Series(dtype=float)
    returns = year_end.pct_change()
    first_year = year_end.index[0]
    first_value = float(data[equity_column].iloc[0])
    returns.loc[first_year] = year_end.iloc[0] / first_value - 1.0
    returns.index = returns.index.year
    return returns.sort_index()


def summary_metrics(curve: pd.DataFrame, equity_column: str, trades: pd.DataFrame | None = None) -> dict[str, Any]:
    if curve.empty:
        return {}
    equity = curve[equity_column].astype(float)
    dates = pd.to_datetime(curve["date"])
    years = years_between(dates)
    daily_returns = equity.pct_change().fillna(0.0)
    cumulative_return = equity.iloc[-1] / INITIAL_CAPITAL - 1.0
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if years > 0 else math.nan
    volatility = daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = daily_returns.mean() * TRADING_DAYS_PER_YEAR / (daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily_returns.std(ddof=0) > 0 else math.nan
    max_dd = max_drawdown_pct(equity)
    calmar = (cagr * 100.0) / abs(max_dd) if math.isfinite(max_dd) and max_dd < 0 else math.nan
    annual = yearly_returns(curve, equity_column)
    best_year = annual.idxmax() if not annual.empty else ""
    worst_year = annual.idxmin() if not annual.empty else ""

    result: dict[str, Any] = {
        "final_equity": equity.iloc[-1],
        "cumulative_return_pct": cumulative_return * 100.0,
        "CAGR_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd,
        "volatility_pct": volatility * 100.0,
        "Sharpe": sharpe,
        "Calmar": calmar,
        "best_year": best_year,
        "best_year_return_pct": annual.max() * 100.0 if not annual.empty else math.nan,
        "worst_year": worst_year,
        "worst_year_return_pct": annual.min() * 100.0 if not annual.empty else math.nan,
    }

    if trades is not None:
        returns = trades["trade_return"].astype(float) if not trades.empty else pd.Series(dtype=float)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        consecutive_losses = 0
        max_consecutive_losses = 0
        for value in returns:
            if value < 0:
                consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            else:
                consecutive_losses = 0
        result.update(
            {
                "trade_count": int(len(returns)),
                "win_rate_pct": len(wins) / len(returns) * 100.0 if len(returns) else math.nan,
                "average_win_pct": wins.mean() * 100.0 if len(wins) else math.nan,
                "average_loss_pct": losses.mean() * 100.0 if len(losses) else math.nan,
                "profit_factor": wins.sum() / abs(losses.sum()) if abs(losses.sum()) > 0 else math.nan,
                "average_holding_days": trades["holding_days"].mean() if not trades.empty else math.nan,
                "max_consecutive_losses": max_consecutive_losses,
                "time_in_market_pct": curve["position"].mean() * 100.0 if "position" in curve else math.nan,
            }
        )
    return result


def period_return(curve: pd.DataFrame, equity_column: str, start: str | None, end: str | None) -> float:
    if curve.empty:
        return math.nan
    data = curve.copy()
    data["date"] = pd.to_datetime(data["date"])
    if start is not None:
        data = data[data["date"] >= pd.to_datetime(start)]
    if end is not None:
        data = data[data["date"] <= pd.to_datetime(end)]
    if len(data) < 2:
        return math.nan
    return float((data[equity_column].iloc[-1] / data[equity_column].iloc[0] - 1.0) * 100.0)


def parameter_grid(full_grid: bool = False) -> list[StrategyParams]:
    if full_grid:
        return [
            StrategyParams(
                swing_n=swing_n,
                breakout_close_position=breakout_close_position,
                pullback_zone=pullback_zone,
                confirmation_close_position=confirmation_close_position,
                take_profit_r=take_profit_r,
                max_holding_days=max_holding_days,
            )
            for swing_n, breakout_close_position, pullback_zone, confirmation_close_position, take_profit_r, max_holding_days in itertools.product(
                [2, 3, 4],
                [0.65, 0.75, 0.85],
                [0.005, 0.01, 0.015],
                [0.60, 0.70, 0.80],
                [1.5, 2.0, 2.5],
                [10, 20, 30],
            )
        ]

    base = DEFAULT_PARAMS
    candidates: list[StrategyParams] = [base]
    candidates.extend(StrategyParams(swing_n=value) for value in [2, 3, 4])
    candidates.extend(StrategyParams(breakout_close_position=value) for value in [0.65, 0.75, 0.85])
    candidates.extend(StrategyParams(pullback_zone=value) for value in [0.005, 0.01, 0.015])
    candidates.extend(StrategyParams(confirmation_close_position=value) for value in [0.60, 0.70, 0.80])
    candidates.extend(StrategyParams(take_profit_r=value) for value in [1.5, 2.0, 2.5])
    candidates.extend(StrategyParams(max_holding_days=value) for value in [10, 20, 30])

    unique: dict[str, StrategyParams] = {}
    for params in candidates:
        unique[params.param_id] = params
    return list(unique.values())


def percent_axis() -> FuncFormatter:
    return FuncFormatter(lambda value, _: f"{value:.0f}%")


def plot_equity_curves(curves: dict[str, pd.DataFrame], charts_dir: Path) -> None:
    cols = 2
    rows = math.ceil(len(curves) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(15, rows * 4), squeeze=False)
    for ax in axes.ravel():
        ax.set_visible(False)
    for ax, (symbol, curve) in zip(axes.ravel(), curves.items()):
        ax.set_visible(True)
        data = curve.copy()
        data["strategy_return"] = data["strategy_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        data["buy_hold_return"] = data["buy_hold_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        ax.plot(data["date"], data["strategy_return"], label="策略", color="#2563eb", linewidth=1.4)
        ax.plot(data["date"], data["buy_hold_return"], label="买入持有", color="#94a3b8", linewidth=1.2)
        ax.set_title(symbol, loc="left", fontsize=12, fontweight="bold")
        ax.yaxis.set_major_formatter(percent_axis())
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.legend(loc="upper left", fontsize=9)
    fig.suptitle("突破回踩站稳策略 vs 买入持有", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(charts_dir / "equity_curves.png", dpi=160)
    plt.close(fig)


def plot_drawdown_curves(curves: dict[str, pd.DataFrame], charts_dir: Path) -> None:
    cols = 2
    rows = math.ceil(len(curves) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(15, rows * 4), squeeze=False)
    for ax in axes.ravel():
        ax.set_visible(False)
    for ax, (symbol, curve) in zip(axes.ravel(), curves.items()):
        ax.set_visible(True)
        strategy_dd = curve["strategy_equity"] / curve["strategy_equity"].cummax() * 100.0 - 100.0
        buy_hold_dd = curve["buy_hold_equity"] / curve["buy_hold_equity"].cummax() * 100.0 - 100.0
        ax.plot(curve["date"], strategy_dd, label="策略", color="#dc2626", linewidth=1.2)
        ax.plot(curve["date"], buy_hold_dd, label="买入持有", color="#64748b", linewidth=1.1)
        ax.set_title(symbol, loc="left", fontsize=12, fontweight="bold")
        ax.yaxis.set_major_formatter(percent_axis())
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.legend(loc="lower left", fontsize=9)
    fig.suptitle("回撤曲线", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(charts_dir / "drawdown_curves.png", dpi=160)
    plt.close(fig)


def plot_metric_bars(summary: pd.DataFrame, charts_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
    ordered = summary.sort_values("strategy_minus_buy_hold_CAGR_pct", ascending=False)
    colors = ["#16a34a" if value >= 0 else "#dc2626" for value in ordered["strategy_minus_buy_hold_CAGR_pct"]]
    axes[0].bar(ordered["symbol"], ordered["strategy_minus_buy_hold_CAGR_pct"], color=colors)
    axes[0].axhline(0, color="#334155", linewidth=0.8)
    axes[0].set_title("策略年化收益差")
    axes[0].set_ylabel("百分点")
    axes[0].grid(axis="y", color="#e5e7eb")

    colors = ["#16a34a" if value >= 0 else "#dc2626" for value in ordered["strategy_minus_buy_hold_max_drawdown_pct"]]
    axes[1].bar(ordered["symbol"], ordered["strategy_minus_buy_hold_max_drawdown_pct"], color=colors)
    axes[1].axhline(0, color="#334155", linewidth=0.8)
    axes[1].set_title("最大回撤差：正数表示策略回撤更浅")
    axes[1].set_ylabel("百分点")
    axes[1].grid(axis="y", color="#e5e7eb")
    fig.tight_layout()
    fig.savefig(charts_dir / "strategy_vs_buy_hold_bars.png", dpi=160)
    plt.close(fig)


def plot_stability(stability: pd.DataFrame, charts_dir: Path) -> None:
    if stability.empty:
        return
    symbols = list(stability["symbol"].drop_duplicates())
    data = [stability.loc[stability["symbol"] == symbol, "strategy_minus_buy_hold_CAGR_pct"].dropna() for symbol in symbols]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.boxplot(data, tick_labels=symbols, showfliers=False)
    ax.axhline(0, color="#334155", linewidth=0.8)
    ax.set_title("参数稳定性：年化收益差分布")
    ax.set_ylabel("策略 - 买入持有，百分点")
    ax.grid(axis="y", color="#e5e7eb")
    fig.tight_layout()
    fig.savefig(charts_dir / "parameter_stability.png", dpi=160)
    plt.close(fig)


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    if not math.isfinite(number):
        return "N/A"
    return f"{number:,.{digits}f}"


def table_html(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "<p class='muted'>无数据</p>"
    data = frame.head(max_rows).copy() if max_rows else frame.copy()
    return data.to_html(index=False, escape=True, classes="data-table", border=0)


def build_answers(summary: pd.DataFrame, stability: pd.DataFrame) -> list[str]:
    if summary.empty:
        return ["没有可用数据，无法给出结论。"]
    improved_cagr = summary[summary["strategy_minus_buy_hold_CAGR_pct"] > 0]["symbol"].tolist()
    improved_dd = summary[summary["strategy_minus_buy_hold_max_drawdown_pct"] > 0]["symbol"].tolist()
    improved_calmar = summary[summary["strategy_minus_buy_hold_Calmar"] > 0]["symbol"].tolist()
    suitable = summary[
        (summary["strategy_minus_buy_hold_CAGR_pct"] > 0)
        & (summary["strategy_minus_buy_hold_max_drawdown_pct"] >= 0)
        & (summary["strategy_minus_buy_hold_Calmar"] > 0)
    ]["symbol"].tolist()
    low_trade = summary[summary["trade_count"] < 30]["symbol"].tolist()
    avg_cagr_diff = summary["strategy_minus_buy_hold_CAGR_pct"].mean()
    avg_dd_diff = summary["strategy_minus_buy_hold_max_drawdown_pct"].mean()
    stable_lines: list[str] = []
    if not stability.empty:
        stable = (
            stability.groupby("symbol")
            .agg(
                positive_rate=("strategy_minus_buy_hold_CAGR_pct", lambda values: (values > 0).mean() * 100.0),
                median_cagr_diff=("strategy_minus_buy_hold_CAGR_pct", "median"),
                tests=("param_id", "count"),
            )
            .reset_index()
        )
        stable_lines = [
            f"{row.symbol} 参数组跑赢比例 {row.positive_rate:.1f}%，中位年化差 {row.median_cagr_diff:.2f} 个百分点"
            for row in stable.itertuples()
        ]

    return [
        f"1. 年化收益：基础参数平均年化差为 {avg_cagr_diff:.2f} 个百分点；跑赢买入持有的品种：{', '.join(improved_cagr) if improved_cagr else '无'}。",
        f"2. 最大回撤：平均回撤差为 {avg_dd_diff:.2f} 个百分点；回撤更浅的品种：{', '.join(improved_dd) if improved_dd else '无'}。",
        f"3. Calmar：Calmar 改善的品种：{', '.join(improved_calmar) if improved_calmar else '无'}。",
        "4. 胜率和盈亏比请看汇总表；如果 Profit Factor 小于 1，说明平均交易质量不足。",
        f"5. 统计意义：交易次数少于 30 笔的品种：{', '.join(low_trade) if low_trade else '无'}。",
        "6. 趋势/震荡适配：看阶段表现表，如果牛市阶段明显落后且熊市也未明显防守，说明该形态并没有转换成可持续优势。",
        "7. 过拟合迹象：" + ("；".join(stable_lines) if stable_lines else "未运行参数稳定性测试。"),
        "8. 是否比买入持有更值得：需要同时看年化、回撤、Calmar 和交易次数，不能只看某一笔形态交易。",
        f"9. 更适合的品种：{', '.join(suitable) if suitable else '暂未看到同时满足收益、回撤和 Calmar 的品种'}。",
        "10. 下一轮研究价值：如果多数参数组跑赢比例很低，应先收紧形态质量或承认该纯价格行为规则不稳定，而不是继续堆参数。",
    ]


def build_report(
    output_dir: Path,
    manifest: pd.DataFrame,
    summary: pd.DataFrame,
    period_perf: pd.DataFrame,
    trades: pd.DataFrame,
    stability: pd.DataFrame,
    stability_mode: str,
) -> None:
    answers = build_answers(summary, stability)
    css = """
    body { margin:0; background:#f1f5f9; color:#0f172a; font-family:"Microsoft YaHei", "Segoe UI", sans-serif; }
    header { padding:28px 40px; background:#0f172a; color:white; }
    header h1 { margin:0 0 8px; font-size:28px; }
    header p { margin:0; color:#cbd5e1; }
    main { padding:28px 40px 60px; }
    section { background:white; border:1px solid #dbe4ef; border-radius:8px; margin:0 0 24px; overflow:hidden; box-shadow:0 1px 2px rgba(15,23,42,.05); }
    section h2 { margin:0; padding:16px 20px; border-bottom:1px solid #e2e8f0; font-size:20px; }
    .content { padding:18px 20px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:16px; }
    .note { background:#f8fafc; border-left:4px solid #2563eb; padding:12px 14px; margin:0 0 12px; }
    .muted { color:#64748b; }
    .chart { width:100%; max-width:1500px; display:block; margin:0 auto 16px; border:1px solid #e2e8f0; border-radius:6px; }
    .data-table { border-collapse:collapse; width:100%; font-size:13px; }
    .data-table th { background:#f8fafc; color:#334155; text-align:left; position:sticky; top:0; }
    .data-table th, .data-table td { border-bottom:1px solid #e2e8f0; padding:8px 9px; white-space:nowrap; }
    .scroll { overflow:auto; max-height:520px; }
    """
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>突破回踩站稳策略研究报告</title>
  <style>{css}</style>
</head>
<body>
<header>
  <h1>突破回踩站稳策略 / Breakout Pullback Price Action</h1>
  <p>一次性本地研究回测；只使用 OHLC 结构价格行为；不修改正式交易系统；交易成本每次成交 {TRANSACTION_COST_RATE:.2%}。</p>
</header>
<main>
  <section>
    <h2>核心规则</h2>
    <div class="content">
      <p class="note">只做多、不加杠杆、不轮动；每个品种只能在 100% 持有自身和 100% 现金之间切换。信号在收盘后生成，次一交易日开盘成交。</p>
      <p>规则链条：已确认的更高高点与更高低点 → 收盘突破最近已确认 swing high → 20 个交易日内回踩突破位 ±1% → 阳线站稳确认 → 次日开盘买入 → 结构止损、假突破失败、2R 止盈、结构破坏、反向强 K 或时间退出。</p>
    </div>
  </section>
  <section>
    <h2>结论回答</h2>
    <div class="content">
      <ol>
        {''.join(f'<li>{html.escape(answer)}</li>' for answer in answers)}
      </ol>
    </div>
  </section>
  <section>
    <h2>数据清单</h2>
    <div class="content scroll">{table_html(manifest)}</div>
  </section>
  <section>
    <h2>五个品种汇总</h2>
    <div class="content scroll">{table_html(summary)}</div>
  </section>
  <section>
    <h2>净值折线图</h2>
    <div class="content"><img class="chart" src="charts/equity_curves.png" alt="净值折线图"></div>
  </section>
  <section>
    <h2>回撤折线图</h2>
    <div class="content"><img class="chart" src="charts/drawdown_curves.png" alt="回撤折线图"></div>
  </section>
  <section>
    <h2>策略相对买入持有</h2>
    <div class="content"><img class="chart" src="charts/strategy_vs_buy_hold_bars.png" alt="指标对比柱状图"></div>
  </section>
  <section>
    <h2>阶段表现</h2>
    <div class="content scroll">{table_html(period_perf)}</div>
  </section>
  <section>
    <h2>参数稳定性</h2>
    <div class="content">
      <p class="muted">{html.escape(stability_mode)}</p>
      <img class="chart" src="charts/parameter_stability.png" alt="参数稳定性图">
      <div class="scroll">{table_html(stability, max_rows=120)}</div>
    </div>
  </section>
  <section>
    <h2>交易日志</h2>
    <div class="content scroll">{table_html(trades, max_rows=200)}</div>
  </section>
</main>
</body>
</html>
"""
    (output_dir / "backtest_report.html").write_text(html_text, encoding="utf-8")


def format_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[column]):
            data[column] = data[column].dt.strftime("%Y-%m-%d")
    return data


def main() -> None:
    args = parse_args()
    requested_symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()]
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    manifest_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    all_trades: list[pd.DataFrame] = []
    stability_rows: list[dict[str, Any]] = []
    curves: dict[str, pd.DataFrame] = {}

    for symbol in requested_symbols:
        path = SYMBOL_FILES.get(symbol)
        if path is None or not path.exists():
            manifest_rows.append(
                {
                    "symbol": symbol,
                    "data_source": "missing",
                    "path": str(path) if path else "",
                    "data_start_date": "",
                    "data_end_date": "",
                    "data_rows": 0,
                    "whether_adjusted_price_used": "No",
                    "status": "missing file",
                }
            )
            continue

        frame = load_ohlc(path)
        manifest_rows.append(
            {
                "symbol": symbol,
                "data_source": SYMBOL_SOURCE.get(symbol, path.name),
                "path": str(path),
                "data_start_date": frame["date"].iloc[0].strftime("%Y-%m-%d") if not frame.empty else "",
                "data_end_date": frame["date"].iloc[-1].strftime("%Y-%m-%d") if not frame.empty else "",
                "data_rows": len(frame),
                "whether_adjusted_price_used": "No",
                "status": "ok",
            }
        )

        swing_cache = {swing_n: confirmed_swing_events(frame, swing_n) for swing_n in [2, 3, 4]}
        buy_hold = run_buy_hold(symbol, frame)
        strategy_curve, trades = run_strategy(symbol, frame, DEFAULT_PARAMS, swing_cache[DEFAULT_PARAMS.swing_n])
        merged_curve = strategy_curve.merge(buy_hold, on="date", how="left")
        curves[symbol] = merged_curve
        if not trades.empty:
            all_trades.append(trades)

        strategy_metrics = summary_metrics(strategy_curve, "strategy_equity", trades)
        buy_hold_metrics = summary_metrics(buy_hold.rename(columns={"buy_hold_equity": "strategy_equity"}), "strategy_equity")

        summary_rows.append(
            {
                "symbol": symbol,
                "strategy": "Pure Price Action",
                "params": DEFAULT_PARAMS.label,
                **strategy_metrics,
                "buy_hold_cumulative_return_pct": buy_hold_metrics.get("cumulative_return_pct", math.nan),
                "buy_hold_CAGR_pct": buy_hold_metrics.get("CAGR_pct", math.nan),
                "buy_hold_max_drawdown_pct": buy_hold_metrics.get("max_drawdown_pct", math.nan),
                "buy_hold_Calmar": buy_hold_metrics.get("Calmar", math.nan),
                "strategy_minus_buy_hold_CAGR_pct": strategy_metrics.get("CAGR_pct", math.nan) - buy_hold_metrics.get("CAGR_pct", math.nan),
                "strategy_minus_buy_hold_max_drawdown_pct": strategy_metrics.get("max_drawdown_pct", math.nan)
                - buy_hold_metrics.get("max_drawdown_pct", math.nan),
                "strategy_minus_buy_hold_Calmar": strategy_metrics.get("Calmar", math.nan) - buy_hold_metrics.get("Calmar", math.nan),
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

        params_to_run = [DEFAULT_PARAMS] if args.skip_stability else parameter_grid(full_grid=args.full_grid_stability)
        for params in params_to_run:
            curve, param_trades = run_strategy(symbol, frame, params, swing_cache[params.swing_n])
            metrics = summary_metrics(curve, "strategy_equity", param_trades)
            stability_rows.append(
                {
                    "symbol": symbol,
                    "param_id": params.param_id,
                    "params": params.label,
                    "CAGR_pct": metrics.get("CAGR_pct", math.nan),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct", math.nan),
                    "Calmar": metrics.get("Calmar", math.nan),
                    "trade_count": metrics.get("trade_count", 0),
                    "win_rate_pct": metrics.get("win_rate_pct", math.nan),
                    "profit_factor": metrics.get("profit_factor", math.nan),
                    "strategy_minus_buy_hold_CAGR_pct": metrics.get("CAGR_pct", math.nan)
                    - buy_hold_metrics.get("CAGR_pct", math.nan),
                    "strategy_minus_buy_hold_max_drawdown_pct": metrics.get("max_drawdown_pct", math.nan)
                    - buy_hold_metrics.get("max_drawdown_pct", math.nan),
                }
            )
        print(f"{symbol}: rows={len(frame)}, trades={len(trades)}, stability_tests={len(params_to_run)}")

    manifest = pd.DataFrame(manifest_rows)
    summary = pd.DataFrame(summary_rows)
    period_perf = pd.DataFrame(period_rows)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    stability = pd.DataFrame(stability_rows)

    avg_advantage = summary["strategy_minus_buy_hold_CAGR_pct"].mean() if not summary.empty else math.nan
    output_dir = REPORTS / f"breakout-pullback-price-action_{timestamp}_avgadv-{avg_advantage:.2f}"
    charts_dir = output_dir / "charts"
    tables_dir = output_dir / "tables"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    if curves:
        equity_csv = []
        for symbol, curve in curves.items():
            data = curve.copy()
            data.insert(0, "symbol", symbol)
            equity_csv.append(data)
        pd.concat(equity_csv, ignore_index=True).to_csv(tables_dir / "equity_curves.csv", index=False, encoding="utf-8-sig")
        plot_equity_curves(curves, charts_dir)
        plot_drawdown_curves(curves, charts_dir)
    else:
        pd.DataFrame().to_csv(tables_dir / "equity_curves.csv", index=False, encoding="utf-8-sig")

    if not summary.empty:
        plot_metric_bars(summary, charts_dir)
    if not stability.empty:
        plot_stability(stability, charts_dir)

    format_for_csv(manifest).to_csv(tables_dir / "input_manifest.csv", index=False, encoding="utf-8-sig")
    format_for_csv(summary).to_csv(tables_dir / "symbol_summary.csv", index=False, encoding="utf-8-sig")
    format_for_csv(period_perf).to_csv(tables_dir / "period_performance.csv", index=False, encoding="utf-8-sig")
    format_for_csv(trades).to_csv(tables_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
    format_for_csv(stability).to_csv(tables_dir / "parameter_stability.csv", index=False, encoding="utf-8-sig")

    if args.skip_stability:
        stability_mode = "本次只运行基础参数，未做额外参数稳定性测试。"
    elif args.full_grid_stability:
        stability_mode = "参数稳定性为全笛卡尔组合测试。"
    else:
        stability_mode = "参数稳定性为单因素扰动测试：每次只改变一个参数，用来观察规则稳不稳定，不用于寻找最优参数。"
    build_report(output_dir, manifest, summary, period_perf, trades, stability, stability_mode)

    print(f"HTML report: {output_dir / 'backtest_report.html'}")
    print(f"PNG charts: {charts_dir}")
    print(f"CSV tables: {tables_dir}")


if __name__ == "__main__":
    main()
