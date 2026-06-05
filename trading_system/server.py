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
MAX_ASSET_POOL_GROUPS = 10
MAX_ASSET_POOL_GROUP_SYMBOLS = 30

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


def resolve_dashboard_view_cache() -> Path:
    return external_root() / "dashboard_view_cache.json"


def empty_asset_pool_config() -> dict[str, object]:
    return {"version": ASSET_POOL_VERSION, "groups": DEFAULT_ASSET_POOL_GROUPS, "instruments": {}}


def empty_manual_holdings_config() -> dict[str, object]:
    return {"version": MANUAL_HOLDINGS_VERSION, "holdings": {}}


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
        if parsed.path == "/api/asset-pool":
            self.handle_asset_pool_post()
            return
        if parsed.path == "/api/manual-holdings":
            self.handle_manual_holdings_post()
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
                        "save_draft": False,
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
    def __init__(self, server_address: tuple[str, int], handler_class: type[DashboardHandler], config_path: Path, report_dir: Path, dashboard_root: Path, asset_pool_path: Path, manual_holdings_path: Path, ui_cache_path: Path):
        super().__init__(server_address, handler_class)
        self.config_path = config_path
        self.report_dir = report_dir
        self.dashboard_root = dashboard_root
        self.asset_pool_path = asset_pool_path
        self.manual_holdings_path = manual_holdings_path
        self.ui_cache_path = ui_cache_path
        self.tailscale_status = detect_tailscale()

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
    ui_cache_path = resolve_dashboard_view_cache()
    report_dir.mkdir(parents=True, exist_ok=True)

    server = DashboardServer((args.host, args.port), DashboardHandler, config_path, report_dir, dashboard_root, asset_pool_path, manual_holdings_path, ui_cache_path)
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
