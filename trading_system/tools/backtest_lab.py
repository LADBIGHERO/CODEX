"""Local backtest lab with persistent Yahoo daily-history cache.

This script is intentionally outside the dashboard runtime. It lets strategy
experiments reuse local CSV history under `.local-data-backup/history/1d/`
instead of downloading the same Yahoo data on every run.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from etf_signal import Bar, fetch_yahoo_bars_range  # noqa: E402


ETF_SYMBOLS = ["SPY", "QQQ", "GLD", "TLT"]
STOCK_SYMBOLS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "INTC", "CSCO", "ORCL", "IBM",
    "QCOM", "TXN", "AVGO", "AMD", "JPM", "BAC", "WFC", "C", "GS", "MS",
    "V", "MA", "AXP", "JNJ", "PFE", "MRK", "UNH", "AMGN", "GILD", "ABBV",
    "CVS", "WMT", "HD", "MCD", "NKE", "COST", "SBUX", "DIS", "KO", "PEP",
    "PG", "GE", "CAT", "BA", "HON", "MMM", "UPS", "XOM", "CVX", "SLB",
]

SECTOR_MAP = {
    "AAPL": "tech_growth",
    "MSFT": "tech_growth",
    "AMZN": "consumer_internet",
    "GOOGL": "communication_services",
    "META": "communication_services",
    "NVDA": "semiconductors",
    "INTC": "semiconductors",
    "CSCO": "networking",
    "ORCL": "enterprise_software",
    "IBM": "enterprise_software",
    "QCOM": "semiconductors",
    "TXN": "semiconductors",
    "AVGO": "semiconductors",
    "AMD": "semiconductors",
    "JPM": "financials",
    "BAC": "financials",
    "WFC": "financials",
    "C": "financials",
    "GS": "financials",
    "MS": "financials",
    "V": "payments",
    "MA": "payments",
    "AXP": "financials",
    "JNJ": "healthcare",
    "PFE": "healthcare",
    "MRK": "healthcare",
    "UNH": "healthcare",
    "AMGN": "biotech",
    "GILD": "biotech",
    "ABBV": "healthcare",
    "CVS": "healthcare",
    "WMT": "consumer_defensive",
    "HD": "consumer_cyclical",
    "MCD": "consumer_defensive",
    "NKE": "consumer_cyclical",
    "COST": "consumer_defensive",
    "SBUX": "consumer_cyclical",
    "DIS": "communication_services",
    "KO": "consumer_defensive",
    "PEP": "consumer_defensive",
    "PG": "consumer_defensive",
    "GE": "industrials",
    "CAT": "industrials",
    "BA": "industrials",
    "HON": "industrials",
    "MMM": "industrials",
    "UPS": "industrials",
    "XOM": "energy",
    "CVX": "energy",
    "SLB": "energy",
}


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def history_path(symbol: str, interval: str = "1d") -> Path:
    return server.resolve_backtest_history_root() / interval / f"{symbol.upper()}.csv"


def read_cached_bars(path: Path) -> list[Bar]:
    if not path.exists():
        return []
    bars: list[Bar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                bars.append(
                    Bar(
                        date=parse_date(str(row.get("Date") or row.get("date") or "")),
                        open=float(row.get("Open") or row.get("open")),
                        high=float(row.get("High") or row.get("high")),
                        low=float(row.get("Low") or row.get("low")),
                        close=float(row.get("Close") or row.get("close")),
                        volume=float(row.get("Volume") or row.get("volume") or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
    return sorted(bars, key=lambda bar: bar.date)


def write_cached_bars(path: Path, bars: list[Bar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_date = {bar.date: bar for bar in bars}
    rows = [by_date[key] for key in sorted(by_date)]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Open", "High", "Low", "Close", "Volume"])
        writer.writeheader()
        for bar in rows:
            writer.writerow(
                {
                    "Date": bar.date.isoformat(),
                    "Open": f"{bar.open:.10g}",
                    "High": f"{bar.high:.10g}",
                    "Low": f"{bar.low:.10g}",
                    "Close": f"{bar.close:.10g}",
                    "Volume": f"{bar.volume:.10g}",
                }
            )


def ensure_daily_history(symbols: list[str], start_date: dt.date, end_date: dt.date, refresh: bool) -> list[dict[str, Any]]:
    warmup_start = start_date - dt.timedelta(days=460)
    start_tolerance = dt.timedelta(days=7)
    end_tolerance = dt.timedelta(days=7)
    report: list[dict[str, Any]] = []
    for symbol in symbols:
        path = history_path(symbol, "1d")
        cached = [] if refresh else read_cached_bars(path)
        covers_start = bool(cached and cached[0].date <= warmup_start + start_tolerance)
        covers_end = bool(cached and cached[-1].date >= end_date - end_tolerance)
        covers_range = covers_start and covers_end
        if covers_range:
            report.append({"symbol": symbol, "status": "cached", "rows": len(cached), "path": str(path)})
            continue

        fetch_start = min([warmup_start] + [bar.date for bar in cached]) if cached else warmup_start
        fetch_end = max([end_date] + [bar.date for bar in cached]) if cached else end_date
        fresh = fetch_yahoo_bars_range(symbol, fetch_start, fetch_end)
        merged = {bar.date: bar for bar in cached}
        merged.update({bar.date: bar for bar in fresh})
        bars = [merged[key] for key in sorted(merged)]
        write_cached_bars(path, bars)
        report.append({"symbol": symbol, "status": "fetched", "rows": len(bars), "path": str(path)})
    return report


def scenario_symbols(name: str) -> list[str]:
    if name == "etf-stock-6040":
        return sorted(set(ETF_SYMBOLS + STOCK_SYMBOLS))
    if name == "config":
        with (ROOT / "config.json").open("r", encoding="utf-8") as f:
            config = json.load(f)
        return sorted(server.all_config_symbols(config) | {"SPY", "QQQ"})
    raise ValueError(f"Unknown scenario: {name}")


def build_scenario(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with (ROOT / "config.json").open("r", encoding="utf-8") as f:
        config = json.load(f)
    config = copy.deepcopy(config)
    asset_pool = {"version": 1, "groups": [], "instruments": {}}

    if name == "config":
        with (ROOT / "asset_pool.json").open("r", encoding="utf-8") as f:
            asset_pool = json.load(f)
        return server.merge_asset_pool_into_config(config, asset_pool), asset_pool

    if name != "etf-stock-6040":
        raise ValueError(f"Unknown scenario: {name}")

    config["universe"]["risk_assets"] = ["SPY", "QQQ"]
    config["universe"]["defensive_assets"] = ["GLD", "TLT"]
    config["universe"]["cash_assets"] = []
    config["universe"]["stock_assets"] = STOCK_SYMBOLS
    config["universe"]["market_filters"] = ["SPY", "QQQ"]
    short = config.setdefault("short_term", {})
    short["max_single_position_pct"] = 30.0
    short["theme_max_position_pct"] = 40.0
    theme_map = config.setdefault("theme_risk", {}).setdefault("theme_map", {})
    theme_map.update(SECTOR_MAP)
    for symbol in ETF_SYMBOLS:
        theme_map[symbol] = "etf_core"

    asset_pool = {
        "version": 1,
        "groups": [
            {"id": "etf_core", "name": "ETF 60 bucket", "symbols": ETF_SYMBOLS},
            {"id": "stock_liquid_50", "name": "US liquid diversified 50", "symbols": STOCK_SYMBOLS},
        ],
        "instruments": {},
    }
    for symbol in ETF_SYMBOLS:
        asset_pool["instruments"][symbol] = {"symbol": symbol, "type": "etf", "assetType": "etf", "active": True}
    for symbol in STOCK_SYMBOLS:
        asset_pool["instruments"][symbol] = {"symbol": symbol, "type": "stock", "assetType": "stock", "active": True}
    return config, asset_pool


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    curve = result.get("equityCurve") if isinstance(result.get("equityCurve"), list) else []
    trades = result.get("trades") if isinstance(result.get("trades"), list) else []
    exposures = [
        float(row["positionValueUsdt"]) / float(row["equityUsdt"]) * 100
        for row in curve
        if isinstance(row, dict) and float(row.get("equityUsdt") or 0) > 0
    ]
    sells = [trade for trade in trades if isinstance(trade, dict) and trade.get("side") == "SELL"]
    return {
        "status": result.get("status"),
        "dateRange": [result.get("startDate"), result.get("endDate")],
        "interval": result.get("interval"),
        "summary": summary,
        "exposure": {
            "avgExposurePct": statistics.fmean(exposures) if exposures else None,
            "medianExposurePct": statistics.median(exposures) if exposures else None,
            "maxExposurePct": max(exposures) if exposures else None,
            "zeroExposurePct": (sum(1 for value in exposures if value < 0.01) / len(exposures) * 100) if exposures else None,
        },
        "trades": {
            "total": len(trades),
            "closed": len(sells),
        },
        "diagnostics": result.get("diagnostics"),
    }


def save_run_summary(payload: dict[str, Any]) -> Path:
    out_dir = ROOT / ".local-data-backup" / "backtest_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{payload.get('scenario', 'run')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local backtest experiments with persistent daily-history cache.")
    parser.add_argument("--scenario", choices=["config", "etf-stock-6040"], default="etf-stock-6040")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2020-12-31")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument("--symbols", help="Optional comma/space separated symbol override for caching and requested backtest symbols.")
    args = parser.parse_args()

    start_date = parse_date(args.start)
    end_date = parse_date(args.end)
    if args.symbols:
        symbols = sorted({value.strip().upper() for value in args.symbols.replace(",", " ").split() if value.strip()})
    else:
        symbols = scenario_symbols(args.scenario)

    cache_report = ensure_daily_history(symbols, start_date, end_date, args.refresh_history)
    fetched = sum(1 for row in cache_report if row["status"] == "fetched")
    cached = sum(1 for row in cache_report if row["status"] == "cached")

    if args.cache_only:
        print(json.dumps({"ok": True, "cached": cached, "fetched": fetched, "symbols": symbols}, ensure_ascii=False, indent=2))
        return 0

    config, asset_pool = build_scenario(args.scenario)
    requested_symbols = symbols if args.symbols else None
    result = server.run_strategy_backtest(
        config=config,
        asset_pool=asset_pool,
        start_date=start_date,
        end_date=end_date,
        interval="1d",
        initial_cash=args.initial_cash,
        requested_symbols=requested_symbols,
    )
    payload = {
        "ok": result.get("status") == "completed",
        "scenario": args.scenario,
        "historyCache": {"cached": cached, "fetched": fetched, "symbols": symbols},
        "result": summarize_result(result),
    }
    payload["savedSummaryPath"] = str(save_run_summary(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
