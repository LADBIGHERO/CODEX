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

import research_leverage_matrix_balance_sheet_7pct as base


INITIAL_CAPITAL = base.INITIAL_CAPITAL
TRADING_DAYS_PER_YEAR = base.TRADING_DAYS_PER_YEAR
TRANSACTION_COST_RATE = base.TRANSACTION_COST_RATE

ROOT = base.ROOT
REPORTS = base.REPORTS

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
    pullback_min: float = 0.03
    pullback_max: float = 0.12
    close_position_threshold: float = 0.70
    stop_buffer_atr: float = 0.5
    take_profit_r: float = 2.0
    max_holding_days: int = 15

    @property
    def param_id(self) -> str:
        return (
            f"pbmin{int(self.pullback_min * 100)}_"
            f"pbmax{int(self.pullback_max * 100)}_"
            f"close{int(self.close_position_threshold * 100)}_"
            f"tp{self.take_profit_r:g}R_"
            f"hold{self.max_holding_days}"
        )

    @property
    def label(self) -> str:
        return (
            f"回踩{self.pullback_min:.0%}-{self.pullback_max:.0%} / "
            f"收盘位{self.close_position_threshold:.0%} / "
            f"{self.take_profit_r:g}R / {self.max_holding_days}日"
        )


DEFAULT_PARAMS = StrategyParams()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research pullback price action strategy.")
    parser.add_argument("--symbols", default=",".join(SYMBOL_FILES.keys()), help="Comma-separated symbols to test.")
    parser.add_argument("--skip-stability", action="store_true", help="Only run the main parameter set.")
    return parser.parse_args()


def _standardize_ohlc(raw: pd.DataFrame, path: Path) -> pd.DataFrame:
    columns = {column.lower(): column for column in raw.columns}
    if "date" in columns:
        date = pd.to_datetime(raw[columns["date"]])
    elif "time_utc" in columns:
        date = pd.to_datetime(raw[columns["time_utc"]], utc=True).dt.tz_convert(None)
    elif "time" in columns:
        date = pd.to_datetime(raw[columns["time"]], unit="s", utc=True).dt.tz_convert(None)
    else:
        raise ValueError(f"{path} missing date/time column")
    frame = pd.DataFrame(
        {
            "date": date,
            "open": pd.to_numeric(raw[columns["open"]], errors="coerce"),
            "high": pd.to_numeric(raw[columns["high"]], errors="coerce"),
            "low": pd.to_numeric(raw[columns["low"]], errors="coerce"),
            "close": pd.to_numeric(raw[columns["close"]], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    return frame


def load_ohlc(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    frame = _standardize_ohlc(raw, path)
    frame["session"] = frame["date"].dt.date
    daily = (
        frame.groupby("session")
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
    daily = daily.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    return add_indicators(daily)


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    previous_close = data["close"].shift(1)
    tr = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["previous_close"] = previous_close
    data["sma10"] = data["close"].rolling(10, min_periods=1).mean()
    data["sma20"] = data["close"].rolling(20, min_periods=1).mean()
    data["sma50"] = data["close"].rolling(50, min_periods=1).mean()
    data["sma200"] = data["close"].rolling(200, min_periods=1).mean()
    data["sma200_slope20"] = data["sma200"] / data["sma200"].shift(20) - 1.0
    data["atr14"] = tr.rolling(14, min_periods=1).mean()
    data["rolling_10_low"] = data["low"].rolling(10, min_periods=1).min()
    data["rolling_20_high"] = data["high"].rolling(20, min_periods=1).max()
    data["rolling_20_low"] = data["low"].rolling(20, min_periods=1).min()
    data["rolling_50_high"] = data["high"].rolling(50, min_periods=1).max()
    data["rolling_50_low"] = data["low"].rolling(50, min_periods=1).min()
    data["prior_20_high"] = data["high"].shift(1).rolling(20, min_periods=1).max()
    data["new_20_high_recent"] = (data["high"] >= data["prior_20_high"]).rolling(20, min_periods=1).max().fillna(0).astype(bool)
    data["recent_20_high"] = data["high"].shift(1).rolling(20, min_periods=1).max()
    return data


def market_filter(row: dict[str, Any]) -> bool:
    return (
        row["close"] > row["sma200"]
        and math.isfinite(row["sma200_slope20"])
        and row["sma200_slope20"] >= 0
        and row["close"] > row["sma50"]
        and row["sma20"] >= row["sma50"] * 0.98
    )


def pullback_signal(row: dict[str, Any], params: StrategyParams) -> tuple[bool, str]:
    if not market_filter(row) or not bool(row["new_20_high_recent"]):
        return False, ""
    recent_high = float(row["recent_20_high"])
    if not math.isfinite(recent_high) or recent_high <= 0:
        return False, ""
    pullback_pct = 1.0 - float(row["close"]) / recent_high
    if pullback_pct < params.pullback_min or pullback_pct > params.pullback_max:
        return False, ""
    atr = float(row["atr14"])
    if not math.isfinite(atr) or atr <= 0:
        return False, ""
    support_ok = (
        float(row["low"]) <= float(row["sma20"]) * 1.01
        or abs(float(row["low"]) - float(row["rolling_10_low"])) <= 0.5 * atr
        or abs(float(row["low"]) - float(row["prior_20_high"])) <= 1.0 * atr
    )
    if not support_ok:
        return False, ""
    if float(row["high"]) == float(row["low"]):
        return False, ""
    close_position = (float(row["close"]) - float(row["low"])) / (float(row["high"]) - float(row["low"]))
    confirmation_ok = (
        float(row["close"]) > float(row["open"])
        and float(row["close"]) > float(row["previous_close"])
        and float(row["close"]) > float(row["sma20"])
        and close_position >= params.close_position_threshold
        and float(row["low"]) >= float(row["rolling_10_low"]) - 0.5 * atr
    )
    if not confirmation_ok:
        return False, ""
    return True, f"趋势向上，回踩{pullback_pct:.2%}后收盘站稳"


def max_drawdown(values: np.ndarray) -> float:
    return float((values / np.maximum.accumulate(values) - 1.0).min() * 100.0)


def cagr(values: np.ndarray, dates: list[dt.date]) -> float:
    if len(values) < 2:
        return math.nan
    years = (dates[-1] - dates[0]).days / 365.25
    if years <= 0 or values[0] <= 0:
        return math.nan
    return float(((values[-1] / values[0]) ** (1.0 / years) - 1.0) * 100.0)


def yearly_extremes(values: np.ndarray, dates: list[dt.date]) -> tuple[str, str]:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "equity": values})
    frame["ret"] = frame["equity"].pct_change().fillna(0.0)
    yearly = frame.groupby(frame["date"].dt.year)["ret"].apply(lambda item: (1.0 + item).prod() - 1.0)
    if yearly.empty:
        return "N/A", "N/A"
    return f"{int(yearly.idxmax())}: {yearly.max() * 100:.2f}%", f"{int(yearly.idxmin())}: {yearly.min() * 100:.2f}%"


def summary_metrics(values: np.ndarray, dates: list[dt.date]) -> dict[str, Any]:
    returns = values[1:] / values[:-1] - 1.0
    daily_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    volatility = daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0
    sharpe = float(np.mean(returns) / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily_std > 0 else math.nan
    mdd = max_drawdown(values)
    cagr_value = cagr(values, dates)
    best_year, worst_year = yearly_extremes(values, dates)
    return {
        "cumulative_return_pct": float((values[-1] / values[0] - 1.0) * 100.0),
        "CAGR_pct": cagr_value,
        "max_drawdown_pct": mdd,
        "volatility_pct": volatility,
        "Sharpe": sharpe,
        "Calmar": cagr_value / abs(mdd) if mdd < 0 and math.isfinite(cagr_value) else math.nan,
        "best_year": best_year,
        "worst_year": worst_year,
    }


def buy_and_hold(frame: pd.DataFrame) -> dict[str, Any]:
    dates = [item.date() for item in frame["date"].dt.to_pydatetime()]
    open_prices = frame["open"].to_numpy(dtype=float)
    close_prices = frame["close"].to_numpy(dtype=float)
    trade_value = INITIAL_CAPITAL / (1.0 + TRANSACTION_COST_RATE)
    units = trade_value / open_prices[0]
    values = units * close_prices
    return {"dates": dates, "values": values, "metrics": summary_metrics(values, dates), "trade_count": 1}


def close_trade(
    trade: dict[str, Any],
    exit_signal_index: int,
    exit_index: int,
    exit_price: float,
    exit_reason: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    gross_exit_value = trade["units"] * exit_price
    exit_cost = gross_exit_value * TRANSACTION_COST_RATE
    net_exit_value = gross_exit_value - exit_cost
    entry_price = trade["entry_price"]
    initial_r = trade["R"]
    holding_days = exit_index - trade["entry_index"]
    trade_return = net_exit_value / trade["entry_value_with_cost"] - 1.0
    trade_r = (exit_price - entry_price) / initial_r if initial_r > 0 else math.nan
    return {
        "entry_signal_date": trade["entry_signal_date"],
        "entry_date": trade["entry_date"],
        "entry_price": entry_price,
        "entry_reason": trade["entry_reason"],
        "SMA20": trade["sma20"],
        "SMA50": trade["sma50"],
        "SMA200": trade["sma200"],
        "ATR14": trade["atr14"],
        "recent_20_high": trade["recent_20_high"],
        "pullback_pct": trade["pullback_pct"] * 100.0,
        "structure_low": trade["structure_low"],
        "initial_stop": trade["initial_stop"],
        "R": initial_r,
        "exit_signal_date": frame.iloc[exit_signal_index]["date"].date().isoformat(),
        "exit_date": frame.iloc[exit_index]["date"].date().isoformat(),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_days": holding_days,
        "trade_return": trade_return * 100.0,
        "trade_R_multiple": trade_r,
        "max_favorable_excursion": trade["mfe"] * 100.0,
        "max_adverse_excursion": trade["mae"] * 100.0,
        "pnl_amount": net_exit_value - trade["entry_value_with_cost"],
    }


def simulate_pullback(frame: pd.DataFrame, params: StrategyParams) -> dict[str, Any]:
    dates = [item.date() for item in frame["date"].dt.to_pydatetime()]
    open_prices = frame["open"].to_numpy(dtype=float)
    close_prices = frame["close"].to_numpy(dtype=float)
    high_prices = frame["high"].to_numpy(dtype=float)
    low_prices = frame["low"].to_numpy(dtype=float)
    values: list[float] = []
    exposure: list[float] = []
    trade_logs: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    cash = INITIAL_CAPITAL
    units = 0.0
    in_position = False
    trade: dict[str, Any] | None = None
    records = frame.to_dict("records")

    for index, row in enumerate(records):
        open_price = float(open_prices[index])
        close_price = float(close_prices[index])

        if pending is not None:
            if pending["action"] == "buy" and not in_position:
                entry_price = open_price
                initial_stop = float(pending["initial_stop"])
                initial_r = entry_price - initial_stop
                risk_pct = initial_r / entry_price if entry_price > 0 else math.inf
                if initial_r > 0 and 0.01 <= risk_pct <= 0.08:
                    trade_value = cash / (1.0 + TRANSACTION_COST_RATE)
                    cost = trade_value * TRANSACTION_COST_RATE
                    units = trade_value / entry_price
                    cash = cash - trade_value - cost
                    in_position = True
                    trade = {
                        "entry_signal_date": dates[int(pending["signal_index"])].isoformat(),
                        "entry_date": dates[index].isoformat(),
                        "entry_index": index,
                        "entry_price": entry_price,
                        "entry_reason": pending["reason"],
                        "entry_value_with_cost": trade_value + cost,
                        "units": units,
                        "initial_stop": initial_stop,
                        "R": initial_r,
                        "structure_low": pending["structure_low"],
                        "sma20": pending["sma20"],
                        "sma50": pending["sma50"],
                        "sma200": pending["sma200"],
                        "atr14": pending["atr14"],
                        "recent_20_high": pending["recent_20_high"],
                        "pullback_pct": pending["pullback_pct"],
                        "mfe": 0.0,
                        "mae": 0.0,
                    }
            elif pending["action"] == "sell" and in_position and trade is not None:
                log = close_trade(trade, int(pending["signal_index"]), index, open_price, pending["reason"], frame)
                trade_logs.append(log)
                gross_exit_value = units * open_price
                cash = gross_exit_value - gross_exit_value * TRANSACTION_COST_RATE
                units = 0.0
                in_position = False
                trade = None
            pending = None

        if in_position and trade is not None:
            trade["mfe"] = max(trade["mfe"], high_prices[index] / trade["entry_price"] - 1.0)
            trade["mae"] = min(trade["mae"], low_prices[index] / trade["entry_price"] - 1.0)
            equity = units * close_price + cash
        else:
            equity = cash
        values.append(equity)
        exposure.append(100.0 if in_position else 0.0)

        if index >= len(records) - 1:
            continue

        if in_position and trade is not None:
            holding_days = index - trade["entry_index"]
            exit_reason = ""
            if close_price < trade["initial_stop"]:
                exit_reason = "止损退出"
            elif close_price < float(row["sma50"]) and float(row["sma20"]) < float(row["sma50"]):
                exit_reason = "趋势破坏退出"
            elif close_price >= trade["entry_price"] + params.take_profit_r * trade["R"]:
                exit_reason = f"达到{params.take_profit_r:g}R止盈"
            elif equity > trade["entry_value_with_cost"] and close_price < float(row["sma10"]):
                exit_reason = "动能衰减退出"
            elif holding_days >= params.max_holding_days:
                exit_reason = "时间退出"
            if exit_reason:
                pending = {"action": "sell", "reason": exit_reason, "signal_index": index}
            continue

        signal, reason = pullback_signal(row, params)
        if signal:
            structure_low = float(frame.iloc[max(0, index - 4) : index + 1]["low"].min())
            initial_stop = structure_low - params.stop_buffer_atr * float(row["atr14"])
            recent_high = float(row["recent_20_high"])
            pending = {
                "action": "buy",
                "reason": reason,
                "signal_index": index,
                "structure_low": structure_low,
                "initial_stop": initial_stop,
                "sma20": float(row["sma20"]),
                "sma50": float(row["sma50"]),
                "sma200": float(row["sma200"]),
                "atr14": float(row["atr14"]),
                "recent_20_high": recent_high,
                "pullback_pct": 1.0 - close_price / recent_high if recent_high > 0 else math.nan,
            }

    values_array = np.array(values, dtype=float)
    return {
        "dates": dates,
        "values": values_array,
        "exposure": np.array(exposure, dtype=float),
        "metrics": summary_metrics(values_array, dates),
        "trades": trade_logs,
    }


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": math.nan,
            "average_win": math.nan,
            "average_loss": math.nan,
            "profit_factor": math.nan,
            "average_holding_days": math.nan,
            "max_consecutive_losses": 0,
        }
    pnl = np.array([trade["pnl_amount"] for trade in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    max_losses = 0
    current = 0
    for item in pnl:
        if item < 0:
            current += 1
            max_losses = max(max_losses, current)
        else:
            current = 0
    return {
        "trade_count": len(trades),
        "win_rate": float((pnl > 0).mean() * 100.0),
        "average_win": float(wins.mean()) if len(wins) else math.nan,
        "average_loss": float(losses.mean()) if len(losses) else math.nan,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() < 0 else math.nan,
        "average_holding_days": float(np.mean([trade["holding_days"] for trade in trades])),
        "max_consecutive_losses": max_losses,
    }


def curve_frame(symbol: str, label: str, result: dict[str, Any]) -> pd.DataFrame:
    start = result["values"][0]
    return pd.DataFrame(
        {
            "symbol": symbol,
            "strategy_label": label,
            "date": pd.to_datetime(result["dates"]),
            "equity": result["values"],
            "return_pct": (result["values"] / start - 1.0) * 100.0,
            "exposure_pct": result.get("exposure", np.full_like(result["values"], 100.0, dtype=float)),
        }
    )


def period_return(curve: pd.DataFrame, start: str | None, end: str | None) -> float:
    subset = curve.copy()
    if start is not None:
        subset = subset[subset["date"] >= pd.Timestamp(start)]
    if end is not None:
        subset = subset[subset["date"] <= pd.Timestamp(end)]
    if len(subset) < 2:
        return math.nan
    return float((subset.iloc[-1]["equity"] / subset.iloc[0]["equity"] - 1.0) * 100.0)


def metric_row(symbol: str, data: pd.DataFrame, strategy: dict[str, Any], buy_hold_result: dict[str, Any], params: StrategyParams) -> dict[str, Any]:
    stats = trade_stats(strategy["trades"])
    metrics = strategy["metrics"]
    buy_metrics = buy_hold_result["metrics"]
    time_in_market = float(np.mean(strategy["exposure"] > 0) * 100.0)
    return {
        "symbol": symbol,
        "param_id": params.param_id,
        "param_label": params.label,
        "data_start_date": data["date"].min().date().isoformat(),
        "data_end_date": data["date"].max().date().isoformat(),
        "data_rows": len(data),
        "data_source": SYMBOL_SOURCE[symbol],
        "whether_adjusted_price_used": "否，使用本地 OHLC 原始字段",
        "cumulative_return": metrics["cumulative_return_pct"],
        "CAGR": metrics["CAGR_pct"],
        "max_drawdown": metrics["max_drawdown_pct"],
        "volatility": metrics["volatility_pct"],
        "Sharpe": metrics["Sharpe"],
        "Calmar": metrics["Calmar"],
        "time_in_market": time_in_market,
        "best_year": metrics["best_year"],
        "worst_year": metrics["worst_year"],
        "buy_hold_cumulative_return": buy_metrics["cumulative_return_pct"],
        "buy_hold_CAGR": buy_metrics["CAGR_pct"],
        "buy_hold_max_drawdown": buy_metrics["max_drawdown_pct"],
        "buy_hold_Calmar": buy_metrics["Calmar"],
        "strategy_minus_buy_hold_CAGR": metrics["CAGR_pct"] - buy_metrics["CAGR_pct"],
        "strategy_minus_buy_hold_max_drawdown": abs(buy_metrics["max_drawdown_pct"]) - abs(metrics["max_drawdown_pct"]),
        "strategy_minus_buy_hold_Calmar": metrics["Calmar"] - buy_metrics["Calmar"],
        **stats,
    }


def stability_grid() -> list[StrategyParams]:
    values: dict[str, StrategyParams] = {}
    for pullback_min, pullback_max, threshold, take_profit, holding_days in itertools.product(
        [0.02, 0.03, 0.05],
        [0.10, 0.12, 0.15],
        [0.60, 0.70, 0.80],
        [1.5, 2.0, 2.5],
        [10, 15, 20],
    ):
        if pullback_min >= pullback_max:
            continue
        item = StrategyParams(
            pullback_min=pullback_min,
            pullback_max=pullback_max,
            close_position_threshold=threshold,
            take_profit_r=take_profit,
            max_holding_days=holding_days,
        )
        values[item.param_id] = item
    return list(values.values())


def build_period_rows(curves: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (symbol, strategy_label), curve in curves.groupby(["symbol", "strategy_label"]):
        for period, (start, end) in PERIODS.items():
            rows.append(
                {
                    "symbol": symbol,
                    "strategy_label": strategy_label,
                    "period": period,
                    "return_pct": period_return(curve, start, end),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def plot_equity(curves: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axes = plt.subplots(len(SYMBOL_FILES), 1, figsize=(15, 20), sharex=False)
    for axis, symbol in zip(axes, SYMBOL_FILES):
        subset = curves[curves["symbol"] == symbol]
        for label, part in subset.groupby("strategy_label"):
            axis.plot(part["date"], part["return_pct"], lw=2 if label == "Buy and Hold" else 1.6, label=label)
        axis.set_title(f"{symbol} 收益曲线")
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8)
    fig.tight_layout()
    path = charts_dir / "equity_curves.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_drawdown(curves: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axes = plt.subplots(len(SYMBOL_FILES), 1, figsize=(15, 20), sharex=False)
    for axis, symbol in zip(axes, SYMBOL_FILES):
        subset = curves[curves["symbol"] == symbol]
        for label, part in subset.groupby("strategy_label"):
            values = part["equity"].to_numpy(dtype=float)
            drawdown = values / np.maximum.accumulate(values) - 1.0
            axis.plot(part["date"], drawdown * 100.0, lw=2 if label == "Buy and Hold" else 1.6, label=label)
        axis.set_title(f"{symbol} 回撤曲线")
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        axis.grid(True, alpha=0.25)
    fig.tight_layout()
    path = charts_dir / "drawdown_curves.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_symbol_bars(summary: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axis = plt.subplots(figsize=(12, 7))
    data = summary.sort_values("strategy_minus_buy_hold_CAGR")
    axis.barh(data["symbol"], data["strategy_minus_buy_hold_CAGR"], color=["#16a34a" if value > 0 else "#dc2626" for value in data["strategy_minus_buy_hold_CAGR"]])
    axis.axvline(0, color="#64748b", lw=1)
    axis.set_title("主参数：相对买入持有年化差")
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}%"))
    axis.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    path = charts_dir / "strategy_vs_buy_hold_bars.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_stability(stability: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axis = plt.subplots(figsize=(12, 7))
    grouped = stability.groupby("param_label").agg(avg_adv=("strategy_minus_buy_hold_CAGR", "mean"), avg_trades=("trade_count", "mean")).reset_index()
    grouped = grouped.sort_values("avg_adv", ascending=False).head(30).sort_values("avg_adv")
    axis.barh(grouped["param_label"], grouped["avg_adv"], color=["#16a34a" if value > 0 else "#dc2626" for value in grouped["avg_adv"]])
    axis.axvline(0, color="#64748b", lw=1)
    axis.set_title("参数稳定性：平均年化优势")
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}%"))
    fig.tight_layout()
    path = charts_dir / "parameter_stability.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def render_table(frame: pd.DataFrame, columns: list[tuple[str, str]], limit: int | None = None) -> str:
    data = frame.head(limit) if limit else frame
    parts = ["<table><thead><tr>"]
    for _, label in columns:
        parts.append(f"<th>{html.escape(label)}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in data.iterrows():
        parts.append("<tr>")
        for key, _ in columns:
            value = row.get(key, "")
            css = ""
            if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
                lower_key = key.lower()
                if any(item in lower_key for item in ["cagr", "calmar", "return", "profit", "factor", "rate"]) and value > 0:
                    css = "good"
                if any(item in lower_key for item in ["cagr", "calmar", "return", "profit", "factor", "rate"]) and value < 0:
                    css = "bad"
                if any(item in lower_key for item in ["count", "days", "rows", "losses"]):
                    text = f"{value:.0f}"
                elif any(item in lower_key for item in ["amount", "win", "loss"]) and abs(value) >= 1000:
                    text = f"{value:,.0f}"
                else:
                    text = f"{value:.2f}"
            else:
                text = "" if pd.isna(value) else str(value)
            parts.append(f"<td class='{css}'>{html.escape(text)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def build_answers(summary: pd.DataFrame, stability: pd.DataFrame) -> list[str]:
    improved = int((summary["strategy_minus_buy_hold_CAGR"] > 0).sum())
    lowered_dd = int((summary["strategy_minus_buy_hold_max_drawdown"] > 0).sum())
    improved_calmar = int((summary["strategy_minus_buy_hold_Calmar"] > 0).sum())
    best = summary.sort_values(["strategy_minus_buy_hold_CAGR", "strategy_minus_buy_hold_Calmar"], ascending=False).iloc[0]
    avg_time = float(summary["time_in_market"].mean())
    avg_trade_count = float(summary["trade_count"].mean())
    stability_avg = stability.groupby("param_label")["strategy_minus_buy_hold_CAGR"].mean()
    stable_positive = int((stability_avg > 0).sum())
    trend_effective = summary.sort_values("strategy_minus_buy_hold_CAGR", ascending=False).iloc[0]
    too_few = int((summary["trade_count"] < 5).sum())
    too_many = int((summary["trade_count"] > 100).sum())
    avg_period = stability.groupby("param_label").agg(
        avg_adv=("strategy_minus_buy_hold_CAGR", "mean"),
        min_adv=("strategy_minus_buy_hold_CAGR", "min"),
        avg_pf=("profit_factor", "mean"),
    )
    overfit_note = "存在明显过拟合风险" if stable_positive <= max(1, len(stability_avg) // 10) else "参数稳定性尚可"
    return [
        f"1. 是否提高 CAGR：{improved}/5 个品种提高，平均年化差 {summary['strategy_minus_buy_hold_CAGR'].mean():.2f} 个百分点。",
        f"2. 是否降低最大回撤：{lowered_dd}/5 个品种降低最大回撤，说明空仓能控回撤，但不等于提高收益。",
        f"3. 是否提高 Calmar：{improved_calmar}/5 个品种提高 Calmar。",
        f"4. 是否只是减少持仓时间导致收益下降：平均在场时间 {avg_time:.2f}%，平均交易次数 {avg_trade_count:.1f}；若多数品种年化显著跑输，主要原因是长期不在场。",
        f"5. 是否趋势市场有效、震荡市场失效：主参数最好的品种是 {trend_effective.symbol}，但仍需看阶段表现；若 2023-2025 牛市跑输，说明趋势市场也未吃到主升段。",
        f"6. 是否交易次数太少或太多：交易少于 5 笔的品种 {too_few} 个，超过 100 笔的品种 {too_many} 个。",
        f"7. 是否存在明显过拟合迹象：{overfit_note}；完整网格中 {stable_positive}/{len(stability_avg)} 组参数平均年化优势为正。",
        f"8. 是否比简单 buy and hold 更值得：如果没有多数品种同时改善 CAGR、回撤和 Calmar，则不值得替代买入持有。",
        f"9. 哪些品种更适合：当前最适合 {best.symbol}，年化优势 {best.strategy_minus_buy_hold_CAGR:.2f} 个百分点，Calmar 差 {best.strategy_minus_buy_hold_Calmar:.2f}。",
        f"10. 是否值得进入下一轮研究：只有当参数网格中多数组合为正且至少 3 个品种改善 Calmar 才值得；当前先按报告结果判断。",
    ]


def render_report(
    out_dir: Path,
    manifest: pd.DataFrame,
    summary: pd.DataFrame,
    trades: pd.DataFrame,
    stability: pd.DataFrame,
    period_frame: pd.DataFrame,
    chart_paths: list[Path],
) -> None:
    summary_columns = [
        ("symbol", "品种"),
        ("data_start_date", "开始"),
        ("data_end_date", "结束"),
        ("CAGR", "策略年化"),
        ("buy_hold_CAGR", "买入持有年化"),
        ("strategy_minus_buy_hold_CAGR", "年化差"),
        ("max_drawdown", "策略最大回撤"),
        ("buy_hold_max_drawdown", "买入持有最大回撤"),
        ("strategy_minus_buy_hold_max_drawdown", "回撤改善"),
        ("Calmar", "策略Calmar"),
        ("strategy_minus_buy_hold_Calmar", "Calmar差"),
        ("trade_count", "交易数"),
        ("win_rate", "胜率"),
        ("profit_factor", "Profit Factor"),
        ("average_holding_days", "平均持仓天数"),
        ("time_in_market", "在场时间"),
    ]
    manifest_columns = [
        ("symbol", "品种"),
        ("data_source", "数据源"),
        ("data_start_date", "开始"),
        ("data_end_date", "结束"),
        ("data_rows", "行数"),
        ("whether_adjusted_price_used", "是否复权"),
    ]
    trade_columns = [
        ("symbol", "品种"),
        ("entry_signal_date", "信号日"),
        ("entry_date", "买入日"),
        ("entry_price", "买入价"),
        ("exit_date", "卖出日"),
        ("exit_price", "卖出价"),
        ("exit_reason", "卖出原因"),
        ("holding_days", "持仓天数"),
        ("trade_return", "交易收益%"),
        ("trade_R_multiple", "R倍数"),
        ("max_favorable_excursion", "最大顺向波动%"),
        ("max_adverse_excursion", "最大逆向波动%"),
    ]
    stability_columns = [
        ("symbol", "品种"),
        ("param_label", "参数"),
        ("CAGR", "年化"),
        ("max_drawdown", "最大回撤"),
        ("Calmar", "Calmar"),
        ("trade_count", "交易数"),
        ("win_rate", "胜率"),
        ("profit_factor", "Profit Factor"),
        ("strategy_minus_buy_hold_CAGR", "年化差"),
        ("strategy_minus_buy_hold_max_drawdown", "回撤改善"),
    ]
    period_columns = [
        ("symbol", "品种"),
        ("strategy_label", "策略"),
        ("period", "阶段"),
        ("return_pct", "收益"),
    ]
    answers = build_answers(summary, stability)
    images = "\n".join(f'<section class="card"><h2>{html.escape(path.stem)}</h2><img src="charts/{html.escape(path.name)}"></section>' for path in chart_paths)
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>上升趋势回踩站稳策略回测</title>
  <style>
    body {{ margin:0; background:#f5f7fb; color:#111827; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; }}
    header {{ background:#111827; color:white; padding:28px 34px; }}
    h1 {{ margin:0 0 8px; font-size:28px; }}
    .wrap {{ padding:24px 34px 44px; }}
    .card {{ background:white; border:1px solid #dde3ee; border-radius:8px; margin-bottom:18px; overflow:hidden; box-shadow:0 6px 18px rgba(15,23,42,.06); }}
    h2 {{ margin:0; padding:16px 18px; border-bottom:1px solid #e5e7eb; font-size:19px; }}
    .pad {{ padding:18px; }}
    .scroll {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:8px 10px; border-bottom:1px solid #e5e7eb; text-align:right; white-space:nowrap; }}
    th:first-child,td:first-child {{ text-align:left; }}
    th {{ background:#f8fafc; color:#334155; }}
    .good {{ color:#15803d; font-weight:700; }}
    .bad {{ color:#dc2626; font-weight:700; }}
    img {{ display:block; width:100%; height:auto; }}
    li {{ margin:7px 0; }}
  </style>
</head>
<body>
<header>
  <h1>上升趋势回踩站稳策略回测</h1>
  <div>只做多，不加杠杆，不轮动；信号收盘后生成，次日开盘成交；买卖各扣 0.14% 成本。</div>
</header>
<div class="wrap">
  <section class="card"><h2>结论摘要</h2><div class="pad"><ul>
    {''.join(f'<li>{html.escape(answer)}</li>' for answer in answers)}
  </ul></div></section>
  <section class="card"><h2>输入数据</h2><div class="scroll">{render_table(manifest, manifest_columns)}</div></section>
  <section class="card"><h2>主参数结果</h2><div class="scroll">{render_table(summary, summary_columns)}</div></section>
  <section class="card"><h2>交易日志</h2><div class="scroll">{render_table(trades, trade_columns, limit=120)}</div></section>
  <section class="card"><h2>参数稳定性</h2><div class="scroll">{render_table(stability, stability_columns, limit=200)}</div></section>
  <section class="card"><h2>阶段表现</h2><div class="scroll">{render_table(period_frame, period_columns, limit=120)}</div></section>
  {images}
</div>
</body>
</html>
"""
    (out_dir / "backtest_report.html").write_text(html_doc, encoding="utf-8")


def main() -> None:
    args = parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    unknown = [symbol for symbol in symbols if symbol not in SYMBOL_FILES]
    if unknown:
        raise SystemExit(f"Unknown symbols: {', '.join(unknown)}")

    frames = {symbol: load_ohlc(SYMBOL_FILES[symbol]) for symbol in symbols}
    summary_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    curve_rows: list[pd.DataFrame] = []

    for symbol, frame in frames.items():
        manifest_rows.append(
            {
                "symbol": symbol,
                "data_start_date": frame["date"].min().date().isoformat(),
                "data_end_date": frame["date"].max().date().isoformat(),
                "data_rows": len(frame),
                "data_source": str(SYMBOL_FILES[symbol]),
                "whether_adjusted_price_used": "否，使用本地 OHLC 原始字段",
            }
        )
        hold = buy_and_hold(frame)
        strategy = simulate_pullback(frame, DEFAULT_PARAMS)
        summary_rows.append(metric_row(symbol, frame, strategy, hold, DEFAULT_PARAMS))
        for trade in strategy["trades"]:
            all_trade_rows.append({"symbol": symbol, **trade})
        curve_rows.append(curve_frame(symbol, "Buy and Hold", hold))
        curve_rows.append(curve_frame(symbol, "Pullback Price Action Strategy", strategy))

        if not args.skip_stability:
            for params in stability_grid():
                result = simulate_pullback(frame, params)
                stability_rows.append(metric_row(symbol, frame, result, hold, params))

    summary = pd.DataFrame(summary_rows).sort_values("strategy_minus_buy_hold_CAGR", ascending=False)
    trades = pd.DataFrame(all_trade_rows)
    stability = pd.DataFrame(stability_rows)
    manifest = pd.DataFrame(manifest_rows)
    curves = pd.concat(curve_rows, ignore_index=True)
    period_frame = pd.DataFrame(build_period_rows(curves))

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    avg_adv = float(summary["strategy_minus_buy_hold_CAGR"].mean()) if not summary.empty else 0.0
    out_dir = REPORTS / f"pullback-price-action-test_{timestamp}_avgadv{avg_adv:+.2f}"
    tables_dir = out_dir / "tables"
    charts_dir = out_dir / "charts"
    tables_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    write_csv(tables_dir / "symbol_summary.csv", summary)
    write_csv(tables_dir / "trade_log.csv", trades)
    write_csv(tables_dir / "parameter_stability.csv", stability)
    write_csv(tables_dir / "period_performance.csv", period_frame)
    write_csv(tables_dir / "equity_curves.csv", curves)
    write_csv(tables_dir / "input_manifest.csv", manifest)

    chart_paths = [
        plot_equity(curves, charts_dir),
        plot_drawdown(curves, charts_dir),
        plot_symbol_bars(summary, charts_dir),
        plot_stability(stability, charts_dir) if not stability.empty else charts_dir / "parameter_stability.png",
    ]
    render_report(out_dir, manifest, summary, trades, stability, period_frame, chart_paths)

    print("HTML report:", out_dir / "backtest_report.html")
    print("Charts dir:", charts_dir)
    print("Tables dir:", tables_dir)
    print("Average strategy-minus-buy-hold CAGR:", f"{avg_adv:.4f}", "pct points")


if __name__ == "__main__":
    main()
