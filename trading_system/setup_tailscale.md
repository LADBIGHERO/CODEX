# Tailscale 手机访问配置

本系统默认只在电脑本机运行。要让手机打开页面，需要电脑和手机都登录同一个 Tailscale tailnet。

## 1. 安装并登录

1. 电脑安装 Tailscale for Windows：<https://tailscale.com/download/windows>
2. 手机安装 Tailscale App。
3. 两边登录同一个账号。
4. 确认电脑和手机都在线。

当前环境没有检测到 `tailscale` 命令；安装后重新打开 PowerShell 再检查：

```powershell
tailscale status
```

## 2. 启动交易系统

在 `E:\CODEX` 运行：

```powershell
python .\trading_system\server.py
```

电脑浏览器会打开：

```text
http://127.0.0.1:8765
```

## 3. 开启私有 Tailscale Serve

保持交易系统运行，再打开一个 PowerShell：

```powershell
tailscale serve --bg 127.0.0.1:8765
tailscale serve status
```

Tailscale Serve 会给出一个 `https://...ts.net` 地址。手机打开 Tailscale App 后，在手机浏览器访问这个地址即可。

## 4. 重要边界

- 使用 `tailscale serve`，只给同一个 tailnet 内的设备访问。
- 不使用 `tailscale funnel`，避免暴露到公网。
- 页面只用于查看指标和刷新数据，不自动下单。
