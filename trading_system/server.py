#!/usr/bin/env python3
"""
Local ETF dashboard server.

The server binds to 127.0.0.1 by default. Use Tailscale Serve to share it
privately inside the user's tailnet.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from binance_service import (
    BinanceIntegrationError,
    build_spot_account_summary,
    integration_status,
    load_local_env,
    test_connection,
)
from etf_signal import DEFAULT_CONFIG, DEFAULT_REPORT_DIR, generate_signal_snapshot


APP_ROOT = Path(__file__).resolve().parent
DASHBOARD_ROOT = APP_ROOT / "dashboard"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ASSET_POOL_VERSION = 1
MANUAL_HOLDINGS_VERSION = 1
PAPER_ACCOUNT_VERSION = 1
DEFAULT_PAPER_CASH_USDT = 100_000.0
MAX_PAPER_TRADES = 500
MAX_PAPER_EQUITY_POINTS = 500
MAX_PAPER_PROCESSED_SIGNALS = 1000
MAX_ASSET_POOL_GROUPS = 10
MAX_ASSET_POOL_GROUP_SYMBOLS = 30

EDITABLE_CONFIG_PATHS = {
    "rules.trend_sma_days",
    "rules.short_sma_days",
    "rules.support_sma_days",
    "rules.momentum_days",
    "rules.short_momentum_days",
    "rules.risk_slots",
    "rules.risk_slot_weight_pct",
    "rules.defensive_weight_pct",
    "rules.risk_off_defensive_weight_pct",
    "rules.cash_floor_pct",
    "rules.rebalance_threshold_pct",
    "rules.drawdown_reduce_pct",
    "rules.drawdown_cash_pct",
    "price_behavior.breakout_hold_days",
    "price_behavior.near_support_pct",
    "price_behavior.near_resistance_pct",
    "price_behavior.breakout_window_days",
    "price_behavior.failed_breakout_pct",
    "price_behavior.bearish_volume_multiplier",
    "execution.buy_limit_buffer_pct",
    "execution.sell_limit_buffer_pct",
    "execution.stop_execution_mode",
    "execution.slippage_pct",
    "short_term.min_avg_dollar_volume_20",
    "short_term.sma20_flat_slope_pct_3d",
    "short_term.breakout_window_days",
    "short_term.pullback_lookback_days",
    "short_term.near_support_pct",
    "short_term.support_near_atr_multiplier",
    "short_term.atr_period",
    "short_term.min_breakout_buffer_pct",
    "short_term.min_stop_buffer_pct",
    "short_term.min_support_confirm_buffer_pct",
    "short_term.atr_breakout_multiplier",
    "short_term.atr_stop_multiplier",
    "short_term.atr_support_multiplier",
    "short_term.volume_multiplier",
    "short_term.max_stop_distance_pct",
    "short_term.min_target1_r",
    "short_term.ideal_target1_r",
    "short_term.target2_pullback_r",
    "short_term.target2_breakout_r",
    "short_term.trailing_stop_atr_multiplier",
    "short_term.min_risk_reward",
    "short_term.second_target_r",
    "short_term.risk_per_trade_pct",
    "short_term.base_position_pct",
    "short_term.max_single_position_pct",
    "short_term.min_position_pct",
    "short_term.max_open_risk_pct",
    "short_term.theme_max_position_pct",
    "short_term.market_warning_position_multiplier",
    "short_term.individual_warning_position_multiplier",
    "short_term.qqq_warning_growth_multiplier",
    "short_term.weak_momentum_5d_pct",
    "short_term.time_stop_mfe_days",
    "short_term.time_stop_mfe_r",
    "short_term.time_stop_tp1_days",
    "short_term.max_holding_days",
    "short_term.event_risk_default",
}

DEFAULT_ASSET_POOL_GROUPS = [
    {"id": "core_strategy", "name": "核心策略资产", "symbols": ["QQQ", "SPY", "GLD", "SGOV"], "locked": False},
    {
        "id": "stock_watchlist",
        "name": "股票观察池",
        "symbols": ["NVDA", "MSFT", "META", "JPM", "XOM", "LLY", "CAT", "GE", "WMT", "V"],
        "locked": False,
    },
]


def external_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return APP_ROOT


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", APP_ROOT))


def resolve_config() -> Path:
    external = external_root() / "config.json"
    if external.exists():
        return external
    bundled = bundled_root() / "config.json"
    if bundled.exists():
        return bundled
    return DEFAULT_CONFIG


def resolve_dashboard_root() -> Path:
    external = external_root() / "dashboard"
    if external.exists():
        return external
    bundled = bundled_root() / "dashboard"
    if bundled.exists():
        return bundled
    return DASHBOARD_ROOT


def resolve_asset_pool_config() -> Path:
    return external_root() / "asset_pool.json"


def resolve_manual_holdings_config() -> Path:
    return external_root() / "manual_holdings.json"


def resolve_paper_account_config() -> Path:
    return external_root() / "paper_account.json"


def resolve_dashboard_view_cache() -> Path:
    return external_root() / "dashboard_view_cache.json"


def empty_asset_pool_config() -> dict[str, object]:
    return {"version": ASSET_POOL_VERSION, "groups": DEFAULT_ASSET_POOL_GROUPS, "instruments": {}}


def empty_manual_holdings_config() -> dict[str, object]:
    return {"version": MANUAL_HOLDINGS_VERSION, "holdings": {}}


def empty_paper_account_config(initial_cash: float = DEFAULT_PAPER_CASH_USDT) -> dict[str, object]:
    cash = float(initial_cash) if initial_cash and initial_cash > 0 else DEFAULT_PAPER_CASH_USDT
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "version": PAPER_ACCOUNT_VERSION,
        "settings": {
            "initialCashUsdt": cash,
            "riskPerTradePct": 1.0,
            "entryPositionPct": 5.0,
            "targetEtfWeightPct": 60.0,
            "targetStockWeightPct": 40.0,
            "maxSinglePositionPct": 15.0,
            "maxOpenRiskPct": 3.0,
            "stopExecutionMode": "intraday_stop",
            "autoRun": True,
            "commissionPct": 0.0,
            "slippagePct": 0.1,
        },
        "cashUsdt": cash,
        "positions": {},
        "trades": [],
        "equityCurve": [],
        "processedSignals": [],
        "risk": {
            "lossStreak": 0,
            "lossStreakByEntryType": {},
            "lossStreakByAssetType": {},
            "entryPaused": False,
        },
        "lastRunAt": None,
        "lastRunLog": [],
        "createdAt": now,
        "updatedAt": now,
    }


def clean_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def clean_float(value: object, default: float = 0.0, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None and number < minimum:
        return minimum
    return number


def config_value_at_path(config: dict[str, object], path: str) -> object:
    current: object = config
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise KeyError(path)
        current = current[key]
    return current


def normalize_config_edit_value(path: str, value: object, current_value: object) -> object:
    if isinstance(current_value, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(current_value, int) and not isinstance(current_value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Invalid numeric value for {path}")
        return int(round(number))
    if isinstance(current_value, float):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Invalid numeric value for {path}")
        return number
    if isinstance(current_value, str):
        return str(value).strip()
    raise ValueError(f"Unsupported editable value for {path}")


def apply_config_edits(config: dict[str, object], changes: object) -> dict[str, object]:
    if not isinstance(changes, dict):
        raise ValueError("Missing config changes")
    next_config = copy.deepcopy(config)
    for path, value in changes.items():
        path = str(path or "").strip()
        if path not in EDITABLE_CONFIG_PATHS:
            raise ValueError(f"Unsupported config path: {path}")
        current_value = config_value_at_path(next_config, path)
        normalized = normalize_config_edit_value(path, value, current_value)
        target: object = next_config
        parts = path.split(".")
        for key in parts[:-1]:
            if not isinstance(target, dict):
                raise ValueError(f"Invalid config path: {path}")
            target = target[key]
        if not isinstance(target, dict):
            raise ValueError(f"Invalid config path: {path}")
        target[parts[-1]] = normalized
    return next_config


def sanitize_manual_holdings_config(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return empty_manual_holdings_config()

    raw_holdings = payload.get("holdings", payload)
    holdings: dict[str, dict[str, object]] = {}
    if isinstance(raw_holdings, dict):
        for raw_symbol, raw_entry in raw_holdings.items():
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or not isinstance(raw_entry, dict):
                continue
            quantity = clean_optional_float(raw_entry.get("quantity"))
            avg_cost = clean_optional_float(raw_entry.get("avgCostUsdt"))
            if not quantity or quantity <= 0:
                continue
            entry: dict[str, object] = {
                "symbol": symbol,
                "quantity": quantity,
            }
            if avg_cost is not None:
                entry["avgCostUsdt"] = avg_cost
            note = raw_entry.get("note")
            if isinstance(note, str) and note.strip():
                entry["note"] = note.strip()[:160]
            updated_at = raw_entry.get("updatedAt")
            if isinstance(updated_at, str) and updated_at.strip():
                entry["updatedAt"] = updated_at.strip()
            holdings[symbol] = entry

    return {"version": MANUAL_HOLDINGS_VERSION, "holdings": holdings}


def sanitize_paper_account_config(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return empty_paper_account_config()

    raw_settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    initial_cash = clean_float(raw_settings.get("initialCashUsdt"), DEFAULT_PAPER_CASH_USDT, 1.0)
    slippage_pct = min(1.0, clean_float(raw_settings.get("slippagePct"), 0.1, 0.0))
    if slippage_pct == 0:
        slippage_pct = 0.1
    settings = {
        "initialCashUsdt": initial_cash,
        "riskPerTradePct": min(5.0, max(0.1, clean_float(raw_settings.get("riskPerTradePct"), 1.0, 0.1))),
        "entryPositionPct": min(10.0, max(1.0, clean_float(raw_settings.get("entryPositionPct"), 5.0, 1.0))),
        "targetEtfWeightPct": min(100.0, max(0.0, clean_float(raw_settings.get("targetEtfWeightPct"), 60.0, 0.0))),
        "targetStockWeightPct": min(100.0, max(0.0, clean_float(raw_settings.get("targetStockWeightPct"), 40.0, 0.0))),
        "maxSinglePositionPct": min(100.0, max(1.0, clean_float(raw_settings.get("maxSinglePositionPct"), 15.0, 1.0))),
        "maxOpenRiskPct": min(20.0, max(0.1, clean_float(raw_settings.get("maxOpenRiskPct"), 3.0, 0.1))),
        "stopExecutionMode": str(raw_settings.get("stopExecutionMode") or "intraday_stop")
        if str(raw_settings.get("stopExecutionMode") or "intraday_stop") in {"intraday_stop", "close_confirm_stop"}
        else "intraday_stop",
        "autoRun": raw_settings.get("autoRun") is not False,
        "commissionPct": min(1.0, clean_float(raw_settings.get("commissionPct"), 0.0, 0.0)),
        "slippagePct": slippage_pct,
    }

    positions: dict[str, dict[str, object]] = {}
    raw_positions = payload.get("positions")
    if isinstance(raw_positions, dict):
        for raw_symbol, raw_entry in raw_positions.items():
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or not isinstance(raw_entry, dict):
                continue
            quantity = clean_float(raw_entry.get("quantity"), 0.0, 0.0)
            avg_cost = clean_float(raw_entry.get("avgCostUsdt", raw_entry.get("entryPrice")), 0.0, 0.0)
            if quantity <= 0 or avg_cost <= 0:
                continue
            asset_type = str(raw_entry.get("assetType") or raw_entry.get("asset_type") or "etf").strip().lower()
            if asset_type not in {"etf", "stock", "cash"}:
                asset_type = "etf"
            entry: dict[str, object] = {
                "symbol": symbol,
                "assetType": asset_type,
                "quantity": quantity,
                "initialQuantity": clean_float(raw_entry.get("initialQuantity"), quantity, 0.0) or quantity,
                "entryPrice": clean_float(raw_entry.get("entryPrice"), avg_cost, 0.0) or avg_cost,
                "avgCostUsdt": avg_cost,
                "stopPrice": clean_float(raw_entry.get("stopPrice"), 0.0, 0.0) or None,
                "targetPrice": clean_float(raw_entry.get("targetPrice"), 0.0, 0.0) or None,
                "target2Price": clean_float(raw_entry.get("target2Price"), 0.0, 0.0) or None,
                "lastPrice": clean_float(raw_entry.get("lastPrice"), avg_cost, 0.0) or avg_cost,
                "partialTaken": bool(raw_entry.get("partialTaken")),
                "realizedPnlUsdt": clean_float(raw_entry.get("realizedPnlUsdt"), 0.0),
                "entryPositionPct": clean_float(raw_entry.get("entryPositionPct"), 0.0, 0.0) or None,
                "allocationCapPct": clean_float(raw_entry.get("allocationCapPct"), 0.0, 0.0) or None,
                "singleCapPct": clean_float(raw_entry.get("singleCapPct"), 0.0, 0.0) or None,
                "positionPct": clean_float(raw_entry.get("positionPct"), 0.0, 0.0) or None,
                "riskBudgetPct": clean_float(raw_entry.get("riskBudgetPct"), 0.0, 0.0) or None,
                "initialRiskPerShare": clean_float(raw_entry.get("initialRiskPerShare"), 0.0, 0.0) or None,
                "target1R": clean_float(raw_entry.get("target1R"), 0.0, 0.0) or None,
                "target2R": clean_float(raw_entry.get("target2R"), 0.0, 0.0) or None,
                "maxFavorableR": clean_float(raw_entry.get("maxFavorableR"), 0.0),
                "maxAdverseR": clean_float(raw_entry.get("maxAdverseR"), 0.0),
                "theme": str(raw_entry.get("theme") or "general")[:60],
            }
            for key in ("openedAt", "openedDate", "openedSignalId", "source", "trigger", "entryType"):
                value = raw_entry.get(key)
                if isinstance(value, str) and value.strip():
                    entry[key] = value.strip()[:120]
            positions[symbol] = entry

    trades: list[dict[str, object]] = []
    raw_trades = payload.get("trades")
    if isinstance(raw_trades, list):
        for raw_trade in raw_trades[-MAX_PAPER_TRADES:]:
            if not isinstance(raw_trade, dict):
                continue
            symbol = str(raw_trade.get("symbol") or "").strip().upper()
            side = str(raw_trade.get("side") or "").strip().upper()
            quantity = clean_float(raw_trade.get("quantity"), 0.0, 0.0)
            price = clean_float(raw_trade.get("price"), 0.0, 0.0)
            if not symbol or side not in {"BUY", "SELL"} or quantity <= 0 or price <= 0:
                continue
            trades.append(
                {
                    "id": str(raw_trade.get("id") or f"{symbol}-{side}-{len(trades)}")[:160],
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "valueUsdt": clean_float(raw_trade.get("valueUsdt"), quantity * price, 0.0),
                    "realizedPnlUsdt": clean_float(raw_trade.get("realizedPnlUsdt"), 0.0),
                    "reason": str(raw_trade.get("reason") or "模拟交易")[:160],
                    "signalId": str(raw_trade.get("signalId") or "")[:200],
                    "executedAt": str(raw_trade.get("executedAt") or "")[:80],
                    "closesPosition": bool(raw_trade.get("closesPosition")),
                    "assetType": str(raw_trade.get("assetType") or "")[:24],
                    "entryType": str(raw_trade.get("entryType") or "")[:40],
                    "theme": str(raw_trade.get("theme") or "")[:60],
                    "stopPrice": clean_float(raw_trade.get("stopPrice"), 0.0, 0.0) or None,
                    "stopDistancePct": clean_float(raw_trade.get("stopDistancePct"), 0.0, 0.0) or None,
                    "positionPct": clean_float(raw_trade.get("positionPct"), 0.0, 0.0) or None,
                    "riskBudgetPct": clean_float(raw_trade.get("riskBudgetPct"), 0.0, 0.0) or None,
                    "target1Price": clean_float(raw_trade.get("target1Price"), 0.0, 0.0) or None,
                    "target2Price": clean_float(raw_trade.get("target2Price"), 0.0, 0.0) or None,
                    "target1R": clean_float(raw_trade.get("target1R"), 0.0, 0.0) or None,
                    "target2R": clean_float(raw_trade.get("target2R"), 0.0, 0.0) or None,
                    "realizedR": clean_float(raw_trade.get("realizedR"), 0.0),
                    "realizedPct": clean_float(raw_trade.get("realizedPct"), 0.0),
                    "holdingDays": clean_float(raw_trade.get("holdingDays"), 0.0, 0.0) or None,
                    "maxFavorableR": clean_float(raw_trade.get("maxFavorableR"), 0.0),
                    "maxAdverseR": clean_float(raw_trade.get("maxAdverseR"), 0.0),
                    "eventRiskStatus": str(raw_trade.get("eventRiskStatus") or "")[:40],
                    "volumeConfirmed": bool(raw_trade.get("volumeConfirmed")),
                    "planFollowed": raw_trade.get("planFollowed") is not False,
                    "slippagePct": clean_float(raw_trade.get("slippagePct"), 0.0, 0.0),
                    "exitReason": str(raw_trade.get("exitReason") or "")[:60],
                    "ambiguousIntraday": bool(raw_trade.get("ambiguousIntraday")),
                }
            )

    equity_curve: list[dict[str, object]] = []
    raw_curve = payload.get("equityCurve")
    if isinstance(raw_curve, list):
        for raw_point in raw_curve[-MAX_PAPER_EQUITY_POINTS:]:
            if not isinstance(raw_point, dict):
                continue
            equity_curve.append(
                {
                    "time": str(raw_point.get("time") or "")[:80],
                    "dailyDate": str(raw_point.get("dailyDate") or "")[:32],
                    "equityUsdt": clean_float(raw_point.get("equityUsdt"), 0.0, 0.0),
                    "cashUsdt": clean_float(raw_point.get("cashUsdt"), 0.0, 0.0),
                    "positionValueUsdt": clean_float(raw_point.get("positionValueUsdt"), 0.0, 0.0),
                    "unrealizedPnlUsdt": clean_float(raw_point.get("unrealizedPnlUsdt"), 0.0),
                    "realizedPnlUsdt": clean_float(raw_point.get("realizedPnlUsdt"), 0.0),
                }
            )

    processed = []
    raw_processed = payload.get("processedSignals")
    if isinstance(raw_processed, list):
        processed = [str(item)[:220] for item in raw_processed[-MAX_PAPER_PROCESSED_SIGNALS:] if item]

    raw_risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
    loss_streak = int(clean_float(raw_risk.get("lossStreak"), 0, 0))
    loss_streak_by_entry = raw_risk.get("lossStreakByEntryType") if isinstance(raw_risk.get("lossStreakByEntryType"), dict) else {}
    loss_streak_by_asset = raw_risk.get("lossStreakByAssetType") if isinstance(raw_risk.get("lossStreakByAssetType"), dict) else {}
    clean_loss_by_entry = {
        str(key)[:40]: int(clean_float(value, 0, 0))
        for key, value in loss_streak_by_entry.items()
        if str(key).strip()
    }
    clean_loss_by_asset = {
        str(key)[:40]: int(clean_float(value, 0, 0))
        for key, value in loss_streak_by_asset.items()
        if str(key).strip()
    }

    return {
        "version": PAPER_ACCOUNT_VERSION,
        "settings": settings,
        "cashUsdt": clean_float(payload.get("cashUsdt"), settings["initialCashUsdt"], 0.0),
        "positions": positions,
        "trades": trades,
        "equityCurve": equity_curve,
        "processedSignals": processed,
        "risk": {
            "lossStreak": loss_streak,
            "lossStreakByEntryType": clean_loss_by_entry,
            "lossStreakByAssetType": clean_loss_by_asset,
            "entryPaused": loss_streak >= 3,
        },
        "lastRunAt": payload.get("lastRunAt") if isinstance(payload.get("lastRunAt"), str) else None,
        "lastRunLog": payload.get("lastRunLog") if isinstance(payload.get("lastRunLog"), list) else [],
        "createdAt": payload.get("createdAt") if isinstance(payload.get("createdAt"), str) else dt.datetime.now(dt.timezone.utc).isoformat(),
        "updatedAt": payload.get("updatedAt") if isinstance(payload.get("updatedAt"), str) else dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def normalize_group_id(value: object, fallback: str = "") -> str:
    raw = str(value or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_")
    return cleaned[:48] or fallback


def sanitize_asset_pool_groups(raw_groups: object) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    source = raw_groups if isinstance(raw_groups, list) and raw_groups else DEFAULT_ASSET_POOL_GROUPS
    for index, raw_group in enumerate(source):
        if len(groups) >= MAX_ASSET_POOL_GROUPS:
            break
        if not isinstance(raw_group, dict):
            continue
        name = str(raw_group.get("name") or "").strip()
        if not name:
            continue
        group_id = normalize_group_id(raw_group.get("id"), f"group_{index + 1}")
        base_id = group_id
        suffix = 2
        while group_id in seen_ids:
            group_id = f"{base_id}_{suffix}"
            suffix += 1
        seen_ids.add(group_id)

        symbols: list[str] = []
        raw_symbols = raw_group.get("symbols")
        if isinstance(raw_symbols, list):
            for value in raw_symbols:
                symbol = str(value or "").strip().upper()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
                if len(symbols) >= MAX_ASSET_POOL_GROUP_SYMBOLS:
                    break

        groups.append(
            {
                "id": group_id,
                "name": name[:40],
                "symbols": symbols,
                "locked": bool(raw_group.get("locked", False)),
            }
        )

    return groups or copy.deepcopy(DEFAULT_ASSET_POOL_GROUPS)


def sanitize_asset_pool_config(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return empty_asset_pool_config()

    groups = sanitize_asset_pool_groups(payload.get("groups"))
    valid_group_ids = {str(group["id"]) for group in groups}
    raw_instruments = payload.get("instruments")
    instruments: dict[str, dict[str, object]] = {}
    allowed_usage = {"watch_only", "signal_monitoring", "strategy"}

    if isinstance(raw_instruments, dict):
        for raw_symbol, raw_config in raw_instruments.items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol or not isinstance(raw_config, dict):
                continue

            entry: dict[str, object] = {}
            entry["symbol"] = symbol

            for key in ("name", "instrumentType", "type", "exchange", "currency", "createdAt", "updatedAt"):
                value = raw_config.get(key)
                if isinstance(value, str) and value.strip():
                    entry[key] = value.strip()

            group_id = raw_config.get("groupId")
            if isinstance(group_id, str) and group_id.strip():
                normalized_group_id = normalize_group_id(group_id)
                if normalized_group_id in valid_group_ids:
                    entry["groupId"] = normalized_group_id

            usage = raw_config.get("usage")
            if isinstance(usage, str) and usage in allowed_usage:
                entry["usage"] = usage

            role = raw_config.get("role")
            if isinstance(role, str) and role.strip():
                entry["role"] = role.strip()

            for key in ("showInOverview", "includeInMonitoring", "includeInBacktest", "removed"):
                if key in raw_config:
                    entry[key] = bool(raw_config.get(key))

            if entry:
                instruments[symbol] = entry

    return {"version": ASSET_POOL_VERSION, "groups": groups, "instruments": instruments}


def all_config_symbols(config: dict[str, object]) -> set[str]:
    universe = config.get("universe") if isinstance(config, dict) else {}
    if not isinstance(universe, dict):
        return set()
    symbols: set[str] = set()
    for key in ("risk_assets", "defensive_assets", "cash_assets", "stock_assets", "market_filters"):
        values = universe.get(key)
        if isinstance(values, list):
            symbols.update(str(value).strip().upper() for value in values if str(value).strip())
    return symbols


def active_asset_pool_symbols(asset_pool: dict[str, object]) -> set[str]:
    raw_instruments = asset_pool.get("instruments") if isinstance(asset_pool, dict) else {}
    if not isinstance(raw_instruments, dict):
        return set()
    symbols: set[str] = set()
    for symbol, entry in raw_instruments.items():
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("removed")) or entry.get("showInOverview") is False:
            continue
        symbols.add(str(symbol).strip().upper())
    raw_groups = asset_pool.get("groups") if isinstance(asset_pool, dict) else []
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            for value in group.get("symbols") or []:
                symbol = str(value or "").strip().upper()
                entry = raw_instruments.get(symbol) if isinstance(raw_instruments, dict) else None
                if isinstance(entry, dict) and (bool(entry.get("removed")) or entry.get("showInOverview") is False):
                    continue
                if symbol:
                    symbols.add(symbol)
    return symbols


def asset_pool_symbol_groups(asset_pool: dict[str, object], symbol: str) -> list[str]:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return []
    groups: list[str] = []
    raw_groups = asset_pool.get("groups") if isinstance(asset_pool, dict) else []
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or "").strip()
            symbols = [str(value or "").strip().upper() for value in (group.get("symbols") or [])]
            if group_id and normalized in symbols:
                groups.append(group_id)
    raw_instruments = asset_pool.get("instruments") if isinstance(asset_pool, dict) else {}
    entry = raw_instruments.get(normalized) if isinstance(raw_instruments, dict) else None
    if isinstance(entry, dict):
        legacy_group_id = str(entry.get("groupId") or "").strip()
        if legacy_group_id and legacy_group_id not in groups:
            groups.append(legacy_group_id)
    return groups


def hidden_asset_pool_symbols(asset_pool: dict[str, object]) -> set[str]:
    raw_instruments = asset_pool.get("instruments") if isinstance(asset_pool, dict) else {}
    if not isinstance(raw_instruments, dict):
        return set()
    symbols: set[str] = set()
    for symbol, entry in raw_instruments.items():
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("removed")) or entry.get("showInOverview") is False:
            symbols.add(str(symbol).strip().upper())
    return symbols


def merge_asset_pool_into_config(config: dict[str, object], asset_pool: dict[str, object]) -> dict[str, object]:
    merged = copy.deepcopy(config)
    universe = merged.setdefault("universe", {})
    if not isinstance(universe, dict):
        return merged

    hidden_symbols = hidden_asset_pool_symbols(asset_pool)
    if hidden_symbols:
        for key in ("risk_assets", "defensive_assets", "cash_assets", "stock_assets", "market_filters"):
            values = universe.get(key)
            if isinstance(values, list):
                universe[key] = [
                    value for value in values
                    if str(value).strip().upper() not in hidden_symbols
                ]

    stock_assets = universe.setdefault("stock_assets", [])
    if not isinstance(stock_assets, list):
        stock_assets = []
        universe["stock_assets"] = stock_assets

    existing_symbols = all_config_symbols(merged)
    for symbol in sorted(active_asset_pool_symbols(asset_pool)):
        if symbol not in existing_symbols:
            stock_assets.append(symbol)
            existing_symbols.add(symbol)

    account = merged.setdefault("account", {})
    if isinstance(account, dict):
        holdings = account.setdefault("holdings_pct", {})
        if isinstance(holdings, dict):
            for symbol in hidden_symbols:
                holdings.pop(symbol, None)
            for symbol in active_asset_pool_symbols(asset_pool):
                holdings.setdefault(symbol, 0)
    return merged


def yahoo_instrument_type(meta: dict[str, object]) -> str:
    instrument_type = str(meta.get("instrumentType") or "").upper()
    symbol = str(meta.get("symbol") or "").upper()
    if "ETF" in instrument_type:
        return "etf"
    if instrument_type in {"EQUITY", "COMMONSTOCK", "STOCK"}:
        return "stock"
    if symbol.endswith("=F") or instrument_type:
        return "other"
    return "other"


def normalize_yahoo_quote_type(value: object) -> str:
    quote_type = str(value or "").upper()
    if quote_type == "ETF":
        return "etf"
    if quote_type in {"EQUITY", "COMMONSTOCK", "STOCK"}:
        return "stock"
    return "other"


def search_yahoo_instruments(raw_query: str, limit: int = 8) -> list[dict[str, object]]:
    query_text = raw_query.strip()
    if not query_text:
        return []
    query = urllib.parse.urlencode({"q": query_text, "quotesCount": limit, "newsCount": 0})
    url = f"https://query2.finance.yahoo.com/v1/finance/search?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ETFTradingDashboard/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results: list[dict[str, object]] = []
    seen: set[str] = set()
    for quote in payload.get("quotes") or []:
        if not isinstance(quote, dict):
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        item_type = normalize_yahoo_quote_type(quote.get("quoteType"))
        if item_type not in {"stock", "etf"}:
            continue
        seen.add(symbol)
        results.append(
            {
                "symbol": symbol,
                "name": str(quote.get("longname") or quote.get("shortname") or symbol).strip(),
                "type": item_type,
                "instrumentType": str(quote.get("quoteType") or "").strip(),
                "exchange": str(quote.get("exchange") or quote.get("exchDisp") or "").strip(),
                "currency": str(quote.get("currency") or "").strip(),
            }
        )
        if len(results) >= limit:
            break
    return results


def lookup_yahoo_instrument(raw_query: str) -> dict[str, object]:
    symbol = raw_query.strip().upper()
    if not symbol:
        raise ValueError("Missing symbol")
    query = urllib.parse.urlencode(
        {
            "range": "5d",
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ETFTradingDashboard/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError("No Yahoo chart result")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    has_close = any(value is not None for value in closes)
    if not timestamps or not has_close:
        raise RuntimeError("No recent price data")

    meta = result.get("meta") or {}
    resolved_symbol = str(meta.get("symbol") or symbol).upper()
    exchange = str(meta.get("exchangeName") or meta.get("fullExchangeName") or "").strip()
    currency = str(meta.get("currency") or "").strip()
    instrument_type = yahoo_instrument_type(meta)
    # Yahoo's chart endpoint validates symbols well but does not always include a long name.
    display_name = str(meta.get("longName") or meta.get("shortName") or resolved_symbol).strip()
    return {
        "symbol": resolved_symbol,
        "name": display_name,
        "type": instrument_type,
        "instrumentType": str(meta.get("instrumentType") or "").strip(),
        "exchange": exchange,
        "currency": currency,
    }


def local_instrument_search_result(raw_query: str, config: dict[str, object], asset_pool: dict[str, object]) -> dict[str, object] | None:
    symbol = raw_query.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-=]{0,14}", symbol):
        return None

    instruments = asset_pool.get("instruments") if isinstance(asset_pool, dict) else {}
    entry = instruments.get(symbol) if isinstance(instruments, dict) else None
    universe = config.get("universe") if isinstance(config, dict) else {}
    type_hint = "stock"
    if isinstance(universe, dict):
        if symbol in {str(value).strip().upper() for value in universe.get("risk_assets", []) + universe.get("defensive_assets", []) + universe.get("cash_assets", []) if str(value).strip()}:
            type_hint = "etf"
        elif symbol in {str(value).strip().upper() for value in universe.get("stock_assets", []) if str(value).strip()}:
            type_hint = "stock"
    if isinstance(entry, dict):
        configured_type = str(entry.get("type") or "").strip().lower()
        if configured_type in {"stock", "etf", "other"}:
            type_hint = configured_type

    return {
        "symbol": symbol,
        "name": str((entry or {}).get("name") or symbol).strip(),
        "type": type_hint,
        "instrumentType": "ETF" if type_hint == "etf" else "EQUITY",
        "exchange": str((entry or {}).get("exchange") or "").strip(),
        "currency": str((entry or {}).get("currency") or "USD").strip(),
        "manualFallback": True,
    }


def paper_price_for_item(item: dict[str, object] | None) -> float | None:
    if not isinstance(item, dict):
        return None
    for key in ("current_price", "close"):
        value = item.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def paper_snapshot_items(snapshot: object) -> dict[str, dict[str, object]]:
    if not isinstance(snapshot, dict):
        return {}
    items = snapshot.get("symbols")
    if not isinstance(items, list):
        return {}
    by_symbol: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol:
            by_symbol[symbol] = item
    return by_symbol


def paper_signal_id(snapshot: dict[str, object], symbol: str, action: str, item: dict[str, object]) -> str:
    short_term = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
    date = str(snapshot.get("latest_daily_date") or item.get("date") or snapshot.get("generated_at") or "")[:32]
    trigger = str(short_term.get("trigger") or action).strip()[:40]
    return f"{date}:{symbol}:{action}:{trigger}"


def paper_asset_type_for_item(item: dict[str, object] | None, fallback: str = "etf") -> str:
    fallback = fallback if fallback in {"etf", "stock", "cash"} else "etf"
    if not isinstance(item, dict):
        return fallback
    role = str(item.get("role") or "").strip().lower()
    if role == "stock":
        return "stock"
    if role == "cash":
        return "cash"
    return "etf"


def paper_asset_type_for_position(position: dict[str, object], item: dict[str, object] | None = None) -> str:
    raw_type = str(position.get("assetType") or position.get("asset_type") or "").strip().lower()
    fallback = raw_type if raw_type in {"etf", "stock", "cash"} else "etf"
    return paper_asset_type_for_item(item, fallback)


def paper_theme_for_item(item: dict[str, object] | None, fallback: str = "general") -> str:
    if isinstance(item, dict):
        short_term = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
        theme = str(short_term.get("theme") or item.get("theme") or fallback).strip()
        return theme or fallback
    return fallback


def paper_theme_for_position(position: dict[str, object], item: dict[str, object] | None = None) -> str:
    fallback = str(position.get("theme") or "general").strip() or "general"
    return paper_theme_for_item(item, fallback)


def paper_realized_pnl(account: dict[str, object]) -> float:
    trades = account.get("trades")
    if not isinstance(trades, list):
        return 0.0
    return sum(clean_float(trade.get("realizedPnlUsdt"), 0.0) for trade in trades if isinstance(trade, dict))


def paper_holding_days(position: dict[str, object], executed_at: str) -> int | None:
    raw_opened = str(position.get("openedDate") or position.get("openedAt") or "")[:10]
    raw_exit = str(executed_at or "")[:10]
    if not raw_opened or not raw_exit:
        return None
    try:
        return max(0, (dt.date.fromisoformat(raw_exit) - dt.date.fromisoformat(raw_opened)).days)
    except ValueError:
        return None


def paper_account_metrics(account: dict[str, object], snapshot: object | None = None) -> dict[str, object]:
    by_symbol = paper_snapshot_items(snapshot)
    positions = account.get("positions") if isinstance(account.get("positions"), dict) else {}
    cash = clean_float(account.get("cashUsdt"), DEFAULT_PAPER_CASH_USDT, 0.0)
    position_value = 0.0
    unrealized = 0.0
    open_risk = 0.0
    etf_value = 0.0
    stock_value = 0.0
    largest_symbol = ""
    largest_value = 0.0
    for symbol, position in positions.items():
        if not isinstance(position, dict):
            continue
        quantity = clean_float(position.get("quantity"), 0.0, 0.0)
        avg_cost = clean_float(position.get("avgCostUsdt"), 0.0, 0.0)
        item = by_symbol.get(str(symbol).upper())
        current_price = paper_price_for_item(item) or clean_float(position.get("lastPrice"), avg_cost, 0.0)
        value = quantity * current_price
        asset_type = paper_asset_type_for_position(position, item)
        if asset_type == "stock":
            stock_value += value
        elif asset_type == "etf":
            etf_value += value
        if value > largest_value:
            largest_symbol = str(symbol).upper()
            largest_value = value
        position_value += value
        unrealized += (current_price - avg_cost) * quantity
        stop_price = clean_float(position.get("stopPrice"), 0.0, 0.0)
        if stop_price > 0 and current_price > stop_price:
            open_risk += (current_price - stop_price) * quantity
    trades = [trade for trade in account.get("trades", []) if isinstance(trade, dict)]
    closed_trades = [trade for trade in trades if trade.get("side") == "SELL" and trade.get("closesPosition")]
    wins = [trade for trade in closed_trades if clean_float(trade.get("realizedPnlUsdt"), 0.0) > 0]
    equity = cash + position_value
    return {
        "cashUsdt": cash,
        "positionValueUsdt": position_value,
        "equityUsdt": equity,
        "unrealizedPnlUsdt": unrealized,
        "openRiskUsdt": open_risk,
        "openRiskPct": open_risk / equity * 100 if equity > 0 else 0.0,
        "realizedPnlUsdt": paper_realized_pnl(account),
        "positionCount": len(positions),
        "tradeCount": len(trades),
        "closedTradeCount": len(closed_trades),
        "winRatePct": len(wins) / len(closed_trades) * 100 if closed_trades else None,
        "etfValueUsdt": etf_value,
        "stockValueUsdt": stock_value,
        "etfWeightPct": etf_value / equity * 100 if equity > 0 else 0.0,
        "stockWeightPct": stock_value / equity * 100 if equity > 0 else 0.0,
        "largestPositionSymbol": largest_symbol,
        "largestPositionValueUsdt": largest_value,
        "largestPositionWeightPct": largest_value / equity * 100 if equity > 0 else 0.0,
    }


def append_paper_trade(
    account: dict[str, object],
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    reason: str,
    signal_id: str,
    executed_at: str,
    realized_pnl: float = 0.0,
    closes_position: bool = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    trades = account.setdefault("trades", [])
    if not isinstance(trades, list):
        trades = []
        account["trades"] = trades
    trade = {
        "id": f"{executed_at}:{symbol}:{side}:{len(trades) + 1}",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "valueUsdt": quantity * price,
        "realizedPnlUsdt": realized_pnl,
        "reason": reason,
        "signalId": signal_id,
        "executedAt": executed_at,
        "closesPosition": closes_position,
    }
    if extra:
        trade.update(extra)
    trades.append(trade)
    del trades[:-MAX_PAPER_TRADES]
    return trade


def close_paper_position(
    account: dict[str, object],
    position: dict[str, object],
    quantity: float,
    price: float,
    reason: str,
    signal_id: str,
    executed_at: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object] | None:
    symbol = str(position.get("symbol") or "").upper()
    current_quantity = clean_float(position.get("quantity"), 0.0, 0.0)
    avg_cost = clean_float(position.get("avgCostUsdt"), 0.0, 0.0)
    sell_quantity = min(quantity, current_quantity)
    if not symbol or sell_quantity <= 0 or price <= 0:
        return None
    realized = (price - avg_cost) * sell_quantity
    remaining = current_quantity - sell_quantity
    closes_position = remaining <= max(current_quantity * 0.000001, 0.00000001)
    account["cashUsdt"] = clean_float(account.get("cashUsdt"), 0.0, 0.0) + sell_quantity * price
    accrued = clean_float(position.get("realizedPnlUsdt"), 0.0) + realized
    initial_risk = clean_float(position.get("initialRiskPerShare"), 0.0, 0.0)
    realized_r = (price - avg_cost) / initial_risk if initial_risk > 0 else None
    realized_pct = (price / avg_cost - 1) * 100 if avg_cost > 0 else None
    trade_extra = {
        "assetType": str(position.get("assetType") or ""),
        "entryType": str(position.get("entryType") or position.get("trigger") or ""),
        "theme": str(position.get("theme") or "general"),
        "stopPrice": clean_float(position.get("stopPrice"), 0.0, 0.0) or None,
        "stopDistancePct": clean_float(position.get("stopDistancePct"), 0.0, 0.0) or None,
        "positionPct": clean_float(position.get("positionPct"), 0.0, 0.0) or None,
        "riskBudgetPct": clean_float(position.get("riskBudgetPct"), 0.0, 0.0) or None,
        "target1Price": clean_float(position.get("targetPrice"), 0.0, 0.0) or None,
        "target2Price": clean_float(position.get("target2Price"), 0.0, 0.0) or None,
        "target1R": clean_float(position.get("target1R"), 0.0, 0.0) or None,
        "target2R": clean_float(position.get("target2R"), 0.0, 0.0) or None,
        "realizedR": realized_r,
        "realizedPct": realized_pct,
        "holdingDays": paper_holding_days(position, executed_at),
        "maxFavorableR": clean_float(position.get("maxFavorableR"), 0.0),
        "maxAdverseR": clean_float(position.get("maxAdverseR"), 0.0),
        "slippagePct": clean_float(position.get("slippagePct"), 0.0, 0.0),
        "planFollowed": True,
    }
    if extra:
        trade_extra.update(extra)
    trade = append_paper_trade(
        account,
        symbol=symbol,
        side="SELL",
        quantity=sell_quantity,
        price=price,
        reason=reason,
        signal_id=signal_id,
        executed_at=executed_at,
        realized_pnl=accrued if closes_position else realized,
        closes_position=closes_position,
        extra=trade_extra,
    )
    positions = account.get("positions") if isinstance(account.get("positions"), dict) else {}
    if closes_position:
        positions.pop(symbol, None)
        risk = account.setdefault("risk", {})
        if not isinstance(risk, dict):
            risk = {}
            account["risk"] = risk
        realized_r_for_streak = realized_r if realized_r is not None else (accrued / initial_risk / sell_quantity if initial_risk > 0 and sell_quantity > 0 else 0)
        is_r_loss = realized_r_for_streak < 0
        loss_streak = int(clean_float(risk.get("lossStreak"), 0, 0))
        risk["lossStreak"] = loss_streak + 1 if is_r_loss else 0
        entry_type = str(position.get("entryType") or position.get("trigger") or "unknown")
        asset_type = str(position.get("assetType") or "unknown")
        by_entry = risk.setdefault("lossStreakByEntryType", {})
        if not isinstance(by_entry, dict):
            by_entry = {}
            risk["lossStreakByEntryType"] = by_entry
        by_asset = risk.setdefault("lossStreakByAssetType", {})
        if not isinstance(by_asset, dict):
            by_asset = {}
            risk["lossStreakByAssetType"] = by_asset
        by_entry[entry_type] = int(clean_float(by_entry.get(entry_type), 0, 0)) + 1 if is_r_loss else 0
        by_asset[asset_type] = int(clean_float(by_asset.get(asset_type), 0, 0)) + 1 if is_r_loss else 0
        risk["lastRealizedR"] = realized_r_for_streak
        risk["entryPaused"] = risk["lossStreak"] >= 3
    else:
        position["quantity"] = remaining
        position["realizedPnlUsdt"] = accrued
    return trade


def append_paper_equity_point(account: dict[str, object], snapshot: dict[str, object], executed_at: str) -> None:
    metrics = paper_account_metrics(account, snapshot)
    curve = account.setdefault("equityCurve", [])
    if not isinstance(curve, list):
        curve = []
        account["equityCurve"] = curve
    curve.append(
        {
            "time": executed_at,
            "dailyDate": str(snapshot.get("latest_daily_date") or "")[:32],
            "equityUsdt": metrics["equityUsdt"],
            "cashUsdt": metrics["cashUsdt"],
            "positionValueUsdt": metrics["positionValueUsdt"],
            "unrealizedPnlUsdt": metrics["unrealizedPnlUsdt"],
            "realizedPnlUsdt": metrics["realizedPnlUsdt"],
        }
    )
    del curve[:-MAX_PAPER_EQUITY_POINTS]


def run_paper_account_once(account: dict[str, object], snapshot: dict[str, object]) -> dict[str, object]:
    account = sanitize_paper_account_config(account)
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be an object")
    by_symbol = paper_snapshot_items(snapshot)
    executed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    run_log: list[dict[str, object]] = []
    processed = account.setdefault("processedSignals", [])
    if not isinstance(processed, list):
        processed = []
        account["processedSignals"] = processed
    positions = account.setdefault("positions", {})
    if not isinstance(positions, dict):
        positions = {}
        account["positions"] = positions
    settings = account.get("settings") if isinstance(account.get("settings"), dict) else {}
    slippage_pct = clean_float(settings.get("slippagePct"), 0.1, 0.0)
    stop_execution_mode = str(settings.get("stopExecutionMode") or "intraday_stop")
    if stop_execution_mode not in {"intraday_stop", "close_confirm_stop"}:
        stop_execution_mode = "intraday_stop"
    max_open_risk_pct = clean_float(settings.get("maxOpenRiskPct"), 3.0, 0.1)

    for symbol, position in list(positions.items()):
        if not isinstance(position, dict):
            continue
        item = by_symbol.get(str(symbol).upper())
        price = paper_price_for_item(item) or clean_float(position.get("lastPrice"), 0.0, 0.0)
        if price <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "缺少当前价格，无法评估退出"})
            continue
        position["lastPrice"] = price
        short_term = item.get("short_term") if isinstance(item, dict) and isinstance(item.get("short_term"), dict) else {}
        daily_open = clean_float(short_term.get("daily_open"), price, 0.0)
        daily_high = clean_float(short_term.get("daily_high"), price, 0.0)
        daily_low = clean_float(short_term.get("daily_low"), price, 0.0)
        stop_price = clean_float(position.get("stopPrice"), 0.0, 0.0)
        target_price = clean_float(position.get("targetPrice"), 0.0, 0.0)
        target2_price = clean_float(position.get("target2Price"), 0.0, 0.0)
        quantity = clean_float(position.get("quantity"), 0.0, 0.0)
        signal_id = paper_signal_id(snapshot, str(symbol).upper(), "sell", item or {"symbol": symbol})
        entry_price = clean_float(position.get("entryPrice"), clean_float(position.get("avgCostUsdt"), 0.0, 0.0), 0.0)
        initial_risk = clean_float(position.get("initialRiskPerShare"), 0.0, 0.0)
        if initial_risk > 0 and entry_price > 0:
            favorable_r = ((daily_high or price) - entry_price) / initial_risk
            adverse_r = ((daily_low or price) - entry_price) / initial_risk
            position["maxFavorableR"] = max(clean_float(position.get("maxFavorableR"), favorable_r), favorable_r)
            position["maxAdverseR"] = min(clean_float(position.get("maxAdverseR"), adverse_r), adverse_r)
        trade = None
        intraday_stop_hit = stop_price > 0 and (price <= stop_price or daily_low <= stop_price)
        close_stop_hit = stop_price > 0 and price <= stop_price
        target1_hit = target_price > 0 and (price >= target_price or daily_high >= target_price)
        target2_hit = target2_price > 0 and (price >= target2_price or daily_high >= target2_price)
        ambiguous_intraday = bool(intraday_stop_hit and (target1_hit or target2_hit))
        if intraday_stop_hit if stop_execution_mode == "intraday_stop" else close_stop_hit:
            slipped_stop = stop_price * (1 - slippage_pct / 100)
            exit_price = price if stop_execution_mode == "close_confirm_stop" else min(price, slipped_stop)
            if stop_execution_mode == "intraday_stop" and daily_open > 0 and daily_open < stop_price:
                exit_price = min(exit_price, daily_open)
            trade = close_paper_position(
                account,
                position,
                quantity,
                exit_price,
                "触发短线硬止损",
                signal_id,
                executed_at,
                {"exitReason": "hard_stop", "slippagePct": slippage_pct, "ambiguousIntraday": ambiguous_intraday},
            )
        if trade is None and stop_price > 0 and price <= stop_price:
            trade = close_paper_position(account, position, quantity, price, "触发短线止损", signal_id, executed_at)
        elif trade is None and target2_hit:
            trade = close_paper_position(account, position, quantity, max(price, target2_price), "到达第二止盈", signal_id, executed_at)
        elif trade is None and target1_hit and not position.get("partialTaken"):
            trade = close_paper_position(account, position, quantity * 0.5, max(price, target_price), "到达第一止盈，卖出一半", signal_id, executed_at)
            if str(symbol).upper() in positions:
                position["partialTaken"] = True
                trail_by_atr = clean_float(short_term.get("atr"), 0.0, 0.0) * clean_float(short_term.get("trailing_stop_atr_multiplier"), 1.5, 0.0)
                trailing_stop = price - trail_by_atr if trail_by_atr > 0 else 0
                position["stopPrice"] = max(stop_price, clean_float(position.get("avgCostUsdt"), 0.0, 0.0), trailing_stop)
        elif trade is None and short_term.get("sell_signal"):
            sell_reasons = short_term.get("sell_reasons")
            if not isinstance(sell_reasons, list):
                sell_reasons = []
            reason = "、".join(str(item) for item in sell_reasons[:3]) or "短线卖出信号"
            trade = close_paper_position(account, position, quantity, price, reason, signal_id, executed_at)
        elif trade is None and short_term.get("soft_exit_action") == "tighten_stop":
            tightened_stop = max(stop_price, min(price, entry_price))
            if tightened_stop > stop_price:
                position["stopPrice"] = tightened_stop
            soft_reasons = short_term.get("soft_exit_reasons")
            if not isinstance(soft_reasons, list):
                soft_reasons = []
            run_log.append({
                "symbol": symbol,
                "action": "watch",
                "reason": "单个软退出信号，仅预警并收紧止损：" + "、".join(str(item) for item in soft_reasons[:2]),
            })
        if not trade:
            holding_days = paper_holding_days(position, executed_at)
            max_favorable_r = clean_float(position.get("maxFavorableR"), 0.0)
            target1_taken = bool(position.get("partialTaken"))
            if holding_days is not None and holding_days >= 14 and not target1_taken:
                trade = close_paper_position(account, position, quantity, price, "时间止损：持仓超过 14 天未到 TP2", signal_id, executed_at, {"exitReason": "time_stop"})
            elif holding_days is not None and holding_days >= 10 and not target1_taken:
                structure_broken = bool(short_term.get("soft_exit_action") == "exit" or short_term.get("hard_exit_reasons"))
                if price < entry_price:
                    trade = close_paper_position(account, position, quantity, price, "时间止损：10 天未到 TP1 且低于入场价", signal_id, executed_at, {"exitReason": "time_stop"})
                elif short_term.get("price_above_sma20") and not structure_broken:
                    position["stopPrice"] = max(stop_price, entry_price)
                    run_log.append({"symbol": symbol, "action": "watch", "reason": "时间止损预警：10 天未到 TP1，但仍在 SMA20 上方且结构未破，止损上移至不低于成本"})
                else:
                    trade = close_paper_position(account, position, quantity, price, "时间止损：10 天未到 TP1 且结构转弱", signal_id, executed_at, {"exitReason": "time_stop"})
            elif holding_days is not None and holding_days >= 5 and max_favorable_r < 0.8:
                run_log.append({"symbol": symbol, "action": "watch", "reason": "时间止损预警：5 天内最高浮盈未到 0.8R"})
        if trade:
            run_log.append({"symbol": symbol, "action": "sell", "reason": trade["reason"], "quantity": trade["quantity"], "price": price})

    risk = account.setdefault("risk", {})
    if not isinstance(risk, dict):
        risk = {}
        account["risk"] = risk
    loss_streak = int(clean_float(risk.get("lossStreak"), 0, 0))
    entry_multiplier = 0.5 if loss_streak >= 2 else 1.0
    entry_paused = loss_streak >= 3
    risk["entryPaused"] = entry_paused

    candidates = []
    for symbol, item in by_symbol.items():
        short_term = item.get("short_term") if isinstance(item.get("short_term"), dict) else {}
        if short_term.get("buy_signal") and item.get("role") != "cash" and symbol not in positions:
            candidates.append((clean_float(short_term.get("risk_reward"), 0.0), symbol, item, short_term))
    candidates.sort(key=lambda row: (-row[0], row[1]))

    for _, symbol, item, short_term in candidates:
        signal_id = paper_signal_id(snapshot, symbol, "buy", item)
        if signal_id in processed:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "同一日同一买入信号已处理"})
            continue
        if entry_paused:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "连续亏损 3 笔，暂停新开仓"})
            continue
        price = paper_price_for_item(item)
        stop_price = clean_float(short_term.get("stop_price"), 0.0, 0.0)
        target_price = clean_float(short_term.get("target_price"), 0.0, 0.0)
        target2_price = clean_float(short_term.get("target2_price"), 0.0, 0.0)
        if not price or stop_price <= 0 or stop_price >= price:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "缺少有效入场价或止损位"})
            continue
        stop_distance_pct = (price - stop_price) / price * 100
        if stop_distance_pct <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "止损距离无效"})
            continue
        settings = account.get("settings") if isinstance(account.get("settings"), dict) else {}
        risk_per_trade_pct = clean_float(settings.get("riskPerTradePct"), 1.0, 0.1)
        entry_position_pct = clean_float(settings.get("entryPositionPct"), 5.0, 1.0)
        target_etf_pct = clean_float(settings.get("targetEtfWeightPct"), 60.0, 0.0)
        target_stock_pct = clean_float(settings.get("targetStockWeightPct"), 40.0, 0.0)
        max_single_pct = clean_float(settings.get("maxSinglePositionPct"), 15.0, 1.0)
        metrics_now = paper_account_metrics(account, snapshot)
        equity = clean_float(metrics_now.get("equityUsdt"), DEFAULT_PAPER_CASH_USDT, 0.0)
        asset_type = paper_asset_type_for_item(item)
        theme = paper_theme_for_item(item)
        theme_max_pct = clean_float(short_term.get("theme_max_position_pct"), 20.0, 1.0)
        bucket_target_pct = target_stock_pct if asset_type == "stock" else target_etf_pct
        bucket_value_key = "stockValueUsdt" if asset_type == "stock" else "etfValueUsdt"
        bucket_label = "个股" if asset_type == "stock" else "ETF"
        bucket_current_value = clean_float(metrics_now.get(bucket_value_key), 0.0, 0.0)
        bucket_remaining_value = max(0.0, equity * bucket_target_pct / 100 - bucket_current_value)
        single_remaining_value = max(0.0, equity * max_single_pct / 100)
        theme_current_value = 0.0
        for held_symbol, held_position in positions.items():
            if not isinstance(held_position, dict):
                continue
            held_item = by_symbol.get(str(held_symbol).upper())
            if paper_theme_for_position(held_position, held_item) != theme:
                continue
            held_price = paper_price_for_item(held_item) or clean_float(held_position.get("lastPrice"), 0.0, 0.0)
            theme_current_value += clean_float(held_position.get("quantity"), 0.0, 0.0) * held_price
        theme_remaining_value = max(0.0, equity * theme_max_pct / 100 - theme_current_value)
        if bucket_remaining_value <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": f"{bucket_label}仓位已达 {bucket_target_pct:g}% 上限"})
            continue
        if single_remaining_value <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": f"单一品种仓位已达 {max_single_pct:g}% 上限"})
            continue
        if theme_remaining_value <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": f"{theme} 主题仓位已达 {theme_max_pct:g}% 上限"})
            continue
        risk_budget = equity * risk_per_trade_pct / 100
        risk_position_value = risk_budget / (stop_distance_pct / 100) * entry_multiplier
        entry_target_value = equity * entry_position_pct / 100 * entry_multiplier
        signal_position_pct = clean_float(short_term.get("position_pct"), entry_position_pct, 0.0)
        signal_cap_value = equity * signal_position_pct / 100 if signal_position_pct > 0 else entry_target_value
        current_open_risk_pct = clean_float(metrics_now.get("openRiskPct"), 0.0, 0.0)
        remaining_open_risk_pct = max(0.0, max_open_risk_pct - current_open_risk_pct)
        open_risk_cap_value = equity * remaining_open_risk_pct / 100 / (stop_distance_pct / 100) if stop_distance_pct > 0 else 0.0
        position_value = risk_position_value
        cash = clean_float(account.get("cashUsdt"), 0.0, 0.0)
        position_value = min(position_value, entry_target_value, signal_cap_value, cash, bucket_remaining_value, single_remaining_value, theme_remaining_value, open_risk_cap_value)
        if position_value <= 0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "模拟现金不足"})
            continue
        position_pct = position_value / equity * 100 if equity > 0 else 0.0
        if position_pct < 1.0:
            run_log.append({"symbol": symbol, "action": "skip", "reason": "按风险反推后实际仓位低于 1%，放弃开仓"})
            continue
        cap_notes: list[str] = []
        if position_value < risk_position_value - 0.01:
            if entry_target_value <= position_value + 0.01:
                cap_notes.append(f"单次开仓 {entry_position_pct:g}%")
            if cash <= position_value + 0.01:
                cap_notes.append("现金上限")
            if bucket_remaining_value <= position_value + 0.01:
                cap_notes.append(f"{bucket_label} {bucket_target_pct:g}% 上限")
            if single_remaining_value <= position_value + 0.01:
                cap_notes.append(f"单品种 {max_single_pct:g}% 上限")
            if theme_remaining_value <= position_value + 0.01:
                cap_notes.append(f"{theme} 主题 {theme_max_pct:g}% 上限")
            if signal_cap_value <= position_value + 0.01:
                cap_notes.append("信号风险降仓")
            if open_risk_cap_value <= position_value + 0.01:
                cap_notes.append(f"组合开放风险 {max_open_risk_pct:g}% 上限")
        buy_reason = f"建议买入信号；基础开仓 {entry_position_pct:g}%"
        if entry_multiplier < 1:
            buy_reason += "；连续亏损降仓 50%"
        if cap_notes:
            buy_reason += "；仓位按" + "、".join(cap_notes) + "截断"
        quantity = position_value / price
        account["cashUsdt"] = cash - position_value
        positions[symbol] = {
            "symbol": symbol,
            "assetType": asset_type,
            "theme": theme,
            "quantity": quantity,
            "initialQuantity": quantity,
            "entryPrice": price,
            "avgCostUsdt": price,
            "lastPrice": price,
            "stopPrice": stop_price,
            "targetPrice": target_price,
            "target2Price": target2_price,
            "partialTaken": False,
            "realizedPnlUsdt": 0.0,
            "openedAt": executed_at,
            "openedDate": str(snapshot.get("latest_daily_date") or item.get("date") or "")[:32],
            "openedSignalId": signal_id,
            "source": "short_term",
            "trigger": str(short_term.get("trigger") or ""),
            "entryType": str(short_term.get("entry_type") or short_term.get("trigger") or ""),
            "riskReward": clean_float(short_term.get("risk_reward"), 0.0, 0.0),
            "stopDistancePct": stop_distance_pct,
            "positionPct": position_pct,
            "riskBudgetPct": risk_per_trade_pct,
            "initialRiskPerShare": price - stop_price,
            "target1R": clean_float(short_term.get("target1_r"), 0.0, 0.0) or None,
            "target2R": clean_float(short_term.get("target2_r"), 0.0, 0.0) or None,
            "maxFavorableR": 0.0,
            "maxAdverseR": 0.0,
            "slippagePct": slippage_pct,
            "entryPositionPct": entry_position_pct,
            "allocationCapPct": bucket_target_pct,
            "singleCapPct": max_single_pct,
        }
        trade_extra = {
            "assetType": asset_type,
            "entryType": str(short_term.get("entry_type") or short_term.get("trigger") or ""),
            "theme": theme,
            "stopPrice": stop_price,
            "stopDistancePct": stop_distance_pct,
            "positionPct": position_pct,
            "riskBudgetPct": risk_per_trade_pct,
            "target1Price": target_price,
            "target2Price": target2_price,
            "target1R": clean_float(short_term.get("target1_r"), 0.0, 0.0) or None,
            "target2R": clean_float(short_term.get("target2_r"), 0.0, 0.0) or None,
            "eventRiskStatus": str(short_term.get("event_risk_status") or ""),
            "volumeConfirmed": bool(short_term.get("pullback_volume_ok") or short_term.get("breakout_volume_ok")),
            "planFollowed": True,
            "slippagePct": slippage_pct,
        }
        append_paper_trade(
            account,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=price,
            reason=buy_reason,
            signal_id=signal_id,
            executed_at=executed_at,
            extra=trade_extra,
        )
        processed.append(signal_id)
        run_log.append({"symbol": symbol, "action": "buy", "reason": buy_reason, "quantity": quantity, "price": price})

    del processed[:-MAX_PAPER_PROCESSED_SIGNALS]
    append_paper_equity_point(account, snapshot, executed_at)
    account["lastRunAt"] = executed_at
    account["lastRunLog"] = run_log[-80:]
    account["updatedAt"] = executed_at
    account["metrics"] = paper_account_metrics(account, snapshot)
    return sanitize_paper_account_config(account) | {"metrics": account["metrics"]}


def detect_tailscale() -> dict[str, str | bool | None]:
    tailscale = shutil.which("tailscale")
    if not tailscale:
        return {"installed": False, "path": None, "status": "not_installed", "url_hint": None}

    try:
        proc = subprocess.run(
            [tailscale, "status", "--json"],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return {"installed": True, "path": tailscale, "status": f"status_error: {exc}", "url_hint": None}

    if proc.returncode != 0:
        return {"installed": True, "path": tailscale, "status": "not_logged_in", "url_hint": None}

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"installed": True, "path": tailscale, "status": "unknown", "url_hint": None}

    dns_name = ((payload.get("Self") or {}).get("DNSName") or "").rstrip(".")
    url_hint = f"https://{dns_name}" if dns_name else None
    return {"installed": True, "path": tailscale, "status": "logged_in", "url_hint": url_hint}


def start_tailscale_serve(port: int) -> dict[str, str | bool | None]:
    tailscale = shutil.which("tailscale")
    if not tailscale:
        return {"started": False, "message": "tailscale command not found"}

    cmd = [tailscale, "serve", "--bg", f"127.0.0.1:{port}"]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip() or "tailscale serve failed"
        return {"started": False, "message": message}
    return {"started": True, "message": "tailscale serve is enabled for this dashboard"}


def cached_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def cached_bool(value: object) -> bool:
    return str(value or "").strip().lower() == "true"


def cached_list(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def cached_report_regime(report_path: Path) -> str:
    if not report_path.exists():
        return "CACHED"
    try:
        for line in report_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("- Regime:"):
                return line.split(":", 1)[1].strip() or "CACHED"
    except Exception:
        return "CACHED"
    return "CACHED"


def load_cached_signal_snapshot(report_dir: Path, reason: str) -> dict[str, object]:
    csv_path = report_dir / "latest_signals.csv"
    markdown_path = report_dir / "latest_report.md"
    if not csv_path.exists():
        raise RuntimeError(reason)

    symbols: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            symbols.append(
                {
                    "date": str(row.get("date") or ""),
                    "symbol": symbol,
                    "role": str(row.get("role") or ""),
                    "close": cached_float(row.get("close")),
                    "sma200": cached_float(row.get("sma200")),
                    "sma50": None,
                    "sma20": None,
                    "trend_ok": cached_bool(row.get("trend_ok")),
                    "structure_ok": cached_bool(row.get("structure_ok")),
                    "near_support": cached_bool(row.get("near_support")),
                    "near_resistance": cached_bool(row.get("near_resistance")),
                    "breakout_hold": cached_bool(row.get("breakout_hold")),
                    "pullback_stand": cached_bool(row.get("pullback_stand")),
                    "risk_signal": cached_bool(row.get("risk_signal")),
                    "risk_reasons": cached_list(row.get("risk_reasons")),
                    "momentum_63_pct": cached_float(row.get("momentum_63_pct")),
                    "momentum_126_pct": cached_float(row.get("momentum_126_pct")),
                    "support": cached_float(row.get("support")),
                    "resistance": cached_float(row.get("resistance")),
                    "target_pct": cached_float(row.get("target_pct")),
                    "current_pct": cached_float(row.get("current_pct")),
                    "trade_delta_pct": cached_float(row.get("trade_delta_pct")),
                    "action": str(row.get("action") or "WATCH"),
                    "limit_price": cached_float(row.get("limit_price")),
                    "notes": cached_list(row.get("notes")),
                    "current_price": None,
                    "current_time": None,
                    "day_change_pct": None,
                    "ten_min_change_pct": None,
                }
            )

    if not symbols:
        raise RuntimeError(reason)

    latest_date = max(str(item.get("date") or "") for item in symbols)
    generated_at = dt.datetime.fromtimestamp(csv_path.stat().st_mtime, tz=dt.timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "latest_daily_date": latest_date,
        "regime": cached_report_regime(markdown_path),
        "drawdown_pct": None,
        "order_rule": "regular-session limit orders only; no market orders",
        "symbols": symbols,
        "errors": {
            "daily": {
                "__snapshot__": f"实时行情生成失败，已使用本地缓存：{reason}",
            },
            "intraday": {},
        },
        "report_paths": {
            "csv": str(csv_path.resolve()),
            "markdown": str(markdown_path.resolve()),
        },
        "cache": {
            "used": True,
            "reason": reason,
            "source": str(csv_path.resolve()),
        },
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ETFTradingDashboard/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[server] {self.address_string()} {fmt % args}")

    @property
    def app(self) -> "DashboardServer":
        return self.server  # type: ignore[return-value]

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/api/snapshot", "/api/refresh"):
            self.handle_snapshot()
            return
        if parsed.path == "/api/config":
            self.handle_config()
            return
        if parsed.path == "/api/asset-pool":
            self.handle_asset_pool_get()
            return
        if parsed.path == "/api/manual-holdings":
            self.handle_manual_holdings_get()
            return
        if parsed.path == "/api/paper-account":
            self.handle_paper_account_get()
            return
        if parsed.path == "/api/ui-cache":
            self.handle_ui_cache_get()
            return
        if parsed.path == "/api/instrument-search":
            self.handle_instrument_search(parsed)
            return
        if parsed.path == "/api/integrations/binance/status":
            self.handle_binance_status()
            return
        if parsed.path == "/api/integrations/binance/spot-account":
            self.handle_binance_spot_account()
            return
        if parsed.path == "/api/status":
            self.send_json(self.app.status_payload())
            return
        self.handle_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.handle_config_post()
            return
        if parsed.path == "/api/asset-pool":
            self.handle_asset_pool_post()
            return
        if parsed.path == "/api/manual-holdings":
            self.handle_manual_holdings_post()
            return
        if parsed.path == "/api/paper-account/reset":
            self.handle_paper_account_reset()
            return
        if parsed.path == "/api/paper-account/run":
            self.handle_paper_account_run()
            return
        if parsed.path == "/api/paper-account/settings":
            self.handle_paper_account_settings()
            return
        if parsed.path == "/api/ui-cache":
            self.handle_ui_cache_post()
            return
        if parsed.path == "/api/integrations/binance/test-connection":
            self.handle_binance_test_connection()
            return
        if parsed.path == "/api/integrations/binance/refresh":
            self.handle_binance_spot_account()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if length < 1:
            return {}
        if length > 1_000_000:
            raise ValueError("Request body is too large")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def handle_config(self) -> None:
        try:
            with self.app.config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            self.send_json(
                {
                    "ok": True,
                    "config": config,
                    "server": self.app.status_payload(),
                    "capabilities": {
                        "read_config": True,
                        "save_draft": True,
                        "run_validation_backtest": False,
                        "publish_config": False,
                        "rollback_config": False,
                    },
                }
            )
        except Exception as exc:
            try:
                snapshot = load_cached_signal_snapshot(self.app.report_dir, str(exc))
                snapshot["server"] = self.app.status_payload()
                self.send_json({"ok": True, "snapshot": snapshot, "warning": str(exc)})
            except Exception:
                self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_config_post(self) -> None:
        try:
            payload = self.read_json_body()
            changes = payload.get("changes") if isinstance(payload, dict) else None
            current = self.app.load_main_config()
            next_config = apply_config_edits(current, changes)
            saved = self.app.save_main_config(next_config)
            self.send_json(
                {
                    "ok": True,
                    "config": saved,
                    "server": self.app.status_payload(),
                    "capabilities": {
                        "read_config": True,
                        "save_draft": True,
                        "run_validation_backtest": False,
                        "publish_config": False,
                        "rollback_config": False,
                    },
                }
            )
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_REQUEST)

    def handle_asset_pool_get(self) -> None:
        try:
            config = self.app.load_asset_pool_config()
            self.send_json(
                {
                    "ok": True,
                    "config": config,
                    "capabilities": {
                        "read": True,
                        "persistConfig": True,
                        "removeInstrument": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_asset_pool_post(self) -> None:
        try:
            payload = self.read_json_body()
            config = sanitize_asset_pool_config(payload.get("config", payload))
            saved = self.app.save_asset_pool_config(config)
            self.send_json(
                {
                    "ok": True,
                    "config": saved,
                    "capabilities": {
                        "read": True,
                        "persistConfig": True,
                        "removeInstrument": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_manual_holdings_get(self) -> None:
        try:
            config = self.app.load_manual_holdings_config()
            self.send_json(
                {
                    "ok": True,
                    "config": config,
                    "capabilities": {
                        "read": True,
                        "persistConfig": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_manual_holdings_post(self) -> None:
        try:
            payload = self.read_json_body()
            config = sanitize_manual_holdings_config(payload.get("config", payload))
            saved = self.app.save_manual_holdings_config(config)
            self.send_json(
                {
                    "ok": True,
                    "config": saved,
                    "capabilities": {
                        "read": True,
                        "persistConfig": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_paper_account_get(self) -> None:
        try:
            account = self.app.load_paper_account_config()
            account["metrics"] = paper_account_metrics(account)
            self.send_json(
                {
                    "ok": True,
                    "account": account,
                    "capabilities": {
                        "read": True,
                        "reset": True,
                        "run": True,
                        "saveSettings": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_paper_account_reset(self) -> None:
        try:
            payload = self.read_json_body()
            raw_initial = payload.get("initialCashUsdt", payload.get("initial_cash_usdt", DEFAULT_PAPER_CASH_USDT))
            account = self.app.reset_paper_account_config(clean_float(raw_initial, DEFAULT_PAPER_CASH_USDT, 1.0))
            account["metrics"] = paper_account_metrics(account)
            self.send_json({"ok": True, "account": account, "server": self.app.status_payload()})
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_paper_account_run(self) -> None:
        try:
            payload = self.read_json_body()
            snapshot = payload.get("snapshot", payload)
            if not isinstance(snapshot, dict):
                raise ValueError("Missing snapshot")
            account = self.app.run_paper_account(snapshot)
            self.send_json({"ok": True, "account": account, "server": self.app.status_payload()})
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_paper_account_settings(self) -> None:
        try:
            payload = self.read_json_body()
            settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
            if not isinstance(settings_payload, dict):
                raise ValueError("Missing settings payload")
            account = self.app.update_paper_account_settings(settings_payload)
            account["metrics"] = paper_account_metrics(account)
            self.send_json(
                {
                    "ok": True,
                    "account": account,
                    "capabilities": {
                        "read": True,
                        "reset": True,
                        "run": True,
                        "saveSettings": True,
                    },
                    "server": self.app.status_payload(),
                }
            )
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_ui_cache_get(self) -> None:
        try:
            cache = self.app.load_dashboard_view_cache()
            self.send_json({"ok": True, "cache": cache, "server": self.app.status_payload()})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_ui_cache_post(self) -> None:
        try:
            payload = self.read_json_body()
            cache = payload.get("cache", payload)
            if not isinstance(cache, dict):
                raise ValueError("UI cache must be an object")
            saved = self.app.save_dashboard_view_cache(cache)
            self.send_json({"ok": True, "cache": saved, "server": self.app.status_payload()})
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_binance_status(self) -> None:
        load_local_env(external_root())
        self.send_json({"ok": True, "status": integration_status(), "server": self.app.status_payload()})

    def handle_binance_test_connection(self) -> None:
        load_local_env(external_root())
        try:
            self.send_json({"ok": True, "result": test_connection(), "server": self.app.status_payload()})
        except BinanceIntegrationError as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": exc.code,
                    "status": integration_status(),
                    "server": self.app.status_payload(),
                },
                HTTPStatus.BAD_GATEWAY if exc.code != "not_configured" else HTTPStatus.OK,
            )
        except Exception:
            self.send_json(
                {
                    "ok": False,
                    "error": "Binance 账户连接测试失败。",
                    "code": "binance_test_failed",
                    "status": integration_status(),
                    "server": self.app.status_payload(),
                },
                HTTPStatus.BAD_GATEWAY,
            )

    def handle_binance_spot_account(self) -> None:
        load_local_env(external_root())
        try:
            self.send_json({"ok": True, "account": build_spot_account_summary(), "server": self.app.status_payload()})
        except BinanceIntegrationError as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": exc.code,
                    "status": integration_status(),
                    "server": self.app.status_payload(),
                },
                HTTPStatus.BAD_GATEWAY if exc.code != "not_configured" else HTTPStatus.OK,
            )
        except Exception:
            self.send_json(
                {
                    "ok": False,
                    "error": "Binance Spot 账户读取失败。",
                    "code": "binance_account_failed",
                    "status": integration_status(),
                    "server": self.app.status_payload(),
                },
                HTTPStatus.BAD_GATEWAY,
            )

    def handle_instrument_search(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("q") or [""])[0].strip()
        if not query:
            self.send_json({"ok": True, "results": [], "query": query})
            return
        try:
            with self.app.config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            asset_pool = self.app.load_asset_pool_config()
            hidden_symbols = hidden_asset_pool_symbols(asset_pool)
            active_symbols = (all_config_symbols(config) - hidden_symbols) | active_asset_pool_symbols(asset_pool)
            search_error = ""
            try:
                results = search_yahoo_instruments(query)
                if not results:
                    results = [lookup_yahoo_instrument(query)]
            except Exception as exc:
                search_error = str(exc)
                fallback = local_instrument_search_result(query, config, asset_pool)
                results = [fallback] if fallback else []
            for result in results:
                symbol = str(result.get("symbol") or "").upper()
                result["alreadyAdded"] = symbol in active_symbols
                result["activeGroupIds"] = asset_pool_symbol_groups(asset_pool, symbol)
            self.send_json({"ok": True, "results": results, "query": query, "error": search_error, "server": self.app.status_payload()})
        except Exception as exc:
            self.send_json({"ok": True, "results": [], "query": query, "error": str(exc), "server": self.app.status_payload()})

    def handle_snapshot(self) -> None:
        try:
            with self.app.config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            asset_pool = self.app.load_asset_pool_config()
            merged_config = merge_asset_pool_into_config(config, asset_pool)
            snapshot = generate_signal_snapshot(
                config_path=self.app.config_path,
                report_dir=self.app.report_dir,
                include_intraday=True,
                write_outputs=True,
                config_override=merged_config,
            )
            snapshot["server"] = self.app.status_payload()
            self.send_json({"ok": True, "snapshot": snapshot})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "server": self.app.status_payload()}, HTTPStatus.BAD_GATEWAY)

    def handle_static(self, request_path: str) -> None:
        path = unquote(request_path.lstrip("/")) or "index.html"
        if path.endswith("/"):
            path += "index.html"
        root = self.app.dashboard_root.resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)) or not target.exists() or target.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        mime, _ = mimetypes.guess_type(target)
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[DashboardHandler], config_path: Path, report_dir: Path, dashboard_root: Path, asset_pool_path: Path, manual_holdings_path: Path, paper_account_path: Path, ui_cache_path: Path):
        super().__init__(server_address, handler_class)
        self.config_path = config_path
        self.report_dir = report_dir
        self.dashboard_root = dashboard_root
        self.asset_pool_path = asset_pool_path
        self.manual_holdings_path = manual_holdings_path
        self.paper_account_path = paper_account_path
        self.ui_cache_path = ui_cache_path
        self.tailscale_status = detect_tailscale()

    def load_main_config(self) -> dict[str, object]:
        with self.config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError("Config root must be an object")
        return config

    def save_main_config(self, config: dict[str, object]) -> dict[str, object]:
        if not isinstance(config, dict):
            raise ValueError("Config root must be an object")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, self.config_path)
        return config

    def load_asset_pool_config(self) -> dict[str, object]:
        if not self.asset_pool_path.exists():
            return empty_asset_pool_config()
        with self.asset_pool_path.open("r", encoding="utf-8") as f:
            return sanitize_asset_pool_config(json.load(f))

    def save_asset_pool_config(self, config: dict[str, object]) -> dict[str, object]:
        sanitized = sanitize_asset_pool_config(config)
        self.asset_pool_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.asset_pool_path.with_suffix(self.asset_pool_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(sanitized, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, self.asset_pool_path)
        return sanitized

    def load_manual_holdings_config(self) -> dict[str, object]:
        if not self.manual_holdings_path.exists():
            return empty_manual_holdings_config()
        with self.manual_holdings_path.open("r", encoding="utf-8") as f:
            return sanitize_manual_holdings_config(json.load(f))

    def save_manual_holdings_config(self, config: dict[str, object]) -> dict[str, object]:
        sanitized = sanitize_manual_holdings_config(config)
        self.manual_holdings_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.manual_holdings_path.with_suffix(self.manual_holdings_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(sanitized, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, self.manual_holdings_path)
        return sanitized

    def load_paper_account_config(self) -> dict[str, object]:
        if not self.paper_account_path.exists():
            return empty_paper_account_config()
        with self.paper_account_path.open("r", encoding="utf-8") as f:
            return sanitize_paper_account_config(json.load(f))

    def save_paper_account_config(self, config: dict[str, object]) -> dict[str, object]:
        sanitized = sanitize_paper_account_config(config)
        self.paper_account_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.paper_account_path.with_suffix(self.paper_account_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(sanitized, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, self.paper_account_path)
        return sanitized

    def reset_paper_account_config(self, initial_cash: float = DEFAULT_PAPER_CASH_USDT) -> dict[str, object]:
        return self.save_paper_account_config(empty_paper_account_config(initial_cash))

    def update_paper_account_settings(self, settings_patch: dict[str, object]) -> dict[str, object]:
        account = self.load_paper_account_config()
        settings = account.get("settings") if isinstance(account.get("settings"), dict) else {}
        settings = dict(settings)
        for key in (
            "entryPositionPct",
            "riskPerTradePct",
            "targetEtfWeightPct",
            "targetStockWeightPct",
            "maxSinglePositionPct",
            "maxOpenRiskPct",
            "stopExecutionMode",
            "slippagePct",
            "autoRun",
        ):
            if key in settings_patch:
                settings[key] = settings_patch.get(key)
        account["settings"] = settings
        return self.save_paper_account_config(account)

    def run_paper_account(self, snapshot: dict[str, object]) -> dict[str, object]:
        account = self.load_paper_account_config()
        updated = run_paper_account_once(account, snapshot)
        saved = self.save_paper_account_config(updated)
        saved["metrics"] = paper_account_metrics(saved, snapshot)
        return saved

    def load_dashboard_view_cache(self) -> dict[str, object] | None:
        if not self.ui_cache_path.exists():
            return None
        with self.ui_cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None

    def save_dashboard_view_cache(self, cache: dict[str, object]) -> dict[str, object]:
        self.ui_cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.ui_cache_path.with_suffix(self.ui_cache_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, self.ui_cache_path)
        return cache

    def status_payload(self) -> dict[str, object]:
        port = self.server_address[1]
        return {
            "local_url": f"http://127.0.0.1:{port}",
            "tailscale": self.tailscale_status,
            "config_path": str(self.config_path.resolve()),
            "asset_pool_path": str(self.asset_pool_path.resolve()),
            "manual_holdings_path": str(self.manual_holdings_path.resolve()),
            "paper_account_path": str(self.paper_account_path.resolve()),
            "ui_cache_path": str(self.ui_cache_path.resolve()),
            "report_dir": str(self.report_dir.resolve()),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF trading dashboard server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address. Keep 127.0.0.1 when using Tailscale Serve.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local dashboard port")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.json")
    parser.add_argument("--report-dir", type=Path, default=None, help="Report output directory")
    parser.add_argument("--no-open", action="store_true", help="Do not open a local browser")
    parser.add_argument("--tailscale-serve", action="store_true", help="Run tailscale serve --bg for this port")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_local_env(external_root())
    config_path = args.config or resolve_config()
    report_dir = args.report_dir or (external_root() / "reports")
    dashboard_root = resolve_dashboard_root()
    asset_pool_path = resolve_asset_pool_config()
    manual_holdings_path = resolve_manual_holdings_config()
    paper_account_path = resolve_paper_account_config()
    ui_cache_path = resolve_dashboard_view_cache()
    report_dir.mkdir(parents=True, exist_ok=True)

    server = DashboardServer((args.host, args.port), DashboardHandler, config_path, report_dir, dashboard_root, asset_pool_path, manual_holdings_path, paper_account_path, ui_cache_path)
    local_url = f"http://127.0.0.1:{server.server_address[1]}"
    if args.tailscale_serve:
        server.tailscale_status["serve"] = start_tailscale_serve(server.server_address[1])
        server.tailscale_status = detect_tailscale() | {"serve": server.tailscale_status["serve"]}

    print("ETF交易系统面板已启动")
    print(f"本机地址: {local_url}")
    if server.tailscale_status.get("url_hint"):
        print(f"手机 Tailscale 地址: {server.tailscale_status['url_hint']}")
        print(f"如未开启 Serve，请运行: tailscale serve --bg 127.0.0.1:{server.server_address[1]}")
    else:
        print("未检测到已登录的 Tailscale。请按 setup_tailscale.md 配置后再用手机访问。")

    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭面板服务...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
