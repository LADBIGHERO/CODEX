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
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
REPORTS = ROOT / "reports"

INITIAL_CAPITAL = 100_000.0
TRADING_DAYS_PER_YEAR = 252
LOOKBACK_HIGH_DAYS = 252
FINANCING_RATE_ANNUAL = 0.07
NORMAL_EXPOSURE = 1.00
MAX_TARGET_EXPOSURE = 1.20
FORCED_EXPOSURE_LIMIT = 1.25
NEW_CYCLE_WAIT_DAYS = 252

COMMISSION_PER_FILL = 0.0002
SLIPPAGE_PER_FILL = 0.0010
SPREAD_PER_FILL = 0.0002
TRANSACTION_COST_RATE = COMMISSION_PER_FILL + SLIPPAGE_PER_FILL + SPREAD_PER_FILL

SYMBOL_FILES = {
    "US500": OUTPUTS / "mt5_US500_M30_20160612_20260612.csv",
    "USTEC": OUTPUTS / "mt5_USTEC_M30_20160614_20260614.csv",
    "JP225": OUTPUTS / "mt5_JP225_M30_20060614_20260614.csv",
    "MidDE50": OUTPUTS / "mt5_MidDE50_M30_20060614_20260614.csv",
    "TecDE30": OUTPUTS / "mt5_TecDE30_M30_20060614_20260614.csv",
}

ENTRY_FAMILIES = [
    "一次性加满",
    "线性分批",
    "前重型",
    "后重型",
    "非线性递增",
    "反弹确认后加",
    "时间分批",
    "波动率过滤",
]

EXIT_FAMILIES = [
    "回撤修复型",
    "镜像分档型",
    "盈利目标型",
    "趋势确认型",
    "时间退出型",
    "风险止损型",
    "融资成本退出型",
    "混合退出型",
]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class EntrySpec:
    entry_id: str
    family: str
    label: str
    mode: str
    thresholds: tuple[float, ...]
    adds: tuple[float, ...]
    rebound_pct: float = 0.0
    time_interval_days: int = 0
    vol_ratio: float = 0.0


@dataclass(frozen=True)
class ExitSpec:
    exit_id: str
    family: str
    label: str
    mode: str
    params: tuple[float, ...] = ()


@dataclass
class Account:
    cash: float = 0.0
    asset_units: float = 0.0
    debt_principal: float = 0.0
    accrued_interest: float = 0.0
    total_interest_paid: float = 0.0
    total_transaction_cost: float = 0.0
    trade_count: int = 0
    max_debt_principal: float = 0.0

    def asset_value(self, price: float) -> float:
        return self.asset_units * price

    def equity(self, price: float) -> float:
        return self.cash + self.asset_value(price) - self.debt_principal - self.accrued_interest

    def actual_exposure(self, price: float) -> float:
        equity = self.equity(price)
        if equity <= 0:
            return math.nan
        return self.asset_value(price) / equity

    def accrue_interest(self) -> float:
        if self.debt_principal <= 1e-9:
            return 0.0
        daily_interest = self.debt_principal * FINANCING_RATE_ANNUAL / TRADING_DAYS_PER_YEAR
        self.accrued_interest += daily_interest
        self.total_interest_paid += daily_interest
        return daily_interest


@dataclass
class EntryState:
    armed: bool = False
    armed_low: float = math.inf
    armed_date: str = ""


@dataclass
class Cycle:
    cycle_id: int
    entry_signal_date: str
    leverage_entry_date: str
    leverage_entry_reason: str
    entry_family: str
    entry_label: str
    exit_family: str
    exit_label: str
    entry_price: float
    entry_equity: float
    entry_drawdown_pct: float
    rolling_high_at_trigger: float
    close_at_trigger: float
    target_exposure_after_entry_pct: float
    triggered_levels: set[int] = field(default_factory=set)
    level_events: list[str] = field(default_factory=list)
    leveraged_days: int = 0
    exposure_sum: float = 0.0
    max_actual_exposure_pct: float = 0.0
    max_debt_principal: float = 0.0
    min_equity: float = math.inf
    financing_interest: float = 0.0
    transaction_cost: float = 0.0
    buy_value: float = 0.0
    sell_value: float = 0.0
    interest_repaid: float = 0.0
    principal_repaid: float = 0.0
    exit_signal_date: str = ""
    deleverage_exit_date: str = ""
    deleverage_exit_reason: str = ""
    exit_price: float = math.nan
    exit_equity: float = math.nan
    remaining_cash_after_exit: float = math.nan
    remaining_debt_after_exit: float = math.nan


def entry_specs() -> list[EntrySpec]:
    specs: list[EntrySpec] = []
    for threshold in (0.20, 0.25, 0.30):
        specs.append(
            EntrySpec(
                f"L_once_{int(threshold * 100)}",
                "一次性加满",
                f"回撤{threshold:.0%}一次加到120%",
                "once",
                (threshold,),
                (0.20,),
            )
        )
    threshold_sets = ((0.10, 0.20, 0.30, 0.40), (0.15, 0.25, 0.35, 0.45), (0.20, 0.30, 0.40, 0.50))
    family_adds = [
        ("线性分批", "linear", (0.05, 0.05, 0.05, 0.05)),
        ("前重型", "front", (0.08, 0.06, 0.04, 0.02)),
        ("后重型", "back", (0.02, 0.04, 0.06, 0.08)),
        ("非线性递增", "convex", (0.01, 0.03, 0.06, 0.10)),
    ]
    for thresholds in threshold_sets:
        tag = "_".join(str(int(item * 100)) for item in thresholds)
        for family, key, adds in family_adds:
            specs.append(
                EntrySpec(
                    f"L_{key}_{tag}",
                    family,
                    f"{'/'.join(str(int(item * 100)) for item in thresholds)}% 加 {'/'.join(str(int(item * 100)) for item in adds)}%",
                    "levels",
                    thresholds,
                    adds,
                )
            )
    for threshold, rebound, target in ((0.20, 0.05, 1.10), (0.25, 0.08, 1.15), (0.30, 0.10, 1.20)):
        specs.append(
            EntrySpec(
                f"L_rebound_{int(threshold * 100)}_{int(rebound * 100)}",
                "反弹确认后加",
                f"回撤{threshold:.0%}后反弹{rebound:.0%}加到{target:.0%}",
                "rebound",
                (threshold,),
                (target - NORMAL_EXPOSURE,),
                rebound_pct=rebound,
            )
        )
    for threshold, interval in ((0.20, 20), (0.25, 30), (0.30, 40)):
        specs.append(
            EntrySpec(
                f"L_time_{int(threshold * 100)}_{interval}",
                "时间分批",
                f"回撤{threshold:.0%}后每{interval}日加5%",
                "time",
                (threshold,),
                (0.05, 0.05, 0.05, 0.05),
                time_interval_days=interval,
            )
        )
    for threshold, target in ((0.20, 1.10), (0.25, 1.15), (0.30, 1.20)):
        specs.append(
            EntrySpec(
                f"L_vol_{int(threshold * 100)}_{int(target * 100)}",
                "波动率过滤",
                f"回撤{threshold:.0%}且波动回落加到{target:.0%}",
                "vol_filter",
                (threshold,),
                (target - NORMAL_EXPOSURE,),
                vol_ratio=1.20,
            )
        )
    return specs


def exit_specs() -> list[ExitSpec]:
    return [
        ExitSpec("D_repair_half", "回撤修复型", "修复到触发回撤一半", "repair_half"),
        ExitSpec("D_repair_10", "回撤修复型", "修复到10%回撤内", "repair_abs", (0.10,)),
        ExitSpec("D_repair_5", "回撤修复型", "修复到5%回撤内", "repair_abs", (0.05,)),
        ExitSpec("D_mirror_entry", "镜像分档型", "按加仓档位镜像降", "mirror_entry"),
        ExitSpec("D_mirror_40_30_20_10", "镜像分档型", "40/30/20/10逐档降", "mirror_fixed", (0.40, 0.30, 0.20, 0.10)),
        ExitSpec("D_mirror_30_20_10_5", "镜像分档型", "30/20/10/5逐档降", "mirror_fixed", (0.30, 0.20, 0.10, 0.05)),
        ExitSpec("D_profit_5_10", "盈利目标型", "盈利5%降半10%全降", "profit_ladder", (0.05, 0.10)),
        ExitSpec("D_profit_10_15", "盈利目标型", "盈利10%降半15%全降", "profit_ladder", (0.10, 0.15)),
        ExitSpec("D_profit_15_once", "盈利目标型", "盈利15%全降", "profit_once", (0.15,)),
        ExitSpec("D_trend_sma50_sma200", "趋势确认型", "站上50日降半200日全降", "trend_sma"),
        ExitSpec("D_trend_sma50_10d", "趋势确认型", "连续10日站上50日全降", "trend_sma50_10d"),
        ExitSpec("D_trend_high60", "趋势确认型", "创60日新高全降", "trend_high60"),
        ExitSpec("D_time_126", "时间退出型", "持有126日全降", "time", (126,)),
        ExitSpec("D_time_252", "时间退出型", "持有252日全降", "time", (252,)),
        ExitSpec("D_time_504", "时间退出型", "持有504日全降", "time", (504,)),
        ExitSpec("D_stop_5", "风险止损型", "加杠杆后再跌5%全降", "stop_from_entry", (0.05,)),
        ExitSpec("D_stop_8", "风险止损型", "加杠杆后再跌8%全降", "stop_from_entry", (0.08,)),
        ExitSpec("D_stop_worse_3", "风险止损型", "杠杆回撤相对恶化3%全降", "stop_worse", (0.03,)),
        ExitSpec("D_cost_equity_1", "融资成本退出型", "融资成本达权益1%全降", "cost_equity", (0.01,)),
        ExitSpec("D_cost_gross_20", "融资成本退出型", "融资成本达毛利润20%全降", "cost_gross", (0.20,)),
        ExitSpec("D_cost_net_negative", "融资成本退出型", "周期净利润转负全降", "cost_net_negative"),
        ExitSpec("D_mix_half_sma200", "混合退出型", "修复一半降半站上200日全降", "mix_half_sma200"),
        ExitSpec("D_mix_profit10_repair10", "混合退出型", "盈利10%降半修复到10%全降", "mix_profit_repair"),
        ExitSpec("D_mix_stop8_time252", "混合退出型", "再跌8%或252日全降", "mix_stop_time"),
    ]


def pct(value: float, digits: int = 2, signed: bool = False) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{float(value):.{digits}f}%"


def money(value: float) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    return f"{float(value):,.2f}"


def load_daily_from_m30(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    if "time_utc" not in raw.columns:
        raise ValueError(f"{path} 缺少 time_utc 字段")
    raw["time_utc"] = pd.to_datetime(raw["time_utc"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close"]:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.dropna(subset=["time_utc", "open", "high", "low", "close"]).copy()
    raw = raw[(raw[["open", "high", "low", "close"]] > 0).all(axis=1)]
    raw = raw.sort_values("time_utc")
    raw["date"] = raw["time_utc"].dt.date
    grouped = raw.groupby("date", sort=True)
    daily = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        first_m30_time=("time_utc", "first"),
        last_m30_time=("time_utc", "last"),
        m30_bar_count=("close", "size"),
    ).reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["rolling_high"] = daily["close"].rolling(LOOKBACK_HIGH_DAYS, min_periods=1).max()
    daily["drawdown_from_high"] = daily["close"] / daily["rolling_high"] - 1.0
    daily["daily_return"] = daily["close"].pct_change().fillna(0.0)
    daily["vol20"] = daily["daily_return"].rolling(20, min_periods=10).std() * math.sqrt(TRADING_DAYS_PER_YEAR)
    daily["vol252_median"] = daily["vol20"].rolling(252, min_periods=20).median()
    daily["sma50"] = daily["close"].rolling(50, min_periods=1).mean()
    daily["sma200"] = daily["close"].rolling(200, min_periods=1).mean()
    daily["high60"] = daily["close"].rolling(60, min_periods=1).max()
    daily["above_sma50"] = daily["close"] > daily["sma50"]
    daily["above_sma50_10d"] = daily["above_sma50"].rolling(10, min_periods=10).sum() >= 10
    return daily


def init_account(first_open: float) -> Account:
    account = Account(cash=INITIAL_CAPITAL)
    trade_value = INITIAL_CAPITAL / (1.0 + TRANSACTION_COST_RATE)
    cost = trade_value * TRANSACTION_COST_RATE
    account.cash = INITIAL_CAPITAL - trade_value - cost
    account.asset_units = trade_value / first_open
    account.total_transaction_cost = cost
    account.trade_count = 1
    return account


def rebalance_to_target(account: Account, price: float, target_exposure: float) -> dict[str, float]:
    target_exposure = min(max(target_exposure, NORMAL_EXPOSURE), MAX_TARGET_EXPOSURE)
    equity_before = account.equity(price)
    asset_before = account.asset_value(price)
    result = {
        "buy_value": 0.0,
        "sell_value": 0.0,
        "transaction_cost": 0.0,
        "borrowed": 0.0,
        "interest_repaid": 0.0,
        "principal_repaid": 0.0,
    }
    if equity_before <= 0 or price <= 0:
        return result

    current_exposure = asset_before / equity_before if equity_before > 0 else math.nan
    if not math.isfinite(current_exposure) or abs(target_exposure - current_exposure) < 1e-5:
        return result

    cost_rate = TRANSACTION_COST_RATE
    if target_exposure > current_exposure:
        target_asset = target_exposure * (equity_before + cost_rate * asset_before) / (1.0 + target_exposure * cost_rate)
    else:
        target_asset = target_exposure * (equity_before - cost_rate * asset_before) / (1.0 - target_exposure * cost_rate)
    target_asset = max(target_asset, 0.0)
    delta_asset = target_asset - asset_before

    if delta_asset > 1e-8:
        cost = delta_asset * cost_rate
        required_cash = delta_asset + cost
        if account.cash >= required_cash:
            account.cash -= required_cash
        else:
            borrowed = required_cash - account.cash
            account.cash = 0.0
            account.debt_principal += borrowed
            account.max_debt_principal = max(account.max_debt_principal, account.debt_principal)
            result["borrowed"] = borrowed
        account.asset_units += delta_asset / price
        result["buy_value"] = delta_asset
        result["transaction_cost"] = cost
    elif delta_asset < -1e-8:
        sell_value = -delta_asset
        cost = sell_value * cost_rate
        net_proceeds = sell_value - cost
        account.asset_units = max(account.asset_units - sell_value / price, 0.0)
        interest_paid = min(account.accrued_interest, net_proceeds)
        account.accrued_interest -= interest_paid
        net_proceeds -= interest_paid
        principal_paid = min(account.debt_principal, net_proceeds)
        account.debt_principal -= principal_paid
        net_proceeds -= principal_paid
        account.cash += max(net_proceeds, 0.0)
        result["sell_value"] = sell_value
        result["transaction_cost"] = cost
        result["interest_repaid"] = interest_paid
        result["principal_repaid"] = principal_paid

    account.total_transaction_cost += result["transaction_cost"]
    if result["buy_value"] > 0 or result["sell_value"] > 0:
        account.trade_count += 1
    return result


def max_drawdown(values: np.ndarray) -> float:
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0) * 100)


def cagr(values: np.ndarray, dates: list[dt.date]) -> float:
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return math.nan
    years = max((dates[-1] - dates[0]).days / 365.25, 1.0 / 365.25)
    return float(((values[-1] / values[0]) ** (1.0 / years) - 1.0) * 100)


def yearly_extremes(values: np.ndarray, dates: list[dt.date]) -> tuple[str, str]:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "equity": values})
    frame["ret"] = frame["equity"].pct_change().fillna(0.0)
    yearly = frame.groupby(frame["date"].dt.year)["ret"].apply(lambda item: (1.0 + item).prod() - 1.0)
    if yearly.empty:
        return "N/A", "N/A"
    best = int(yearly.idxmax())
    worst = int(yearly.idxmin())
    return f"{best}: {yearly.loc[best] * 100:.2f}%", f"{worst}: {yearly.loc[worst] * 100:.2f}%"


def summary_metrics(values: np.ndarray, dates: list[dt.date]) -> dict[str, float | str]:
    returns = values[1:] / values[:-1] - 1.0
    daily_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    volatility = daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
    sharpe = float(np.mean(returns) / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily_std > 0 else math.nan
    mdd = max_drawdown(values)
    cagr_value = cagr(values, dates)
    calmar = cagr_value / abs(mdd) if mdd < 0 and math.isfinite(cagr_value) else math.nan
    best_year, worst_year = yearly_extremes(values, dates)
    return {
        "cumulative_return_pct": float((values[-1] / values[0] - 1.0) * 100),
        "CAGR_pct": cagr_value,
        "max_drawdown_pct": mdd,
        "volatility_pct": volatility,
        "Sharpe": sharpe,
        "Calmar": calmar,
        "best_year": best_year,
        "worst_year": worst_year,
    }


def new_high_allows_cycle(close: float, rolling_high: float, index: int, last_delever_index: int | None) -> bool:
    if last_delever_index is None:
        return True
    return close >= rolling_high * (1.0 - 1e-12) or index - last_delever_index >= NEW_CYCLE_WAIT_DAYS


def desired_from_thresholds(
    entry: EntrySpec,
    abs_drawdown: float,
    current_target: float,
    triggered_levels: set[int],
) -> tuple[float | None, str, set[int]]:
    reached = {idx for idx, threshold in enumerate(entry.thresholds) if abs_drawdown >= threshold}
    new_levels = reached - triggered_levels
    if not new_levels:
        return None, "", triggered_levels
    triggered = set(triggered_levels) | new_levels
    desired = NORMAL_EXPOSURE + sum(entry.adds[idx] for idx in triggered if idx < len(entry.adds))
    desired = min(desired, MAX_TARGET_EXPOSURE)
    if desired <= current_target + 1e-9:
        return None, "", triggered_levels
    labels = ",".join(str(int(entry.thresholds[idx] * 100)) for idx in sorted(new_levels))
    return desired, f"回撤触发档位{labels}%", triggered


def evaluate_entry(
    entry: EntrySpec,
    state: EntryState,
    cycle: Cycle | None,
    current_target: float,
    triggered_levels: set[int],
    can_start: bool,
    index: int,
    date: dt.date,
    close: float,
    abs_drawdown: float,
    rolling_high: float,
    vol20: float,
    vol252_median: float,
) -> tuple[float | None, str, set[int]]:
    if cycle is None and not can_start:
        return None, "", triggered_levels

    if entry.mode == "once":
        if cycle is None and abs_drawdown >= entry.thresholds[0]:
            return MAX_TARGET_EXPOSURE, f"回撤达到{entry.thresholds[0]:.0%}一次性加满", {0}
        return None, "", triggered_levels

    if entry.mode == "levels":
        return desired_from_thresholds(entry, abs_drawdown, current_target, triggered_levels)

    if entry.mode == "rebound":
        threshold = entry.thresholds[0]
        if cycle is not None:
            return None, "", triggered_levels
        if abs_drawdown >= threshold:
            if not state.armed:
                state.armed = True
                state.armed_low = close
                state.armed_date = date.isoformat()
            else:
                state.armed_low = min(state.armed_low, close)
        if state.armed and close >= state.armed_low * (1.0 + entry.rebound_pct):
            state.armed = False
            target = min(NORMAL_EXPOSURE + entry.adds[0], MAX_TARGET_EXPOSURE)
            return target, f"回撤{threshold:.0%}后从低点反弹{entry.rebound_pct:.0%}确认", {0}
        if close >= rolling_high * (1.0 - 1e-12):
            state.armed = False
            state.armed_low = math.inf
        return None, "", triggered_levels

    if entry.mode == "time":
        threshold = entry.thresholds[0]
        if cycle is None:
            if abs_drawdown >= threshold:
                return min(NORMAL_EXPOSURE + entry.adds[0], MAX_TARGET_EXPOSURE), f"回撤{threshold:.0%}后时间分批首档", {0}
            return None, "", triggered_levels
        next_level = len(triggered_levels)
        if next_level < len(entry.adds) and cycle.leveraged_days >= entry.time_interval_days * next_level:
            triggered = set(triggered_levels)
            triggered.add(next_level)
            desired = NORMAL_EXPOSURE + sum(entry.adds[idx] for idx in triggered)
            desired = min(desired, MAX_TARGET_EXPOSURE)
            if desired > current_target + 1e-9:
                return desired, f"时间分批第{next_level + 1}档", triggered
        return None, "", triggered_levels

    if entry.mode == "vol_filter":
        threshold = entry.thresholds[0]
        vol_ok = math.isfinite(vol20) and math.isfinite(vol252_median) and vol20 <= vol252_median * entry.vol_ratio
        if cycle is None and abs_drawdown >= threshold and vol_ok:
            target = min(NORMAL_EXPOSURE + entry.adds[0], MAX_TARGET_EXPOSURE)
            return target, f"回撤{threshold:.0%}且波动率回落确认", {0}
        return None, "", triggered_levels

    return None, "", triggered_levels


def half_target(current_target: float) -> float:
    return max(NORMAL_EXPOSURE, NORMAL_EXPOSURE + (current_target - NORMAL_EXPOSURE) * 0.5)


def evaluate_exit(
    entry: EntrySpec,
    exit_spec: ExitSpec,
    cycle: Cycle,
    account: Account,
    current_target: float,
    index: int,
    close: float,
    abs_drawdown: float,
    sma50: float,
    sma200: float,
    high60: float,
    above_sma50_10d: bool,
) -> tuple[float | None, str]:
    equity = account.equity(close)
    cycle_net_profit = equity - cycle.entry_equity
    cycle_gross_profit = cycle_net_profit + cycle.financing_interest
    asset_return = close / cycle.entry_price - 1.0 if cycle.entry_price > 0 else 0.0

    mode = exit_spec.mode
    if mode == "repair_half":
        threshold = abs(cycle.entry_drawdown_pct / 100.0) * 0.5
        if abs_drawdown <= threshold:
            return NORMAL_EXPOSURE, f"回撤修复到触发回撤一半以内({threshold:.1%})"
    elif mode == "repair_abs":
        threshold = exit_spec.params[0]
        if abs_drawdown <= threshold:
            return NORMAL_EXPOSURE, f"回撤修复到{threshold:.0%}以内"
    elif mode == "mirror_entry":
        thresholds = entry.thresholds
        adds = entry.adds
        if not thresholds or not adds:
            return None, ""
        desired = NORMAL_EXPOSURE + sum(adds[idx] for idx, threshold in enumerate(thresholds) if idx < len(adds) and abs_drawdown >= threshold)
        desired = min(desired, MAX_TARGET_EXPOSURE)
        if desired < current_target - 1e-9:
            return desired, "按加杠杆档位镜像降杠杆"
    elif mode == "mirror_fixed":
        thresholds = exit_spec.params
        desired = NORMAL_EXPOSURE + 0.05 * sum(1 for threshold in thresholds if abs_drawdown >= threshold)
        desired = min(desired, MAX_TARGET_EXPOSURE)
        if desired < current_target - 1e-9:
            return desired, "固定回撤档位镜像降杠杆"
    elif mode == "profit_ladder":
        half_profit, full_profit = exit_spec.params
        if asset_return >= full_profit:
            return NORMAL_EXPOSURE, f"杠杆周期品种涨幅达到{full_profit:.0%}全降"
        if asset_return >= half_profit and current_target > NORMAL_EXPOSURE + 0.01:
            return half_target(current_target), f"杠杆周期品种涨幅达到{half_profit:.0%}降半"
    elif mode == "profit_once":
        if asset_return >= exit_spec.params[0]:
            return NORMAL_EXPOSURE, f"杠杆周期品种涨幅达到{exit_spec.params[0]:.0%}全降"
    elif mode == "trend_sma":
        if close > sma200:
            return NORMAL_EXPOSURE, "收盘站上200日均线全降"
        if close > sma50 and current_target > NORMAL_EXPOSURE + 0.01:
            return half_target(current_target), "收盘站上50日均线降半"
    elif mode == "trend_sma50_10d":
        if above_sma50_10d:
            return NORMAL_EXPOSURE, "连续10日站上50日均线全降"
    elif mode == "trend_high60":
        if close >= high60 * (1.0 - 1e-12):
            return NORMAL_EXPOSURE, "创60日收盘新高全降"
    elif mode == "time":
        if cycle.leveraged_days >= int(exit_spec.params[0]):
            return NORMAL_EXPOSURE, f"杠杆持有满{int(exit_spec.params[0])}日全降"
    elif mode == "stop_from_entry":
        threshold = exit_spec.params[0]
        if close <= cycle.entry_price * (1.0 - threshold):
            return NORMAL_EXPOSURE, f"加杠杆后继续下跌{threshold:.0%}全降"
    elif mode == "stop_worse":
        leveraged_return = equity / cycle.entry_equity - 1.0 if cycle.entry_equity > 0 else 0.0
        if leveraged_return < asset_return - exit_spec.params[0]:
            return NORMAL_EXPOSURE, "杠杆表现相对品种恶化超过3%全降"
    elif mode == "cost_equity":
        if equity > 0 and cycle.financing_interest >= equity * exit_spec.params[0]:
            return NORMAL_EXPOSURE, "融资成本达到当前权益1%全降"
    elif mode == "cost_gross":
        if cycle_gross_profit > 0 and cycle.financing_interest >= cycle_gross_profit * exit_spec.params[0]:
            return NORMAL_EXPOSURE, "融资成本达到周期毛利润20%全降"
    elif mode == "cost_net_negative":
        if cycle.leveraged_days >= 20 and cycle_net_profit < 0 and cycle.financing_interest > 0:
            return NORMAL_EXPOSURE, "融资后周期净利润转负全降"
    elif mode == "mix_half_sma200":
        if close > sma200:
            return NORMAL_EXPOSURE, "混合退出：站上200日均线全降"
        threshold = abs(cycle.entry_drawdown_pct / 100.0) * 0.5
        if abs_drawdown <= threshold and current_target > NORMAL_EXPOSURE + 0.01:
            return half_target(current_target), "混合退出：修复一半先降半"
    elif mode == "mix_profit_repair":
        if abs_drawdown <= 0.10:
            return NORMAL_EXPOSURE, "混合退出：修复到10%回撤内全降"
        if asset_return >= 0.10 and current_target > NORMAL_EXPOSURE + 0.01:
            return half_target(current_target), "混合退出：盈利10%先降半"
    elif mode == "mix_stop_time":
        if close <= cycle.entry_price * 0.92:
            return NORMAL_EXPOSURE, "混合退出：继续下跌8%止损全降"
        if cycle.leveraged_days >= 252:
            return NORMAL_EXPOSURE, "混合退出：持有252日全降"
    return None, ""


def close_cycle(cycle: Cycle, signal_date: str, exit_date: str, reason: str, price: float, account: Account) -> dict[str, Any]:
    cycle.exit_signal_date = signal_date
    cycle.deleverage_exit_date = exit_date
    cycle.deleverage_exit_reason = reason
    cycle.exit_price = price
    cycle.exit_equity = account.equity(price)
    cycle.remaining_cash_after_exit = account.cash
    cycle.remaining_debt_after_exit = account.debt_principal + account.accrued_interest
    avg_exposure = cycle.exposure_sum / cycle.leveraged_days if cycle.leveraged_days else math.nan
    net_profit = cycle.exit_equity - cycle.entry_equity
    gross_profit = net_profit + cycle.financing_interest
    return {
        "cycle_id": cycle.cycle_id,
        "entry_signal_date": cycle.entry_signal_date,
        "leverage_entry_date": cycle.leverage_entry_date,
        "entry_family": cycle.entry_family,
        "entry_label": cycle.entry_label,
        "exit_family": cycle.exit_family,
        "exit_label": cycle.exit_label,
        "leverage_entry_reason": cycle.leverage_entry_reason,
        "rolling_high_at_trigger": cycle.rolling_high_at_trigger,
        "close_at_trigger": cycle.close_at_trigger,
        "drawdown_from_high_pct": cycle.entry_drawdown_pct,
        "entry_price": cycle.entry_price,
        "entry_equity": cycle.entry_equity,
        "target_exposure_after_entry_pct": cycle.target_exposure_after_entry_pct,
        "exit_signal_date": cycle.exit_signal_date,
        "deleverage_exit_date": cycle.deleverage_exit_date,
        "deleverage_exit_reason": cycle.deleverage_exit_reason,
        "exit_price": cycle.exit_price,
        "exit_equity": cycle.exit_equity,
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
        "net_positive_after_financing": net_profit > 0,
        "remaining_cash_after_exit": cycle.remaining_cash_after_exit,
        "remaining_debt_after_exit": cycle.remaining_debt_after_exit,
        "debt_left_after_deleverage_warning": cycle.remaining_debt_after_exit > 1e-6,
        "level_events": " | ".join(cycle.level_events),
    }


def simulate(
    symbol: str,
    frame: pd.DataFrame,
    entry: EntrySpec | None,
    exit_spec: ExitSpec | None,
    keep_daily: bool = False,
) -> dict[str, Any]:
    dates = [item.date() for item in frame["date"].dt.to_pydatetime()]
    open_prices = frame["open"].to_numpy(dtype=float)
    close_prices = frame["close"].to_numpy(dtype=float)
    rolling_highs = frame["rolling_high"].to_numpy(dtype=float)
    drawdowns = frame["drawdown_from_high"].to_numpy(dtype=float)
    vol20_values = frame["vol20"].to_numpy(dtype=float)
    vol252_values = frame["vol252_median"].to_numpy(dtype=float)
    sma50_values = frame["sma50"].to_numpy(dtype=float)
    sma200_values = frame["sma200"].to_numpy(dtype=float)
    high60_values = frame["high60"].to_numpy(dtype=float)
    above_sma50_10d_values = frame["above_sma50_10d"].to_numpy(dtype=bool)
    account = init_account(float(open_prices[0]))
    values: list[float] = []
    actual_exposures: list[float] = []
    debt_values: list[float] = []
    interest_values: list[float] = []
    daily_rows: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    current_cycle: Cycle | None = None
    current_target = NORMAL_EXPOSURE
    pending: dict[str, Any] | None = None
    entry_state = EntryState()
    triggered_levels: set[int] = set()
    last_delever_index: int | None = None
    cycle_count = 0

    for index in range(len(frame)):
        open_price = float(open_prices[index])
        close_price = float(close_prices[index])
        rolling_high = float(rolling_highs[index])
        drawdown = float(drawdowns[index])
        abs_drawdown = abs(drawdown)
        vol20 = float(vol20_values[index]) if math.isfinite(float(vol20_values[index])) else math.nan
        vol252_median = float(vol252_values[index]) if math.isfinite(float(vol252_values[index])) else math.nan
        sma50 = float(sma50_values[index])
        sma200 = float(sma200_values[index])
        high60 = float(high60_values[index])
        above_sma50_10d = bool(above_sma50_10d_values[index])
        date = dates[index]
        action = ""
        action_reason = ""
        trade = {"buy_value": 0.0, "sell_value": 0.0, "transaction_cost": 0.0, "borrowed": 0.0, "interest_repaid": 0.0, "principal_repaid": 0.0}

        if pending is not None:
            old_debt = account.debt_principal + account.accrued_interest
            target = float(pending["target"])
            action_reason = str(pending["reason"])
            trade = rebalance_to_target(account, open_price, target)
            current_target = target
            action = "buy_or_add" if trade["buy_value"] > 0 else "sell_or_deleverage" if trade["sell_value"] > 0 else "no_trade"
            if entry is not None and exit_spec is not None and trade["buy_value"] > 0 and old_debt <= 1e-6 and account.debt_principal + account.accrued_interest > 1e-6:
                cycle_count += 1
                signal_index = int(pending["signal_index"])
                current_cycle = Cycle(
                    cycle_id=cycle_count,
                    entry_signal_date=dates[signal_index].isoformat(),
                    leverage_entry_date=date.isoformat(),
                    leverage_entry_reason=action_reason,
                    entry_family=entry.family,
                    entry_label=entry.label,
                    exit_family=exit_spec.family,
                    exit_label=exit_spec.label,
                    entry_price=open_price,
                    entry_equity=account.equity(open_price),
                    entry_drawdown_pct=float(drawdowns[signal_index]) * 100,
                    rolling_high_at_trigger=float(rolling_highs[signal_index]),
                    close_at_trigger=float(close_prices[signal_index]),
                    target_exposure_after_entry_pct=account.actual_exposure(open_price) * 100,
                    triggered_levels=set(pending.get("triggered_levels", set())),
                )
            if current_cycle is not None:
                if trade["buy_value"] > 0:
                    current_cycle.buy_value += trade["buy_value"]
                    current_cycle.level_events.append(f"{date.isoformat()} {action_reason} 买入 {trade['buy_value']:.2f}")
                if trade["sell_value"] > 0:
                    current_cycle.sell_value += trade["sell_value"]
                    current_cycle.interest_repaid += trade["interest_repaid"]
                    current_cycle.principal_repaid += trade["principal_repaid"]
                    current_cycle.level_events.append(f"{date.isoformat()} {action_reason} 卖出 {trade['sell_value']:.2f}")
                current_cycle.transaction_cost += trade["transaction_cost"]
                if pending.get("triggered_levels") is not None:
                    current_cycle.triggered_levels = set(pending["triggered_levels"])
                    triggered_levels = set(pending["triggered_levels"])
            if trade["sell_value"] > 0 and account.debt_principal + account.accrued_interest <= 1e-6:
                last_delever_index = index
                current_target = NORMAL_EXPOSURE
                triggered_levels = set()
                entry_state = EntryState()
                if current_cycle is not None:
                    cycles.append(close_cycle(current_cycle, dates[int(pending["signal_index"])].isoformat(), date.isoformat(), action_reason, open_price, account))
                    current_cycle = None
            pending = None

        daily_interest = account.accrue_interest()
        equity = account.equity(close_price)
        exposure = account.actual_exposure(close_price)
        values.append(equity)
        actual_exposures.append(exposure)
        debt_values.append(account.debt_principal)
        interest_values.append(account.accrued_interest)

        if current_cycle is not None:
            current_cycle.leveraged_days += 1
            current_cycle.exposure_sum += exposure * 100 if math.isfinite(exposure) else 0.0
            current_cycle.max_actual_exposure_pct = max(current_cycle.max_actual_exposure_pct, exposure * 100 if math.isfinite(exposure) else 0.0)
            current_cycle.max_debt_principal = max(current_cycle.max_debt_principal, account.debt_principal)
            current_cycle.min_equity = min(current_cycle.min_equity, equity)
            current_cycle.financing_interest += daily_interest

        if keep_daily:
            lhs_equity = account.cash + account.asset_value(close_price) - account.debt_principal - account.accrued_interest
            daily_rows.append(
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
                    "equity_identity_error": lhs_equity - equity,
                    "actual_exposure_pct": exposure * 100 if math.isfinite(exposure) else math.nan,
                    "target_exposure_pct": current_target * 100,
                    "action": action,
                    "action_reason": action_reason,
                    "buy_value": trade["buy_value"],
                    "sell_value": trade["sell_value"],
                    "borrowed": trade["borrowed"],
                    "interest_repaid": trade["interest_repaid"],
                    "principal_repaid": trade["principal_repaid"],
                    "transaction_cost": trade["transaction_cost"],
                }
            )

        if entry is None or exit_spec is None or index >= len(frame) - 1:
            continue

        if math.isfinite(exposure) and exposure > FORCED_EXPOSURE_LIMIT:
            pending = {"target": MAX_TARGET_EXPOSURE, "reason": "实际exposure超过125%强制降回120%", "signal_index": index}
            continue

        exit_target = None
        exit_reason = ""
        if current_cycle is not None:
            exit_target, exit_reason = evaluate_exit(
                entry,
                exit_spec,
                current_cycle,
                account,
                current_target,
                index,
                close_price,
                abs_drawdown,
                sma50,
                sma200,
                high60,
                above_sma50_10d,
            )
        if exit_target is not None and exit_target < current_target - 1e-9:
            pending = {"target": exit_target, "reason": exit_reason, "signal_index": index}
            continue

        can_start = new_high_allows_cycle(close_price, rolling_high, index, last_delever_index)
        target, reason, new_levels = evaluate_entry(
            entry,
            entry_state,
            current_cycle,
            current_target,
            triggered_levels,
            can_start,
            index,
            date,
            close_price,
            abs_drawdown,
            rolling_high,
            vol20,
            vol252_median,
        )
        if target is not None and target > current_target + 1e-9:
            pending = {"target": target, "reason": reason, "signal_index": index, "triggered_levels": new_levels}

    if current_cycle is not None:
        cycles.append(close_cycle(current_cycle, dates[-1].isoformat(), dates[-1].isoformat(), "期末仍持有杠杆", float(close_prices[-1]), account))

    value_array = np.array(values, dtype=float)
    exposure_array = np.array(actual_exposures, dtype=float)
    debt_array = np.array(debt_values, dtype=float)
    interest_array = np.array(interest_values, dtype=float)
    metrics = summary_metrics(value_array, dates)
    gross_profit_before_interest = value_array[-1] + account.total_interest_paid - value_array[0]
    return {
        "dates": dates,
        "values": value_array,
        "actual_exposure": exposure_array,
        "debt_principal": debt_array,
        "accrued_interest": interest_array,
        "daily_rows": daily_rows,
        "cycles": cycles,
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
    frame: pd.DataFrame,
    entry: EntrySpec | None,
    exit_spec: ExitSpec | None,
    result: dict[str, Any],
    buy_hold_metrics: dict[str, Any],
) -> dict[str, Any]:
    metrics = result["metrics"]
    cagr_adv = metrics["CAGR_pct"] - buy_hold_metrics["CAGR_pct"]
    mdd_improvement = abs(buy_hold_metrics["max_drawdown_pct"]) - abs(metrics["max_drawdown_pct"])
    calmar_adv = metrics["Calmar"] - buy_hold_metrics["Calmar"] if math.isfinite(metrics["Calmar"]) and math.isfinite(buy_hold_metrics["Calmar"]) else math.nan
    row = {
        "symbol": symbol,
        "entry_id": "BUY_HOLD" if entry is None else entry.entry_id,
        "entry_family": "买入持有" if entry is None else entry.family,
        "entry_label": "买入持有" if entry is None else entry.label,
        "exit_id": "BUY_HOLD" if exit_spec is None else exit_spec.exit_id,
        "exit_family": "买入持有" if exit_spec is None else exit_spec.family,
        "exit_label": "买入持有" if exit_spec is None else exit_spec.label,
        "data_start_date": str(frame.iloc[0]["date"].date()),
        "data_end_date": str(frame.iloc[-1]["date"].date()),
        "data_rows": len(frame),
        "financing_rate_annual_pct": FINANCING_RATE_ANNUAL * 100,
        "cumulative_return_pct": metrics["cumulative_return_pct"],
        "net_CAGR_after_financing_pct": metrics["CAGR_pct"],
        "CAGR_advantage_vs_buy_hold": cagr_adv,
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "max_drawdown_improvement_vs_buy_hold": mdd_improvement,
        "volatility_pct": metrics["volatility_pct"],
        "Sharpe": metrics["Sharpe"],
        "Calmar": metrics["Calmar"],
        "Calmar_advantage_vs_buy_hold": calmar_adv,
        "best_year": metrics["best_year"],
        "worst_year": metrics["worst_year"],
        "total_financing_interest": result["total_financing_interest"],
        "total_transaction_cost": result["total_transaction_cost"],
        "financing_interest_pct_gross_profit": result["financing_interest_pct_gross_profit"],
        "max_debt_principal": result["max_debt_principal"],
        "average_actual_exposure_pct": result["average_actual_exposure_pct"],
        "max_actual_exposure_pct": result["max_actual_exposure_pct"],
        "leveraged_days": result["leveraged_days"],
        "leveraged_time_ratio_pct": result["leveraged_time_ratio_pct"],
        "trade_count": result["trade_count"],
        "final_debt_or_interest": result["final_debt_or_interest"],
    }
    row["weak_advantage_warning"] = "是" if 0 < cagr_adv < 0.5 else "否"
    row["drawdown_worse_warning"] = "是" if mdd_improvement < -3 else "否"
    row["financing_sensitive_warning"] = "是" if math.isfinite(row["financing_interest_pct_gross_profit"]) and row["financing_interest_pct_gross_profit"] > 20 else "否"
    row["long_financing_dependency_warning"] = "是" if row["leveraged_time_ratio_pct"] > 40 else "否"
    row["debt_left_warning"] = "是" if row["final_debt_or_interest"] > 1e-6 else "否"
    return row


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def heatmap(ax: plt.Axes, pivot: pd.DataFrame, title: str, fmt: str = ".2f", cmap: str = "RdYlGn") -> None:
    data = pivot.reindex(index=EXIT_FAMILIES, columns=ENTRY_FAMILIES)
    values = data.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        ax.set_title(title)
        ax.axis("off")
        return
    if np.nanmin(values) < 0 < np.nanmax(values):
        norm = TwoSlopeNorm(vmin=np.nanmin(values), vcenter=0, vmax=np.nanmax(values))
        image = ax.imshow(values, cmap=cmap, norm=norm)
    else:
        image = ax.imshow(values, cmap=cmap)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xticks(range(len(ENTRY_FAMILIES)))
    ax.set_xticklabels(ENTRY_FAMILIES, rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(len(EXIT_FAMILIES)))
    ax.set_yticklabels(EXIT_FAMILIES, fontsize=9)
    for y in range(values.shape[0]):
        for x in range(values.shape[1]):
            value = values[y, x]
            if math.isfinite(value):
                ax.text(x, y, format(value, fmt), ha="center", va="center", fontsize=8, color="#111827")
    plt.colorbar(image, ax=ax, fraction=0.046, pad=0.04)


def plot_family_heatmaps(metrics: pd.DataFrame, charts_dir: Path) -> list[Path]:
    paths: list[Path] = []
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    grouped = leverage.groupby(["exit_family", "entry_family"]).agg(
        CAGR_advantage_vs_buy_hold=("CAGR_advantage_vs_buy_hold", "mean"),
        max_drawdown_pct=("max_drawdown_pct", "mean"),
        Calmar=("Calmar", "mean"),
    ).reset_index()
    specs = [
        ("CAGR_advantage_vs_buy_hold", "8×8 家族平均年化优势", "family_heatmap_cagr_advantage.png", ".2f", "RdYlGn"),
        ("max_drawdown_pct", "8×8 家族平均最大回撤", "family_heatmap_max_drawdown.png", ".1f", "RdYlGn_r"),
        ("Calmar", "8×8 家族平均 Calmar", "family_heatmap_calmar.png", ".2f", "RdYlGn"),
    ]
    for metric, title, filename, fmt, cmap in specs:
        fig, ax = plt.subplots(figsize=(15, 8.6))
        pivot = grouped.pivot(index="exit_family", columns="entry_family", values=metric)
        heatmap(ax, pivot, title, fmt, cmap)
        fig.tight_layout()
        path = charts_dir / filename
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def plot_symbol_heatmaps(metrics: pd.DataFrame, charts_dir: Path) -> Path:
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    symbols = list(dict.fromkeys(leverage["symbol"]))
    fig, axes = plt.subplots(len(symbols), 1, figsize=(15, 4.8 * len(symbols)))
    if len(symbols) == 1:
        axes = [axes]
    for ax, symbol in zip(axes, symbols):
        sub = leverage[leverage["symbol"] == symbol]
        grouped = sub.groupby(["exit_family", "entry_family"])["CAGR_advantage_vs_buy_hold"].mean().reset_index()
        pivot = grouped.pivot(index="exit_family", columns="entry_family", values="CAGR_advantage_vs_buy_hold")
        heatmap(ax, pivot, f"{symbol} 8×8 年化优势热力图", ".2f", "RdYlGn")
    fig.tight_layout()
    path = charts_dir / "per_symbol_family_cagr_heatmaps.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_selected_curves(curves: pd.DataFrame, charts_dir: Path) -> Path:
    symbols = list(dict.fromkeys(curves["symbol"]))
    fig, axes = plt.subplots(len(symbols), 1, figsize=(15, 4.2 * len(symbols)))
    if len(symbols) == 1:
        axes = [axes]
    for ax, symbol in zip(axes, symbols):
        sub = curves[curves["symbol"] == symbol].copy()
        sub["date"] = pd.to_datetime(sub["date"])
        for label, line in sub.groupby("curve_label"):
            ax.plot(line["date"], line["return_pct"], label=label, linewidth=1.8)
        ax.axhline(0, color="#94a3b8", linewidth=0.8)
        ax.set_title(f"{symbol} 买入持有 vs 优选组合", fontsize=13, fontweight="bold")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.legend(fontsize=8)
    fig.tight_layout()
    path = charts_dir / "selected_equity_curves.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_scatter(metrics: pd.DataFrame, charts_dir: Path) -> Path:
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    fig, ax = plt.subplots(figsize=(12, 7))
    for family, sub in leverage.groupby("entry_family"):
        ax.scatter(sub["max_drawdown_pct"], sub["CAGR_advantage_vs_buy_hold"], s=20, alpha=0.55, label=family)
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=1)
    ax.axhline(0.5, color="#16a34a", linestyle=":", linewidth=1)
    ax.set_title("年化优势 vs 最大回撤", fontsize=15, fontweight="bold")
    ax.set_xlabel("最大回撤（%）")
    ax.set_ylabel("相对买入持有年化优势（百分点）")
    ax.grid(True, color="#e5e7eb")
    ax.legend(ncol=4, fontsize=8)
    path = charts_dir / "cagr_advantage_vs_drawdown_scatter.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_financing_bars(metrics: pd.DataFrame, charts_dir: Path) -> Path:
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    grouped = leverage.groupby(["entry_family", "exit_family"]).agg(
        financing_interest_pct_gross_profit=("financing_interest_pct_gross_profit", "mean"),
        leveraged_time_ratio_pct=("leveraged_time_ratio_pct", "mean"),
    ).reset_index()
    grouped["family_pair"] = grouped["entry_family"] + " × " + grouped["exit_family"]
    grouped = grouped.sort_values("financing_interest_pct_gross_profit", ascending=False).head(25)
    fig, ax = plt.subplots(figsize=(13, 8))
    colors = ["#dc2626" if value > 20 else "#2563eb" for value in grouped["financing_interest_pct_gross_profit"]]
    ax.barh(grouped["family_pair"], grouped["financing_interest_pct_gross_profit"], color=colors)
    ax.axvline(20, color="#ef4444", linestyle="--", linewidth=1)
    ax.set_title("融资利息占毛利润比例最高的家族组合", fontsize=15, fontweight="bold")
    ax.set_xlabel("融资利息 / 毛利润（%）")
    ax.invert_yaxis()
    ax.grid(True, axis="x", color="#e5e7eb")
    path = charts_dir / "financing_interest_ratio_top.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_diagnostics(ledger: pd.DataFrame, charts_dir: Path) -> Path:
    if ledger.empty:
        path = charts_dir / "selected_balance_sheet_diagnostics.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "无诊断数据", ha="center", va="center")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path
    symbols = list(dict.fromkeys(ledger["symbol"]))
    fig, axes = plt.subplots(len(symbols), 1, figsize=(15, 4.0 * len(symbols)))
    if len(symbols) == 1:
        axes = [axes]
    for ax, symbol in zip(axes, symbols):
        sub = ledger[(ledger["symbol"] == symbol) & (ledger["curve_role"] == "best_cagr")].copy()
        if sub.empty:
            continue
        sub["date"] = pd.to_datetime(sub["date"])
        ax.plot(sub["date"], sub["actual_exposure_pct"], label="实际 exposure", color="#2563eb", linewidth=1.5)
        ax2 = ax.twinx()
        ax2.plot(sub["date"], sub["debt_principal"], label="借款本金", color="#dc2626", alpha=0.65, linewidth=1.2)
        ax2.plot(sub["date"], sub["accrued_interest"], label="累计未还利息", color="#f59e0b", alpha=0.65, linewidth=1.2)
        ax.axhline(100, color="#94a3b8", linewidth=0.8)
        ax.axhline(120, color="#64748b", linestyle="--", linewidth=0.8)
        ax.set_title(f"{symbol} 最佳年化组合：exposure / 借款 / 利息", fontsize=12, fontweight="bold")
        ax.set_ylabel("exposure %")
        ax2.set_ylabel("金额")
        lines, labels = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines + lines2, labels + labels2, fontsize=8, loc="upper left")
        ax.grid(True, color="#e5e7eb")
    fig.tight_layout()
    path = charts_dir / "selected_balance_sheet_diagnostics.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def render_table(rows: list[dict[str, Any]] | pd.DataFrame, columns: list[tuple[str, str]], limit: int | None = None) -> str:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if limit is not None:
        frame = frame.head(limit)
    parts = ["<table><thead><tr>"]
    for _, label in columns:
        parts.append(f"<th>{html.escape(label)}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in frame.iterrows():
        parts.append("<tr>")
        for key, _ in columns:
            value = row.get(key, "")
            css = ""
            if isinstance(value, (float, int, np.floating, np.integer)):
                if key.endswith("_pct") or "advantage" in key or "improvement" in key:
                    formatted = pct(float(value), signed=("advantage" in key or "improvement" in key))
                    if "advantage" in key or "improvement" in key:
                        css = "good" if float(value) >= 0 else "bad"
                elif "cost" in key or "interest" in key or "debt" in key or "principal" in key:
                    formatted = money(float(value))
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


def build_summaries(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    family = leverage.groupby(["symbol", "entry_family", "exit_family"]).agg(
        avg_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
        avg_max_drawdown=("max_drawdown_pct", "mean"),
        avg_Calmar=("Calmar", "mean"),
        avg_financing_interest=("total_financing_interest", "mean"),
        avg_financing_interest_pct_gross_profit=("financing_interest_pct_gross_profit", "mean"),
        combo_count=("entry_id", "count"),
    ).reset_index()
    all_family = leverage.groupby(["entry_family", "exit_family"]).agg(
        avg_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
        avg_max_drawdown=("max_drawdown_pct", "mean"),
        avg_Calmar=("Calmar", "mean"),
        avg_financing_interest=("total_financing_interest", "mean"),
        avg_financing_interest_pct_gross_profit=("financing_interest_pct_gross_profit", "mean"),
        combo_count=("entry_id", "count"),
    ).reset_index()
    all_family.insert(0, "symbol", "ALL")
    family = pd.concat([family, all_family], ignore_index=True)
    entry_summary = leverage.groupby("entry_family").agg(
        avg_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
        avg_max_drawdown=("max_drawdown_pct", "mean"),
        avg_Calmar=("Calmar", "mean"),
        avg_financing_interest=("total_financing_interest", "mean"),
        effective_count=("CAGR_advantage_vs_buy_hold", lambda item: int((item > 0.5).sum())),
        combo_count=("entry_id", "count"),
    ).reset_index().sort_values(["avg_CAGR_advantage", "avg_Calmar"], ascending=False)
    exit_summary = leverage.groupby("exit_family").agg(
        avg_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
        avg_max_drawdown=("max_drawdown_pct", "mean"),
        avg_Calmar=("Calmar", "mean"),
        avg_financing_interest=("total_financing_interest", "mean"),
        effective_count=("CAGR_advantage_vs_buy_hold", lambda item: int((item > 0.5).sum())),
        combo_count=("exit_id", "count"),
    ).reset_index().sort_values(["avg_CAGR_advantage", "avg_Calmar"], ascending=False)
    cross = leverage.groupby(["entry_id", "entry_family", "entry_label", "exit_id", "exit_family", "exit_label"]).agg(
        symbols_tested=("symbol", "nunique"),
        avg_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "mean"),
        min_CAGR_advantage=("CAGR_advantage_vs_buy_hold", "min"),
        avg_max_drawdown=("max_drawdown_pct", "mean"),
        avg_drawdown_improvement=("max_drawdown_improvement_vs_buy_hold", "mean"),
        avg_Calmar=("Calmar", "mean"),
        avg_financing_interest=("total_financing_interest", "mean"),
        effective_symbol_count=("CAGR_advantage_vs_buy_hold", lambda item: int((item > 0.5).sum())),
    ).reset_index()
    cross = cross.sort_values(["effective_symbol_count", "avg_CAGR_advantage", "avg_Calmar"], ascending=False)
    return family, entry_summary, exit_summary, cross


def make_conclusions(metrics: pd.DataFrame, entry_summary: pd.DataFrame, exit_summary: pd.DataFrame, family: pd.DataFrame, cross: pd.DataFrame) -> list[str]:
    leverage = metrics[metrics["entry_family"] != "买入持有"].copy()
    best_entry = entry_summary.iloc[0]
    best_exit = exit_summary.iloc[0]
    all_family = family[family["symbol"] == "ALL"].sort_values(["avg_CAGR_advantage", "avg_Calmar"], ascending=False)
    best_cell = all_family.iloc[0]
    us = leverage[leverage["symbol"].isin(["US500", "USTEC"])]
    us_group = us.groupby(["entry_id", "exit_id"]).agg(
        count=("symbol", "nunique"),
        min_adv=("CAGR_advantage_vs_buy_hold", "min"),
        avg_adv=("CAGR_advantage_vs_buy_hold", "mean"),
    ).reset_index()
    us_good = int(((us_group["count"] == 2) & (us_group["min_adv"] > 0.5)).sum())
    all_good = int((cross["effective_symbol_count"] >= 5).sum())
    high_return_bad_dd = leverage[(leverage["CAGR_advantage_vs_buy_hold"] > 0.5) & (leverage["max_drawdown_improvement_vs_buy_hold"] < -3)]
    high_cost = leverage[(leverage["CAGR_advantage_vs_buy_hold"] > 0.5) & (leverage["financing_interest_pct_gross_profit"] > 20)]
    def summary_value(frame: pd.DataFrame, column: str, name: str) -> float | None:
        sub = frame.loc[frame[column] == name, "avg_CAGR_advantage"]
        if sub.empty:
            return None
        return float(sub.iloc[0])

    front = summary_value(entry_summary, "entry_family", "前重型")
    back = summary_value(entry_summary, "entry_family", "后重型")
    rebound = summary_value(entry_summary, "entry_family", "反弹确认后加")
    direct_series = entry_summary[entry_summary["entry_family"].isin(["一次性加满", "线性分批"])]["avg_CAGR_advantage"]
    direct = float(direct_series.mean()) if not direct_series.empty else None
    time_exit = summary_value(exit_summary, "exit_family", "时间退出型")
    cost_exit = summary_value(exit_summary, "exit_family", "融资成本退出型")
    answers = [
        f"整体平均表现最好的加杠杆方式是「{best_entry['entry_family']}」，平均年化优势 {best_entry['avg_CAGR_advantage']:.2f} 个百分点。",
        f"整体平均表现最好的去杠杆方式是「{best_exit['exit_family']}」，平均年化优势 {best_exit['avg_CAGR_advantage']:.2f} 个百分点。",
        f"8×8 家族中平均最好的格子是「{best_cell['entry_family']} × {best_cell['exit_family']}」，平均年化优势 {best_cell['avg_CAGR_advantage']:.2f} 个百分点。",
        f"在 US500 和 USTEC 上同时年化优势超过 0.5 个百分点的具体组合数量为 {us_good} 个。",
        f"五个品种都达到年化优势超过 0.5 个百分点的组合数量为 {all_good} 个；若数量很少，说明策略仍有明显市场特征依赖。",
        f"收益高但最大回撤恶化超过 3 个百分点的组合共有 {len(high_return_bad_dd)} 个，需要谨慎过滤。",
        f"收益高但融资利息吃掉毛利润超过 20% 的组合共有 {len(high_cost)} 个，属于融资敏感组合。",
    ]
    if front is not None and back is not None:
        answers.append(f"前重型平均年化优势 {front:.2f}，后重型平均年化优势 {back:.2f}；数值更高的一侧更适合本轮深跌加杠杆设定。")
    else:
        answers.append("本轮只测试筛选后的少量组合，未同时覆盖前重型和后重型，不能比较二者优劣。")
    if rebound is not None and direct is not None:
        answers.append(f"反弹确认后加的平均年化优势 {rebound:.2f}，直接左侧加仓类平均年化优势 {direct:.2f}，可据此判断确认后加是否更稳。")
    else:
        answers.append("本轮筛选组合不足以完整比较反弹确认后加与直接左侧加仓。")
    if time_exit is not None and cost_exit is not None:
        answers.append(f"时间退出型平均年化优势 {time_exit:.2f}，融资成本退出型平均年化优势 {cost_exit:.2f}；两者用于观察坏周期损失控制是否有效。")
    else:
        answers.append("本轮筛选组合不足以完整比较时间退出型与融资成本退出型。")
    return answers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 7% financing leverage matrix research backtest.")
    parser.add_argument(
        "--symbols",
        default=",".join(SYMBOL_FILES.keys()),
        help="Comma-separated symbols to test. Available: " + ", ".join(SYMBOL_FILES.keys()),
    )
    parser.add_argument(
        "--top-combos-from",
        default="",
        help="Optional all_combinations_metrics.csv path. If set, only the top combos from that file are tested.",
    )
    parser.add_argument("--top-n", type=int, default=5, help="Number of top combos to reuse when --top-combos-from is set.")
    return parser.parse_args()


def load_selected_combos(path_text: str, top_n: int, entries: list[EntrySpec], exits: list[ExitSpec]) -> set[tuple[str, str]] | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        raise SystemExit(f"Top combo file not found: {path}")
    frame = pd.read_csv(path)
    required = {"entry_id", "exit_id", "CAGR_advantage_vs_buy_hold", "Calmar"}
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"Top combo file missing columns: {', '.join(sorted(missing))}")
    frame = frame[frame["entry_id"] != "BUY_HOLD"].copy()
    frame = frame.drop_duplicates(subset=["entry_id", "exit_id"])
    frame = frame.sort_values(["CAGR_advantage_vs_buy_hold", "Calmar"], ascending=False).head(top_n)
    entry_ids = {item.entry_id for item in entries}
    exit_ids = {item.exit_id for item in exits}
    combos: set[tuple[str, str]] = set()
    for _, row in frame.iterrows():
        entry_id = str(row["entry_id"])
        exit_id = str(row["exit_id"])
        if entry_id not in entry_ids or exit_id not in exit_ids:
            raise SystemExit(f"Unknown combo in top combo file: {entry_id} / {exit_id}")
        combos.add((entry_id, exit_id))
    if not combos:
        raise SystemExit(f"No usable combos found in {path}")
    return combos


def main() -> None:
    args = parse_args()
    selected_symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    unknown = [item for item in selected_symbols if item not in SYMBOL_FILES]
    if unknown:
        raise SystemExit(f"Unknown symbol(s): {', '.join(unknown)}. Available: {', '.join(SYMBOL_FILES)}")
    start_time = dt.datetime.now()
    entries = entry_specs()
    exits = exit_specs()
    selected_combos = load_selected_combos(args.top_combos_from, args.top_n, entries, exits)
    frames: dict[str, pd.DataFrame] = {}
    input_rows: list[dict[str, Any]] = []
    for symbol in selected_symbols:
        path = SYMBOL_FILES[symbol]
        frame = load_daily_from_m30(path)
        frames[symbol] = frame
        input_rows.append(
            {
                "symbol": symbol,
                "data_start_date": str(frame.iloc[0]["date"].date()),
                "data_end_date": str(frame.iloc[-1]["date"].date()),
                "data_rows": len(frame),
                "data_source": str(path),
                "whether_adjusted_price_used": "否，使用 MT5 原始 M30 报价聚合",
                "first_m30_time": str(frame.iloc[0]["first_m30_time"]),
                "last_m30_time": str(frame.iloc[-1]["last_m30_time"]),
                "m30_bar_count": int(frame["m30_bar_count"].sum()),
            }
        )

    metrics_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    buy_hold_by_symbol: dict[str, dict[str, Any]] = {}

    for symbol, frame in frames.items():
        buy_hold_result = simulate(symbol, frame, None, None, keep_daily=False)
        buy_hold_metrics = buy_hold_result["metrics"]
        buy_hold_by_symbol[symbol] = buy_hold_metrics
        metrics_rows.append(metric_row(symbol, frame, None, None, buy_hold_result, buy_hold_metrics))
        for entry in entries:
            for exit_spec in exits:
                if selected_combos is not None and (entry.entry_id, exit_spec.exit_id) not in selected_combos:
                    continue
                result = simulate(symbol, frame, entry, exit_spec, keep_daily=False)
                row = metric_row(symbol, frame, entry, exit_spec, result, buy_hold_metrics)
                metrics_rows.append(row)
                for cycle in result["cycles"]:
                    cycle = dict(cycle)
                    cycle.update(
                        {
                            "symbol": symbol,
                            "entry_id": entry.entry_id,
                            "exit_id": exit_spec.exit_id,
                            "financing_rate_annual_pct": FINANCING_RATE_ANNUAL * 100,
                        }
                    )
                    cycle_rows.append(cycle)

    metrics = pd.DataFrame(metrics_rows)
    family, entry_summary, exit_summary, cross = build_summaries(metrics)
    avg_adv = float(metrics[metrics["entry_family"] != "买入持有"]["CAGR_advantage_vs_buy_hold"].mean())
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    symbol_slug = "-".join(selected_symbols).lower()
    top_slug = f"_top{len(selected_combos)}" if selected_combos is not None else ""
    run_id = f"leverage-matrix-balance-sheet-7pct_{symbol_slug}{top_slug}_avgadv{avg_adv:+.2f}_{timestamp}"
    out_dir = REPORTS / run_id
    tables_dir = out_dir / "tables"
    charts_dir = out_dir / "charts"
    tables_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Pick curves after full matrix is known; rerun only selected combinations with daily ledger kept.
    selected_specs: list[dict[str, str]] = []
    for symbol in frames:
        sub = metrics[(metrics["symbol"] == symbol) & (metrics["entry_family"] != "买入持有")]
        best_cagr = sub.sort_values(["CAGR_advantage_vs_buy_hold", "Calmar"], ascending=False).iloc[0]
        best_calmar = sub.sort_values(["Calmar", "CAGR_advantage_vs_buy_hold"], ascending=False).iloc[0]
        selected_specs.append({"symbol": symbol, "entry_id": "BUY_HOLD", "exit_id": "BUY_HOLD", "curve_role": "buy_hold", "curve_label": f"{symbol} 买入持有"})
        selected_specs.append({"symbol": symbol, "entry_id": best_cagr["entry_id"], "exit_id": best_cagr["exit_id"], "curve_role": "best_cagr", "curve_label": f"{symbol} 最佳年化"})
        if best_calmar["entry_id"] != best_cagr["entry_id"] or best_calmar["exit_id"] != best_cagr["exit_id"]:
            selected_specs.append({"symbol": symbol, "entry_id": best_calmar["entry_id"], "exit_id": best_calmar["exit_id"], "curve_role": "best_calmar", "curve_label": f"{symbol} 最佳Calmar"})
    best_cross = cross.iloc[0]
    for symbol in frames:
        selected_specs.append({"symbol": symbol, "entry_id": best_cross["entry_id"], "exit_id": best_cross["exit_id"], "curve_role": "best_cross", "curve_label": f"{symbol} 综合最佳"})

    entry_map = {item.entry_id: item for item in entries}
    exit_map = {item.exit_id: item for item in exits}
    curve_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    seen_selection: set[tuple[str, str, str, str]] = set()
    for spec in selected_specs:
        key = (spec["symbol"], spec["entry_id"], spec["exit_id"], spec["curve_role"])
        if key in seen_selection:
            continue
        seen_selection.add(key)
        frame = frames[spec["symbol"]]
        if spec["entry_id"] == "BUY_HOLD":
            result = simulate(spec["symbol"], frame, None, None, keep_daily=True)
        else:
            result = simulate(spec["symbol"], frame, entry_map[spec["entry_id"]], exit_map[spec["exit_id"]], keep_daily=True)
        start_value = result["values"][0]
        for date, value in zip(result["dates"], result["values"]):
            curve_rows.append(
                {
                    "symbol": spec["symbol"],
                    "curve_role": spec["curve_role"],
                    "curve_label": spec["curve_label"],
                    "entry_id": spec["entry_id"],
                    "exit_id": spec["exit_id"],
                    "date": date.isoformat(),
                    "equity": value,
                    "return_pct": (value / start_value - 1.0) * 100,
                }
            )
        for row in result["daily_rows"]:
            row = dict(row)
            row.update({"symbol": spec["symbol"], "curve_role": spec["curve_role"], "curve_label": spec["curve_label"], "entry_id": spec["entry_id"], "exit_id": spec["exit_id"]})
            ledger_rows.append(row)

    write_csv(tables_dir / "all_combinations_metrics.csv", metrics)
    write_csv(tables_dir / "family_matrix_summary.csv", family)
    write_csv(tables_dir / "entry_method_summary.csv", entry_summary)
    write_csv(tables_dir / "exit_method_summary.csv", exit_summary)
    write_csv(tables_dir / "per_symbol_rankings.csv", metrics[metrics["entry_family"] != "买入持有"].sort_values(["symbol", "CAGR_advantage_vs_buy_hold", "Calmar"], ascending=[True, False, False]))
    write_csv(tables_dir / "cross_symbol_rankings.csv", cross)
    write_csv(tables_dir / "selected_equity_curves.csv", curve_rows)
    write_csv(tables_dir / "leverage_cycle_logs.csv", cycle_rows)
    write_csv(tables_dir / "account_daily_ledger_selected.csv", ledger_rows)
    write_csv(tables_dir / "input_manifest.csv", input_rows)

    chart_paths = []
    chart_paths.extend(plot_family_heatmaps(metrics, charts_dir))
    chart_paths.append(plot_symbol_heatmaps(metrics, charts_dir))
    chart_paths.append(plot_selected_curves(pd.DataFrame(curve_rows), charts_dir))
    chart_paths.append(plot_scatter(metrics, charts_dir))
    chart_paths.append(plot_financing_bars(metrics, charts_dir))
    chart_paths.append(plot_diagnostics(pd.DataFrame(ledger_rows), charts_dir))

    conclusions = make_conclusions(metrics, entry_summary, exit_summary, family, cross)
    metric_columns = [
        ("symbol", "品种"),
        ("entry_family", "加杠杆类"),
        ("entry_label", "加杠杆规则"),
        ("exit_family", "去杠杆类"),
        ("exit_label", "去杠杆规则"),
        ("net_CAGR_after_financing_pct", "融资后年化"),
        ("CAGR_advantage_vs_buy_hold", "年化优势"),
        ("max_drawdown_pct", "最大回撤"),
        ("max_drawdown_improvement_vs_buy_hold", "回撤改善"),
        ("Calmar", "Calmar"),
        ("total_financing_interest", "融资利息"),
        ("total_transaction_cost", "交易成本"),
        ("financing_interest_pct_gross_profit", "利息/毛利润"),
        ("max_debt_principal", "最大借款本金"),
        ("leveraged_days", "杠杆天数"),
        ("trade_count", "交易次数"),
        ("weak_advantage_warning", "弱优势"),
        ("drawdown_worse_warning", "回撤恶化"),
        ("financing_sensitive_warning", "融资敏感"),
    ]
    family_columns = [
        ("symbol", "范围"),
        ("entry_family", "加杠杆类"),
        ("exit_family", "去杠杆类"),
        ("avg_CAGR_advantage", "平均年化优势"),
        ("avg_max_drawdown", "平均最大回撤"),
        ("avg_Calmar", "平均Calmar"),
        ("avg_financing_interest", "平均融资利息"),
        ("avg_financing_interest_pct_gross_profit", "平均利息/毛利润"),
        ("combo_count", "组合数"),
    ]
    cycle_columns = [
        ("symbol", "品种"),
        ("entry_family", "加杠杆类"),
        ("exit_family", "去杠杆类"),
        ("leverage_entry_date", "加杠杆日"),
        ("deleverage_exit_date", "去杠杆日"),
        ("leverage_entry_reason", "加杠杆原因"),
        ("deleverage_exit_reason", "去杠杆原因"),
        ("leveraged_days", "杠杆天数"),
        ("cycle_buy_value", "买入金额"),
        ("cycle_sell_value", "卖出金额"),
        ("cycle_interest_repaid", "偿还利息"),
        ("cycle_principal_repaid", "偿还本金"),
        ("cycle_financing_interest", "累计融资利息"),
        ("cycle_net_profit_after_interest", "周期净利润"),
        ("remaining_debt_after_exit", "退出后剩余债务"),
        ("debt_left_after_deleverage_warning", "剩余债务警告"),
    ]

    top_metrics = metrics[metrics["entry_family"] != "买入持有"].sort_values(["CAGR_advantage_vs_buy_hold", "Calmar"], ascending=False).head(40)
    top_family = family[family["symbol"] == "ALL"].sort_values(["avg_CAGR_advantage", "avg_Calmar"], ascending=False).head(30)
    top_cross = cross.head(30)
    duration = (dt.datetime.now() - start_time).total_seconds()

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>7% 融资成本下的 8×8 杠杆策略矩阵实验</title>
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #111827; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }}
    header {{ padding: 28px 34px; background: #111827; color: white; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 0; padding: 16px 18px; font-size: 19px; border-bottom: 1px solid #e5e7eb; }}
    p {{ line-height: 1.7; }}
    .wrap {{ padding: 22px 34px 42px; }}
    .card {{ background: white; border: 1px solid #dde3ee; border-radius: 8px; margin: 0 0 18px; overflow: hidden; box-shadow: 0 6px 18px rgba(15,23,42,0.06); }}
    .pad {{ padding: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 7px; padding: 12px; }}
    .metric b {{ display:block; font-size:20px; margin-top:4px; }}
    .scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #f8fafc; color: #334155; position: sticky; top: 0; }}
    img {{ display: block; width: 100%; height: auto; }}
    .good {{ color: #15803d; font-weight: 700; }}
    .bad {{ color: #dc2626; font-weight: 700; }}
    .warn {{ color: #b45309; font-weight: 700; }}
    ol li {{ margin-bottom: 8px; line-height: 1.7; }}
    code {{ background:#eef2ff; padding:2px 5px; border-radius:4px; }}
  </style>
</head>
<body>
  <header>
    <h1>7% 融资成本下的 8×8 杠杆策略矩阵实验</h1>
    <div>真实资产负债表口径：借款买入、每日计息、卖出资产后先还利息再还本金。运行耗时 {duration:.1f} 秒。</div>
  </header>
  <main class="wrap">
    <section class="card"><h2>核心口径</h2><div class="pad">
      <p>本报告只用于一次性研究回测，不接真实交易，不自动下单，不修改正式交易系统。每个品种独立运行，只能交易自身。融资成本固定为 <code>7%</code> 年化，只对借款本金每日计息。真实权益每日按 <code>cash + asset_value - debt_principal - accrued_interest</code> 计算。</p>
      <div class="grid">
        <div class="metric">品种数<b>{len(frames)}</b></div>
        <div class="metric">杠杆组合数<b>{len(metrics) - len(frames)}</b></div>
        <div class="metric">加杠杆路径<b>{len(entries)}</b></div>
        <div class="metric">去杠杆路径<b>{len(exits)}</b></div>
      </div>
    </div></section>
    <section class="card"><h2>最终回答</h2><div class="pad"><ol>{''.join(f'<li>{html.escape(item)}</li>' for item in conclusions)}</ol></div></section>
    <section class="card"><h2>8×8 家族平均年化优势</h2><img src="charts/family_heatmap_cagr_advantage.png" alt="8×8 家族平均年化优势"></section>
    <section class="card"><h2>8×8 家族平均最大回撤</h2><img src="charts/family_heatmap_max_drawdown.png" alt="8×8 家族平均最大回撤"></section>
    <section class="card"><h2>8×8 家族平均 Calmar</h2><img src="charts/family_heatmap_calmar.png" alt="8×8 家族平均 Calmar"></section>
    <section class="card"><h2>每个品种 8×8 年化优势热力图</h2><img src="charts/per_symbol_family_cagr_heatmaps.png" alt="每个品种 8×8 年化优势热力图"></section>
    <section class="card"><h2>买入持有 vs 优选组合净值曲线</h2><img src="charts/selected_equity_curves.png" alt="买入持有 vs 优选组合净值曲线"></section>
    <section class="card"><h2>年化优势 vs 最大回撤</h2><img src="charts/cagr_advantage_vs_drawdown_scatter.png" alt="年化优势 vs 最大回撤"></section>
    <section class="card"><h2>融资利息占毛利润比例</h2><img src="charts/financing_interest_ratio_top.png" alt="融资利息占毛利润比例"></section>
    <section class="card"><h2>资产负债表诊断曲线</h2><img src="charts/selected_balance_sheet_diagnostics.png" alt="资产负债表诊断曲线"></section>
    <section class="card"><h2>全市场具体组合前 40</h2><div class="scroll">{render_table(top_metrics, metric_columns)}</div></section>
    <section class="card"><h2>8×8 家族汇总前 30</h2><div class="scroll">{render_table(top_family, family_columns)}</div></section>
    <section class="card"><h2>跨品种具体组合前 30</h2><div class="scroll">{render_table(top_cross, [
        ("entry_family", "加杠杆类"), ("entry_label", "加杠杆规则"), ("exit_family", "去杠杆类"), ("exit_label", "去杠杆规则"),
        ("effective_symbol_count", "有效品种数"), ("avg_CAGR_advantage", "平均年化优势"), ("min_CAGR_advantage", "最低年化优势"),
        ("avg_max_drawdown", "平均最大回撤"), ("avg_drawdown_improvement", "平均回撤改善"), ("avg_Calmar", "平均Calmar")
    ])}</div></section>
    <section class="card"><h2>杠杆周期日志样例</h2><div class="scroll">{render_table(pd.DataFrame(cycle_rows).head(120), cycle_columns)}</div></section>
    <section class="card"><h2>输出文件</h2><div class="pad">
      <p>CSV 表格保存在 <code>tables/</code>，PNG 图表保存在 <code>charts/</code>。完整组合指标、每日账户流水、杠杆周期日志都已落地到本地文件。</p>
    </div></section>
  </main>
</body>
</html>"""
    (out_dir / "backtest_report.html").write_text(html_doc, encoding="utf-8")

    print(f"HTML report: {out_dir / 'backtest_report.html'}")
    print(f"Charts dir: {charts_dir}")
    print(f"Tables dir: {tables_dir}")
    print(f"Average CAGR advantage vs buy-and-hold: {avg_adv:.4f} pct points")


if __name__ == "__main__":
    main()
