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
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

import research_leverage_matrix_balance_sheet_7pct as base


INITIAL_CAPITAL = base.INITIAL_CAPITAL
NORMAL_EXPOSURE = base.NORMAL_EXPOSURE
MAX_TARGET_EXPOSURE = base.MAX_TARGET_EXPOSURE
FINANCING_RATE_ANNUAL = base.FINANCING_RATE_ANNUAL
TRADING_DAYS_PER_YEAR = base.TRADING_DAYS_PER_YEAR

DEFAULT_SYMBOLS = ["US500", "USTEC", "JP225"]
VALIDATION_SYMBOLS = ["MidDE50", "TecDE30"]

PERIODS = {
    "全样本": (None, None),
    "2020暴跌反弹": ("2020-02-19", "2020-12-31"),
    "2022慢熊": ("2022-01-01", "2022-12-31"),
    "2023-2025牛市": ("2023-01-01", "2025-12-31"),
}

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class EntryRule:
    entry_id: str
    label: str
    mode: str


@dataclass(frozen=True)
class ExitRule:
    exit_id: str
    family: str
    label: str
    mode: str
    params: tuple[float, ...] = ()


@dataclass
class EntryState:
    armed: bool = False
    low_since_armed: float = math.inf


@dataclass
class CycleState:
    cycle_id: int
    entry_signal_date: str
    leverage_entry_date: str
    entry_price: float
    entry_equity: float
    entry_buy_hold_equity: float
    entry_drawdown_pct: float
    entry_reason: str
    leveraged_days: int = 0
    high_equity: float = 0.0
    exposure_sum: float = 0.0
    max_actual_exposure_pct: float = 0.0
    financing_interest: float = 0.0
    transaction_cost: float = 0.0
    buy_value: float = 0.0
    sell_value: float = 0.0
    interest_repaid: float = 0.0
    principal_repaid: float = 0.0
    max_debt_principal: float = 0.0
    half_flags: set[str] = field(default_factory=set)
    slow_bear_streak: int = 0
    level_events: list[str] = field(default_factory=list)


def entry_rules() -> list[EntryRule]:
    return [
        EntryRule("E1_direct_dd30", "回撤30%直接加到120%", "direct"),
        EntryRule("E2_rebound_dd30_r10", "回撤30%后反弹10%加到120%", "rebound"),
    ]


def exit_rules() -> list[ExitRule]:
    return [
        ExitRule("X_current_best", "当前最优对照", "加杠杆后再跌8%全降", "stop_from_entry", (0.08,)),
        ExitRule("X_profit_20_30", "盈利保护退出", "涨20%降半，涨30%全降", "profit_ladder", (0.20, 0.30)),
        ExitRule("X_profit_30_40", "盈利保护退出", "涨30%降半，涨40%全降", "profit_ladder", (0.30, 0.40)),
        ExitRule("X_profit_40_once", "盈利保护退出", "涨40%一次性全降", "profit_once", (0.40,)),
        ExitRule("X_rel_5_10", "相对优势锁定退出", "领先5%降半，领先10%全降", "relative_ladder", (0.05, 0.10)),
        ExitRule("X_rel_10_15", "相对优势锁定退出", "领先10%降半，领先15%全降", "relative_ladder", (0.10, 0.15)),
        ExitRule("X_rel_15_once", "相对优势锁定退出", "领先15%一次性全降", "relative_once", (0.15,)),
        ExitRule("X_giveback_5", "回吐止盈退出", "周期高点回吐5%全降", "giveback_once", (0.05,)),
        ExitRule("X_giveback_8", "回吐止盈退出", "周期高点回吐8%全降", "giveback_once", (0.08,)),
        ExitRule("X_giveback_10", "回吐止盈退出", "周期高点回吐10%全降", "giveback_once", (0.10,)),
        ExitRule("X_giveback_5_10", "回吐止盈退出", "回吐5%降半，回吐10%全降", "giveback_ladder", (0.05, 0.10)),
        ExitRule("X_slow_2", "慢熊结构退出", "慢熊条件满足2个全降", "slow_bear_full", (2,)),
        ExitRule("X_slow_3", "慢熊结构退出", "慢熊条件满足3个全降", "slow_bear_full", (3,)),
        ExitRule("X_slow_2_streak10", "慢熊结构退出", "慢熊2条件先降半，连续10日全降", "slow_bear_half_streak", (2, 10)),
        ExitRule("X_time_252", "融资与时间退出", "持杠杆252日全降", "time_full", (252,)),
        ExitRule("X_time_504", "融资与时间退出", "持杠杆504日全降", "time_full", (504,)),
        ExitRule("X_cost_gross_10", "融资与时间退出", "利息达毛利润10%全降", "cost_gross", (0.10,)),
        ExitRule("X_cost_gross_15", "融资与时间退出", "利息达毛利润15%全降", "cost_gross", (0.15,)),
        ExitRule("X_cost_gross_20", "融资与时间退出", "利息达毛利润20%全降", "cost_gross", (0.20,)),
        ExitRule("X_mix_profit30_slow", "混合退出", "涨30%降半，慢熊全降", "mix_profit_slow"),
        ExitRule("X_mix_rel10_giveback8", "混合退出", "领先10%降半，回吐8%全降", "mix_relative_giveback"),
        ExitRule("X_mix_repair10_cost_time", "混合退出", "修复到10%降半，成本15%或252日全降", "mix_repair_cost_time"),
        ExitRule("X_mix_slow_recover", "混合退出", "慢熊降半，未恢复则连续10日全降", "mix_slow_recover"),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research exit optimization after deep drawdown leverage.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols to test.")
    parser.add_argument("--include-validation", action="store_true", help="Also test MidDE50 and TecDE30.")
    return parser.parse_args()


def enrich_frame(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["sma200_slope20"] = enriched["sma200"] / enriched["sma200"].shift(20) - 1.0
    enriched["dd60"] = enriched["close"] / enriched["high60"] - 1.0
    enriched["slow_vol_high"] = enriched["vol20"] > enriched["vol252_median"] * 1.5
    return enriched


def slow_bear_count(row: dict[str, Any]) -> int:
    count = 0
    count += int(row["close"] < row["sma200"])
    count += int(math.isfinite(row["sma200_slope20"]) and row["sma200_slope20"] <= 0)
    count += int(row["dd60"] <= -0.15)
    count += int(bool(row["slow_vol_high"]))
    return count


def period_return(curve: pd.DataFrame, start: str | None, end: str | None) -> float:
    sub = curve.copy()
    if start is not None:
        sub = sub[sub["date"] >= pd.Timestamp(start)]
    if end is not None:
        sub = sub[sub["date"] <= pd.Timestamp(end)]
    if len(sub) < 2:
        return math.nan
    return float((sub.iloc[-1]["equity"] / sub.iloc[0]["equity"] - 1.0) * 100)


def maybe_finish_cycle(cycle: CycleState, account: base.Account, price: float, exit_signal_date: str, exit_date: str, reason: str) -> dict[str, Any]:
    avg_exposure = cycle.exposure_sum / cycle.leveraged_days if cycle.leveraged_days else math.nan
    exit_equity = account.equity(price)
    net_profit = exit_equity - cycle.entry_equity
    gross_profit = net_profit + cycle.financing_interest
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
        "leveraged_days": cycle.leveraged_days,
        "average_actual_exposure_pct": avg_exposure,
        "max_actual_exposure_pct": cycle.max_actual_exposure_pct,
        "max_debt_principal": cycle.max_debt_principal,
        "cycle_buy_value": cycle.buy_value,
        "cycle_sell_value": cycle.sell_value,
        "cycle_transaction_cost": cycle.transaction_cost,
        "cycle_financing_interest": cycle.financing_interest,
        "cycle_interest_repaid": cycle.interest_repaid,
        "cycle_principal_repaid": cycle.principal_repaid,
        "cycle_gross_profit_before_interest": gross_profit,
        "cycle_net_profit_after_interest": net_profit,
        "remaining_debt_after_exit": account.debt_principal + account.accrued_interest,
        "level_events": " | ".join(cycle.level_events),
    }


def target_half(current_target: float) -> float:
    return max(NORMAL_EXPOSURE, NORMAL_EXPOSURE + (current_target - NORMAL_EXPOSURE) * 0.5)


def evaluate_exit_rule(
    rule: ExitRule,
    cycle: CycleState,
    account: base.Account,
    current_target: float,
    price: float,
    row: dict[str, Any],
    buy_hold_equity: float,
) -> tuple[float | None, str]:
    equity = account.equity(price)
    asset_return = price / cycle.entry_price - 1.0 if cycle.entry_price > 0 else 0.0
    relative_lead = equity / buy_hold_equity - 1.0 if buy_hold_equity > 0 else 0.0
    giveback = 1.0 - equity / cycle.high_equity if cycle.high_equity > 0 else 0.0
    net_profit = equity - cycle.entry_equity
    gross_profit = net_profit + cycle.financing_interest
    slow_count = slow_bear_count(row)

    if rule.mode == "stop_from_entry":
        if price <= cycle.entry_price * (1.0 - rule.params[0]):
            return NORMAL_EXPOSURE, f"加杠杆后继续跌{rule.params[0]:.0%}全降"
    elif rule.mode == "profit_ladder":
        half, full = rule.params
        if asset_return >= full:
            return NORMAL_EXPOSURE, f"杠杆周期涨幅达到{full:.0%}全降"
        if asset_return >= half and "profit_half" not in cycle.half_flags:
            cycle.half_flags.add("profit_half")
            return target_half(current_target), f"杠杆周期涨幅达到{half:.0%}降半"
    elif rule.mode == "profit_once":
        if asset_return >= rule.params[0]:
            return NORMAL_EXPOSURE, f"杠杆周期涨幅达到{rule.params[0]:.0%}全降"
    elif rule.mode == "relative_ladder":
        half, full = rule.params
        if relative_lead >= full:
            return NORMAL_EXPOSURE, f"相对买入持有领先{full:.0%}全降"
        if relative_lead >= half and "relative_half" not in cycle.half_flags:
            cycle.half_flags.add("relative_half")
            return target_half(current_target), f"相对买入持有领先{half:.0%}降半"
    elif rule.mode == "relative_once":
        if relative_lead >= rule.params[0]:
            return NORMAL_EXPOSURE, f"相对买入持有领先{rule.params[0]:.0%}全降"
    elif rule.mode == "giveback_once":
        if giveback >= rule.params[0]:
            return NORMAL_EXPOSURE, f"杠杆周期权益高点回吐{rule.params[0]:.0%}全降"
    elif rule.mode == "giveback_ladder":
        half, full = rule.params
        if giveback >= full:
            return NORMAL_EXPOSURE, f"杠杆周期权益高点回吐{full:.0%}全降"
        if giveback >= half and "giveback_half" not in cycle.half_flags:
            cycle.half_flags.add("giveback_half")
            return target_half(current_target), f"杠杆周期权益高点回吐{half:.0%}降半"
    elif rule.mode == "slow_bear_full":
        if slow_count >= int(rule.params[0]):
            return NORMAL_EXPOSURE, f"慢熊结构满足{int(rule.params[0])}项全降"
    elif rule.mode == "slow_bear_half_streak":
        need, streak = int(rule.params[0]), int(rule.params[1])
        if slow_count >= need:
            cycle.slow_bear_streak += 1
            if cycle.slow_bear_streak >= streak:
                return NORMAL_EXPOSURE, f"慢熊结构连续{streak}日全降"
            if "slow_half" not in cycle.half_flags:
                cycle.half_flags.add("slow_half")
                return target_half(current_target), f"慢熊结构满足{need}项先降半"
        else:
            cycle.slow_bear_streak = 0
    elif rule.mode == "time_full":
        if cycle.leveraged_days >= int(rule.params[0]):
            return NORMAL_EXPOSURE, f"杠杆持有满{int(rule.params[0])}日全降"
    elif rule.mode == "cost_gross":
        if gross_profit > 0 and cycle.financing_interest >= gross_profit * rule.params[0]:
            return NORMAL_EXPOSURE, f"融资利息达到周期毛利润{rule.params[0]:.0%}全降"
    elif rule.mode == "mix_profit_slow":
        if slow_count >= 2:
            return NORMAL_EXPOSURE, "混合退出：慢熊结构全降"
        if asset_return >= 0.30 and "profit_half" not in cycle.half_flags:
            cycle.half_flags.add("profit_half")
            return target_half(current_target), "混合退出：涨30%先降半"
    elif rule.mode == "mix_relative_giveback":
        if giveback >= 0.08:
            return NORMAL_EXPOSURE, "混合退出：高点回吐8%全降"
        if relative_lead >= 0.10 and "relative_half" not in cycle.half_flags:
            cycle.half_flags.add("relative_half")
            return target_half(current_target), "混合退出：领先10%先降半"
    elif rule.mode == "mix_repair_cost_time":
        abs_dd = abs(float(row["drawdown_from_high"]))
        if cycle.leveraged_days >= 252:
            return NORMAL_EXPOSURE, "混合退出：持有252日全降"
        if gross_profit > 0 and cycle.financing_interest >= gross_profit * 0.15:
            return NORMAL_EXPOSURE, "混合退出：融资利息达毛利润15%全降"
        if abs_dd <= 0.10 and "repair_half" not in cycle.half_flags:
            cycle.half_flags.add("repair_half")
            return target_half(current_target), "混合退出：回撤修复到10%先降半"
    elif rule.mode == "mix_slow_recover":
        recovered = price > row["sma200"] and math.isfinite(row["sma200_slope20"]) and row["sma200_slope20"] > 0
        if slow_count >= 2:
            cycle.slow_bear_streak += 1
            if "slow_half" not in cycle.half_flags:
                cycle.half_flags.add("slow_half")
                return target_half(current_target), "混合退出：慢熊结构先降半"
            if cycle.slow_bear_streak >= 10 and not recovered:
                return NORMAL_EXPOSURE, "混合退出：慢熊未恢复连续10日全降"
        elif recovered:
            cycle.slow_bear_streak = 0
    return None, ""


def simulate_strategy(
    symbol: str,
    frame: pd.DataFrame,
    entry_rule: EntryRule | None,
    exit_rule: ExitRule | None,
    buy_hold_values: np.ndarray | None,
    keep_daily: bool = False,
) -> dict[str, Any]:
    dates = [item.date() for item in frame["date"].dt.to_pydatetime()]
    open_prices = frame["open"].to_numpy(dtype=float)
    close_prices = frame["close"].to_numpy(dtype=float)
    account = base.init_account(float(open_prices[0]))
    values: list[float] = []
    exposure_values: list[float] = []
    debt_values: list[float] = []
    cycles: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    current_target = NORMAL_EXPOSURE
    cycle: CycleState | None = None
    entry_state = EntryState()
    cycle_count = 0

    records = frame.to_dict("records")
    for index, row in enumerate(records):
        date = dates[index]
        open_price = float(open_prices[index])
        close_price = float(close_prices[index])
        action = ""
        action_reason = ""
        trade = {"buy_value": 0.0, "sell_value": 0.0, "transaction_cost": 0.0, "borrowed": 0.0, "interest_repaid": 0.0, "principal_repaid": 0.0}

        if pending is not None:
            old_debt = account.debt_principal + account.accrued_interest
            trade = base.rebalance_to_target(account, open_price, float(pending["target"]))
            current_target = float(pending["target"])
            action_reason = str(pending["reason"])
            action = "buy_or_add" if trade["buy_value"] > 0 else "sell_or_deleverage" if trade["sell_value"] > 0 else "no_trade"
            if entry_rule is not None and exit_rule is not None and trade["buy_value"] > 0 and old_debt <= 1e-6:
                cycle_count += 1
                signal_index = int(pending["signal_index"])
                cycle = CycleState(
                    cycle_id=cycle_count,
                    entry_signal_date=dates[signal_index].isoformat(),
                    leverage_entry_date=date.isoformat(),
                    entry_price=open_price,
                    entry_equity=account.equity(open_price),
                    entry_buy_hold_equity=float(buy_hold_values[index]) if buy_hold_values is not None else account.equity(open_price),
                    entry_drawdown_pct=float(frame.iloc[signal_index]["drawdown_from_high"]) * 100,
                    entry_reason=action_reason,
                    high_equity=account.equity(open_price),
                )
            if cycle is not None:
                cycle.buy_value += trade["buy_value"]
                cycle.sell_value += trade["sell_value"]
                cycle.transaction_cost += trade["transaction_cost"]
                cycle.interest_repaid += trade["interest_repaid"]
                cycle.principal_repaid += trade["principal_repaid"]
                if trade["buy_value"] > 0 or trade["sell_value"] > 0:
                    cycle.level_events.append(f"{date.isoformat()} {action_reason} buy={trade['buy_value']:.2f} sell={trade['sell_value']:.2f}")
            if trade["sell_value"] > 0 and account.debt_principal + account.accrued_interest <= 1e-6:
                current_target = NORMAL_EXPOSURE
                if cycle is not None:
                    cycles.append(maybe_finish_cycle(cycle, account, open_price, dates[int(pending["signal_index"])].isoformat(), date.isoformat(), action_reason))
                    cycle = None
                    entry_state = EntryState()
            pending = None

        daily_interest = account.accrue_interest()
        equity = account.equity(close_price)
        exposure = account.actual_exposure(close_price)
        values.append(equity)
        exposure_values.append(exposure)
        debt_values.append(account.debt_principal)

        if cycle is not None:
            cycle.leveraged_days += 1
            cycle.high_equity = max(cycle.high_equity, equity)
            cycle.exposure_sum += exposure * 100 if math.isfinite(exposure) else 0.0
            cycle.max_actual_exposure_pct = max(cycle.max_actual_exposure_pct, exposure * 100 if math.isfinite(exposure) else 0.0)
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
                    "actual_exposure_pct": exposure * 100 if math.isfinite(exposure) else math.nan,
                    "target_exposure_pct": current_target * 100,
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
            target, reason = evaluate_exit_rule(exit_rule, cycle, account, current_target, close_price, row, float(buy_hold_values[index]))
            if target is not None and target < current_target - 1e-9:
                pending = {"target": target, "reason": reason, "signal_index": index}
                continue

        if cycle is None:
            abs_dd = abs(float(row["drawdown_from_high"]))
            if entry_rule.mode == "direct" and abs_dd >= 0.30:
                pending = {"target": MAX_TARGET_EXPOSURE, "reason": "回撤达到30%直接加到120%", "signal_index": index}
            elif entry_rule.mode == "rebound":
                if abs_dd >= 0.30:
                    entry_state.armed = True
                    entry_state.low_since_armed = min(entry_state.low_since_armed, close_price)
                if entry_state.armed and close_price >= entry_state.low_since_armed * 1.10:
                    pending = {"target": MAX_TARGET_EXPOSURE, "reason": "回撤30%后从低点反弹10%加到120%", "signal_index": index}
                if close_price >= float(row["rolling_high"]) * (1.0 - 1e-12):
                    entry_state = EntryState()

    if cycle is not None:
        cycles.append(maybe_finish_cycle(cycle, account, float(close_prices[-1]), dates[-1].isoformat(), dates[-1].isoformat(), "期末仍持有杠杆"))

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
        "cycles": cycles,
        "ledger_rows": ledger_rows,
        "metrics": metrics,
        "total_financing_interest": account.total_interest_paid,
        "total_transaction_cost": account.total_transaction_cost,
        "max_debt_principal": account.max_debt_principal,
        "average_actual_exposure_pct": float(np.nanmean(exposure_array) * 100),
        "max_actual_exposure_pct": float(np.nanmax(exposure_array) * 100),
        "leveraged_days": int(np.sum(debt_array > 1e-6)),
        "leveraged_time_ratio_pct": float(np.mean(debt_array > 1e-6) * 100),
        "trade_count": account.trade_count,
        "financing_interest_pct_gross_profit": float(account.total_interest_paid / gross_profit_before_interest * 100) if gross_profit_before_interest > 0 else math.nan,
        "final_debt_or_interest": float(account.debt_principal + account.accrued_interest),
    }


def metric_row(
    symbol: str,
    entry_rule: EntryRule | None,
    exit_rule: ExitRule | None,
    result: dict[str, Any],
    buy_hold_result: dict[str, Any],
    current_best_result: dict[str, Any] | None,
    curve: pd.DataFrame,
    buy_hold_curve: pd.DataFrame,
    current_best_curve: pd.DataFrame | None,
) -> dict[str, Any]:
    m = result["metrics"]
    bh = buy_hold_result["metrics"]
    cb = current_best_result["metrics"] if current_best_result is not None else None
    cagr_adv = m["CAGR_pct"] - bh["CAGR_pct"]
    current_best_cagr_diff = m["CAGR_pct"] - cb["CAGR_pct"] if cb is not None else math.nan
    dd_improve = abs(bh["max_drawdown_pct"]) - abs(m["max_drawdown_pct"])
    current_best_interest = current_best_result["total_financing_interest"] if current_best_result else math.nan
    current_best_days = current_best_result["leveraged_days"] if current_best_result else math.nan
    ret_2022 = period_return(curve, *PERIODS["2022慢熊"])
    bh_2022 = period_return(buy_hold_curve, *PERIODS["2022慢熊"])
    cb_2022 = period_return(current_best_curve, *PERIODS["2022慢熊"]) if current_best_curve is not None else math.nan
    leverage_days_reduction = (1.0 - result["leveraged_days"] / current_best_days) * 100 if current_best_days and current_best_days > 0 else math.nan
    interest_reduction = (1.0 - result["total_financing_interest"] / current_best_interest) * 100 if current_best_interest and current_best_interest > 0 else math.nan
    pass_hard = (
        cagr_adv > 0.5
        and dd_improve >= -1.0
        and ret_2022 - bh_2022 >= -2.0
        and (math.isnan(leverage_days_reduction) or leverage_days_reduction >= 30.0)
        and (math.isnan(interest_reduction) or interest_reduction >= 30.0)
        and result["final_debt_or_interest"] <= 1e-6
    )
    return {
        "symbol": symbol,
        "entry_id": "BUY_HOLD" if entry_rule is None else entry_rule.entry_id,
        "entry_label": "买入持有" if entry_rule is None else entry_rule.label,
        "exit_id": "BUY_HOLD" if exit_rule is None else exit_rule.exit_id,
        "exit_family": "买入持有" if exit_rule is None else exit_rule.family,
        "exit_label": "买入持有" if exit_rule is None else exit_rule.label,
        "net_CAGR_after_financing_pct": m["CAGR_pct"],
        "CAGR_advantage_vs_buy_hold": cagr_adv,
        "CAGR_diff_vs_current_best": current_best_cagr_diff,
        "cumulative_return_pct": m["cumulative_return_pct"],
        "max_drawdown_pct": m["max_drawdown_pct"],
        "max_drawdown_improvement_vs_buy_hold": dd_improve,
        "Calmar": m["Calmar"],
        "Sharpe": m["Sharpe"],
        "volatility_pct": m["volatility_pct"],
        "best_year": m["best_year"],
        "worst_year": m["worst_year"],
        "total_financing_interest": result["total_financing_interest"],
        "total_transaction_cost": result["total_transaction_cost"],
        "financing_interest_pct_gross_profit": result["financing_interest_pct_gross_profit"],
        "max_debt_principal": result["max_debt_principal"],
        "average_actual_exposure_pct": result["average_actual_exposure_pct"],
        "max_actual_exposure_pct": result["max_actual_exposure_pct"],
        "leveraged_days": result["leveraged_days"],
        "leveraged_days_reduction_vs_current_best_pct": leverage_days_reduction,
        "financing_interest_reduction_vs_current_best_pct": interest_reduction,
        "leveraged_time_ratio_pct": result["leveraged_time_ratio_pct"],
        "trade_count": result["trade_count"],
        "return_2022_pct": ret_2022,
        "buy_hold_return_2022_pct": bh_2022,
        "current_best_return_2022_pct": cb_2022,
        "return_2022_vs_buy_hold": ret_2022 - bh_2022,
        "return_2022_vs_current_best": ret_2022 - cb_2022 if math.isfinite(cb_2022) else math.nan,
        "final_debt_or_interest": result["final_debt_or_interest"],
        "pass_hard_filters_bool": bool(pass_hard),
        "pass_hard_filters_int": int(pass_hard),
        "pass_hard_filters": "是" if pass_hard else "否",
        "risk_for_return_warning": "是" if cagr_adv > 0.5 and dd_improve < -1.0 else "否",
        "long_financing_dependency_warning": "是" if result["leveraged_time_ratio_pct"] > 40 else "否",
        "slow_bear_failure_warning": "是" if ret_2022 - bh_2022 < -2.0 else "否",
        "debt_left_warning": "是" if result["final_debt_or_interest"] > 1e-6 else "否",
    }


def make_curve_rows(symbol: str, label: str, entry_id: str, exit_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    start = result["values"][0]
    return [
        {
            "symbol": symbol,
            "strategy_label": label,
            "entry_id": entry_id,
            "exit_id": exit_id,
            "date": date.isoformat(),
            "equity": value,
            "return_pct": (value / start - 1.0) * 100,
            "actual_exposure_pct": exposure * 100 if math.isfinite(exposure) else math.nan,
            "debt_principal": debt,
        }
        for date, value, exposure, debt in zip(result["dates"], result["values"], result["actual_exposure"], result["debt_principal"])
    ]


def build_period_rows(metrics_curves: dict[tuple[str, str, str], pd.DataFrame]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (symbol, entry_id, exit_id), curve in metrics_curves.items():
        label = curve["strategy_label"].iloc[0]
        for period, (start, end) in PERIODS.items():
            rows.append(
                {
                    "symbol": symbol,
                    "entry_id": entry_id,
                    "exit_id": exit_id,
                    "strategy_label": label,
                    "period": period,
                    "period_start": start or str(curve["date"].min().date()),
                    "period_end": end or str(curve["date"].max().date()),
                    "return_pct": period_return(curve, start, end),
                }
            )
    return rows


def plot_equity(curves: pd.DataFrame, charts_dir: Path) -> Path:
    symbols = list(dict.fromkeys(curves["symbol"]))
    fig, axes = plt.subplots(len(symbols), 1, figsize=(15, 4.2 * len(symbols)))
    if len(symbols) == 1:
        axes = [axes]
    for ax, symbol in zip(axes, symbols):
        sub = curves[curves["symbol"] == symbol].copy()
        sub["date"] = pd.to_datetime(sub["date"])
        for label, line in sub.groupby("strategy_label"):
            ax.plot(line["date"], line["return_pct"], label=label, linewidth=1.7)
        ax.axhline(0, color="#94a3b8", linewidth=0.8)
        ax.set_title(f"{symbol} 收益曲线", fontsize=13, fontweight="bold")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.grid(True, color="#e5e7eb")
        ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    path = charts_dir / "equity_curves.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_drawdown(curves: pd.DataFrame, charts_dir: Path) -> Path:
    symbols = list(dict.fromkeys(curves["symbol"]))
    fig, axes = plt.subplots(len(symbols), 1, figsize=(15, 4.2 * len(symbols)))
    if len(symbols) == 1:
        axes = [axes]
    for ax, symbol in zip(axes, symbols):
        sub = curves[curves["symbol"] == symbol].copy()
        sub["date"] = pd.to_datetime(sub["date"])
        for label, line in sub.groupby("strategy_label"):
            eq = line["equity"].to_numpy(dtype=float)
            dd = eq / np.maximum.accumulate(eq) - 1.0
            ax.plot(line["date"], dd * 100, label=label, linewidth=1.5)
        ax.axhline(0, color="#94a3b8", linewidth=0.8)
        ax.set_title(f"{symbol} 回撤曲线", fontsize=13, fontweight="bold")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.grid(True, color="#e5e7eb")
        ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    path = charts_dir / "drawdown_curves.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_period_bars(periods: pd.DataFrame, charts_dir: Path) -> Path:
    sub = periods[periods["period"].isin(["2020暴跌反弹", "2022慢熊", "2023-2025牛市"])].copy()
    focus = sub[sub["strategy_label"].str.contains("买入持有|当前最优|最佳", regex=True)].copy()
    if focus.empty:
        focus = sub
    fig, ax = plt.subplots(figsize=(14, 7))
    labels = focus["symbol"] + " / " + focus["period"] + " / " + focus["strategy_label"]
    colors = ["#16a34a" if value >= 0 else "#dc2626" for value in focus["return_pct"]]
    ax.barh(labels, focus["return_pct"], color=colors)
    ax.axvline(0, color="#64748b", linewidth=1)
    ax.set_title("阶段收益对比", fontsize=15, fontweight="bold")
    ax.set_xlabel("阶段收益 %")
    ax.grid(True, axis="x", color="#e5e7eb")
    fig.tight_layout()
    path = charts_dir / "period_return_bars.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_scatter(metrics: pd.DataFrame, charts_dir: Path) -> Path:
    sub = metrics[(metrics["entry_id"] != "BUY_HOLD") & (metrics["exit_id"] != "X_current_best")].copy()
    fig, ax = plt.subplots(figsize=(12, 7))
    for family, line in sub.groupby("exit_family"):
        ax.scatter(line["leveraged_days"], line["CAGR_advantage_vs_buy_hold"], label=family, alpha=0.7, s=45)
    ax.axhline(0.5, color="#16a34a", linestyle="--", linewidth=1)
    ax.set_title("杠杆天数 vs 年化优势", fontsize=15, fontweight="bold")
    ax.set_xlabel("杠杆天数")
    ax.set_ylabel("相对买入持有年化优势")
    ax.grid(True, color="#e5e7eb")
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    path = charts_dir / "leverage_days_vs_cagr.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_financing(metrics: pd.DataFrame, charts_dir: Path) -> Path:
    sub = metrics[(metrics["entry_id"] != "BUY_HOLD") & (metrics["exit_id"] != "X_current_best")].copy()
    fig, ax = plt.subplots(figsize=(12, 7))
    for family, line in sub.groupby("exit_family"):
        ax.scatter(line["total_financing_interest"], line["CAGR_advantage_vs_buy_hold"], label=family, alpha=0.7, s=45)
    ax.axhline(0.5, color="#16a34a", linestyle="--", linewidth=1)
    ax.set_title("融资利息 vs 年化优势", fontsize=15, fontweight="bold")
    ax.set_xlabel("总融资利息")
    ax.set_ylabel("相对买入持有年化优势")
    ax.grid(True, color="#e5e7eb")
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    path = charts_dir / "financing_cost_vs_advantage.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
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
            if isinstance(value, (float, int, np.floating, np.integer)):
                if key.endswith("_pct") or "advantage" in key or "improvement" in key or key.startswith("return_"):
                    formatted = base.pct(float(value), signed=("advantage" in key or "improvement" in key or key.startswith("return_2022_vs")))
                    if "advantage" in key or "improvement" in key or key.startswith("return_2022_vs"):
                        css = "good" if float(value) >= 0 else "bad"
                elif "interest" in key or "cost" in key or "debt" in key:
                    formatted = base.money(float(value))
                else:
                    formatted = f"{float(value):.4f}" if abs(float(value)) < 10 else f"{float(value):.2f}"
            else:
                formatted = str(value)
                if formatted == "是":
                    css = "warn"
            parts.append(f"<td class='{css}'>{html.escape(formatted)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def conclusions(metrics: pd.DataFrame) -> list[str]:
    candidates = metrics[(metrics["entry_id"] != "BUY_HOLD") & (metrics["exit_id"] != "X_current_best")].copy()
    if candidates.empty:
        return ["没有候选策略结果。"]
    best_2020 = candidates.sort_values("return_2022_vs_buy_hold", ascending=False).iloc[0]
    best_return = candidates.sort_values(["CAGR_advantage_vs_buy_hold", "Calmar"], ascending=False).iloc[0]
    best_days = candidates.sort_values(["leveraged_days_reduction_vs_current_best_pct", "CAGR_advantage_vs_buy_hold"], ascending=False).iloc[0]
    pass_count = int(candidates["pass_hard_filters_int"].sum())
    by_entry = candidates.groupby("entry_label")["CAGR_advantage_vs_buy_hold"].mean().sort_values(ascending=False)
    usj = candidates[candidates["symbol"].isin(DEFAULT_SYMBOLS)]
    grouped = usj.groupby(["entry_id", "exit_id"]).agg(
        symbols=("symbol", "nunique"),
        min_pass=("pass_hard_filters_int", "sum"),
        min_adv=("CAGR_advantage_vs_buy_hold", "min"),
        avg_adv=("CAGR_advantage_vs_buy_hold", "mean"),
    ).reset_index()
    robust = grouped[(grouped["symbols"] == len(DEFAULT_SYMBOLS)) & (grouped["min_pass"] == len(DEFAULT_SYMBOLS))]
    return [
        f"全样本年化收益最强的退出规则是「{best_return['exit_family']} / {best_return['exit_label']}」，对应入场为「{best_return['entry_label']}」，年化优势 {best_return['CAGR_advantage_vs_buy_hold']:.2f} 个百分点。",
        f"2022 慢熊相对买入持有表现最好的规则是「{best_2020['exit_family']} / {best_2020['exit_label']}」，2022 相对买入持有 {best_2020['return_2022_vs_buy_hold']:.2f} 个百分点。",
        f"最能减少杠杆天数的是「{best_days['exit_family']} / {best_days['exit_label']}」，杠杆天数相对当前最优减少 {best_days['leveraged_days_reduction_vs_current_best_pct']:.2f}%。",
        f"硬性通过标准下，共有 {pass_count} 个 品种×策略 组合合格。",
        f"两个入场平均年化优势排名：{'; '.join(f'{idx}: {val:.2f}' for idx, val in by_entry.items())}。",
        f"US500、USTEC、JP225 三个品种同时通过硬性标准的具体组合数量为 {len(robust)}。",
        "若通过组合数量很少，说明深跌加杠杆仍值得研究，但必须继续围绕退出和慢熊保护做精简验证。",
    ]


def main() -> None:
    args = parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    if args.include_validation:
        symbols.extend([item for item in VALIDATION_SYMBOLS if item not in symbols])
    unknown = [item for item in symbols if item not in base.SYMBOL_FILES]
    if unknown:
        raise SystemExit(f"Unknown symbols: {', '.join(unknown)}")

    entries = entry_rules()
    exits = exit_rules()
    frames = {symbol: enrich_frame(base.load_daily_from_m30(base.SYMBOL_FILES[symbol])) for symbol in symbols}

    metric_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    selected_curve_rows: list[dict[str, Any]] = []
    all_curve_map: dict[tuple[str, str, str], pd.DataFrame] = {}
    input_rows: list[dict[str, Any]] = []

    for symbol, frame in frames.items():
        input_rows.append(
            {
                "symbol": symbol,
                "data_start_date": str(frame.iloc[0]["date"].date()),
                "data_end_date": str(frame.iloc[-1]["date"].date()),
                "data_rows": len(frame),
                "data_source": str(base.SYMBOL_FILES[symbol]),
                "whether_adjusted_price_used": "否，使用 MT5 原始 M30 报价聚合",
                "financing_rate_annual_pct": FINANCING_RATE_ANNUAL * 100,
            }
        )
        buy_hold = simulate_strategy(symbol, frame, None, None, None, keep_daily=True)
        buy_hold_curve_rows = make_curve_rows(symbol, "买入持有", "BUY_HOLD", "BUY_HOLD", buy_hold)
        buy_hold_curve = pd.DataFrame(buy_hold_curve_rows)
        buy_hold_curve["date"] = pd.to_datetime(buy_hold_curve["date"])
        all_curve_map[(symbol, "BUY_HOLD", "BUY_HOLD")] = buy_hold_curve
        current_best = simulate_strategy(symbol, frame, entries[0], exits[0], buy_hold["values"], keep_daily=True)
        current_best_rows = make_curve_rows(symbol, "当前最优对照", entries[0].entry_id, exits[0].exit_id, current_best)
        current_best_curve = pd.DataFrame(current_best_rows)
        current_best_curve["date"] = pd.to_datetime(current_best_curve["date"])
        all_curve_map[(symbol, entries[0].entry_id, exits[0].exit_id)] = current_best_curve
        metric_rows.append(metric_row(symbol, None, None, buy_hold, buy_hold, None, buy_hold_curve, buy_hold_curve, None))
        metric_rows.append(metric_row(symbol, entries[0], exits[0], current_best, buy_hold, current_best, current_best_curve, buy_hold_curve, current_best_curve))
        for row in buy_hold["ledger_rows"]:
            ledger_rows.append({**row, "symbol": symbol, "strategy_label": "买入持有", "entry_id": "BUY_HOLD", "exit_id": "BUY_HOLD"})
        for row in current_best["ledger_rows"]:
            ledger_rows.append({**row, "symbol": symbol, "strategy_label": "当前最优对照", "entry_id": entries[0].entry_id, "exit_id": exits[0].exit_id})
        for cycle in current_best["cycles"]:
            cycle_rows.append({**cycle, "symbol": symbol, "entry_id": entries[0].entry_id, "entry_label": entries[0].label, "exit_id": exits[0].exit_id, "exit_family": exits[0].family, "exit_label": exits[0].label})

        for entry in entries:
            for exit_rule in exits[1:]:
                result = simulate_strategy(symbol, frame, entry, exit_rule, buy_hold["values"], keep_daily=False)
                curve_rows = make_curve_rows(symbol, f"{entry.entry_id}/{exit_rule.exit_id}", entry.entry_id, exit_rule.exit_id, result)
                curve = pd.DataFrame(curve_rows)
                curve["date"] = pd.to_datetime(curve["date"])
                all_curve_map[(symbol, entry.entry_id, exit_rule.exit_id)] = curve
                metric_rows.append(metric_row(symbol, entry, exit_rule, result, buy_hold, current_best, curve, buy_hold_curve, current_best_curve))
                for cycle in result["cycles"]:
                    cycle_rows.append({**cycle, "symbol": symbol, "entry_id": entry.entry_id, "entry_label": entry.label, "exit_id": exit_rule.exit_id, "exit_family": exit_rule.family, "exit_label": exit_rule.label})

    metrics = pd.DataFrame(metric_rows)
    period_rows = build_period_rows(all_curve_map)
    period_frame = pd.DataFrame(period_rows)
    candidate_metrics = metrics[(metrics["entry_id"] != "BUY_HOLD") & (metrics["exit_id"] != "X_current_best")].copy()
    rankings = candidate_metrics.sort_values(
        ["pass_hard_filters_int", "CAGR_advantage_vs_buy_hold", "return_2022_vs_buy_hold", "Calmar"],
        ascending=[False, False, False, False],
    )

    for symbol in symbols:
        selected = metrics[metrics["symbol"] == symbol].copy()
        selected_ids = [("BUY_HOLD", "BUY_HOLD"), (entries[0].entry_id, exits[0].exit_id)]
        best = selected[(selected["entry_id"] != "BUY_HOLD") & (selected["exit_id"] != "X_current_best")].sort_values(
            ["pass_hard_filters_int", "CAGR_advantage_vs_buy_hold", "return_2022_vs_buy_hold", "Calmar"],
            ascending=[False, False, False, False],
        ).head(2)
        selected_ids.extend(list(best[["entry_id", "exit_id"]].itertuples(index=False, name=None)))
        for entry_id, exit_id in dict.fromkeys(selected_ids):
            curve = all_curve_map[(symbol, entry_id, exit_id)].copy()
            label = "买入持有" if entry_id == "BUY_HOLD" else "当前最优对照" if exit_id == "X_current_best" else metrics[(metrics["symbol"] == symbol) & (metrics["entry_id"] == entry_id) & (metrics["exit_id"] == exit_id)].iloc[0]["exit_label"]
            curve["strategy_label"] = label
            selected_curve_rows.extend(curve.to_dict("records"))

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    avg_adv = float(candidate_metrics["CAGR_advantage_vs_buy_hold"].mean()) if not candidate_metrics.empty else 0.0
    symbol_slug = "-".join(symbols).lower()
    out_dir = base.REPORTS / f"leverage-exit-optimization-7pct_{symbol_slug}_avgadv{avg_adv:+.2f}_{timestamp}"
    tables_dir = out_dir / "tables"
    charts_dir = out_dir / "charts"
    tables_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    write_csv(tables_dir / "all_exit_tests.csv", metrics)
    write_csv(tables_dir / "per_symbol_rankings.csv", rankings)
    write_csv(tables_dir / "period_performance.csv", period_frame)
    write_csv(tables_dir / "leverage_cycle_logs.csv", cycle_rows)
    write_csv(tables_dir / "account_daily_ledger_selected.csv", ledger_rows)
    write_csv(tables_dir / "selected_equity_curves.csv", selected_curve_rows)
    write_csv(tables_dir / "input_manifest.csv", input_rows)

    selected_curves = pd.DataFrame(selected_curve_rows)
    selected_curves["date"] = pd.to_datetime(selected_curves["date"])
    chart_paths = [
        plot_equity(selected_curves, charts_dir),
        plot_drawdown(selected_curves, charts_dir),
        plot_period_bars(period_frame, charts_dir),
        plot_scatter(metrics, charts_dir),
        plot_financing(metrics, charts_dir),
    ]

    metric_columns = [
        ("symbol", "品种"),
        ("entry_label", "入场"),
        ("exit_family", "退出类"),
        ("exit_label", "退出规则"),
        ("net_CAGR_after_financing_pct", "年化"),
        ("CAGR_advantage_vs_buy_hold", "年化优势"),
        ("CAGR_diff_vs_current_best", "相对当前最优"),
        ("max_drawdown_pct", "最大回撤"),
        ("max_drawdown_improvement_vs_buy_hold", "回撤改善"),
        ("return_2022_vs_buy_hold", "2022相对买入持有"),
        ("return_2022_vs_current_best", "2022相对当前最优"),
        ("leveraged_days", "杠杆天数"),
        ("leveraged_days_reduction_vs_current_best_pct", "杠杆天数减少"),
        ("total_financing_interest", "融资利息"),
        ("financing_interest_reduction_vs_current_best_pct", "融资利息减少"),
        ("pass_hard_filters", "硬性通过"),
        ("risk_for_return_warning", "收益换风险"),
        ("slow_bear_failure_warning", "慢熊失效"),
    ]
    answers = conclusions(metrics)
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>深跌加杠杆后的退出优化测试</title>
  <style>
    body {{ margin:0; background:#f5f7fb; color:#111827; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; }}
    header {{ padding:28px 34px; background:#111827; color:white; }}
    h1 {{ margin:0 0 8px; font-size:28px; }}
    h2 {{ margin:0; padding:16px 18px; font-size:19px; border-bottom:1px solid #e5e7eb; }}
    .wrap {{ padding:22px 34px 42px; }}
    .card {{ background:white; border:1px solid #dde3ee; border-radius:8px; margin-bottom:18px; overflow:hidden; box-shadow:0 6px 18px rgba(15,23,42,.06); }}
    .pad {{ padding:18px; }}
    .scroll {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:8px 10px; border-bottom:1px solid #e5e7eb; text-align:right; white-space:nowrap; }}
    th:first-child,td:first-child {{ text-align:left; }}
    th {{ background:#f8fafc; color:#334155; position:sticky; top:0; }}
    img {{ display:block; width:100%; height:auto; }}
    .good {{ color:#15803d; font-weight:700; }}
    .bad {{ color:#dc2626; font-weight:700; }}
    .warn {{ color:#b45309; font-weight:700; }}
    li {{ margin-bottom:8px; line-height:1.7; }}
    code {{ background:#eef2ff; padding:2px 5px; border-radius:4px; }}
  </style>
</head>
<body>
<header>
  <h1>深跌加杠杆后的退出优化测试</h1>
  <div>固定入场：回撤30%直接加 / 回撤30%后反弹10%加；融资成本固定 7%；真实资产负债表口径。</div>
</header>
<main class="wrap">
  <section class="card"><h2>最终回答</h2><div class="pad"><ol>{''.join(f'<li>{html.escape(item)}</li>' for item in answers)}</ol></div></section>
  <section class="card"><h2>收益曲线</h2><img src="charts/equity_curves.png" alt="收益曲线"></section>
  <section class="card"><h2>回撤曲线</h2><img src="charts/drawdown_curves.png" alt="回撤曲线"></section>
  <section class="card"><h2>阶段收益</h2><img src="charts/period_return_bars.png" alt="阶段收益"></section>
  <section class="card"><h2>杠杆天数 vs 年化优势</h2><img src="charts/leverage_days_vs_cagr.png" alt="杠杆天数 vs 年化优势"></section>
  <section class="card"><h2>融资利息 vs 年化优势</h2><img src="charts/financing_cost_vs_advantage.png" alt="融资利息 vs 年化优势"></section>
  <section class="card"><h2>候选策略排名</h2><div class="scroll">{render_table(rankings, metric_columns, 80)}</div></section>
  <section class="card"><h2>输出文件</h2><div class="pad"><p>表格在 <code>tables/</code>，图表在 <code>charts/</code>。正式交易系统未修改。</p></div></section>
</main>
</body>
</html>"""
    (out_dir / "backtest_report.html").write_text(html_doc, encoding="utf-8")
    print(f"HTML report: {out_dir / 'backtest_report.html'}")
    print(f"Charts dir: {charts_dir}")
    print(f"Tables dir: {tables_dir}")
    print(f"Average candidate CAGR advantage vs buy-and-hold: {avg_adv:.4f} pct points")


if __name__ == "__main__":
    main()
