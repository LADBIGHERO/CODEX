#!/usr/bin/env python3
"""
Read-only Binance Spot account integration.

This module never exposes API keys, secrets, signatures, withdrawals, transfers,
or order placement. It only reads Spot account balances and public ticker prices.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BINANCE_API_BASE_URL = "https://api.binance.com"
STABLECOINS = {"USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP"}
ENV_KEYS = ("BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_API_BASE_URL")


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str
    base_url: str


class BinanceIntegrationError(RuntimeError):
    def __init__(self, message: str, code: str = "binance_error") -> None:
        super().__init__(message)
        self.code = code


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS or os.environ.get(key):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def load_local_env(root: Path) -> None:
    load_env_file(root / ".env.local")
    load_env_file(root / ".env")


def binance_credentials() -> BinanceCredentials | None:
    api_key = (os.environ.get("BINANCE_API_KEY") or "").strip()
    api_secret = (os.environ.get("BINANCE_API_SECRET") or "").strip()
    base_url = (os.environ.get("BINANCE_API_BASE_URL") or DEFAULT_BINANCE_API_BASE_URL).strip().rstrip("/")
    if not api_key or not api_secret:
        return None
    return BinanceCredentials(api_key=api_key, api_secret=api_secret, base_url=base_url)


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}****{api_key[-4:]}"


def integration_status() -> dict[str, Any]:
    creds = binance_credentials()
    return {
        "configured": creds is not None,
        "connected": False,
        "accountType": "SPOT",
        "readOnly": True,
        "baseUrl": creds.base_url if creds else os.environ.get("BINANCE_API_BASE_URL", DEFAULT_BINANCE_API_BASE_URL),
        "apiKeyMasked": mask_api_key(creds.api_key if creds else None),
        "lastSyncedAt": None,
    }


def signed_query(params: dict[str, str | int | float], secret: str) -> str:
    query = urllib.parse.urlencode(params)
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ETFTradingDashboard/1.0",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise map_binance_http_error(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise BinanceIntegrationError("Binance 请求失败，请检查网络或 API Base URL。", "network_error") from exc


def map_binance_http_error(status: int, body: str) -> BinanceIntegrationError:
    message = "Binance 请求失败。"
    code = "binance_request_failed"
    try:
        payload = json.loads(body)
        raw_code = payload.get("code")
        raw_msg = str(payload.get("msg") or "")
        if raw_code in (-2014, -2015):
            message = "API Key 无效、权限不足，或服务器 IP 不在 Binance 白名单。"
            code = "invalid_key_or_ip"
        elif raw_code in (-1021, -1022):
            message = "Binance 签名或时间戳校验失败，请检查服务器时间。"
            code = "signature_or_time_error"
        elif raw_msg:
            message = f"Binance 请求失败：{raw_msg}"
    except Exception:
        if status in (401, 403):
            message = "Binance 鉴权失败，请检查只读权限与 IP 白名单。"
            code = "auth_failed"
    return BinanceIntegrationError(message, code)


def fetch_spot_account_raw() -> dict[str, Any]:
    creds = binance_credentials()
    if creds is None:
        raise BinanceIntegrationError("未配置 Binance API Key / Secret。", "not_configured")
    params = {
        "omitZeroBalances": "true",
        "recvWindow": 5000,
        "timestamp": int(time.time() * 1000),
    }
    query = signed_query(params, creds.api_secret)
    url = f"{creds.base_url}/api/v3/account?{query}"
    payload = request_json(url, headers={"X-MBX-APIKEY": creds.api_key})
    if not isinstance(payload, dict):
        raise BinanceIntegrationError("Binance 返回了无法识别的账户响应。", "invalid_response")
    return payload


def public_price_usdt(asset: str, base_url: str) -> tuple[float | None, str]:
    asset = asset.upper()
    if asset in STABLECOINS:
        return 1.0, "stablecoin"
    if asset == "USDT":
        return 1.0, "stablecoin"
    symbol = f"{asset}USDT"
    query = urllib.parse.urlencode({"symbol": symbol})
    url = f"{base_url}/api/v3/ticker/price?{query}"
    try:
        payload = request_json(url, timeout=12)
        price = float(payload.get("price"))
        if price > 0:
            return price, "priced"
    except Exception:
        return None, "unpriced"
    return None, "unpriced"


def build_spot_account_summary() -> dict[str, Any]:
    creds = binance_credentials()
    raw = fetch_spot_account_raw()
    assert creds is not None

    assets: list[dict[str, Any]] = []
    total_value = 0.0
    has_unpriced = False
    for balance in raw.get("balances") or []:
        try:
            asset = str(balance.get("asset") or "").upper()
            free = float(balance.get("free") or 0)
            locked = float(balance.get("locked") or 0)
        except (TypeError, ValueError):
            continue
        total = free + locked
        if not asset or total <= 0:
            continue

        price, valuation_status = public_price_usdt(asset, creds.base_url)
        value = total * price if price is not None else None
        if value is not None:
            total_value += value
        else:
            has_unpriced = True
        assets.append(
            {
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
                "priceUsdt": price,
                "valueUsdt": value,
                "weightPct": None,
                "valuationStatus": valuation_status,
            }
        )

    if total_value > 0:
        for asset in assets:
            value = asset.get("valueUsdt")
            if isinstance(value, (int, float)):
                asset["weightPct"] = value / total_value * 100

    now = datetime.now(timezone.utc).isoformat()
    return {
        "source": "binance",
        "accountType": "spot",
        "readOnly": True,
        "connected": True,
        "lastSyncedAt": now,
        "totalValueUsdt": total_value if total_value > 0 else None,
        "hasUnpricedAssets": has_unpriced,
        "assets": sorted(assets, key=lambda item: item.get("valueUsdt") or 0, reverse=True),
    }


def test_connection() -> dict[str, Any]:
    summary = build_spot_account_summary()
    return {
        "connected": True,
        "accountType": "SPOT",
        "readOnly": True,
        "nonZeroAssetCount": len(summary["assets"]),
        "checkedAt": summary["lastSyncedAt"],
        "hasUnpricedAssets": summary["hasUnpricedAssets"],
    }
