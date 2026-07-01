from __future__ import annotations

import argparse
import datetime as dt
import html
import math
import re
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
OUTPUTS = ROOT / "outputs"
REPORTS = ROOT / "reports"

INITIAL_CAPITAL = 100_000.0
LOOKBACK_DAYS = 20
COOLDOWN_COMPLETE_DAYS = 5
TAKE_PROFIT_PCT = 0.05
STOP_LOSS_PCT = 0.02
TRANSACTION_COST_PER_FILL = 0.0014
M30_FILE_PATTERN = re.compile(r"^mt5_([A-Za-z0-9]+)_M30_\d{8}_\d{8}\.csv$")

MAJOR_EQUITY_SYMBOLS = ["US500", "USTEC", "JP225", "XAUUSD", "US30", "DE40", "UK100", "US2000"]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    entry_session: dt.date
    entry_session_index: int
    entry_price: float
    lookback_start_date: dt.date
    lookback_end_date: dt.date
    lookback_start_close: float
    lookback_end_close: float
    lookback_return_pct: float
    take_profit_price: float
    stop_loss_price: float
    exit_time: pd.Timestamp
    exit_session: dt.date
    exit_session_index: int
    exit_price: float
    exit_reason: str
    same_bar_conflict: bool
    holding_bars: int
    holding_days: int
    gross_return_pct: float
    net_return_pct: float
    equity_after_trade: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research fixed TP5/SL2 previous-20-day direction strategy on local M30 files.")
    parser.add_argument("--outputs-dir", default=str(OUTPUTS), help="Directory containing mt5_*_M30_YYYYMMDD_YYYYMMDD.csv files.")
    return parser.parse_args()


def discover_inputs(outputs_dir: Path) -> list[tuple[str, Path]]:
    inputs: list[tuple[str, Path]] = []
    for path in sorted(outputs_dir.glob("mt5_*_M30_*.csv")):
        match = M30_FILE_PATTERN.match(path.name)
        if match:
            inputs.append((match.group(1), path))
    return inputs


def load_m30(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    columns = {str(column).lower(): column for column in raw.columns}
    required = ["open", "high", "low", "close"]
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(f"missing OHLC columns: {', '.join(missing)}")
    if "time_utc" in columns:
        timestamp = pd.to_datetime(raw[columns["time_utc"]], utc=True, errors="coerce").dt.tz_convert(None)
    elif "time" in columns:
        timestamp = pd.to_datetime(pd.to_numeric(raw[columns["time"]], errors="coerce"), unit="s", utc=True, errors="coerce").dt.tz_convert(None)
    else:
        raise ValueError("missing time_utc/time column")
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": pd.to_numeric(raw[columns["open"]], errors="coerce"),
            "high": pd.to_numeric(raw[columns["high"]], errors="coerce"),
            "low": pd.to_numeric(raw[columns["low"]], errors="coerce"),
            "close": pd.to_numeric(raw[columns["close"]], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
    frame["session"] = frame["timestamp"].dt.date
    return frame


def build_daily(frame: pd.DataFrame) -> pd.DataFrame:
    daily = (
        frame.groupby("session", sort=True)
        .agg(
            date=("timestamp", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            m30_rows=("close", "size"),
        )
        .reset_index()
    )
    daily["date"] = pd.to_datetime(daily["date"].dt.date)
    daily["session"] = pd.to_datetime(daily["session"]).dt.date
    return daily


def gross_return(direction: str, entry_price: float, exit_price: float) -> float:
    if direction == "long":
        return exit_price / entry_price - 1.0
    return entry_price / exit_price - 1.0


def net_return_from_gross(gross: float) -> float:
    return gross - 2 * TRANSACTION_COST_PER_FILL


def resolve_trade(
    symbol: str,
    direction: str,
    entry_row_index: int,
    entry_session_index: int,
    frame: pd.DataFrame,
    session_to_index: dict[dt.date, int],
    daily: pd.DataFrame,
    equity: float,
) -> Trade:
    entry_row = frame.iloc[entry_row_index]
    entry_price = float(entry_row["open"])
    entry_time = entry_row["timestamp"]
    entry_session = entry_row["session"]
    lookback_start_idx = entry_session_index - LOOKBACK_DAYS - 1
    lookback_end_idx = entry_session_index - 1
    lookback_start_close = float(daily.iloc[lookback_start_idx]["close"])
    lookback_end_close = float(daily.iloc[lookback_end_idx]["close"])
    lookback_return = lookback_end_close / lookback_start_close - 1.0

    if direction == "long":
        take_profit_price = entry_price * (1.0 + TAKE_PROFIT_PCT)
        stop_loss_price = entry_price * (1.0 - STOP_LOSS_PCT)
    else:
        take_profit_price = entry_price * (1.0 - TAKE_PROFIT_PCT)
        stop_loss_price = entry_price * (1.0 + STOP_LOSS_PCT)

    for row_index in range(entry_row_index, len(frame)):
        row = frame.iloc[row_index]
        high = float(row["high"])
        low = float(row["low"])
        if direction == "long":
            tp_hit = high >= take_profit_price
            sl_hit = low <= stop_loss_price
        else:
            tp_hit = low <= take_profit_price
            sl_hit = high >= stop_loss_price
        if tp_hit or sl_hit:
            same_bar_conflict = bool(tp_hit and sl_hit)
            exit_reason = "stop_loss" if sl_hit else "take_profit"
            exit_price = stop_loss_price if sl_hit else take_profit_price
            gross = gross_return(direction, entry_price, exit_price)
            net = net_return_from_gross(gross)
            exit_session = row["session"]
            exit_session_index = session_to_index[exit_session]
            return Trade(
                symbol=symbol,
                direction=direction,
                entry_time=entry_time,
                entry_session=entry_session,
                entry_session_index=entry_session_index,
                entry_price=entry_price,
                lookback_start_date=daily.iloc[lookback_start_idx]["session"],
                lookback_end_date=daily.iloc[lookback_end_idx]["session"],
                lookback_start_close=lookback_start_close,
                lookback_end_close=lookback_end_close,
                lookback_return_pct=lookback_return * 100.0,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                exit_time=row["timestamp"],
                exit_session=exit_session,
                exit_session_index=exit_session_index,
                exit_price=exit_price,
                exit_reason=exit_reason,
                same_bar_conflict=same_bar_conflict,
                holding_bars=row_index - entry_row_index + 1,
                holding_days=exit_session_index - entry_session_index + 1,
                gross_return_pct=gross * 100.0,
                net_return_pct=net * 100.0,
                equity_after_trade=equity * (1.0 + net),
            )

    last = frame.iloc[-1]
    exit_price = float(last["close"])
    gross = gross_return(direction, entry_price, exit_price)
    net = net_return_from_gross(gross)
    exit_session = last["session"]
    exit_session_index = session_to_index[exit_session]
    return Trade(
        symbol=symbol,
        direction=direction,
        entry_time=entry_time,
        entry_session=entry_session,
        entry_session_index=entry_session_index,
        entry_price=entry_price,
        lookback_start_date=daily.iloc[lookback_start_idx]["session"],
        lookback_end_date=daily.iloc[lookback_end_idx]["session"],
        lookback_start_close=lookback_start_close,
        lookback_end_close=lookback_end_close,
        lookback_return_pct=lookback_return * 100.0,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        exit_time=last["timestamp"],
        exit_session=exit_session,
        exit_session_index=exit_session_index,
        exit_price=exit_price,
        exit_reason="sample_end",
        same_bar_conflict=False,
        holding_bars=len(frame) - entry_row_index,
        holding_days=exit_session_index - entry_session_index + 1,
        gross_return_pct=gross * 100.0,
        net_return_pct=net * 100.0,
        equity_after_trade=equity * (1.0 + net),
    )


def run_symbol(symbol: str, path: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    frame = load_m30(path)
    daily = build_daily(frame)
    if len(daily) <= LOOKBACK_DAYS + 1:
        raise ValueError(f"not enough daily sessions: {len(daily)}")

    session_to_index = {session: idx for idx, session in enumerate(daily["session"])}
    first_row_by_session = frame.groupby("session", sort=True).head(1).reset_index()
    first_row_index = {row["session"]: int(row["index"]) for _, row in first_row_by_session.iterrows()}
    next_allowed_session_index = LOOKBACK_DAYS + 1
    equity = INITIAL_CAPITAL
    trades: list[Trade] = []
    equity_rows = [{"symbol": symbol, "date": daily.iloc[0]["date"], "equity": equity, "trade_number": 0}]

    session_index = LOOKBACK_DAYS + 1
    while session_index < len(daily):
        if session_index < next_allowed_session_index:
            session_index += 1
            continue
        current_session = daily.iloc[session_index]["session"]
        entry_row_index = first_row_index.get(current_session)
        if entry_row_index is None:
            session_index += 1
            continue
        lookback_start_close = float(daily.iloc[session_index - LOOKBACK_DAYS - 1]["close"])
        lookback_end_close = float(daily.iloc[session_index - 1]["close"])
        lookback_return = lookback_end_close / lookback_start_close - 1.0
        if lookback_return == 0 or not math.isfinite(lookback_return):
            session_index += 1
            continue
        direction = "long" if lookback_return > 0 else "short"
        trade = resolve_trade(symbol, direction, entry_row_index, session_index, frame, session_to_index, daily, equity)
        trades.append(trade)
        equity = trade.equity_after_trade
        equity_rows.append({"symbol": symbol, "date": pd.to_datetime(trade.exit_session), "equity": equity, "trade_number": len(trades)})
        if trade.exit_reason == "sample_end":
            break
        next_allowed_session_index = trade.exit_session_index + COOLDOWN_COMPLETE_DAYS + 1
        session_index = next_allowed_session_index

    trade_df = pd.DataFrame([trade.__dict__ for trade in trades])
    equity_df = pd.DataFrame(equity_rows)
    summary = summarize_symbol(symbol, path, frame, daily, trade_df, equity)
    return summary, trade_df, equity_df


def max_consecutive_losses(trades: pd.DataFrame) -> int:
    max_streak = 0
    current = 0
    for reason in trades["exit_reason"].tolist():
        if reason == "stop_loss":
            current += 1
            max_streak = max(max_streak, current)
        elif reason == "take_profit":
            current = 0
    return max_streak


def win_rate(values: pd.Series) -> float:
    if values.empty:
        return math.nan
    return float((values == "take_profit").mean() * 100.0)


def summarize_symbol(
    symbol: str,
    path: Path,
    frame: pd.DataFrame,
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    final_equity: float,
) -> dict[str, Any]:
    resolved = trades[trades["exit_reason"].isin(["take_profit", "stop_loss"])] if not trades.empty else pd.DataFrame()
    wins = int((resolved["exit_reason"] == "take_profit").sum()) if not resolved.empty else 0
    losses = int((resolved["exit_reason"] == "stop_loss").sum()) if not resolved.empty else 0
    long_trades = resolved[resolved["direction"] == "long"] if not resolved.empty else pd.DataFrame()
    short_trades = resolved[resolved["direction"] == "short"] if not resolved.empty else pd.DataFrame()
    return {
        "symbol": symbol,
        "data_start": frame["timestamp"].iloc[0],
        "data_end": frame["timestamp"].iloc[-1],
        "m30_rows": len(frame),
        "daily_sessions": len(daily),
        "input_file": str(path),
        "trade_count": int(len(trades)),
        "resolved_trade_count": int(len(resolved)),
        "win_count": wins,
        "loss_count": losses,
        "sample_end_count": int((trades["exit_reason"] == "sample_end").sum()) if not trades.empty else 0,
        "win_rate_pct": wins / len(resolved) * 100.0 if len(resolved) else math.nan,
        "long_trade_count": int(len(long_trades)),
        "long_win_rate_pct": win_rate(long_trades["exit_reason"]) if not long_trades.empty else math.nan,
        "short_trade_count": int(len(short_trades)),
        "short_win_rate_pct": win_rate(short_trades["exit_reason"]) if not short_trades.empty else math.nan,
        "same_bar_conflict_count": int(trades["same_bar_conflict"].sum()) if not trades.empty else 0,
        "avg_holding_bars": float(trades["holding_bars"].mean()) if not trades.empty else math.nan,
        "avg_holding_days": float(trades["holding_days"].mean()) if not trades.empty else math.nan,
        "avg_gross_return_pct": float(trades["gross_return_pct"].mean()) if not trades.empty else math.nan,
        "avg_net_return_pct": float(trades["net_return_pct"].mean()) if not trades.empty else math.nan,
        "total_net_return_pct": (final_equity / INITIAL_CAPITAL - 1.0) * 100.0,
        "final_equity": final_equity,
        "max_consecutive_losses": max_consecutive_losses(resolved) if not resolved.empty else 0,
    }


def build_direction_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    resolved = trades[trades["exit_reason"].isin(["take_profit", "stop_loss"])].copy()
    if resolved.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (symbol, direction), group in resolved.groupby(["symbol", "direction"], sort=True):
        rows.append(
            {
                "symbol": symbol,
                "direction": direction,
                "trade_count": len(group),
                "win_count": int((group["exit_reason"] == "take_profit").sum()),
                "loss_count": int((group["exit_reason"] == "stop_loss").sum()),
                "win_rate_pct": float((group["exit_reason"] == "take_profit").mean() * 100.0),
                "avg_gross_return_pct": float(group["gross_return_pct"].mean()),
                "avg_net_return_pct": float(group["net_return_pct"].mean()),
                "same_bar_conflict_count": int(group["same_bar_conflict"].sum()),
            }
        )
    return pd.DataFrame(rows)


def audit_results(input_manifest: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rows.append(
        {
            "check": "only_true_m30_files",
            "passed": bool(input_manifest["is_true_m30_file"].all()) if not input_manifest.empty else False,
            "details": f"{int(input_manifest['is_true_m30_file'].sum())}/{len(input_manifest)} true M30 files",
        }
    )
    if trades.empty:
        rows.append({"check": "non_overlapping_trades", "passed": True, "details": "no trades"})
        rows.append({"check": "cooldown_gap", "passed": True, "details": "no trades"})
        rows.append({"check": "lookback_available", "passed": True, "details": "no trades"})
        rows.append({"check": "same_bar_conflicts_are_losses", "passed": True, "details": "no conflicts"})
        return pd.DataFrame(rows)

    overlap_ok = True
    cooldown_ok = True
    min_gap = math.inf
    for _, group in trades.sort_values(["symbol", "entry_session_index"]).groupby("symbol"):
        previous_exit = None
        for trade in group.itertuples(index=False):
            if previous_exit is not None:
                gap = int(trade.entry_session_index) - int(previous_exit)
                min_gap = min(min_gap, gap)
                if gap < COOLDOWN_COMPLETE_DAYS + 1:
                    cooldown_ok = False
                if int(trade.entry_session_index) <= int(previous_exit):
                    overlap_ok = False
            previous_exit = int(trade.exit_session_index)
    rows.append({"check": "non_overlapping_trades", "passed": overlap_ok, "details": "entry session is after previous exit session"})
    rows.append(
        {
            "check": "cooldown_gap",
            "passed": cooldown_ok,
            "details": f"minimum entry-after-exit session gap = {min_gap if math.isfinite(min_gap) else 'N/A'}",
        }
    )
    lookback_ok = bool((trades["entry_session_index"] >= LOOKBACK_DAYS + 1).all())
    rows.append({"check": "lookback_available", "passed": lookback_ok, "details": f"entry_session_index >= {LOOKBACK_DAYS + 1}"})
    conflicts = trades[trades["same_bar_conflict"]]
    conflict_ok = conflicts.empty or bool((conflicts["exit_reason"] == "stop_loss").all())
    rows.append(
        {
            "check": "same_bar_conflicts_are_losses",
            "passed": conflict_ok,
            "details": f"{len(conflicts)} same-bar conflicts",
        }
    )
    return pd.DataFrame(rows)


def pct_axis() -> FuncFormatter:
    return FuncFormatter(lambda value, _: f"{value:.0f}%")


def plot_win_rate(summary: pd.DataFrame, charts_dir: Path) -> None:
    data = summary.sort_values("win_rate_pct", ascending=True)
    fig, ax = plt.subplots(figsize=(12, max(5, len(data) * 0.35)))
    colors = ["#16a34a" if value >= 50 else "#dc2626" for value in data["win_rate_pct"].fillna(0)]
    ax.barh(data["symbol"], data["win_rate_pct"], color=colors)
    ax.axvline(50, color="#334155", linewidth=0.9)
    ax.set_title("胜率：明确止盈/止损交易")
    ax.set_xlabel("胜率")
    ax.xaxis.set_major_formatter(pct_axis())
    ax.grid(axis="x", color="#e5e7eb")
    fig.tight_layout()
    fig.savefig(charts_dir / "win_rate_by_symbol.png", dpi=160)
    plt.close(fig)


def plot_long_short(direction_summary: pd.DataFrame, charts_dir: Path) -> None:
    if direction_summary.empty:
        return
    pivot = direction_summary.pivot(index="symbol", columns="direction", values="win_rate_pct").fillna(np.nan)
    pivot = pivot.reindex(sorted(pivot.index))
    fig, ax = plt.subplots(figsize=(13, max(5, len(pivot) * 0.36)))
    y = np.arange(len(pivot))
    width = 0.38
    long_values = pivot["long"] if "long" in pivot else pd.Series(np.nan, index=pivot.index)
    short_values = pivot["short"] if "short" in pivot else pd.Series(np.nan, index=pivot.index)
    ax.barh(y - width / 2, long_values, width, label="long", color="#2563eb")
    ax.barh(y + width / 2, short_values, width, label="short", color="#f97316")
    ax.axvline(50, color="#334155", linewidth=0.9)
    ax.set_yticks(y, pivot.index)
    ax.set_title("多空方向胜率")
    ax.set_xlabel("胜率")
    ax.xaxis.set_major_formatter(pct_axis())
    ax.grid(axis="x", color="#e5e7eb")
    ax.legend()
    fig.tight_layout()
    fig.savefig(charts_dir / "long_short_win_rate.png", dpi=160)
    plt.close(fig)


def plot_trade_count(summary: pd.DataFrame, charts_dir: Path) -> None:
    data = summary.sort_values("trade_count", ascending=True)
    fig, ax = plt.subplots(figsize=(12, max(5, len(data) * 0.35)))
    ax.barh(data["symbol"], data["trade_count"], color="#64748b")
    ax.set_title("交易次数")
    ax.set_xlabel("trade_count")
    ax.grid(axis="x", color="#e5e7eb")
    fig.tight_layout()
    fig.savefig(charts_dir / "trade_count_by_symbol.png", dpi=160)
    plt.close(fig)


def plot_equity_selected(equity_curves: pd.DataFrame, summary: pd.DataFrame, charts_dir: Path) -> None:
    if equity_curves.empty:
        return
    selected: list[str] = [symbol for symbol in MAJOR_EQUITY_SYMBOLS if symbol in set(equity_curves["symbol"])]
    if len(selected) < 8:
        top_count = summary.sort_values("trade_count", ascending=False)["symbol"].head(8).tolist()
        for symbol in top_count:
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= 8:
                break
    fig, ax = plt.subplots(figsize=(14, 7))
    for symbol in selected:
        data = equity_curves[equity_curves["symbol"] == symbol].sort_values("date")
        if data.empty:
            continue
        ax.plot(pd.to_datetime(data["date"]), data["equity"] / INITIAL_CAPITAL * 100.0 - 100.0, linewidth=1.4, label=symbol)
    ax.set_title("代表品种累计净收益曲线")
    ax.set_ylabel("累计净收益")
    ax.yaxis.set_major_formatter(pct_axis())
    ax.grid(True, color="#e5e7eb")
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(charts_dir / "equity_curves_selected.png", dpi=160)
    plt.close(fig)


def table_html(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "<p class='muted'>无数据</p>"
    data = frame.head(max_rows).copy() if max_rows else frame.copy()
    return data.to_html(index=False, escape=True, classes="data-table", border=0)


def build_report(
    output_dir: Path,
    input_manifest: pd.DataFrame,
    summary: pd.DataFrame,
    direction_summary: pd.DataFrame,
    trades: pd.DataFrame,
    audit: pd.DataFrame,
) -> None:
    css = """
    body { margin:0; background:#f1f5f9; color:#0f172a; font-family:"Microsoft YaHei","Segoe UI",sans-serif; }
    header { padding:28px 40px; background:#0f172a; color:white; }
    header h1 { margin:0 0 8px; font-size:28px; }
    header p { margin:0; color:#cbd5e1; }
    main { padding:28px 40px 60px; }
    section { background:white; border:1px solid #dbe4ef; border-radius:8px; margin:0 0 22px; overflow:hidden; }
    h2 { margin:0; padding:15px 18px; border-bottom:1px solid #e2e8f0; font-size:19px; }
    .content { padding:18px; }
    .note { background:#f8fafc; border-left:4px solid #2563eb; padding:12px 14px; margin-bottom:12px; }
    .warn { background:#fff7ed; border-left:4px solid #f97316; padding:12px 14px; margin-bottom:12px; }
    .chart { width:100%; max-width:1500px; display:block; margin:auto; border:1px solid #e2e8f0; border-radius:6px; }
    .scroll { overflow:auto; max-height:620px; }
    .data-table { border-collapse:collapse; width:100%; font-size:13px; }
    .data-table th { background:#f8fafc; text-align:left; color:#334155; }
    .data-table th, .data-table td { border-bottom:1px solid #e2e8f0; padding:8px 9px; white-space:nowrap; }
    .muted { color:#64748b; }
    """
    total_resolved = int(summary["resolved_trade_count"].sum()) if not summary.empty else 0
    total_wins = int(summary["win_count"].sum()) if not summary.empty else 0
    total_losses = int(summary["loss_count"].sum()) if not summary.empty else 0
    total_win_rate = total_wins / total_resolved * 100.0 if total_resolved else math.nan
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>TP5 SL2 Prev20 M30 胜率验证</title><style>{css}</style></head>
<body>
<header>
  <h1>全本地 M30：过去20日方向 + 5%止盈 / 2%止损</h1>
  <p>每天第一个 M30 开盘尝试开仓；过去20日涨做多、跌做空；止盈止损用 M30 高低点触发；两次交易间隔 5 个完整交易日。</p>
</header>
<main>
  <section><h2>总览</h2><div class="content">
    <p class="note">全样本明确止盈/止损交易 {total_resolved} 笔，止盈 {total_wins} 笔，止损 {total_losses} 笔，整体胜率 {total_win_rate:.2f}%。</p>
    <p class="warn">做空未计融资费/借券费；胜率按触发结果统计，收益表另扣每次进出各 {TRANSACTION_COST_PER_FILL:.2%} 成本。样本末尾强平交易不计入胜率。</p>
  </div></section>
  <section><h2>审计检查</h2><div class="content scroll">{table_html(audit)}</div></section>
  <section><h2>输入清单</h2><div class="content scroll">{table_html(input_manifest)}</div></section>
  <section><h2>品种汇总</h2><div class="content scroll">{table_html(summary)}</div></section>
  <section><h2>胜率图</h2><div class="content"><img class="chart" src="charts/win_rate_by_symbol.png" alt="胜率图"></div></section>
  <section><h2>多空方向胜率</h2><div class="content"><img class="chart" src="charts/long_short_win_rate.png" alt="多空方向胜率"></div></section>
  <section><h2>交易次数</h2><div class="content"><img class="chart" src="charts/trade_count_by_symbol.png" alt="交易次数"></div></section>
  <section><h2>代表品种净值曲线</h2><div class="content"><img class="chart" src="charts/equity_curves_selected.png" alt="净值曲线"></div></section>
  <section><h2>方向汇总</h2><div class="content scroll">{table_html(direction_summary)}</div></section>
  <section><h2>交易日志</h2><div class="content scroll">{table_html(trades, 500)}</div></section>
</main>
</body></html>
"""
    (output_dir / "backtest_report.html").write_text(html_text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    outputs_dir = Path(args.outputs_dir)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = REPORTS / f"tp5-sl2-prev20-all-local-m30_{timestamp}"
    charts_dir = output_dir / "charts"
    tables_dir = output_dir / "tables"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    input_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    all_trades: list[pd.DataFrame] = []
    all_equity: list[pd.DataFrame] = []
    inputs = discover_inputs(outputs_dir)

    for symbol, path in inputs:
        manifest_row = {
            "symbol": symbol,
            "path": str(path),
            "is_true_m30_file": bool(M30_FILE_PATTERN.match(path.name)),
            "status": "pending",
            "error": "",
        }
        try:
            summary, trades, equity_curve = run_symbol(symbol, path)
            summary_rows.append(summary)
            all_trades.append(trades)
            all_equity.append(equity_curve)
            manifest_row.update(
                {
                    "status": "tested",
                    "data_start": summary["data_start"],
                    "data_end": summary["data_end"],
                    "m30_rows": summary["m30_rows"],
                    "daily_sessions": summary["daily_sessions"],
                }
            )
            print(f"{symbol}: trades={summary['trade_count']}, win_rate={summary['win_rate_pct']:.2f}%")
        except Exception as exc:
            manifest_row.update({"status": "error", "error": str(exc)})
            print(f"ERROR {symbol}: {exc}")
        input_rows.append(manifest_row)

    input_manifest = pd.DataFrame(input_rows)
    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["win_rate_pct", "trade_count"], ascending=[False, False])
    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    equity_df = pd.concat(all_equity, ignore_index=True) if all_equity else pd.DataFrame()
    direction_summary = build_direction_summary(trades_df)
    audit = audit_results(input_manifest, trades_df)

    input_manifest.to_csv(tables_dir / "input_manifest.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv(tables_dir / "symbol_summary.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(tables_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
    direction_summary.to_csv(tables_dir / "direction_summary.csv", index=False, encoding="utf-8-sig")
    equity_df.to_csv(tables_dir / "equity_curves.csv", index=False, encoding="utf-8-sig")
    audit.to_csv(tables_dir / "audit_checks.csv", index=False, encoding="utf-8-sig")

    if not summary_df.empty:
        plot_win_rate(summary_df, charts_dir)
        plot_trade_count(summary_df, charts_dir)
    if not direction_summary.empty:
        plot_long_short(direction_summary, charts_dir)
    if not equity_df.empty and not summary_df.empty:
        plot_equity_selected(equity_df, summary_df, charts_dir)
    build_report(output_dir, input_manifest, summary_df, direction_summary, trades_df, audit)

    print(f"HTML report: {output_dir / 'backtest_report.html'}")
    print(f"PNG charts: {charts_dir}")
    print(f"CSV tables: {tables_dir}")


if __name__ == "__main__":
    main()
