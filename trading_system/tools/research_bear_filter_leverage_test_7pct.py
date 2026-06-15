from __future__ import annotations

import argparse
import datetime as dt
import html
import math
from dataclasses import dataclass, field
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
NORMAL_EXPOSURE = base.NORMAL_EXPOSURE
MAX_TARGET_EXPOSURE = base.MAX_TARGET_EXPOSURE
LOOKBACK_HIGH_DAYS = base.LOOKBACK_HIGH_DAYS
TRADING_DAYS_PER_YEAR = base.TRADING_DAYS_PER_YEAR

DATASETS = {
    "US500": base.ROOT / "outputs" / "yahoo_US500_GSPC_1d_19950101_20260615.csv",
    "USTEC": base.ROOT / "outputs" / "yahoo_USTEC_NDX_1d_19950101_20260615.csv",
    "JP225": base.ROOT / "outputs" / "yahoo_JP225_N225_1d_19950101_20260615.csv",
}

PREVIOUS_TOP10_SUMMARY = (
    base.REPORTS
    / "top10-exit-long-yahoo-7pct_us500-ustec-jp225_avgadv-0.30_20260615-192751"
    / "tables"
    / "top10_strategy_summary.csv"
)

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
class EntryFilter:
    filter_id: str
    label: str
    mode: str


@dataclass(frozen=True)
class ExitRule:
    exit_id: str
    label: str
    mode: str


@dataclass
class FilterState:
    armed: bool = False
    low_since_armed: float = math.inf


@dataclass
class CycleState:
    cycle_id: int
    entry_signal_date: str
    leverage_entry_date: str
    entry_price: float
    entry_equity: float
    entry_reason: str
    entry_drawdown_pct: float
    leveraged_days: int = 0
    high_equity: float = 0.0
    exposure_sum: float = 0.0
    financing_interest: float = 0.0
    transaction_cost: float = 0.0
    buy_value: float = 0.0
    sell_value: float = 0.0
    interest_repaid: float = 0.0
    principal_repaid: float = 0.0
    max_actual_exposure_pct: float = 0.0
    max_debt_principal: float = 0.0
    half_delevered: bool = False
    events: list[str] = field(default_factory=list)


def entry_filters() -> list[EntryFilter]:
    return [
        EntryFilter("F0_no_filter", "F0 无过滤对照", "no_filter"),
        EntryFilter("F1_long_trend", "F1 长期趋势过滤", "long_trend"),
        EntryFilter("F2_rebound_sma50", "F2 右侧确认过滤", "rebound_sma50"),
        EntryFilter("F3_monthly_trend", "F3 月线趋势过滤", "monthly_trend"),
        EntryFilter("F4_strict_bear_filter", "F4 严格熊市过滤", "strict_bear"),
    ]


def exit_rules() -> list[ExitRule]:
    return [
        ExitRule("X1_profit_40", "X1 涨40%一次性全降", "profit_40"),
        ExitRule("X2_time_252", "X2 持杠杆252日全降", "time_252"),
        ExitRule("X3_trend_break", "X3 趋势恶化全降", "trend_break"),
        ExitRule("X4_profit30_then_time_or_trend", "X4 涨30%降到110%，再按时间或趋势全降", "mixed"),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bear-market filter test for deep drawdown leverage.")
    parser.add_argument("--symbols", default=",".join(DATASETS.keys()), help="Comma-separated symbols to test.")
    return parser.parse_args()


def load_yahoo_daily(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    column_map = {column.lower(): column for column in raw.columns}
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[column_map.get("date", "Date")]),
            "open": pd.to_numeric(raw[column_map.get("open", "Open")], errors="coerce"),
            "high": pd.to_numeric(raw[column_map.get("high", "High")], errors="coerce"),
            "low": pd.to_numeric(raw[column_map.get("low", "Low")], errors="coerce"),
            "close": pd.to_numeric(raw[column_map.get("close", "Close")], errors="coerce"),
        }
    )
    frame = (
        frame.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates("date")
        .reset_index(drop=True)
    )
    frame["rolling_high"] = frame["close"].rolling(LOOKBACK_HIGH_DAYS, min_periods=1).max()
    frame["drawdown_from_high"] = frame["close"] / frame["rolling_high"] - 1.0
    frame["daily_return"] = frame["close"].pct_change().fillna(0.0)
    frame["sma50"] = frame["close"].rolling(50, min_periods=1).mean()
    frame["sma200"] = frame["close"].rolling(200, min_periods=1).mean()
    frame["sma200_slope20"] = frame["sma200"] / frame["sma200"].shift(20) - 1.0
    frame["sma200_slope60"] = frame["sma200"] / frame["sma200"].shift(60) - 1.0
    frame["momentum_12m"] = frame["close"] / frame["close"].shift(252) - 1.0

    monthly = frame.set_index("date")["close"].resample("ME").last().to_frame("month_close")
    monthly["ma10m"] = monthly["month_close"].rolling(10, min_periods=1).mean()
    monthly["ma10m_slope3"] = monthly["ma10m"] / monthly["ma10m"].shift(3) - 1.0
    monthly = monthly.reset_index()[["date", "ma10m", "ma10m_slope3"]]
    frame = pd.merge_asof(frame.sort_values("date"), monthly.sort_values("date"), on="date", direction="backward")
    return frame


def period_return(curve: pd.DataFrame, start: str | None, end: str | None) -> float:
    subset = curve.copy()
    if start is not None:
        subset = subset[subset["date"] >= pd.Timestamp(start)]
    if end is not None:
        subset = subset[subset["date"] <= pd.Timestamp(end)]
    if len(subset) < 2:
        return math.nan
    return float((subset.iloc[-1]["equity"] / subset.iloc[0]["equity"] - 1.0) * 100)


def period_max_drawdown(curve: pd.DataFrame, start: str | None, end: str | None) -> float:
    subset = curve.copy()
    if start is not None:
        subset = subset[subset["date"] >= pd.Timestamp(start)]
    if end is not None:
        subset = subset[subset["date"] <= pd.Timestamp(end)]
    if len(subset) < 2:
        return math.nan
    values = subset["equity"].to_numpy(dtype=float)
    return float((values / np.maximum.accumulate(values) - 1.0).min() * 100)


def entry_filter_passes(rule: EntryFilter, row: dict[str, Any], state: FilterState, close_price: float) -> tuple[bool, str]:
    drawdown = float(row["drawdown_from_high"])
    if drawdown > -0.30:
        if close_price >= float(row["rolling_high"]) * (1.0 - 1e-12):
            state.armed = False
            state.low_since_armed = math.inf
        return False, ""

    if rule.mode == "no_filter":
        return True, "回撤达到30%，无过滤直接加杠杆"

    if rule.mode == "long_trend":
        passes = (
            math.isfinite(float(row["sma200_slope60"]))
            and float(row["sma200_slope60"]) > 0
            and math.isfinite(float(row["momentum_12m"]))
            and float(row["momentum_12m"]) > 0
        )
        return passes, "回撤30%且长期趋势过滤通过"

    if rule.mode == "rebound_sma50":
        state.armed = True
        state.low_since_armed = min(state.low_since_armed, close_price)
        passes = close_price >= state.low_since_armed * 1.10 and close_price > float(row["sma50"])
        return passes, "回撤30%后反弹10%且站上50日均线"

    if rule.mode == "monthly_trend":
        passes = (
            math.isfinite(float(row["ma10m"]))
            and math.isfinite(float(row["ma10m_slope3"]))
            and close_price > float(row["ma10m"])
            and float(row["ma10m_slope3"]) > 0
        )
        return passes, "回撤30%且月线趋势过滤通过"

    if rule.mode == "strict_bear":
        passes = (
            close_price > float(row["sma200"])
            and math.isfinite(float(row["sma200_slope60"]))
            and float(row["sma200_slope60"]) > 0
            and math.isfinite(float(row["momentum_12m"]))
            and float(row["momentum_12m"]) > 0
        )
        return passes, "回撤30%且严格熊市过滤通过"

    return False, ""


def evaluate_exit(rule: ExitRule, cycle: CycleState, row: dict[str, Any], close_price: float, current_target: float) -> tuple[float | None, str]:
    asset_return = close_price / cycle.entry_price - 1.0
    trend_break = close_price < float(row["sma200"]) and math.isfinite(float(row["sma200_slope20"])) and float(row["sma200_slope20"]) <= 0

    if rule.mode == "profit_40" and asset_return >= 0.40:
        return NORMAL_EXPOSURE, "杠杆周期涨幅达到40%，全降"
    if rule.mode == "time_252" and cycle.leveraged_days >= 252:
        return NORMAL_EXPOSURE, "杠杆持有满252日，全降"
    if rule.mode == "trend_break" and trend_break:
        return NORMAL_EXPOSURE, "收盘价跌破200日均线且200日均线20日斜率小于等于0，全降"
    if rule.mode == "mixed":
        if trend_break:
            return NORMAL_EXPOSURE, "混合退出：趋势恶化，全降"
        if cycle.leveraged_days >= 252:
            return NORMAL_EXPOSURE, "混合退出：杠杆持有满252日，全降"
        if asset_return >= 0.30 and not cycle.half_delevered and current_target > 1.10:
            cycle.half_delevered = True
            return 1.10, "混合退出：涨幅达到30%，降到110%"
    return None, ""


def finish_cycle(cycle: CycleState, account: base.Account, price: float, exit_signal_date: str, exit_date: str, reason: str) -> dict[str, Any]:
    exit_equity = account.equity(price)
    net_profit = exit_equity - cycle.entry_equity
    gross_profit = net_profit + cycle.financing_interest
    average_exposure = cycle.exposure_sum / cycle.leveraged_days if cycle.leveraged_days else math.nan
    return {
        "cycle_id": cycle.cycle_id,
        "entry_signal_date": cycle.entry_signal_date,
        "leverage_entry_date": cycle.leverage_entry_date,
        "exit_signal_date": exit_signal_date,
        "deleverage_exit_date": exit_date,
        "entry_price": cycle.entry_price,
        "exit_price": price,
        "entry_equity": cycle.entry_equity,
        "exit_equity": exit_equity,
        "entry_reason": cycle.entry_reason,
        "exit_reason": reason,
        "entry_drawdown_pct": cycle.entry_drawdown_pct,
        "leveraged_days": cycle.leveraged_days,
        "average_actual_exposure_pct": average_exposure,
        "max_actual_exposure_pct": cycle.max_actual_exposure_pct,
        "max_debt_principal": cycle.max_debt_principal,
        "cycle_financing_interest": cycle.financing_interest,
        "cycle_transaction_cost": cycle.transaction_cost,
        "cycle_buy_value": cycle.buy_value,
        "cycle_sell_value": cycle.sell_value,
        "cycle_interest_repaid": cycle.interest_repaid,
        "cycle_principal_repaid": cycle.principal_repaid,
        "cycle_gross_profit_before_interest": gross_profit,
        "cycle_net_profit_after_interest": net_profit,
        "remaining_debt_after_exit": account.debt_principal + account.accrued_interest,
        "events": " | ".join(cycle.events),
    }


def simulate_strategy(
    symbol: str,
    frame: pd.DataFrame,
    entry_rule: EntryFilter | None,
    exit_rule: ExitRule | None,
    keep_daily: bool = False,
) -> dict[str, Any]:
    dates = [item.date() for item in frame["date"].dt.to_pydatetime()]
    open_prices = frame["open"].to_numpy(dtype=float)
    close_prices = frame["close"].to_numpy(dtype=float)
    account = base.init_account(float(open_prices[0]))
    values: list[float] = []
    exposure_values: list[float] = []
    debt_values: list[float] = []
    ledger_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    filter_state = FilterState()
    cycle: CycleState | None = None
    cycle_id = 0
    current_target = NORMAL_EXPOSURE
    records = frame.to_dict("records")

    for index, row in enumerate(records):
        date = dates[index]
        open_price = float(open_prices[index])
        close_price = float(close_prices[index])
        action = ""
        action_reason = ""
        trade = {
            "buy_value": 0.0,
            "sell_value": 0.0,
            "transaction_cost": 0.0,
            "borrowed": 0.0,
            "interest_repaid": 0.0,
            "principal_repaid": 0.0,
        }

        if pending is not None:
            old_debt = account.debt_principal + account.accrued_interest
            trade = base.rebalance_to_target(account, open_price, float(pending["target"]))
            current_target = float(pending["target"])
            action_reason = str(pending["reason"])
            action = "buy_or_add" if trade["buy_value"] > 0 else "sell_or_deleverage" if trade["sell_value"] > 0 else "no_trade"
            signal_index = int(pending["signal_index"])
            if entry_rule is not None and exit_rule is not None and trade["buy_value"] > 0 and old_debt <= 1e-6:
                cycle_id += 1
                cycle = CycleState(
                    cycle_id=cycle_id,
                    entry_signal_date=dates[signal_index].isoformat(),
                    leverage_entry_date=date.isoformat(),
                    entry_price=open_price,
                    entry_equity=account.equity(open_price),
                    entry_reason=action_reason,
                    entry_drawdown_pct=float(frame.iloc[signal_index]["drawdown_from_high"]) * 100.0,
                    high_equity=account.equity(open_price),
                )
            if cycle is not None:
                cycle.buy_value += trade["buy_value"]
                cycle.sell_value += trade["sell_value"]
                cycle.transaction_cost += trade["transaction_cost"]
                cycle.interest_repaid += trade["interest_repaid"]
                cycle.principal_repaid += trade["principal_repaid"]
                if trade["buy_value"] > 0 or trade["sell_value"] > 0:
                    cycle.events.append(f"{date.isoformat()} {action_reason} buy={trade['buy_value']:.2f} sell={trade['sell_value']:.2f}")
            if trade["sell_value"] > 0 and account.debt_principal + account.accrued_interest <= 1e-6:
                current_target = NORMAL_EXPOSURE
                if cycle is not None:
                    cycle_rows.append(finish_cycle(cycle, account, open_price, dates[signal_index].isoformat(), date.isoformat(), action_reason))
                    cycle = None
                    filter_state = FilterState()
            pending = None

        daily_interest = account.accrue_interest()
        equity = account.equity(close_price)
        actual_exposure = account.actual_exposure(close_price)
        values.append(equity)
        exposure_values.append(actual_exposure)
        debt_values.append(account.debt_principal)

        if cycle is not None:
            cycle.leveraged_days += 1
            cycle.high_equity = max(cycle.high_equity, equity)
            cycle.exposure_sum += actual_exposure * 100.0 if math.isfinite(actual_exposure) else 0.0
            cycle.max_actual_exposure_pct = max(cycle.max_actual_exposure_pct, actual_exposure * 100.0 if math.isfinite(actual_exposure) else 0.0)
            cycle.max_debt_principal = max(cycle.max_debt_principal, account.debt_principal)
            cycle.financing_interest += daily_interest

        if keep_daily:
            identity = account.cash + account.asset_value(close_price) - account.debt_principal - account.accrued_interest
            ledger_rows.append(
                {
                    "date": date.isoformat(),
                    "open": open_price,
                    "close": close_price,
                    "asset_units": account.asset_units,
                    "asset_value": account.asset_value(close_price),
                    "cash": account.cash,
                    "debt_principal": account.debt_principal,
                    "accrued_interest": account.accrued_interest,
                    "daily_interest": daily_interest,
                    "equity": equity,
                    "equity_identity_error": identity - equity,
                    "actual_exposure_pct": actual_exposure * 100.0 if math.isfinite(actual_exposure) else math.nan,
                    "target_exposure_pct": current_target * 100.0,
                    "action": action,
                    "action_reason": action_reason,
                    "buy_value": trade["buy_value"],
                    "sell_value": trade["sell_value"],
                    "interest_repaid": trade["interest_repaid"],
                    "principal_repaid": trade["principal_repaid"],
                    "transaction_cost": trade["transaction_cost"],
                }
            )

        if entry_rule is None or exit_rule is None or index >= len(frame) - 1:
            continue

        if cycle is not None:
            target, reason = evaluate_exit(exit_rule, cycle, row, close_price, current_target)
            if target is not None and target < current_target - 1e-9:
                pending = {"target": target, "reason": reason, "signal_index": index}
                continue
            if actual_exposure > 1.205:
                pending = {"target": MAX_TARGET_EXPOSURE, "reason": "实际暴露超过120%，次日降回120%", "signal_index": index}
                continue

        if cycle is None:
            passes, reason = entry_filter_passes(entry_rule, row, filter_state, close_price)
            if passes:
                pending = {"target": MAX_TARGET_EXPOSURE, "reason": reason, "signal_index": index}

    if cycle is not None:
        cycle_rows.append(finish_cycle(cycle, account, float(close_prices[-1]), dates[-1].isoformat(), dates[-1].isoformat(), "期末仍持有杠杆"))

    values_array = np.array(values, dtype=float)
    exposure_array = np.array(exposure_values, dtype=float)
    debt_array = np.array(debt_values, dtype=float)
    metrics = base.summary_metrics(values_array, dates)
    gross_profit_before_interest = values_array[-1] + account.total_interest_paid - values_array[0]
    return {
        "dates": dates,
        "values": values_array,
        "actual_exposure": exposure_array,
        "debt_principal": debt_array,
        "metrics": metrics,
        "cycles": cycle_rows,
        "ledger_rows": ledger_rows,
        "total_financing_interest": account.total_interest_paid,
        "total_transaction_cost": account.total_transaction_cost,
        "max_debt_principal": account.max_debt_principal,
        "average_actual_exposure_pct": float(np.nanmean(exposure_array) * 100.0),
        "max_actual_exposure_pct": float(np.nanmax(exposure_array) * 100.0),
        "leveraged_days": int(np.sum(debt_array > 1e-6)),
        "leveraged_time_ratio_pct": float(np.mean(debt_array > 1e-6) * 100.0),
        "trade_count": account.trade_count,
        "financing_interest_pct_gross_profit": float(account.total_interest_paid / gross_profit_before_interest * 100.0)
        if gross_profit_before_interest > 0
        else math.nan,
        "final_debt_or_interest": float(account.debt_principal + account.accrued_interest),
        "final_equity": float(values_array[-1]),
    }


def curve_rows(symbol: str, label: str, entry_id: str, exit_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    start = float(result["values"][0])
    return [
        {
            "symbol": symbol,
            "strategy_label": label,
            "entry_id": entry_id,
            "exit_id": exit_id,
            "date": date.isoformat(),
            "equity": value,
            "return_pct": (value / start - 1.0) * 100.0,
            "actual_exposure_pct": exposure * 100.0 if math.isfinite(exposure) else math.nan,
            "debt_principal": debt,
        }
        for date, value, exposure, debt in zip(result["dates"], result["values"], result["actual_exposure"], result["debt_principal"])
    ]


def metric_row(
    symbol: str,
    entry_rule: EntryFilter | None,
    exit_rule: ExitRule | None,
    result: dict[str, Any],
    buy_hold: dict[str, Any],
    weak_control: dict[str, Any] | None,
    curve: pd.DataFrame,
    buy_hold_curve: pd.DataFrame,
    weak_control_curve: pd.DataFrame | None,
) -> dict[str, Any]:
    metrics = result["metrics"]
    buy_metrics = buy_hold["metrics"]
    weak_metrics = weak_control["metrics"] if weak_control else None
    cagr_adv = metrics["CAGR_pct"] - buy_metrics["CAGR_pct"]
    max_drawdown_improvement = abs(buy_metrics["max_drawdown_pct"]) - abs(metrics["max_drawdown_pct"])
    final_equity = result["final_equity"]
    buy_final_equity = buy_hold["final_equity"]
    financed_gross = final_equity + result["total_financing_interest"] - buy_final_equity
    financed_net = final_equity - buy_final_equity
    row: dict[str, Any] = {
        "symbol": symbol,
        "entry_id": "BUY_HOLD" if entry_rule is None else entry_rule.filter_id,
        "entry_label": "买入持有" if entry_rule is None else entry_rule.label,
        "exit_id": "BUY_HOLD" if exit_rule is None else exit_rule.exit_id,
        "exit_label": "买入持有" if exit_rule is None else exit_rule.label,
        "net_CAGR_after_financing_pct": metrics["CAGR_pct"],
        "CAGR_advantage_vs_buy_hold": cagr_adv,
        "CAGR_diff_vs_weak_control": metrics["CAGR_pct"] - weak_metrics["CAGR_pct"] if weak_metrics else math.nan,
        "cumulative_return_pct": metrics["cumulative_return_pct"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "max_drawdown_improvement_vs_buy_hold": max_drawdown_improvement,
        "Calmar": metrics["Calmar"],
        "Sharpe": metrics["Sharpe"],
        "volatility_pct": metrics["volatility_pct"],
        "best_year": metrics["best_year"],
        "worst_year": metrics["worst_year"],
        "final_equity": final_equity,
        "buy_hold_final_equity": buy_final_equity,
        "financed_money_gross_profit_before_interest": financed_gross,
        "total_financing_interest": result["total_financing_interest"],
        "financed_money_net_profit_after_interest": financed_net,
        "financing_interest_drag_on_financed_profit_pct": result["total_financing_interest"] / financed_gross * 100.0
        if financed_gross > 0
        else math.nan,
        "total_transaction_cost": result["total_transaction_cost"],
        "max_debt_principal": result["max_debt_principal"],
        "average_actual_exposure_pct": result["average_actual_exposure_pct"],
        "max_actual_exposure_pct": result["max_actual_exposure_pct"],
        "leveraged_days": result["leveraged_days"],
        "leveraged_time_ratio_pct": result["leveraged_time_ratio_pct"],
        "trade_count": result["trade_count"],
        "final_debt_or_interest": result["final_debt_or_interest"],
        "symbol_positive_CAGR_advantage": int(cagr_adv > 0),
        "symbol_drawdown_ok": int(max_drawdown_improvement >= -1.0),
        "symbol_financed_net_positive": int(financed_net > 0),
        "symbol_no_debt_left": int(result["final_debt_or_interest"] <= 1e-6),
    }
    for period, (start, end) in PERIODS.items():
        period_key = period.replace(" ", "_")
        row[f"{period_key}_return_pct"] = period_return(curve, start, end)
        row[f"{period_key}_buy_hold_return_pct"] = period_return(buy_hold_curve, start, end)
        row[f"{period_key}_return_vs_buy_hold"] = row[f"{period_key}_return_pct"] - row[f"{period_key}_buy_hold_return_pct"]
        row[f"{period_key}_max_drawdown_pct"] = period_max_drawdown(curve, start, end)
        row[f"{period_key}_buy_hold_max_drawdown_pct"] = period_max_drawdown(buy_hold_curve, start, end)
    if weak_control_curve is not None:
        row["weak_control_return_2000_2002_pct"] = period_return(weak_control_curve, "2000-01-01", "2002-12-31")
        row["return_2000_2002_vs_weak_control"] = row["2000-2002_科技泡沫熊市_return_pct"] - row["weak_control_return_2000_2002_pct"]
    return row


def previous_average_leverage_days() -> float:
    if not PREVIOUS_TOP10_SUMMARY.exists():
        return 2500.0
    frame = pd.read_csv(PREVIOUS_TOP10_SUMMARY)
    if "avg_lev_days" not in frame.columns or frame.empty:
        return 2500.0
    return float(frame["avg_lev_days"].mean())


def add_summary_flags(summary: pd.DataFrame, previous_avg_days: float) -> pd.DataFrame:
    result = summary.copy()
    leverage_day_limit = previous_avg_days * 0.5
    result["hard_pass_bool"] = (
        (result["positive_symbol_count"] >= 2)
        & (result["avg_cagr_advantage"] > 0.5)
        & (result["min_drawdown_improvement"] >= -1.0)
        & (result["USTEC_drawdown_improvement"] >= -1.0)
        & (result["avg_leveraged_days"] <= leverage_day_limit)
        & (result["avg_financed_net_profit"] > 0)
        & (result["debt_warning_count"] == 0)
    )
    result["hard_pass"] = np.where(result["hard_pass_bool"], "是", "否")
    warnings: list[str] = []
    for row in result.itertuples(index=False):
        tags: list[str] = []
        if row.avg_cagr_advantage > 0 and row.min_drawdown_improvement < -1.0:
            tags.append("收益换风险")
        if row.avg_leveraged_days > leverage_day_limit:
            tags.append("长期融资依赖")
        if row.avg_financed_gross_profit > 0 and row.avg_financed_net_profit <= 0:
            tags.append("融资成本吞噬")
        if row.positive_symbol_count == 1 and row.US500_CAGR_advantage > 0:
            tags.append("单市场依赖")
        if row.USTEC_CAGR_advantage <= 0 or row.USTEC_drawdown_improvement < -1.0:
            tags.append("纳指熊市过滤不足")
        if row.hard_pass_bool and row.positive_symbol_count == 3:
            tags.append("强候选")
        warnings.append("；".join(tags) if tags else "无")
    result["warning_tags"] = warnings
    return result.sort_values(
        ["hard_pass_bool", "positive_symbol_count", "avg_cagr_advantage", "avg_financed_net_profit", "avg_Calmar"],
        ascending=[False, False, False, False, False],
    )


def build_summary(metrics: pd.DataFrame, previous_avg_days: float) -> pd.DataFrame:
    candidates = metrics[(metrics["entry_id"] != "BUY_HOLD") & (metrics["exit_id"] != "WEAK_CONTROL")].copy()
    summary = (
        candidates.groupby(["entry_id", "entry_label", "exit_id", "exit_label"])
        .agg(
            tested_symbols=("symbol", "nunique"),
            positive_symbol_count=("symbol_positive_CAGR_advantage", "sum"),
            avg_CAGR=("net_CAGR_after_financing_pct", "mean"),
            avg_cagr_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
            min_cagr_advantage=("CAGR_advantage_vs_buy_hold", "min"),
            avg_drawdown_improvement=("max_drawdown_improvement_vs_buy_hold", "mean"),
            min_drawdown_improvement=("max_drawdown_improvement_vs_buy_hold", "min"),
            avg_Calmar=("Calmar", "mean"),
            avg_leveraged_days=("leveraged_days", "mean"),
            avg_financing_interest=("total_financing_interest", "mean"),
            avg_financed_gross_profit=("financed_money_gross_profit_before_interest", "mean"),
            avg_financed_net_profit=("financed_money_net_profit_after_interest", "mean"),
            min_financed_net_profit=("financed_money_net_profit_after_interest", "min"),
            debt_warning_count=("symbol_no_debt_left", lambda item: int((item == 0).sum())),
            avg_2000_2002_vs_buy_hold=("2000-2002_科技泡沫熊市_return_vs_buy_hold", "mean"),
            avg_2008_vs_buy_hold=("2008_金融危机_return_vs_buy_hold", "mean"),
            avg_2022_vs_buy_hold=("2022_加息慢熊_return_vs_buy_hold", "mean"),
        )
        .reset_index()
    )
    pivots = candidates.pivot_table(
        index=["entry_id", "exit_id"],
        columns="symbol",
        values=["CAGR_advantage_vs_buy_hold", "max_drawdown_improvement_vs_buy_hold"],
        aggfunc="first",
    )
    flat_rows: list[dict[str, Any]] = []
    for (entry_id, exit_id), row in pivots.iterrows():
        item = {"entry_id": entry_id, "exit_id": exit_id}
        for symbol in DATASETS:
            item[f"{symbol}_CAGR_advantage"] = row.get(("CAGR_advantage_vs_buy_hold", symbol), math.nan)
            item[f"{symbol}_drawdown_improvement"] = row.get(("max_drawdown_improvement_vs_buy_hold", symbol), math.nan)
        flat_rows.append(item)
    summary = summary.merge(pd.DataFrame(flat_rows), on=["entry_id", "exit_id"], how="left")
    summary["previous_top10_avg_leveraged_days"] = previous_avg_days
    summary["required_leveraged_days_limit"] = previous_avg_days * 0.5
    return add_summary_flags(summary, previous_avg_days)


def build_period_rows(curves: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (symbol, entry_id, exit_id, label), curve in curves.groupby(["symbol", "entry_id", "exit_id", "strategy_label"]):
        for period, (start, end) in PERIODS.items():
            rows.append(
                {
                    "symbol": symbol,
                    "entry_id": entry_id,
                    "exit_id": exit_id,
                    "strategy_label": label,
                    "period": period,
                    "return_pct": period_return(curve, start, end),
                    "max_drawdown_pct": period_max_drawdown(curve, start, end),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def plot_equity(curves: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axes = plt.subplots(3, 1, figsize=(15, 16), sharex=False)
    for axis, symbol in zip(axes, DATASETS):
        subset = curves[curves["symbol"] == symbol]
        for label, part in subset.groupby("strategy_label"):
            width = 2.6 if label in {"买入持有", "上轮弱对照"} else 1.1
            alpha = 0.95 if label in {"买入持有", "上轮弱对照"} else 0.5
            axis.plot(part["date"], part["return_pct"], lw=width, alpha=alpha, label=label)
        axis.set_title(f"{symbol} 收益曲线")
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    path = charts_dir / "equity_curves.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_drawdown(curves: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axes = plt.subplots(3, 1, figsize=(15, 16), sharex=False)
    for axis, symbol in zip(axes, DATASETS):
        subset = curves[curves["symbol"] == symbol]
        for label, part in subset.groupby("strategy_label"):
            values = part["equity"].to_numpy(dtype=float)
            drawdown = values / np.maximum.accumulate(values) - 1.0
            width = 2.6 if label in {"买入持有", "上轮弱对照"} else 1.1
            alpha = 0.95 if label in {"买入持有", "上轮弱对照"} else 0.5
            axis.plot(part["date"], drawdown * 100.0, lw=width, alpha=alpha, label=label)
        axis.set_title(f"{symbol} 回撤曲线")
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        axis.grid(True, alpha=0.25)
    fig.tight_layout()
    path = charts_dir / "drawdown_curves.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_entry_filter_comparison(summary: pd.DataFrame, charts_dir: Path) -> Path:
    grouped = summary.groupby("entry_label").agg(avg_adv=("avg_cagr_advantage", "mean"), avg_days=("avg_leveraged_days", "mean")).reset_index()
    fig, axis = plt.subplots(figsize=(12, 7))
    axis.bar(grouped["entry_label"], grouped["avg_adv"], color=["#16a34a" if value > 0 else "#dc2626" for value in grouped["avg_adv"]])
    axis.axhline(0, color="#64748b", lw=1)
    axis.set_title("不同熊市过滤器的平均年化优势")
    axis.set_ylabel("年化优势")
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}%"))
    axis.tick_params(axis="x", rotation=20)
    axis.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path = charts_dir / "entry_filter_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_leverage_days_vs_cagr(summary: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axis = plt.subplots(figsize=(11, 7))
    for entry_label, part in summary.groupby("entry_label"):
        axis.scatter(part["avg_leveraged_days"], part["avg_cagr_advantage"], label=entry_label, s=70, alpha=0.8)
    axis.axhline(0, color="#64748b", lw=1)
    axis.set_title("杠杆天数 vs 平均年化优势")
    axis.set_xlabel("平均杠杆天数")
    axis.set_ylabel("平均年化优势")
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}%"))
    axis.grid(True, alpha=0.25)
    axis.legend(fontsize=8)
    fig.tight_layout()
    path = charts_dir / "leverage_days_vs_cagr.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_financing_cost_vs_net_contribution(summary: pd.DataFrame, charts_dir: Path) -> Path:
    fig, axis = plt.subplots(figsize=(11, 7))
    colors = ["#16a34a" if value > 0 else "#dc2626" for value in summary["avg_financed_net_profit"]]
    axis.scatter(summary["avg_financing_interest"], summary["avg_financed_net_profit"], c=colors, s=80, alpha=0.8)
    axis.axhline(0, color="#64748b", lw=1)
    axis.set_title("融资利息 vs 融资资金扣息后净贡献")
    axis.set_xlabel("平均融资利息")
    axis.set_ylabel("平均融资资金扣息后净贡献")
    axis.grid(True, alpha=0.25)
    fig.tight_layout()
    path = charts_dir / "financing_cost_vs_net_contribution.png"
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
                if any(item in lower_key for item in ["advantage", "improvement", "return", "profit", "calmar", "cagr"]) and value > 0:
                    css = "good"
                if any(item in lower_key for item in ["advantage", "improvement", "return", "profit", "calmar", "cagr"]) and value < 0:
                    css = "bad"
                if any(item in lower_key for item in ["profit", "interest", "equity"]) and abs(value) >= 1000:
                    text = f"{value:,.0f}"
                elif any(item in lower_key for item in ["count", "days", "symbols"]):
                    text = f"{value:.0f}"
                elif any(item in lower_key for item in ["pct", "cagr", "advantage", "return", "drawdown", "improvement"]):
                    text = f"{value:.2f}%"
                else:
                    text = f"{value:.2f}"
            else:
                text = "" if pd.isna(value) else str(value)
                if text == "是":
                    css = "good"
                elif text == "否":
                    css = "bad"
            parts.append(f"<td class='{css}'>{html.escape(text)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def build_answers(summary: pd.DataFrame) -> list[str]:
    filter_group = summary.groupby("entry_label").agg(
        avg_adv=("avg_cagr_advantage", "mean"),
        avg_2000=("avg_2000_2002_vs_buy_hold", "mean"),
        avg_2008=("avg_2008_vs_buy_hold", "mean"),
        avg_2022=("avg_2022_vs_buy_hold", "mean"),
        avg_days=("avg_leveraged_days", "mean"),
        avg_net=("avg_financed_net_profit", "mean"),
    )
    exit_group = summary.groupby("exit_label").agg(
        avg_adv=("avg_cagr_advantage", "mean"),
        avg_days=("avg_leveraged_days", "mean"),
        avg_net=("avg_financed_net_profit", "mean"),
    )
    best_filter = filter_group["avg_adv"].sort_values(ascending=False)
    best_exit = exit_group["avg_adv"].sort_values(ascending=False)
    hard_pass_count = int(summary["hard_pass_bool"].sum())
    best = summary.iloc[0]
    no_filter = filter_group.loc["F0 无过滤对照"] if "F0 无过滤对照" in filter_group.index else None
    best_filter_row = filter_group.loc[best_filter.index[0]]
    positive_two_count = int((summary["positive_symbol_count"] >= 2).sum())
    positive_net_count = int((summary["avg_financed_net_profit"] > 0).sum())
    max_net = summary.sort_values("avg_financed_net_profit", ascending=False).iloc[0]
    worth = "不适合直接作为候选策略；只值得继续研究更严格的入场过滤或更低杠杆版本" if hard_pass_count == 0 else "存在通过硬性标准的候选，值得进入下一轮精简验证"
    if no_filter is not None:
        change_2000 = best_filter_row["avg_2000"] - no_filter["avg_2000"]
        change_2008 = best_filter_row["avg_2008"] - no_filter["avg_2008"]
        change_2022 = best_filter_row["avg_2022"] - no_filter["avg_2022"]
        period_answer = (
            f"相对无过滤，最佳过滤器在 2000-2002 改善 {change_2000:.2f} 个百分点，"
            f"2008 改善 {change_2008:.2f} 个百分点，2022 改善 {change_2022:.2f} 个百分点。"
        )
    else:
        period_answer = "缺少无过滤对照，无法计算阶段改善。"
    return [
        f"哪个熊市过滤器最有效：{best_filter.index[0]}，平均年化优势 {best_filter.iloc[0]:.2f} 个百分点。",
        f"哪个退出规则最有效：{best_exit.index[0]}，平均年化优势 {best_exit.iloc[0]:.2f} 个百分点。",
        f"综合排名第一：{best.entry_label} + {best.exit_label}，平均年化优势 {best.avg_cagr_advantage:.2f} 个百分点，通过 {int(best.positive_symbol_count)}/3 个品种收益正优势。",
        period_answer,
        f"是否还有至少两个品种跑赢买入持有：{'有' if positive_two_count else '没有'}，符合该宽松条件的组合数为 {positive_two_count}。",
        f"融资资金扣息后净贡献是否转正：{'有' if positive_net_count else '没有'}，净贡献最高的是 {max_net.entry_label} + {max_net.exit_label}，平均净贡献 {max_net.avg_financed_net_profit:,.0f}。",
        f"硬性通过策略数量：{hard_pass_count}。",
        f"这类深跌加杠杆策略是否还值得继续研究：{worth}。",
    ]


def render_report(
    out_dir: Path,
    manifest: pd.DataFrame,
    summary: pd.DataFrame,
    per_symbol: pd.DataFrame,
    period_frame: pd.DataFrame,
    chart_paths: list[Path],
) -> None:
    summary_columns = [
        ("entry_label", "入场过滤"),
        ("exit_label", "退出规则"),
        ("hard_pass", "硬性通过"),
        ("warning_tags", "标记"),
        ("positive_symbol_count", "收益正优势品种数"),
        ("avg_CAGR", "平均年化"),
        ("avg_cagr_advantage", "平均年化优势"),
        ("min_cagr_advantage", "最差年化优势"),
        ("avg_drawdown_improvement", "平均回撤改善"),
        ("min_drawdown_improvement", "最差回撤改善"),
        ("USTEC_drawdown_improvement", "USTEC回撤改善"),
        ("avg_leveraged_days", "平均杠杆天数"),
        ("avg_financing_interest", "平均融资利息"),
        ("avg_financed_net_profit", "融资资金扣息后净贡献"),
        ("avg_2000_2002_vs_buy_hold", "2000-2002相对买入持有"),
        ("avg_2008_vs_buy_hold", "2008相对买入持有"),
        ("avg_2022_vs_buy_hold", "2022相对买入持有"),
    ]
    symbol_columns = [
        ("symbol", "品种"),
        ("entry_label", "入场过滤"),
        ("exit_label", "退出规则"),
        ("net_CAGR_after_financing_pct", "年化"),
        ("CAGR_advantage_vs_buy_hold", "年化优势"),
        ("max_drawdown_pct", "最大回撤"),
        ("max_drawdown_improvement_vs_buy_hold", "回撤改善"),
        ("leveraged_days", "杠杆天数"),
        ("total_financing_interest", "融资利息"),
        ("financed_money_net_profit_after_interest", "融资资金扣息后净贡献"),
        ("2000-2002_科技泡沫熊市_return_vs_buy_hold", "2000-2002相对买入持有"),
        ("2008_金融危机_return_vs_buy_hold", "2008相对买入持有"),
        ("2022_加息慢熊_return_vs_buy_hold", "2022相对买入持有"),
        ("final_debt_or_interest", "期末债务利息"),
    ]
    manifest_columns = [
        ("symbol", "品种"),
        ("data_source", "数据文件"),
        ("data_start_date", "开始"),
        ("data_end_date", "结束"),
        ("data_rows", "行数"),
        ("adjusted_price_used", "复权价格"),
    ]
    period_columns = [
        ("symbol", "品种"),
        ("strategy_label", "策略"),
        ("period", "阶段"),
        ("return_pct", "收益"),
        ("max_drawdown_pct", "最大回撤"),
    ]
    answers = build_answers(summary)
    image_blocks = "\n".join(f'<section class="card"><h2>{html.escape(path.stem)}</h2><img src="charts/{html.escape(path.name)}"></section>' for path in chart_paths)
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>深跌加杠杆熊市过滤验证</title>
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
  <h1>深跌加杠杆熊市过滤验证</h1>
  <div>Yahoo 长历史日线，融资成本 7%，真实资产负债表口径；每个品种只交易自身，不轮动。</div>
</header>
<div class="wrap">
  <section class="card"><h2>结论摘要</h2><div class="pad"><ul>
    {''.join(f'<li>{html.escape(answer)}</li>' for answer in answers)}
  </ul></div></section>
  <section class="card"><h2>输入数据</h2><div class="scroll">{render_table(manifest, manifest_columns)}</div></section>
  <section class="card"><h2>综合排名</h2><div class="scroll">{render_table(summary, summary_columns)}</div></section>
  <section class="card"><h2>分品种结果</h2><div class="scroll">{render_table(per_symbol, symbol_columns, limit=75)}</div></section>
  <section class="card"><h2>阶段表现</h2><div class="scroll">{render_table(period_frame, period_columns, limit=120)}</div></section>
  {image_blocks}
</div>
</body>
</html>
"""
    (out_dir / "backtest_report.html").write_text(html_doc, encoding="utf-8")


def main() -> None:
    args = parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    unknown = [symbol for symbol in symbols if symbol not in DATASETS]
    if unknown:
        raise SystemExit(f"Unknown symbols: {', '.join(unknown)}. Available: {', '.join(DATASETS)}")

    filters = entry_filters()
    exits = exit_rules()
    previous_avg_days = previous_average_leverage_days()
    frames = {symbol: load_yahoo_daily(DATASETS[symbol]) for symbol in symbols}

    metrics_rows: list[dict[str, Any]] = []
    curve_rows_all: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []

    weak_filter = next(item for item in filters if item.filter_id == "F2_rebound_sma50")
    weak_exit = next(item for item in exits if item.exit_id == "X1_profit_40")

    for symbol, frame in frames.items():
        manifest_rows.append(
            {
                "symbol": symbol,
                "data_source": str(DATASETS[symbol]),
                "data_start_date": frame["date"].min().date().isoformat(),
                "data_end_date": frame["date"].max().date().isoformat(),
                "data_rows": len(frame),
                "adjusted_price_used": "否，Yahoo 指数 OHLC 原始字段",
            }
        )

        buy_hold = simulate_strategy(symbol, frame, None, None, keep_daily=True)
        buy_hold_curve = pd.DataFrame(curve_rows(symbol, "买入持有", "BUY_HOLD", "BUY_HOLD", buy_hold))
        buy_hold_curve["date"] = pd.to_datetime(buy_hold_curve["date"])
        metrics_rows.append(metric_row(symbol, None, None, buy_hold, buy_hold, None, buy_hold_curve, buy_hold_curve, None))
        curve_rows_all.extend(buy_hold_curve.to_dict("records"))
        for row in buy_hold["ledger_rows"]:
            ledger_rows.append({**row, "symbol": symbol, "strategy_label": "买入持有", "entry_id": "BUY_HOLD", "exit_id": "BUY_HOLD"})

        weak_control = simulate_strategy(symbol, frame, weak_filter, weak_exit, keep_daily=True)
        weak_curve = pd.DataFrame(curve_rows(symbol, "上轮弱对照", "WEAK_CONTROL", "WEAK_CONTROL", weak_control))
        weak_curve["date"] = pd.to_datetime(weak_curve["date"])
        metrics_rows.append(metric_row(symbol, weak_filter, weak_exit, weak_control, buy_hold, weak_control, weak_curve, buy_hold_curve, weak_curve) | {"entry_id": "WEAK_CONTROL", "exit_id": "WEAK_CONTROL", "entry_label": "上轮弱对照", "exit_label": "上轮弱对照"})
        curve_rows_all.extend(weak_curve.to_dict("records"))
        for row in weak_control["ledger_rows"]:
            ledger_rows.append({**row, "symbol": symbol, "strategy_label": "上轮弱对照", "entry_id": "WEAK_CONTROL", "exit_id": "WEAK_CONTROL"})
        for cycle in weak_control["cycles"]:
            cycle_rows.append({**cycle, "symbol": symbol, "strategy_label": "上轮弱对照", "entry_id": "WEAK_CONTROL", "entry_label": "上轮弱对照", "exit_id": "WEAK_CONTROL", "exit_label": "上轮弱对照"})

        for entry_filter in filters:
            for exit_rule in exits:
                result = simulate_strategy(symbol, frame, entry_filter, exit_rule, keep_daily=False)
                label = f"{entry_filter.label} / {exit_rule.label}"
                strategy_curve = pd.DataFrame(curve_rows(symbol, label, entry_filter.filter_id, exit_rule.exit_id, result))
                strategy_curve["date"] = pd.to_datetime(strategy_curve["date"])
                metrics_rows.append(metric_row(symbol, entry_filter, exit_rule, result, buy_hold, weak_control, strategy_curve, buy_hold_curve, weak_curve))
                curve_rows_all.extend(strategy_curve.to_dict("records"))
                for cycle in result["cycles"]:
                    cycle_rows.append({**cycle, "symbol": symbol, "strategy_label": label, "entry_id": entry_filter.filter_id, "entry_label": entry_filter.label, "exit_id": exit_rule.exit_id, "exit_label": exit_rule.label})

    metrics = pd.DataFrame(metrics_rows)
    curves = pd.DataFrame(curve_rows_all)
    curves["date"] = pd.to_datetime(curves["date"])
    summary = build_summary(metrics, previous_avg_days)
    per_symbol = metrics[(metrics["entry_id"] != "BUY_HOLD")].sort_values(
        ["symbol", "CAGR_advantage_vs_buy_hold", "max_drawdown_improvement_vs_buy_hold", "Calmar"],
        ascending=[True, False, False, False],
    )
    period_frame = pd.DataFrame(build_period_rows(curves))
    manifest = pd.DataFrame(manifest_rows)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    avg_adv = float(summary["avg_cagr_advantage"].mean()) if not summary.empty else 0.0
    out_dir = base.REPORTS / f"bear-filter-leverage-test-7pct_{timestamp}_avgadv{avg_adv:+.2f}"
    tables_dir = out_dir / "tables"
    charts_dir = out_dir / "charts"
    tables_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    write_csv(tables_dir / "all_tests.csv", metrics)
    write_csv(tables_dir / "strategy_summary.csv", summary)
    write_csv(tables_dir / "per_symbol_rankings.csv", per_symbol)
    write_csv(tables_dir / "period_performance.csv", period_frame)
    write_csv(tables_dir / "leverage_cycle_logs.csv", cycle_rows)
    write_csv(tables_dir / "account_daily_ledger_selected.csv", ledger_rows)
    write_csv(tables_dir / "input_manifest.csv", manifest)

    chart_paths = [
        plot_equity(curves, charts_dir),
        plot_drawdown(curves, charts_dir),
        plot_entry_filter_comparison(summary, charts_dir),
        plot_leverage_days_vs_cagr(summary, charts_dir),
        plot_financing_cost_vs_net_contribution(summary, charts_dir),
    ]
    render_report(out_dir, manifest, summary, per_symbol, period_frame, chart_paths)

    print("HTML report:", out_dir / "backtest_report.html")
    print("Charts dir:", charts_dir)
    print("Tables dir:", tables_dir)
    print("Average candidate CAGR advantage vs buy-and-hold:", f"{avg_adv:.4f}", "pct points")
    print("Hard pass count:", int(summary["hard_pass_bool"].sum()))


if __name__ == "__main__":
    main()
