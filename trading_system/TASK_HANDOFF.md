# TASK_HANDOFF.md

## Current Task Goal

Prepare this ETF / multi-asset trading dashboard project for continuation in a new Codex thread. Feature expansion is paused. This file records current local state, recent work, remaining issues, verification results, and Git/worktree status.

## Current Project Root

- Continue from: `E:\CODEX\trading_system`
- Parent Git repository: `E:\CODEX`
- Current branch reported by Git: `main...origin/main`
- Important: `trading_system/` is currently an untracked directory in the parent repository. A new local thread in the same workspace can see these files. A remote/cloud task or another machine will not see them unless the directory is added, committed, pushed, or copied.

## Completed Work In Current Thread

- Built a local ETF / stock dashboard served by `server.py` at `http://127.0.0.1:8765`.
- Added/iterated main dashboard routes:
  - overview / asset pool
  - signals
  - portfolio
  - monitor
  - backtest
  - settings
- Added a mobile/private-access approach using local service plus Tailscale documentation; latest verification focused on local desktop.
- Added Binance Spot read-only integration:
  - server-side env loading from `.env.local`;
  - status/test/read endpoints;
  - actual-account view in the portfolio page;
  - no trading endpoints implemented.
- Added asset-pool persistence and UI:
  - local `asset_pool.json`;
  - configurable groups;
  - max 10 groups;
  - max 30 symbols per group;
  - same symbol may appear in multiple groups;
  - default core strategy and stock watchlist groups.
- Added row "more" menu interactions and right rail modes:
  - `detail`;
  - `add`;
  - `edit`.
- Changed add-instrument search behavior:
  - typing no longer triggers immediate search;
  - press Enter or click Search to request results.
- Added Yahoo symbol search fallback behavior for ticker-like input when Yahoo search fails.
- Rebuilt and restarted the packaged exe after stopping stale services.

## Modified Files And Purposes

- `dashboard/app.js`
  - Main frontend state/rendering.
  - Asset-pool groups, usage badges, row menus, add/edit/detail right rail, manual search trigger, group create/delete, and per-group remove behavior.
  - Binance settings/portfolio UI and other dashboard pages are also implemented here.
- `dashboard/styles.css`
  - Dashboard styling, asset-pool layout, row menus, right rail contextual header, add/search UI, settings/portfolio/monitor/backtest styles.
- `server.py`
  - Local API server.
  - Asset-pool sanitization/persistence, group limits, symbol search, Yahoo fallback, snapshot merge with asset-pool config, Binance route wiring.
- `etf_signal.py`
  - Signal/snapshot engine and Yahoo fetch retry behavior.
  - Core trading logic is high risk and should not be changed casually.
- `binance_service.py`
  - Binance Spot read-only account connection, masked status, signed account requests, public USDT valuation, friendly errors.
- `build_exe.ps1`
  - PyInstaller build.
  - Preserves `.env.local`, `binance api.txt`, and existing `dist/asset_pool.json` instead of overwriting runtime asset-pool changes.
- `asset_pool.json`
  - Local runtime asset-pool configuration.
- `config.json`
  - Trading system universe/config; current state includes ETF and stock universe used by snapshot generation.
- `dist/`
  - Packaged exe and runtime files. Generated/local; do not assume committed.

## Current Unfinished Items

- Real account PnL/profit is not implemented.
  - Binance API currently reads current Spot balances and valuations only.
  - It does not calculate cost basis, realized PnL, unrealized PnL, deposits/withdrawals, or equity curve.
  - To show real profit, future work needs trade history, account snapshots, and cost-basis logic.
- Backtest page is mostly UI/empty state.
  - No verified real backtest result series, trade logs, annual returns, signal statistics, or parameter robustness results are currently connected.
- Asset-pool persistence is local JSON only.
  - No database, auth, cloud sync, or multi-user backend.
- Strategy promotion/publish workflow is not implemented.
  - Adding arbitrary symbols as `strategy` is intentionally guarded/disabled unless baseline strategy symbol rules allow it.
- Some source files and old README text contain mojibake from prior encoding issues.
  - Browser-rendered core UI paths were verified for latest asset-pool interactions, but source readability is imperfect.
- Tailscale status currently reports not installed in the API status on this machine.

## Known Issues / Failed Attempts / Do Not Repeat

- Port `8765` was once served by a stale Python process from around 16:xx, not the newly built exe. It caused old behavior such as missing asset-pool `groups`.
  - Always check the owning process for port `8765` before assuming changes are live:
    ```powershell
    Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
    Get-Process -Id <OwningProcess> | Select-Object Id,ProcessName,Path,StartTime
    ```
- `build_exe.ps1` initially failed because `dist/ETF-Trading-System.exe` was still running and locked. Stop running exe processes before rebuilding.
- `/api/refresh` does not exist. Use `/api/snapshot` for snapshot read/refresh behavior.
- Browser automation once timed out when using a Chinese placeholder locator. CSS selectors such as `#addInstrumentSearch` and `[data-asset-action="add"]` were more reliable.
- Do not ask the user to paste Binance keys into chat or frontend fields. Use `.env.local` / server-side environment variables only.

## Key Technical Decisions

- Keep the app as Python local server + static frontend; do not introduce a frontend framework unless explicitly requested.
- Keep asset-pool customization in a UI adapter/local JSON layer; do not mutate strategy logic when a user adds ordinary watchlist symbols.
- Non-strategy symbols display `WATCH` or `-` instead of BUY/HOLD/SELL to avoid implying formal trade advice.
- Binance connection is read-only and isolated from model strategy pages.
- Same ticker in multiple groups is represented through group membership lists, not duplicated core quote records.
- Removing a row removes the symbol from the current group first; it is marked removed only when no group contains it.

## Verification Already Run

From `E:\CODEX\trading_system`:

```powershell
node --check dashboard\app.js
```

Result: passed.

```powershell
python -m py_compile server.py etf_signal.py binance_service.py
```

Result: passed.

```powershell
$null = [scriptblock]::Create((Get-Content -Raw build_exe.ps1)); 'build_exe.ps1 syntax ok'
```

Result: passed.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Result: passed after stopping old exe processes.

API checks after restarting packaged exe:

- `/api/asset-pool`: returned `groups` and instruments.
- `/api/instrument-search?q=CAT`: returned `CAT / Caterpillar Inc.` and marked `activeGroupIds: ["stock_watchlist"]`.
- `/api/snapshot`: returned 14 symbols, including `SGOV` and `CAT`; daily errors were empty.
- Browser check: typing `CAT` did not search immediately; pressing Enter returned CAT/RCAT/CPRX.
- Browser console errors: none reported in the final check.

Current running service observed:

- Process: `ETF-Trading-System.exe`
- Path: `E:\CODEX\trading_system\dist\ETF-Trading-System.exe`
- URL: `http://127.0.0.1:8765/?v=20260604-assets#overview`

## Verification Still Recommended For New Thread

Run again before further development:

```powershell
node --check .\dashboard\app.js
python -m py_compile .\server.py .\etf_signal.py .\binance_service.py
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/status' -UseBasicParsing
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/asset-pool' -UseBasicParsing
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/snapshot' -UseBasicParsing
```

If modifying packaged behavior, rebuild and restart exe:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

## Next Thread Recommended Order

1. Start in `E:\CODEX\trading_system`.
2. Read `AGENTS.md` and this `TASK_HANDOFF.md`.
3. Run `git status --short --branch` from both `E:\CODEX` and `E:\CODEX\trading_system`.
4. Confirm whether the user wants to commit/add the currently untracked `trading_system/` directory before more work.
5. Check which process owns port `8765`; restart the source server or packaged exe if needed.
6. Re-run the verification commands listed above.
7. If continuing feature work, prioritize one of:
   - real account PnL/cost-basis module;
   - robust backtest engine/results;
   - cleanup of mojibake source strings;
   - asset-pool UX polish and persistence edge cases.

## Current Git Status

As of handoff:

- `E:\CODEX` is on `main...origin/main`.
- `trading_system/` is untracked in the parent Git repository.
- There are also unrelated untracked files/directories in `E:\CODEX`.
- No commit was made in this handoff.
- A new local Codex thread using the same workspace should see the untracked files; a remote/cloud task will not unless the user commits/pushes or otherwise transfers them.

## Suggested First Prompt For New Thread

```text
Continue this project in E:\CODEX\trading_system. First read AGENTS.md and TASK_HANDOFF.md, confirm Git status and the process serving port 8765, then rerun the handoff verification commands for the asset pool, Binance read-only connection, and current dashboard state. Do not develop new features until verification is complete; after verification, tell me which next area is safest to tackle.
```
