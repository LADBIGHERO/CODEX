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
class RegimeParams:
    entry_ma_days: int = 100
    entry_ma_slope_days: int = 20
    entry_momentum_days: int = 126
    entry_breakout_days: int = 20
    entry_breakout_tolerance: float = 0.01
    exit_ma_days: int = 300
    exit_ma_slope_days: int = 20
    exit_confirm_days: int = 20

    @property
    def label(self) -> str:
        return (
            "大级别最小阻力状态策略："
            f"收盘价 > {self.entry_ma_days}日均线，"
            f"{self.entry_ma_days}日均线{self.entry_ma_slope_days}日斜率 >= 0，"
            f"{self.entry_momentum_days}日动量 > 0，"
            f"收盘价接近{self.entry_breakout_days}日新高；"
            f"连续{self.exit_confirm_days}日跌破{self.exit_ma_days}日均线且均线斜率 <= 0 时退出。"
        )


PARAMS = RegimeParams()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimum resistance regime winner research on QQQ/VOO proxies.")
    parser.add_argument("--symbols", default="QQQ_PROXY,VOO_PROXY", help="Comma-separated symbols.")
    return parser.parse_args()


def load_ohlc(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Date"], errors="coerce"),
            "open": pd.to_numeric(raw["Open"], errors="coerce"),
            "high": pd.to_numeric(raw["High"], errors="coerce"),
            "low": pd.to_numeric(raw["Low"], errors="coerce"),
            "close": pd.to_numeric(raw["Close"], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    return add_features(frame)


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    needed = {
        PARAMS.entry_ma_days,
        PARAMS.entry_momentum_days,
        PARAMS.entry_breakout_days,
        PARAMS.exit_ma_days,
    }
    for days in sorted(needed):
        data[f"ma{days}"] = data["close"].rolling(days, min_periods=days).mean()
        data[f"high{days}"] = data["close"].shift(1).rolling(days, min_periods=days).max()
        data[f"mom{days}"] = data["close"] / data["close"].shift(days) - 1.0
    return data


def buy_hold(frame: pd.DataFrame) -> pd.DataFrame:
    units = INITIAL_CAPITAL / (float(frame.iloc[0]["open"]) * (1.0 + TRANSACTION_COST_RATE))
    return pd.DataFrame({"date": frame["date"], "buy_hold_equity": units * frame["close"].astype(float)})


def compute_signals(frame: pd.DataFrame, params: RegimeParams) -> pd.DataFrame:
    data = frame.copy()
    entry_ma = data[f"ma{params.entry_ma_days}"]
    exit_ma = data[f"ma{params.exit_ma_days}"]
    entry_slope = entry_ma / entry_ma.shift(params.entry_ma_slope_days) - 1.0
    exit_slope = exit_ma / exit_ma.shift(params.exit_ma_slope_days) - 1.0
    momentum = data[f"mom{params.entry_momentum_days}"]
    prior_high = data[f"high{params.entry_breakout_days}"]

    data["entry_signal"] = (
        (data["close"] > entry_ma)
        & (entry_slope >= 0)
        & (momentum > 0)
        & (data["close"] >= prior_high * (1.0 - params.entry_breakout_tolerance))
    ).fillna(False)

    raw_exit = ((data["close"] < exit_ma) & (exit_slope <= 0)).fillna(False)
    data["raw_exit_signal"] = raw_exit
    data["exit_signal"] = raw_exit.rolling(params.exit_confirm_days, min_periods=params.exit_confirm_days).sum() >= params.exit_confirm_days
    return data


def run_strategy(symbol: str, frame: pd.DataFrame, params: RegimeParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = compute_signals(frame, params)
    cash = INITIAL_CAPITAL
    units = 0.0
    position = False
    pending: str | None = None
    entry_date: pd.Timestamp | None = None
    entry_price = math.nan
    entry_equity = math.nan
    entry_signal_date: pd.Timestamp | None = None
    exit_signal_count = 0
    ledger: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for idx, row in data.iterrows():
        date = row["date"]
        open_price = float(row["open"])
        close_price = float(row["close"])

        if pending == "buy" and not position:
            units = cash / (open_price * (1.0 + TRANSACTION_COST_RATE))
            entry_cost = cash - units * open_price
            entry_equity = cash
            cash = 0.0
            position = True
            entry_date = date
            entry_price = open_price
            trade_entry_signal_date = entry_signal_date
            trade_entry_cost = entry_cost
        elif pending == "sell" and position:
            gross = units * open_price
            exit_cost = gross * TRANSACTION_COST_RATE
            cash = gross - exit_cost
            trade_return = cash / entry_equity - 1.0
            trades.append(
                {
                    "symbol": symbol,
                    "entry_signal_date": trade_entry_signal_date,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_signal_date": exit_signal_date,
                    "exit_date": date,
                    "exit_price": open_price,
                    "exit_reason": f"{params.exit_confirm_days}日慢熊确认",
                    "holding_days": (date - entry_date).days if entry_date is not None else math.nan,
                    "trade_return_pct": trade_return * 100.0,
                    "entry_cost": trade_entry_cost,
                    "exit_cost": exit_cost,
                }
            )
            units = 0.0
            position = False
            entry_date = None
            entry_price = math.nan
            entry_equity = math.nan
        pending = None

        equity = cash + units * close_price
        ledger.append(
            {
                "date": date,
                "strategy_equity": equity,
                "cash": cash,
                "asset_value": units * close_price,
                "position": 1 if position else 0,
                "entry_signal": bool(row["entry_signal"]),
                "exit_signal": bool(row["exit_signal"]),
            }
        )

        if idx + 1 >= len(data):
            continue
        if position:
            if bool(row["exit_signal"]):
                pending = "sell"
                exit_signal_date = date
        else:
            if bool(row["entry_signal"]):
                pending = "buy"
                entry_signal_date = date

    if position:
        last = data.iloc[-1]
        gross = units * float(last["close"])
        exit_cost = gross * TRANSACTION_COST_RATE
        cash = gross - exit_cost
        trade_return = cash / entry_equity - 1.0
        trades.append(
            {
                "symbol": symbol,
                "entry_signal_date": trade_entry_signal_date,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_signal_date": last["date"],
                "exit_date": last["date"],
                "exit_price": float(last["close"]),
                "exit_reason": "样本结束",
                "holding_days": (last["date"] - entry_date).days if entry_date is not None else math.nan,
                "trade_return_pct": trade_return * 100.0,
                "entry_cost": trade_entry_cost,
                "exit_cost": exit_cost,
            }
        )
        ledger[-1]["strategy_equity"] = cash
        ledger[-1]["cash"] = cash
        ledger[-1]["asset_value"] = 0.0
        ledger[-1]["position"] = 0

    return pd.DataFrame(ledger), pd.DataFrame(trades)


def years_between(dates: pd.Series) -> float:
    return max((pd.to_datetime(dates.iloc[-1]) - pd.to_datetime(dates.iloc[0])).days / 365.25, 1 / 365.25)


def max_drawdown_pct(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min() * 100.0)


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


def metrics(curve: pd.DataFrame, column: str, trades: pd.DataFrame | None = None) -> dict[str, Any]:
    equity = curve[column].astype(float)
    daily = equity.pct_change().fillna(0.0)
    years = years_between(curve["date"])
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    max_dd = max_drawdown_pct(equity)
    vol = daily.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = daily.mean() * TRADING_DAYS_PER_YEAR / (daily.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily.std(ddof=0) > 0 else math.nan
    calmar = cagr * 100.0 / abs(max_dd) if max_dd < 0 else math.nan
    annual = yearly_returns(curve, column)
    out = {
        "final_equity": equity.iloc[-1],
        "cumulative_return_pct": (equity.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0,
        "CAGR_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd,
        "volatility_pct": vol * 100.0,
        "Sharpe": sharpe,
        "Calmar": calmar,
        "best_year": annual.idxmax() if not annual.empty else "",
        "best_year_return_pct": annual.max() * 100.0 if not annual.empty else math.nan,
        "worst_year": annual.idxmin() if not annual.empty else "",
        "worst_year_return_pct": annual.min() * 100.0 if not annual.empty else math.nan,
    }
    if trades is not None:
        returns = trades["trade_return_pct"].astype(float) / 100.0 if not trades.empty else pd.Series(dtype=float)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        out.update(
            {
                "trade_count": int(len(returns)),
                "win_rate_pct": len(wins) / len(returns) * 100.0 if len(returns) else math.nan,
                "average_win_pct": wins.mean() * 100.0 if len(wins) else math.nan,
                "average_loss_pct": losses.mean() * 100.0 if len(losses) else math.nan,
                "profit_factor": wins.sum() / abs(losses.sum()) if abs(losses.sum()) > 0 else math.nan,
                "average_holding_days": trades["holding_days"].mean() if not trades.empty else math.nan,
                "time_in_market_pct": curve["position"].mean() * 100.0 if "position" in curve else math.nan,
            }
        )
    return out


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
    fig, axes = plt.subplots(len(curves), 2, figsize=(15, 4.5 * len(curves)), squeeze=False)
    for row_idx, (symbol, curve) in enumerate(curves.items()):
        strategy_return = curve["strategy_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        buy_hold_return = curve["buy_hold_equity"] / INITIAL_CAPITAL * 100.0 - 100.0
        ax = axes[row_idx][0]
        ax.plot(curve["date"], strategy_return, color="#2563eb", linewidth=1.4, label="最小阻力策略")
        ax.plot(curve["date"], buy_hold_return, color="#94a3b8", linewidth=1.2, label="买入持有")
        ax.set_title(f"{symbol} 收益曲线", loc="left", fontweight="bold")
        ax.yaxis.set_major_formatter(pct_axis())
        ax.grid(True, color="#e5e7eb")
        ax.legend()

        strategy_dd = curve["strategy_equity"] / curve["strategy_equity"].cummax() * 100.0 - 100.0
        buy_hold_dd = curve["buy_hold_equity"] / curve["buy_hold_equity"].cummax() * 100.0 - 100.0
        ax = axes[row_idx][1]
        ax.plot(curve["date"], strategy_dd, color="#dc2626", linewidth=1.2, label="最小阻力策略")
        ax.plot(curve["date"], buy_hold_dd, color="#64748b", linewidth=1.1, label="买入持有")
        ax.set_title(f"{symbol} 回撤曲线", loc="left", fontweight="bold")
        ax.yaxis.set_major_formatter(pct_axis())
        ax.grid(True, color="#e5e7eb")
        ax.legend()
    fig.tight_layout()
    fig.savefig(charts_dir / "equity_and_drawdown_curves.png", dpi=160)
    plt.close(fig)


def plot_bars(summary: pd.DataFrame, charts_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    axes[0].bar(summary["symbol"], summary["strategy_minus_buy_hold_CAGR_pct"], color="#16a34a")
    axes[0].axhline(0, color="#334155", linewidth=0.8)
    axes[0].set_title("年化收益优势")
    axes[0].set_ylabel("百分点")
    axes[0].grid(axis="y", color="#e5e7eb")

    axes[1].bar(summary["symbol"], summary["strategy_minus_buy_hold_max_drawdown_pct"], color="#2563eb")
    axes[1].axhline(0, color="#334155", linewidth=0.8)
    axes[1].set_title("最大回撤改善")
    axes[1].set_ylabel("百分点，正数表示回撤更浅")
    axes[1].grid(axis="y", color="#e5e7eb")
    fig.tight_layout()
    fig.savefig(charts_dir / "advantage_bars.png", dpi=160)
    plt.close(fig)


def table_html(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "<p class='muted'>无数据</p>"
    data = frame.head(max_rows).copy() if max_rows else frame.copy()
    return data.to_html(index=False, escape=True, classes="data-table", border=0)


def build_report(
    output_dir: Path,
    manifest: pd.DataFrame,
    summary: pd.DataFrame,
    periods: pd.DataFrame,
    trades: pd.DataFrame,
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
    .scroll { overflow:auto; max-height:560px; }
    .data-table { border-collapse:collapse; width:100%; font-size:13px; }
    .data-table th { background:#f8fafc; text-align:left; color:#334155; }
    .data-table th, .data-table td { border-bottom:1px solid #e2e8f0; padding:8px 9px; white-space:nowrap; }
    .muted { color:#64748b; }
    """
    wins = summary[
        (summary["strategy_minus_buy_hold_CAGR_pct"] > 0)
        & (summary["strategy_minus_buy_hold_max_drawdown_pct"] > 0)
    ]["symbol"].tolist()
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>最小阻力状态策略优化报告</title><style>{css}</style></head>
<body>
<header>
  <h1>最小阻力状态策略：QQQ / VOO 本地代理跑赢验证</h1>
  <p>使用本地 USTEC/^NDX 代理 QQQ，US500/^GSPC 代理 VOO。信号收盘后生成，次日开盘成交；每次成交成本 {TRANSACTION_COST_RATE:.2%}。</p>
</header>
<main>
  <section><h2>为什么上一版没跑赢</h2><div class="content">
    <p class="warn">上一版把“最小阻力”做成了短线突破回踩形态，持仓时间只有约 11%-13%。它能避开熊市，但也错过了指数长期主升浪，所以年化收益被买入持有远远甩开。</p>
    <p>本版改成状态策略：只要大方向仍然向上，就尽量持有；只有连续确认进入 300 日级别慢熊时才退出。也就是把“最小阻力”理解为长期推进方向，而不是单根 K 线形态。</p>
  </div></section>
  <section><h2>策略规则</h2><div class="content">
    <p class="note">{html.escape(PARAMS.label)}</p>
    <p>买入：满足入场条件后，次一交易日开盘 100% 买入当前品种。卖出：满足退出条件后，次一交易日开盘全部卖出。空仓时现金收益按 0 计算。不做空、不加杠杆、不轮动。</p>
  </div></section>
  <section><h2>是否跑赢</h2><div class="content">
    <p class="note">同时跑赢年化收益并降低最大回撤的品种：{html.escape(', '.join(wins) if wins else '无')}。</p>
  </div></section>
  <section><h2>数据清单</h2><div class="content scroll">{table_html(manifest)}</div></section>
  <section><h2>核心结果</h2><div class="content scroll">{table_html(summary)}</div></section>
  <section><h2>收益与回撤折线图</h2><div class="content"><img class="chart" src="charts/equity_and_drawdown_curves.png" alt="收益与回撤曲线"></div></section>
  <section><h2>优势柱状图</h2><div class="content"><img class="chart" src="charts/advantage_bars.png" alt="优势柱状图"></div></section>
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
        strategy_curve, trades = run_strategy(symbol, frame, PARAMS)
        buy_hold_curve = buy_hold(frame)
        merged = strategy_curve.merge(buy_hold_curve, on="date", how="left")
        curves[symbol] = merged
        if not trades.empty:
            all_trades.append(trades)

        strategy_metrics = metrics(strategy_curve, "strategy_equity", trades)
        buy_hold_metrics = metrics(buy_hold_curve.rename(columns={"buy_hold_equity": "strategy_equity"}), "strategy_equity")
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
                    "buy_hold_return_pct": period_return(buy_hold_curve, "buy_hold_equity", start, end),
                }
            )
        print(f"{symbol}: rows={len(frame)}, trades={len(trades)}, strategy_CAGR={strategy_metrics['CAGR_pct']:.2f}%")

    manifest = pd.DataFrame(manifest_rows)
    summary = pd.DataFrame(summary_rows)
    periods = pd.DataFrame(period_rows)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    avg_adv = summary["strategy_minus_buy_hold_CAGR_pct"].mean()
    output_dir = REPORTS / f"min-resistance-regime-winner_qqq-voo-proxy_{timestamp}_avgadv-{avg_adv:.2f}"
    charts_dir = output_dir / "charts"
    tables_dir = output_dir / "tables"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    plot_curves(curves, charts_dir)
    plot_bars(summary, charts_dir)
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
