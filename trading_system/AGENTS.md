# AGENTS.md

## Project Facts

- Project root: `E:\CODEX\trading_system`.
- Runtime: Python 3.11 local HTTP service plus static frontend.
- Frontend: plain HTML/CSS/JavaScript in `dashboard/`; no React, Next.js, Vue, Tailwind, npm, or TypeScript build pipeline is present.
- Backend/service: `server.py` serves static files and JSON API endpoints on `127.0.0.1:8765`.
- Signal engine: `etf_signal.py` fetches/loads market data, calculates indicators/signals, writes reports, and returns snapshot data.
- Binance read-only integration: `binance_service.py`; secrets come only from server-side environment variables or `.env.local`.
- Persistent local asset-pool config: `asset_pool.json`.
- Main config: `config.json`.
- Build script: `build_exe.ps1` creates `dist/ETF-Trading-System.exe`.

## Directory Responsibilities

- `dashboard/index.html`: static page shell.
- `dashboard/app.js`: frontend state, routing, rendering, asset-pool UI, settings, portfolio, monitor, signal, and backtest display logic.
- `dashboard/styles.css`: visual design and responsive styles.
- `server.py`: local web server, API routes, asset-pool persistence, Yahoo symbol search, Tailscale status.
- `etf_signal.py`: trading-system calculations and snapshot/report generation.
- `binance_service.py`: Binance Spot read-only account access and valuation helpers.
- `reports/`: generated CSV/Markdown reports.
- `outputs/`: generated output artifacts.
- `dist/`: packaged exe and runtime-side config/assets.
- `.env.local`: local secrets; do not print, commit, or expose.

## Commands

Run from `E:\CODEX\trading_system` unless noted.

- Start local dashboard from source:
  ```powershell
  python .\server.py
  ```
- Start without opening browser:
  ```powershell
  python .\server.py --no-open
  ```
- Generate signal report:
  ```powershell
  python .\etf_signal.py
  ```
- Check frontend syntax:
  ```powershell
  node --check .\dashboard\app.js
  ```
- Check Python syntax/import compilation:
  ```powershell
  python -m py_compile .\server.py .\etf_signal.py .\binance_service.py
  ```
- Build exe:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
  ```
- Run packaged app:
  ```powershell
  .\dist\ETF-Trading-System.exe
  ```

There is currently no repository-provided npm lint/test/build command.

## Code Style And Reuse

- Keep the app dependency-light. Prefer existing plain JS/CSS patterns over introducing frameworks or heavy libraries.
- Reuse existing helpers in `dashboard/app.js` such as badges, summary cards, momentum bars, filters, tables, right-rail panels, and status derivation.
- Keep UI labels primarily Chinese and avoid duplicate Chinese/English labels unless needed for ticker/action names.
- Keep CSS consistent with the existing light dashboard style: white cards, subtle borders/shadows, green/amber/red/blue-gray status semantics.
- For durable file edits, use focused changes; avoid broad rewrites of `dashboard/app.js` unless necessary.
- Keep asset-pool display adapters separate from core trading calculations.
- Preserve `.env.local`, API keys, and secrets; never write them into frontend code, logs, commits, or final replies.

## High-Risk Areas

- Do not modify trading rules, trend filters, momentum calculation, price-structure logic, risk rules, or BUY/HOLD/SELL semantics unless explicitly requested.
- Do not add trading, withdrawal, transfer, margin, futures, or order-placement Binance API calls.
- Do not expose Binance Secret/API Key to the browser. `NEXT_PUBLIC_`, `VITE_`, localStorage, sessionStorage, and frontend constants are not allowed for secrets.
- Do not treat Binance actual account balances as strategy/backtest performance.
- Do not delete or overwrite user-created local config files such as `asset_pool.json`, `.env.local`, or reports without explicit approval.
- Do not assume changes in `dist/` or local untracked files are committed or available to a new remote/cloud task.

## Required Verification Before Handoff

For code changes, run at minimum:

```powershell
node --check .\dashboard\app.js
python -m py_compile .\server.py .\etf_signal.py .\binance_service.py
```

When server behavior changes, also verify relevant API endpoints, for example:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/status' -UseBasicParsing
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/asset-pool' -UseBasicParsing
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/snapshot' -UseBasicParsing
```

When packaged behavior matters, rebuild with `build_exe.ps1`, restart the running exe, and confirm the process serving port `8765` is the expected executable.

## Final Reply Checklist

Report:

- files changed;
- commands run and results;
- whether source app, packaged exe, or both were updated;
- any running service URL/process information relevant to the user;
- remaining limitations or data that is not yet truly implemented;
- whether changes are committed/tracked or only local.
