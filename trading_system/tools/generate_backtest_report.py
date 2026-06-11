"""Generate a standalone backtest analysis report.

The script intentionally does not import or modify the trading application.
It reads a CSV/JSON trade-detail file, writes CSV summaries, renders PNG
charts with a small standard-library renderer, and builds a self-contained
HTML report that can be opened directly from disk.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import html
import json
import math
import os
import struct
import sys
import zlib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable


FIELD_ALIASES = {
    "symbol": ["symbol", "ticker"],
    "entry_date": ["entry_date", "buy_date", "open_date", "opened_at", "openedAt", "entryTime"],
    "exit_date": ["exit_date", "sell_date", "close_date", "closed_at", "date", "time", "exitTime"],
    "entry_price": ["entry_price", "buy_price", "open_price", "entryPrice"],
    "exit_price": ["exit_price", "sell_price", "close_price", "price", "exitPrice"],
    "quantity": ["quantity", "shares", "qty"],
    "pnl_amount": ["pnl_amount", "pnl", "profit", "net_profit", "realizedPnlUsdt", "realized_pnl"],
    "pnl_pct": ["pnl_pct", "return_pct", "returnPct"],
    "stop_loss_price": ["stop_loss_price", "stop_price", "stopPrice"],
    "r_multiple": ["r_multiple", "r", "realizedR", "realized_r"],
    "holding_days": ["holding_days", "holdingDays"],
    "entry_type": ["entry_type", "signal_type", "buy_type", "entryType"],
    "exit_reason": ["exit_reason", "sell_reason", "reason", "exitReason"],
    "equity": ["equity", "equityUsdt", "account_equity"],
}

MONEY_FIELDS = ["pnl_amount", "entry_price", "exit_price", "quantity", "stop_loss_price", "r_multiple", "holding_days", "equity"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(text).date()
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text:
            return None
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def norm_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def build_key_map(keys: Iterable[str]) -> dict[str, str]:
    normalized = {norm_key(key): key for key in keys}
    mapping: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            original = normalized.get(norm_key(alias))
            if original is not None:
                mapping[canonical] = original
                break
    return mapping


def canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    mapping = build_key_map(row.keys())
    out: dict[str, Any] = {}
    for canonical, source in mapping.items():
        out[canonical] = row.get(source)
    out["symbol"] = str(out.get("symbol") or "").upper().strip()
    out["entry_date"] = parse_date(out.get("entry_date"))
    out["exit_date"] = parse_date(out.get("exit_date"))
    for field in MONEY_FIELDS:
        if field in out:
            out[field] = parse_float(out.get(field))
    out["entry_type"] = str(out.get("entry_type") or "unknown").strip() or "unknown"
    out["exit_reason"] = str(out.get("exit_reason") or "unknown").strip() or "unknown"
    return out


def find_trade_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        trades = data.get("trades")
        if isinstance(trades, list) and all(isinstance(x, dict) for x in trades):
            return trades
        for value in data.values():
            found = find_trade_list(value)
            if found:
                return found
    if isinstance(data, list) and all(isinstance(x, dict) for x in data):
        return data
    return []


def find_equity_curve(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("equityCurve", "equity_curve", "curve"):
            value = data.get(key)
            if isinstance(value, list) and all(isinstance(x, dict) for x in value):
                return value
        for value in data.values():
            found = find_equity_curve(value)
            if found:
                return found
    return []


def direct_closed_trades(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed: list[dict[str, Any]] = []
    for raw in rows:
        row = canonicalize_row(raw)
        if not row.get("symbol") or row.get("exit_date") is None or row.get("pnl_amount") is None:
            continue
        if row.get("entry_date") and row.get("holding_days") is None:
            row["holding_days"] = max(0, (row["exit_date"] - row["entry_date"]).days)
        if row.get("r_multiple") is None:
            row["r_multiple"] = estimate_r(row)
        closed.append(row)
    return closed


def reconstruct_closed_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build closed trade rows from BUY/SELL event logs using FIFO lots."""

    lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    closed: list[dict[str, Any]] = []
    for raw in sorted(events, key=lambda x: str(x.get("time") or x.get("date") or "")):
        side = str(raw.get("side") or "").upper()
        row = canonicalize_row(raw)
        symbol = row.get("symbol")
        if not symbol:
            continue
        quantity = row.get("quantity") or 0.0
        price = row.get("exit_price") or row.get("entry_price")
        if quantity <= 0 or price is None:
            continue
        if side == "BUY":
            lots[symbol].append(
                {
                    "symbol": symbol,
                    "entry_date": row.get("exit_date") or row.get("entry_date"),
                    "entry_price": price,
                    "quantity": quantity,
                    "entry_type": row.get("entry_type") or "unknown",
                    "stop_loss_price": row.get("stop_loss_price"),
                }
            )
            continue
        if side != "SELL":
            continue
        remaining = quantity
        pnl_total = row.get("pnl_amount")
        while remaining > 1e-12 and lots[symbol]:
            lot = lots[symbol][0]
            lot_qty = float(lot.get("quantity") or 0.0)
            close_qty = min(remaining, lot_qty)
            if close_qty <= 0:
                lots[symbol].popleft()
                continue
            if pnl_total is not None and quantity > 0:
                pnl_amount = pnl_total * close_qty / quantity
            else:
                pnl_amount = (price - float(lot["entry_price"])) * close_qty
            entry_date = lot.get("entry_date")
            exit_date = row.get("exit_date")
            trade = {
                "symbol": symbol,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": lot.get("entry_price"),
                "exit_price": price,
                "quantity": close_qty,
                "pnl_amount": pnl_amount,
                "pnl_pct": ((price / float(lot["entry_price"]) - 1) * 100) if lot.get("entry_price") else None,
                "stop_loss_price": lot.get("stop_loss_price"),
                "entry_type": lot.get("entry_type") or row.get("entry_type") or "unknown",
                "exit_reason": row.get("exit_reason") or "unknown",
                "holding_days": max(0, (exit_date - entry_date).days) if entry_date and exit_date else None,
            }
            trade["r_multiple"] = row.get("r_multiple") if row.get("r_multiple") is not None else estimate_r(trade)
            closed.append(trade)
            lot["quantity"] = lot_qty - close_qty
            remaining -= close_qty
            if lot["quantity"] <= 1e-12:
                lots[symbol].popleft()
    return closed


def estimate_r(row: dict[str, Any]) -> float | None:
    entry = row.get("entry_price")
    stop = row.get("stop_loss_price")
    qty = row.get("quantity")
    pnl = row.get("pnl_amount")
    if entry is None or stop is None or qty is None or pnl is None:
        return None
    initial_risk = abs(entry - stop) * qty
    if initial_risk <= 0:
        return None
    return pnl / initial_risk


def read_input(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            raw_rows = list(csv.DictReader(f))
        trades = direct_closed_trades(raw_rows)
        equity_curve: list[dict[str, Any]] = []
    else:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_trades = find_trade_list(data)
        equity_curve = find_equity_curve(data)
        direct = direct_closed_trades(raw_trades)
        has_side_events = any(str(row.get("side") or "").upper() in {"BUY", "SELL"} for row in raw_trades)
        trades = reconstruct_closed_trades(raw_trades) if has_side_events else direct
        if has_side_events and not trades and direct:
            trades = direct
    missing = minimum_missing(path, trades)
    if missing:
        warnings.append("缺少最低要求字段或无法识别有效记录: " + ", ".join(missing))
    return trades, equity_curve, warnings


def minimum_missing(path: Path, trades: list[dict[str, Any]]) -> list[str]:
    if trades:
        return []
    return ["symbol", "exit_date", "pnl_amount"]


def money(value: float | None) -> str:
    return "N/A" if value is None else f"{value:,.2f}"


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def rfmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def group_summary(trades: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    buckets: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        buckets[key_fn(trade)].append(trade)
    rows = []
    for key, items in buckets.items():
        pnl = sum(float(t.get("pnl_amount") or 0.0) for t in items)
        wins = sum(1 for t in items if float(t.get("pnl_amount") or 0.0) > 0)
        r_values = [float(t["r_multiple"]) for t in items if t.get("r_multiple") is not None]
        rows.append(
            {
                "group": key,
                "trade_count": len(items),
                "total_pnl": pnl,
                "win_rate": wins / len(items) * 100 if items else 0.0,
                "avg_pnl": pnl / len(items) if items else 0.0,
                "avg_r": sum(r_values) / len(r_values) if r_values else None,
            }
        )
    return sorted(rows, key=lambda row: str(row["group"]))


def equity_from_trades(trades: list[dict[str, Any]], initial_capital: float, raw_equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if raw_equity_curve:
        rows = []
        for raw in raw_equity_curve:
            mapping = build_key_map(raw.keys())
            date_value = parse_date(raw.get(mapping.get("exit_date", "")) or raw.get("date") or raw.get("time"))
            equity_value = parse_float(raw.get(mapping.get("equity", "")) or raw.get("equityUsdt"))
            if date_value and equity_value is not None:
                rows.append({"date": date_value, "equity": equity_value})
        if rows:
            return sorted(rows, key=lambda row: row["date"])
    by_date: dict[dt.date, float] = defaultdict(float)
    for trade in trades:
        if trade.get("exit_date"):
            by_date[trade["exit_date"]] += float(trade.get("pnl_amount") or 0.0)
    equity = initial_capital
    rows = []
    for date_value in sorted(by_date):
        equity += by_date[date_value]
        rows.append({"date": date_value, "equity": equity})
    return rows


class Canvas:
    def __init__(self, width: int, height: int, bg=(255, 255, 255)):
        self.width = width
        self.height = height
        self.pixels = bytearray(bg * (width * height))

    def set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self.pixels[idx : idx + 3] = bytes(color)

    def rect(self, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
        x1, x2 = sorted((max(0, x1), min(self.width - 1, x2)))
        y1, y2 = sorted((max(0, y1), min(self.height - 1, y2)))
        for y in range(y1, y2 + 1):
            start = (y * self.width + x1) * 3
            end = (y * self.width + x2 + 1) * 3
            self.pixels[start:end] = bytes(color) * (x2 - x1 + 1)

    def line(self, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], width: int = 1) -> None:
        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx + dy
        x, y = x1, y1
        while True:
            for ox in range(-(width // 2), width // 2 + 1):
                for oy in range(-(width // 2), width // 2 + 1):
                    self.set(x + ox, y + oy, color)
            if x == x2 and y == y2:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def png(self, path: Path) -> None:
        raw = bytearray()
        stride = self.width * 3
        for y in range(self.height):
            raw.append(0)
            raw.extend(self.pixels[y * stride : (y + 1) * stride])
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        data = b"\x89PNG\r\n\x1a\n"
        data += chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0))
        data += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        data += chunk(b"IEND", b"")
        path.write_bytes(data)


def scale(values: list[float], lo_px: int, hi_px: int, pad: float = 0.08):
    lo = min(values + [0.0])
    hi = max(values + [0.0])
    if lo == hi:
        lo -= 1
        hi += 1
    span = hi - lo
    lo -= span * pad
    hi += span * pad
    def f(v: float) -> int:
        return int(hi_px - (v - lo) / (hi - lo) * (hi_px - lo_px))
    return f, lo, hi


def draw_axes(c: Canvas, left: int, top: int, right: int, bottom: int) -> None:
    grey = (203, 213, 225)
    for i in range(6):
        y = top + int((bottom - top) * i / 5)
        c.line(left, y, right, y, (226, 232, 240))
    c.line(left, top, left, bottom, grey, 2)
    c.line(left, bottom, right, bottom, grey, 2)


def line_chart(path: Path, rows: list[dict[str, Any]], value_key: str, color: tuple[int, int, int]) -> None:
    c = Canvas(1200, 640)
    left, top, right, bottom = 80, 50, 1140, 570
    draw_axes(c, left, top, right, bottom)
    if len(rows) > 1:
        values = [float(r[value_key]) for r in rows]
        yscale, _, _ = scale(values, top, bottom)
        n = len(rows) - 1
        pts = [(left + int((right - left) * i / n), yscale(values[i])) for i in range(len(rows))]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            c.line(x1, y1, x2, y2, color, 3)
    c.png(path)


def bar_chart(path: Path, rows: list[dict[str, Any]], value_key: str, limit: int = 30, horizontal: bool = False) -> None:
    c = Canvas(1200, 760)
    left, top, right, bottom = 90, 40, 1120, 700
    draw_axes(c, left, top, right, bottom)
    rows = rows[:limit]
    values = [float(r.get(value_key) or 0.0) for r in rows]
    if not values:
        c.png(path)
        return
    max_abs = max(abs(v) for v in values) or 1
    zero = left + int((right - left) * 0.5) if horizontal else bottom
    if horizontal:
        bar_h = max(4, int((bottom - top) / max(1, len(rows)) * 0.72))
        for i, row in enumerate(rows):
            v = float(row.get(value_key) or 0.0)
            y = top + int((bottom - top) * (i + 0.5) / len(rows))
            x2 = zero + int(v / max_abs * (right - left) * 0.45)
            color = (22, 163, 74) if v >= 0 else (220, 38, 38)
            c.rect(min(zero, x2), y - bar_h // 2, max(zero, x2), y + bar_h // 2, color)
        c.line(zero, top, zero, bottom, (100, 116, 139), 2)
    else:
        bar_w = max(4, int((right - left) / max(1, len(rows)) * 0.72))
        for i, row in enumerate(rows):
            v = float(row.get(value_key) or 0.0)
            x = left + int((right - left) * (i + 0.5) / len(rows))
            y = bottom - int(abs(v) / max_abs * (bottom - top) * 0.90)
            color = (22, 163, 74) if v >= 0 else (220, 38, 38)
            if v >= 0:
                c.rect(x - bar_w // 2, y, x + bar_w // 2, bottom, color)
            else:
                c.rect(x - bar_w // 2, bottom, x + bar_w // 2, y, color)
    c.png(path)


def heatmap(path: Path, monthly_rows: list[dict[str, Any]]) -> None:
    years = sorted({int(row["year"]) for row in monthly_rows})
    lookup = {(int(row["year"]), int(row["month"])): float(row["total_pnl"]) for row in monthly_rows}
    c = Canvas(1200, max(360, 90 + len(years) * 52))
    left, top = 110, 60
    cell_w, cell_h = 78, 42
    vals = [abs(v) for v in lookup.values()]
    max_abs = max(vals) if vals else 1
    for yi, year in enumerate(years):
        y = top + yi * cell_h
        for month in range(1, 13):
            v = lookup.get((year, month), 0.0)
            intensity = min(1.0, abs(v) / max_abs)
            if v >= 0:
                color = (int(235 - 140 * intensity), int(255 - 80 * intensity), int(240 - 150 * intensity))
            else:
                color = (int(255 - 35 * intensity), int(235 - 165 * intensity), int(235 - 165 * intensity))
            x = left + (month - 1) * cell_w
            c.rect(x, y, x + cell_w - 4, y + cell_h - 4, color)
    c.png(path)


def render_charts_with_matplotlib(
    charts: dict[str, Path],
    equity_curve: list[dict[str, Any]],
    dd_rows: list[dict[str, Any]],
    symbol_rows: list[dict[str, Any]],
    yearly_rows: list[dict[str, Any]],
    monthly_rows: list[dict[str, Any]],
    rolling_rows: list[dict[str, Any]],
    holding_rows: list[dict[str, Any]],
    entry_rows: list[dict[str, Any]],
    r_rows: list[dict[str, Any]],
) -> bool:
    """Render labeled charts with matplotlib when it is available.

    The standard-library PNG renderer below is intentionally dependency-free,
    but it cannot draw text labels. This renderer is preferred for readable
    standalone reports and falls back cleanly when matplotlib is missing.
    """

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception:
        return False

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    def finish(fig, ax, path: Path, xlabel: str, ylabel: str) -> None:
        ax.set_xlabel(xlabel, fontsize=10, labelpad=8)
        ax.set_ylabel(ylabel, fontsize=10, labelpad=8)
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)

    def value_color(value: float) -> str:
        return "#16a34a" if value >= 0 else "#dc2626"

    if equity_curve:
        fig, ax = plt.subplots(figsize=(11, 5.2))
        dates = [row["date"] for row in equity_curve]
        values = [float(row["equity"]) for row in equity_curve]
        ax.plot(dates, values, color="#2563eb", linewidth=2.2)
        ax.set_title("Equity Curve", fontsize=14, weight="bold")
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        finish(fig, ax, charts["equity"], "Exit Date", "Account Equity")

    if dd_rows:
        fig, ax = plt.subplots(figsize=(11, 5.2))
        dates = [row["date"] for row in dd_rows]
        values = [float(row["drawdown_pct"]) for row in dd_rows]
        ax.fill_between(dates, values, 0, color="#fecaca", alpha=0.9)
        ax.plot(dates, values, color="#dc2626", linewidth=1.8)
        ax.set_title("Drawdown Curve", fontsize=14, weight="bold")
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        finish(fig, ax, charts["drawdown"], "Exit Date", "Drawdown (%)")

    if symbol_rows:
        rows = symbol_rows[:35]
        labels = [str(row["group"]) for row in rows][::-1]
        values = [float(row["total_pnl"]) for row in rows][::-1]
        fig, ax = plt.subplots(figsize=(11, max(5.5, len(rows) * 0.28)))
        ax.barh(labels, values, color=[value_color(v) for v in values])
        ax.axvline(0, color="#64748b", linewidth=1)
        ax.set_title("Net PnL by Symbol", fontsize=14, weight="bold")
        finish(fig, ax, charts["symbol"], "Net PnL", "Symbol")

    if yearly_rows:
        rows = sorted(yearly_rows, key=lambda row: str(row["group"]))
        labels = [str(row["group"]) for row in rows]
        values = [float(row["total_pnl"]) for row in rows]
        fig, ax = plt.subplots(figsize=(10, 5.2))
        ax.bar(labels, values, color=[value_color(v) for v in values])
        ax.axhline(0, color="#64748b", linewidth=1)
        ax.set_title("Yearly PnL", fontsize=14, weight="bold")
        finish(fig, ax, charts["yearly"], "Year", "Net PnL")

    if monthly_rows:
        years = sorted({int(row["year"]) for row in monthly_rows})
        matrix = [[0.0 for _ in range(12)] for _ in years]
        for row in monthly_rows:
            y_index = years.index(int(row["year"]))
            matrix[y_index][int(row["month"]) - 1] = float(row["total_pnl"])
        max_abs = max([abs(value) for row in matrix for value in row] + [1.0])
        fig, ax = plt.subplots(figsize=(12, max(3.8, len(years) * 0.55)))
        image = ax.imshow(matrix, cmap="RdYlGn", vmin=-max_abs, vmax=max_abs, aspect="auto")
        ax.set_xticks(range(12), MONTH_NAMES, rotation=0)
        ax.set_yticks(range(len(years)), [str(year) for year in years])
        ax.set_title("Monthly PnL Heatmap", fontsize=14, weight="bold")
        ax.set_xlabel("Month", fontsize=10, labelpad=8)
        ax.set_ylabel("Year", fontsize=10, labelpad=8)
        for y, row in enumerate(matrix):
            for x, value in enumerate(row):
                if value:
                    ax.text(x, y, f"{value:,.0f}", ha="center", va="center", fontsize=7, color="#111827")
        fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label="Net PnL")
        fig.tight_layout()
        fig.savefig(charts["monthly"], dpi=160, bbox_inches="tight")
        plt.close(fig)

    if rolling_rows:
        fig, ax = plt.subplots(figsize=(11, 5.2))
        dates = [row["date"] for row in rolling_rows]
        values = [float(row["rolling_pnl"]) for row in rolling_rows]
        ax.plot(dates, values, color="#9333ea", linewidth=2.0)
        ax.axhline(0, color="#64748b", linewidth=1)
        ax.set_title("Rolling 20-Trade PnL", fontsize=14, weight="bold")
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        finish(fig, ax, charts["rolling"], "Exit Date", "Rolling PnL")

    def categorical_bar(path: Path, rows: list[dict[str, Any]], title: str, ylabel: str, value_key: str) -> None:
        if not rows:
            return
        labels = [str(row["group"]) for row in rows]
        values = [float(row.get(value_key) or 0.0) for row in rows]
        fig, ax = plt.subplots(figsize=(10.5, 5.4))
        ax.bar(labels, values, color=[value_color(v) for v in values])
        ax.axhline(0, color="#64748b", linewidth=1)
        ax.set_title(title, fontsize=14, weight="bold")
        ax.tick_params(axis="x", labelrotation=25)
        finish(fig, ax, path, "Category", ylabel)

    categorical_bar(charts["holding"], holding_rows, "PnL by Holding Period", "Net PnL", "total_pnl")
    categorical_bar(charts["entry"], entry_rows, "PnL by Entry Type", "Net PnL", "total_pnl")
    categorical_bar(charts["r"], r_rows, "R-Multiple Distribution", "Trade Count", "trade_count")
    return True


def holding_bucket(days: float | None) -> str:
    if days is None:
        return "unknown"
    if days <= 2:
        return "1-2 days"
    if days <= 5:
        return "3-5 days"
    if days <= 10:
        return "6-10 days"
    if days <= 15:
        return "11-15 days"
    return "15+ days"


def r_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= -1:
        return "<= -1R"
    if value <= 0:
        return "-1R to 0"
    if value <= 1:
        return "0 to 1R"
    if value <= 2:
        return "1R to 2R"
    if value <= 3:
        return "2R to 3R"
    return "> 3R"


def max_consecutive_losses(trades: list[dict[str, Any]]) -> int:
    current = 0
    best = 0
    for trade in sorted(trades, key=lambda t: t.get("exit_date") or dt.date.min):
        if float(trade.get("pnl_amount") or 0.0) < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def html_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 50) -> str:
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body = []
    for row in rows[:limit]:
        cells = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, float):
                value = money(value) if "pnl" in col or "equity" in col else f"{value:.2f}"
            elif isinstance(value, dt.date):
                value = value.isoformat()
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def img_tag(path: Path, title: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"<figure><h3>{html.escape(title)}</h3><img src=\"data:image/png;base64,{data}\" alt=\"{html.escape(title)}\"></figure>"


def generate(input_path: Path, initial_capital: float, output_path: Path) -> None:
    trades, raw_equity_curve, warnings = read_input(input_path)
    if not trades:
        print("无法生成报告：未找到有效交易明细。")
        print("最低要求字段：symbol, exit_date, pnl_amount")
        if warnings:
            print("\n".join(warnings))
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    chart_dir = output_path.parent / "backtest_charts"
    summary_dir = output_path.parent / "backtest_summary"
    chart_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    equity_curve = equity_from_trades(trades, initial_capital, raw_equity_curve)
    if not equity_curve:
        equity_curve = [{"date": t["exit_date"], "equity": initial_capital + sum(float(x.get("pnl_amount") or 0) for x in trades[: i + 1])} for i, t in enumerate(sorted(trades, key=lambda t: t["exit_date"]))]
    rolling_max = None
    dd_rows = []
    for row in equity_curve:
        equity = float(row["equity"])
        rolling_max = equity if rolling_max is None else max(rolling_max, equity)
        dd_rows.append({"date": row["date"], "drawdown_pct": (equity / rolling_max - 1) * 100 if rolling_max else 0.0})

    total_pnl = sum(float(t.get("pnl_amount") or 0.0) for t in trades)
    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital + total_pnl
    wins = [t for t in trades if float(t.get("pnl_amount") or 0.0) > 0]
    losses = [t for t in trades if float(t.get("pnl_amount") or 0.0) < 0]
    gross_profit = sum(float(t["pnl_amount"]) for t in wins)
    gross_loss = sum(float(t["pnl_amount"]) for t in losses)
    r_values = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    metrics = {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "total_return_pct": (final_equity / initial_capital - 1) * 100 if initial_capital else None,
        "max_drawdown_pct": min((row["drawdown_pct"] for row in dd_rows), default=0.0),
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": None if gross_loss == 0 else gross_profit / abs(gross_loss),
        "avg_r": sum(r_values) / len(r_values) if r_values else None,
        "max_consecutive_losses": max_consecutive_losses(trades),
    }

    symbol_rows = group_summary(trades, lambda t: t["symbol"])
    symbol_rows.sort(key=lambda row: row["total_pnl"], reverse=True)
    yearly_rows = group_summary(trades, lambda t: t["exit_date"].year if t.get("exit_date") else "unknown")
    monthly_rows = []
    monthly_groups = defaultdict(list)
    for trade in trades:
        date_value = trade.get("exit_date")
        if date_value:
            monthly_groups[(date_value.year, date_value.month)].append(trade)
    for (year, month), items in sorted(monthly_groups.items()):
        pnl = sum(float(t.get("pnl_amount") or 0.0) for t in items)
        wins_m = sum(1 for t in items if float(t.get("pnl_amount") or 0.0) > 0)
        monthly_rows.append({"year": year, "month": month, "total_pnl": pnl, "trade_count": len(items), "win_rate": wins_m / len(items) * 100 if items else 0})
    holding_rows = group_summary(trades, lambda t: holding_bucket(t.get("holding_days")))
    entry_rows = group_summary(trades, lambda t: t.get("entry_type") or "unknown")
    r_rows = group_summary(trades, lambda t: r_bucket(t.get("r_multiple")))
    holding_order = {"1-2 days": 1, "3-5 days": 2, "6-10 days": 3, "11-15 days": 4, "15+ days": 5, "unknown": 99}
    r_order = {"<= -1R": 1, "-1R to 0": 2, "0 to 1R": 3, "1R to 2R": 4, "2R to 3R": 5, "> 3R": 6, "unknown": 99}
    holding_rows.sort(key=lambda row: holding_order.get(str(row["group"]), 99))
    r_rows.sort(key=lambda row: r_order.get(str(row["group"]), 99))
    top_winners = sorted(trades, key=lambda t: float(t.get("pnl_amount") or 0), reverse=True)[:20]
    top_losers = sorted(trades, key=lambda t: float(t.get("pnl_amount") or 0))[:20]
    rolling_rows = []
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date") or dt.date.min)
    for i in range(len(sorted_trades)):
        window = sorted_trades[max(0, i - 19) : i + 1]
        rolling_rows.append({"date": sorted_trades[i].get("exit_date"), "rolling_pnl": sum(float(t.get("pnl_amount") or 0) for t in window)})

    write_csv(summary_dir / "symbol_summary.csv", symbol_rows, ["group", "trade_count", "total_pnl", "win_rate", "avg_pnl", "avg_r"])
    write_csv(summary_dir / "yearly_summary.csv", yearly_rows, ["group", "trade_count", "total_pnl", "win_rate", "avg_pnl", "avg_r"])
    write_csv(summary_dir / "monthly_summary.csv", monthly_rows, ["year", "month", "total_pnl", "trade_count", "win_rate"])
    write_csv(summary_dir / "holding_period_summary.csv", holding_rows, ["group", "trade_count", "total_pnl", "win_rate", "avg_pnl", "avg_r"])
    write_csv(summary_dir / "entry_type_summary.csv", entry_rows, ["group", "trade_count", "total_pnl", "win_rate", "avg_pnl", "avg_r"])
    write_csv(summary_dir / "r_multiple_summary.csv", r_rows, ["group", "trade_count", "total_pnl", "win_rate", "avg_pnl", "avg_r"])
    trade_cols = ["symbol", "entry_date", "exit_date", "holding_days", "entry_type", "exit_reason", "pnl_amount", "pnl_pct", "r_multiple"]
    write_csv(summary_dir / "holding_segments.csv", sorted(trades, key=lambda t: (t.get("symbol") or "", t.get("entry_date") or dt.date.min, t.get("exit_date") or dt.date.min)), trade_cols)
    write_csv(summary_dir / "top_winners.csv", top_winners, trade_cols)
    write_csv(summary_dir / "top_losers.csv", top_losers, trade_cols)

    charts = {
        "equity": chart_dir / "equity_curve.png",
        "drawdown": chart_dir / "drawdown_curve.png",
        "symbol": chart_dir / "symbol_net_profit.png",
        "yearly": chart_dir / "yearly_pnl.png",
        "monthly": chart_dir / "monthly_heatmap.png",
        "rolling": chart_dir / "rolling_20_trade_pnl.png",
        "holding": chart_dir / "holding_period_pnl.png",
        "entry": chart_dir / "entry_type_pnl.png",
        "r": chart_dir / "r_multiple_distribution.png",
    }
    rendered = render_charts_with_matplotlib(
        charts,
        equity_curve,
        dd_rows,
        symbol_rows,
        yearly_rows,
        monthly_rows,
        rolling_rows,
        holding_rows,
        entry_rows,
        r_rows,
    )
    if not rendered:
        line_chart(charts["equity"], equity_curve, "equity", (37, 99, 235))
        line_chart(charts["drawdown"], dd_rows, "drawdown_pct", (220, 38, 38))
        bar_chart(charts["symbol"], symbol_rows, "total_pnl", 35, horizontal=True)
        bar_chart(charts["yearly"], yearly_rows, "total_pnl", 20, horizontal=False)
        heatmap(charts["monthly"], monthly_rows)
        line_chart(charts["rolling"], rolling_rows, "rolling_pnl", (147, 51, 234))
        bar_chart(charts["holding"], holding_rows, "total_pnl", 20, horizontal=False)
        bar_chart(charts["entry"], entry_rows, "total_pnl", 20, horizontal=False)
        bar_chart(charts["r"], r_rows, "trade_count", 20, horizontal=False)

    note_r = "" if r_values else "<p class=\"warn\">缺少初始风险数据，无法生成 R 倍数分布。</p>"
    profit_factor_text = "N/A" if metrics["profit_factor"] is None else f"{metrics['profit_factor']:.2f}"
    metric_cards = "".join(
        [
            f"<div><b>initial_capital</b><span>{money(metrics['initial_capital'])}</span></div>",
            f"<div><b>final_equity</b><span>{money(metrics['final_equity'])}</span></div>",
            f"<div><b>total_pnl</b><span>{money(metrics['total_pnl'])}</span></div>",
            f"<div><b>total_return_pct</b><span>{pct(metrics['total_return_pct'])}</span></div>",
            f"<div><b>max_drawdown_pct</b><span>{pct(metrics['max_drawdown_pct'])}</span></div>",
            f"<div><b>trade_count</b><span>{metrics['trade_count']}</span></div>",
            f"<div><b>win_rate</b><span>{pct(metrics['win_rate'])}</span></div>",
            f"<div><b>profit_factor</b><span>{profit_factor_text}</span></div>",
            f"<div><b>avg_r</b><span>{rfmt(metrics['avg_r'])}</span></div>",
            f"<div><b>max_consecutive_losses</b><span>{metrics['max_consecutive_losses']}</span></div>",
        ]
    )
    warnings_html = "".join(f"<p class=\"warn\">{html.escape(w)}</p>" for w in warnings)
    report = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Backtest Analysis Report</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f6f8fb;color:#172033}}
header{{padding:28px 36px;background:#0f172a;color:white}}
main{{max-width:1280px;margin:0 auto;padding:28px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:20px 0}}
.cards div{{background:white;border:1px solid #e2e8f0;border-radius:8px;padding:14px;box-shadow:0 1px 2px rgba(15,23,42,.06)}}
.cards b{{display:block;color:#64748b;font-size:12px;margin-bottom:8px}}.cards span{{font-size:22px;font-weight:700}}
figure{{background:white;border:1px solid #e2e8f0;border-radius:8px;padding:18px;margin:18px 0;box-shadow:0 1px 2px rgba(15,23,42,.05)}}
figure img{{width:100%;height:auto;display:block}}h2{{margin-top:34px}}h3{{margin-top:0}}
table{{width:100%;border-collapse:collapse;background:white;margin:16px 0;border:1px solid #e2e8f0}}
th,td{{border-bottom:1px solid #e2e8f0;padding:8px 10px;text-align:right;font-size:13px}}th:first-child,td:first-child{{text-align:left}}th{{background:#f1f5f9;color:#334155}}
.warn{{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;padding:10px 12px;border-radius:8px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><h1>五年回测分析报告</h1><p>Input: {html.escape(str(input_path))}</p></header>
<main>
{warnings_html}
<section class="cards">{metric_cards}</section>
<section>{img_tag(charts['equity'], '资金曲线图')}{img_tag(charts['drawdown'], '回撤曲线图')}</section>
<section>{img_tag(charts['symbol'], '品种净利润排行图')}{img_tag(charts['yearly'], '年度收益柱状图')}{img_tag(charts['monthly'], '月度收益热力图')}</section>
<section>{img_tag(charts['rolling'], '最近20笔滚动盈亏图')}{img_tag(charts['holding'], '持仓天数盈亏图')}{img_tag(charts['entry'], '买入类型盈亏图')}{note_r}{img_tag(charts['r'], 'R倍数分布图')}</section>
<h2>最大盈利交易 Top 20</h2>{html_table(top_winners, trade_cols, 20)}
<h2>最大亏损交易 Top 20</h2>{html_table(top_losers, trade_cols, 20)}
<h2>持仓分段明细（前 200 行，完整 CSV 已保存）</h2>{html_table(sorted(trades, key=lambda t: (t.get('symbol') or '', t.get('entry_date') or dt.date.min, t.get('exit_date') or dt.date.min)), trade_cols, 200)}
<div class="grid"><section><h2>品种汇总</h2>{html_table(symbol_rows, ['group','trade_count','total_pnl','win_rate','avg_pnl','avg_r'], 80)}</section><section><h2>月份汇总</h2>{html_table(monthly_rows, ['year','month','total_pnl','trade_count','win_rate'], 80)}</section></div>
</main></body></html>"""
    output_path.write_text(report, encoding="utf-8")
    print(f"HTML report: {output_path.resolve()}")
    print(f"PNG chart directory: {chart_dir.resolve()}")
    print(f"CSV summary directory: {summary_dir.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a standalone backtest HTML analysis report.")
    parser.add_argument("--input", required=True, help="Path to a CSV or JSON backtest trade-detail file.")
    parser.add_argument("--initial-capital", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        generate(Path(args.input), args.initial_capital, Path(args.output))
    except Exception as exc:
        print(f"生成报告失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
