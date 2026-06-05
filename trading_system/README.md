# 美股 ETF 趋势 + 价格行为交易系统 V1.1

这是一个低盯盘、半自动的 ETF 信号工具。它只看日线收盘后的数据，不做盘中追单，默认适合每天花 10 分钟检查一次。

> 说明：这是一套规则化交易工具，不是个性化投资建议。请先纸面运行和小资金验证。

## ETF 池

- `SPY`：标普 500，大盘核心。
- `QQQ`：纳斯达克 100，科技成长权重更高。
- `IWM`：罗素 2000，小盘股，波动更大。
- `TLT`：20 年以上美国国债 ETF，防守/分散。
- `GLD`：黄金 ETF，防守/避险。
- `SGOV`：0-3 个月短债 ETF，默认现金停车位。

## 网页面板怎么用

在 `E:\CODEX` 打开 PowerShell：

```powershell
python .\trading_system\server.py
```

电脑浏览器会打开：

```text
http://127.0.0.1:8765
```

如果要让手机通过 Tailscale 访问，请看 `trading_system\setup_tailscale.md`。

## 每天命令行怎么用

在 `E:\CODEX` 打开 PowerShell：

```powershell
python .\trading_system\etf_signal.py
```

脚本会生成：

- `trading_system\reports\latest_signals.csv`
- `trading_system\reports\latest_report.md`

先看 `latest_report.md`，再按信号去券商挂普通交易时段限价单。

## 打包成 EXE

在 `E:\CODEX` 打开 PowerShell：

```powershell
.\trading_system\build_exe.ps1
```

完成后运行：

```text
trading_system\dist\ETF-Trading-System.exe
```

exe 会启动本地网页面板。若已配置 Tailscale Serve，手机可通过 `https://...ts.net` 地址访问。

## 规则摘要

- 大方向：`SPY` 和 `QQQ` 是市场过滤器；风险资产必须在 200 日均线上方才允许买。
- 价格行为：优先选择突破站稳、回踩后重新收强、结构高低点抬高的 ETF。
- 风险信号：跌破 200 日均线、跌破波段低点、突破失败、放量长阴线。
- 风控：账户回撤到 `8%`，风险资产仓位减半；回撤到 `12%`，转入 `SGOV/现金`。
- 执行：只用限价单，不用市价单，不追盘前盘后。

## 配置账户

编辑 `trading_system\config.json`：

```json
"account": {
  "equity": 10000,
  "high_watermark": 11000,
  "cash_symbol": "SGOV",
  "holdings_pct": {
    "SPY": 30,
    "QQQ": 30,
    "IWM": 0,
    "TLT": 0,
    "GLD": 20,
    "SGOV": 20
  }
}
```

- `equity`：当前账户总权益。
- `high_watermark`：历史最高账户权益。
- `holdings_pct`：当前各 ETF 仓位百分比。

如果暂时不填账户权益，脚本仍会给目标仓位和信号，但不会触发 8%/12% 的账户回撤风控。

## 本地 CSV 备用数据

如果网络数据源临时不可用，可以准备本地 CSV：

```text
Date,Open,High,Low,Close,Volume
2026-01-02,100,102,99,101,123456
```

放在一个文件夹里，文件名用 `SPY.csv`、`QQQ.csv` 这种格式，然后运行：

```powershell
python .\trading_system\etf_signal.py --data-dir .\my_price_data
```

## 每笔交易复盘

每次下单后，只记录三件事：

- 趋势是否允许？
- 价格位置是否合理？
- 退出是否按规则？

如果答案说不清楚，这笔交易就不该做。
