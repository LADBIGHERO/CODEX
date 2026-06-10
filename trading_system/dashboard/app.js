const fmt = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

const groupOrder = [
  { key: "etf", title: "ETF", symbols: ["SPY", "QQQ", "SGOV", "GLD"] },
  { key: "stock", title: "股票", symbols: ["NVDA", "MSFT", "META", "JPM", "XOM", "LLY", "CAT", "GE", "WMT", "V"] },
];

const MAX_ASSET_POOL_GROUPS = 10;
const MAX_ASSET_POOL_GROUP_SYMBOLS = 30;
let assetPoolGroups = [
  { id: "core_strategy", name: "核心策略资产", symbols: ["QQQ", "SPY", "GLD", "SGOV"] },
  { id: "stock_watchlist", name: "股票观察池", symbols: ["NVDA", "MSFT", "META", "JPM", "XOM", "LLY", "CAT", "GE", "WMT", "V"] },
];

const defaultAssetPoolGroups = assetPoolGroups.map((group) => ({ ...group, symbols: [...group.symbols] }));

const instrumentUsageLabels = {
  watch_only: "观察",
  signal_monitoring: "监控",
  strategy: "策略",
};

const addInstrumentPreviewResults = [
  { symbol: "AAPL", name: "Apple Inc.", type: "股票" },
  { symbol: "TLT", name: "iShares 20+ Year Treasury Bond ETF", type: "ETF" },
  { symbol: "GLD", name: "SPDR Gold Shares ETF", type: "ETF" },
];

const instrumentRoleOptions = [
  ["core_equity", "核心权益"],
  ["growth_driver", "成长驱动"],
  ["risk_breadth", "风险扩散"],
  ["defensive_hedge", "防御对冲"],
  ["duration_defense", "久期防御"],
  ["cash_parking", "现金停泊"],
  ["single_stock_watch", "单股观察"],
  ["custom", "自定义"],
];

let assetPoolCapabilities = {
  persistConfig: false,
  removeInstrument: false,
};

const DASHBOARD_CACHE_KEY = "etfTradingDashboard.lastView.v1";
const AUTO_REFRESH_INTERVAL_KEY = "etfTradingDashboard.autoRefreshIntervalMinutes.v1";
const AUTO_REFRESH_INTERVAL_OPTIONS = [0, 5, 15, 30, 60];
const DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES = 15;
const DASHBOARD_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
let dashboardCacheSaveTimer = null;
let autoRefreshTimer = null;
let autoRefreshIntervalMinutes = loadAutoRefreshIntervalSetting();
let refreshInFlight = false;

const etfDescriptions = {
  QQQ: "纳斯达克 100 指数 ETF",
  SPY: "标普 500 指数 ETF",
  GLD: "黄金 ETF",
  SGOV: "0-3 个月短期美债 ETF",
  NVDA: "英伟达",
  MSFT: "微软",
  META: "Meta Platforms",
  JPM: "摩根大通",
  XOM: "埃克森美孚",
  LLY: "礼来",
  CAT: "卡特彼勒",
  GE: "通用电气",
  WMT: "沃尔玛",
  V: "Visa",
};

const roleLabels = {
  risk: "风险",
  defensive: "防御",
  cash: "现金",
  stock: "股票",
};

const portfolioRoles = {
  QQQ: { label: "成长驱动", key: "growth_driver" },
  SPY: { label: "核心权益", key: "core_equity" },
  GLD: { label: "防御对冲", key: "defensive_hedge" },
  SGOV: { label: "现金停泊", key: "cash_parking" },
  NVDA: { label: "AI 芯片", key: "stock_ai_chip" },
  MSFT: { label: "软件云服务", key: "stock_cloud" },
  META: { label: "互联网平台", key: "stock_platform" },
  JPM: { label: "金融核心", key: "stock_financial" },
  XOM: { label: "能源暴露", key: "stock_energy" },
  LLY: { label: "医药成长", key: "stock_healthcare" },
  CAT: { label: "工业周期", key: "stock_industrial" },
  GE: { label: "工业制造", key: "stock_industrial" },
  WMT: { label: "消费防御", key: "stock_consumer" },
  V: { label: "支付网络", key: "stock_payment" },
};

const riskLabels = {
  close_below_sma200: "跌破 SMA200",
  close_below_swing_low: "跌破波段低点",
  failed_breakout: "突破失败",
  long_bearish_volume: "放量长阴线",
};

const noteLabels = {
  cash_parking: "现金停泊",
  trend_ok: "趋势通过",
  higher_high_higher_low: "高低点抬高",
  near_support: "接近支撑",
  near_resistance: "接近阻力",
  breakout_hold: "突破确认",
  pullback_stand: "回踩站稳",
};

const signalTypeLabels = {
  trend: "趋势",
  breakout: "突破",
  support: "支撑",
  resistance: "阻力",
  momentum: "动量",
  risk: "风险",
  short_buy: "建议买入",
  short_sell: "建议卖出",
};

const signalStatusLabels = {
  new: "新触发",
  pending: "待确认",
  confirmed: "已确认",
  warning: "风险中",
  invalidated: "已失效",
  resolved: "已解除",
};

const signalImportanceLabels = {
  high: "高",
  medium: "中",
  low: "低",
};

const monitorCategoryLabels = {
  trend_risk: "趋势风险",
  resistance_watch: "阻力监控",
  support_watch: "支撑监控",
  breakout_hold: "突破保持",
  momentum_change: "动量变化",
  volatility_alert: "波动异常",
  data_issue: "数据异常",
};

const monitorStatusLabels = {
  triggered: "已触发",
  approaching: "接近",
  normal: "正常",
  pending: "待确认",
  resolved: "已解除",
  data_error: "数据异常",
};

const alertSeverityLabels = {
  high: "高",
  medium: "中",
  low: "低",
};

const settingsCategories = [
  { key: "strategy", label: "策略参数", icon: "☷" },
  { key: "assets", label: "资产池与角色", icon: "♙" },
  { key: "data", label: "数据与计算", icon: "▣" },
  { key: "connections", label: "账户连接", icon: "🔗" },
  { key: "alerts", label: "告警与通知", icon: "♧" },
  { key: "appearance", label: "展示与偏好", icon: "▤" },
  { key: "version_security", label: "版本与安全", icon: "◇" },
];

const settingsFieldLabels = {
  "rules.trend_sma_days": "长期趋势均线",
  "rules.momentum_days": "主要动量周期",
  "rules.short_momentum_days": "辅助动量周期",
  "rules.drawdown_reduce_pct": "减仓回撤阈值",
  "rules.drawdown_cash_pct": "现金防守阈值",
  "price_behavior.breakout_hold_days": "突破站稳确认",
  "price_behavior.near_support_pct": "接近支撑阈值",
  "price_behavior.near_resistance_pct": "接近阻力阈值",
  "price_behavior.breakout_window_days": "突破/失败监测窗口",
  "price_behavior.failed_breakout_pct": "假突破回落阈值",
  "price_behavior.bearish_volume_multiplier": "放量风险倍数",
  "execution.buy_limit_buffer_pct": "买入限价缓冲",
  "execution.sell_limit_buffer_pct": "卖出限价缓冲",
};

const routeTitles = {
  overview: "今日信号总览",
  signals: "信号中心",
  portfolio: "组合分析",
  monitor: "监控中心",
  backtest: "回测分析",
  paper: "模拟账户",
  settings: "系统设置",
};

let selectedSymbol = "QQQ";
let selectedGroupId = "core_strategy";
let selectedSignalId = null;
let selectedMonitorId = null;
let selectedSettingsCategory = "strategy";
let selectedPortfolioMode = "model";
let rightRailMode = "detail";
let openMenuInstrumentId = null;
let openMenuPosition = null;
let removeConfirmInstrumentId = null;
let removeConfirmGroupId = null;
let editInstrumentState = null;
let assetPoolFilters = {
  search: "",
  group: "全部分组",
  usage: "全部用途",
  status: "全部状态",
};
let collapsedAssetGroups = {};
let addInstrumentState = {
  query: "",
  selectedInstrument: null,
  results: [],
  searchStatus: "idle",
  searchError: "",
  isSaving: false,
  saveError: "",
  groupId: "stock_watchlist",
  usage: "signal_monitoring",
  role: "single_stock_watch",
  showInOverview: true,
  includeInMonitoring: true,
  includeInBacktest: false,
};
let addSearchTimer = null;
let addSearchRequestId = 0;
let assetPoolConfig = {
  version: 1,
  instruments: {},
};
let manualHoldingsConfig = {
  version: 1,
  holdings: {},
};
let manualHoldingsCapabilities = {
  read: false,
  persistConfig: false,
};
let paperAccount = {
  version: 1,
  settings: {
    initialCashUsdt: 100000,
    riskPerTradePct: 1,
    targetEtfWeightPct: 60,
    targetStockWeightPct: 40,
    maxSinglePositionPct: 15,
    autoRun: true,
  },
  cashUsdt: 100000,
  positions: {},
  trades: [],
  equityCurve: [],
  processedSignals: [],
  risk: { lossStreak: 0, entryPaused: false },
};
let paperAccountCapabilities = {
  read: false,
  reset: false,
  run: false,
};
let paperAccountLoading = false;
let paperAccountError = "";
let lastSnapshot = null;
let currentConfig = null;
let currentConfigError = "";
let binanceStatus = {
  configured: false,
  connected: false,
  accountType: "SPOT",
  readOnly: true,
  apiKeyMasked: null,
  lastSyncedAt: null,
};
let binanceAccount = null;
let binanceError = "";
let binanceLoading = false;
let settingsDraft = {};
let settingsCapabilities = {
  read_config: false,
  save_draft: false,
  run_validation_backtest: false,
  publish_config: false,
  rollback_config: false,
};
let signalFilters = {
  range: "全部",
  etf: "全部",
  type: "全部",
  status: "全部",
  importance: "全部",
  search: "",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pct(value, options = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = options.sign && value > 0 ? "+" : "";
  return `${sign}${fmt.format(value)}%`;
}

function price(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return fmt.format(value);
}

function changeClass(value) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

function labelFor(value, labels) {
  return labels[value] || value?.replaceAll?.("_", " ") || "—";
}

function actionBase(action) {
  if (!action) return "WATCH";
  if (action.includes("BUY")) return "BUY";
  if (action.includes("SELL")) return "SELL";
  if (action.includes("HOLD")) return "HOLD";
  return "WATCH";
}

function actionClass(action) {
  const base = actionBase(action);
  if (base === "BUY") return "buy";
  if (base === "SELL") return "sell";
  if (base === "HOLD") return "hold";
  return "watch";
}

function getRoute() {
  const route = window.location.hash.replace("#", "") || "overview";
  return Object.hasOwn(routeTitles, route) ? route : "overview";
}

function ensurePaperNavItem() {
  if (document.querySelector('[data-route="paper"]')) return;
  const settingsLink = document.querySelector('[data-route="settings"]');
  if (!settingsLink) return;
  settingsLink.insertAdjacentHTML("beforebegin", `
    <a class="nav-item" href="#paper" data-route="paper">
      <span class="nav-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M5 18.5V7.5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v11" />
          <path d="M8 9h8" />
          <path d="M8 13h4" />
          <path d="M7 18.5h10" />
          <path d="M15.5 13.5 18 16l-2.5 2.5" />
        </svg>
      </span>
      <span>模拟</span>
    </a>
  `);
}

function getSystemState(item) {
  if (item.role === "cash") return { text: "停泊", className: "parked" };
  if (item.risk_signal || !item.trend_ok) return { text: "受损", className: "damaged" };
  if (item.role === "defensive") return { text: "稳健", className: "stable" };
  if (item.notes?.includes("near_resistance")) return { text: "观察", className: "watch" };
  if (item.trend_ok && (item.structure_ok || item.breakout_hold || item.pullback_stand)) {
    return { text: "强势", className: "strong" };
  }
  return { text: "观察", className: "watch" };
}

function getKeyPrompt(item) {
  const risks = item.risk_reasons || [];
  if (risks.includes("close_below_sma200")) return "跌破 SMA200";
  if (risks.includes("close_below_swing_low")) return "跌破波段低点";
  if (risks.includes("failed_breakout")) return "突破失败";
  if (risks.includes("long_bearish_volume")) return "放量长阴线";

  const notes = item.notes || [];
  if (notes.includes("breakout_hold")) return "突破确认";
  if (notes.includes("near_resistance")) return "接近阻力";
  if (notes.includes("near_support")) return "接近支撑";
  if (notes.includes("pullback_stand")) return "回踩站稳";
  if (notes.includes("higher_high_higher_low")) return "结构抬高";
  if (notes.includes("cash_parking")) return "现金停泊";
  return "—";
}

function deriveStats(items, snapshot) {
  const actions = items.map((item) => actionBase(item.action));
  const buyCount = actions.filter((item) => item === "BUY").length;
  const sellCount = actions.filter((item) => item === "SELL").length;
  const riskAlertCount = items.filter((item) => item.risk_signal || (item.risk_reasons || []).length > 0).length;
  const pendingCount = items.filter((item) => actionBase(item.action) !== "HOLD").length;
  const regime = snapshot.regime === "RISK_ON" ? "Risk-On" : snapshot.regime || "—";
  return { buyCount, sellCount, riskAlertCount, pendingCount, regime };
}

function renderOverviewSummary(items, snapshot) {
  const stats = deriveStats(items, snapshot);
  const updated = formatTime(snapshot.generated_at);
  const cards = [
    { label: "市场状态", value: stats.regime, helper: "整体风险偏好积极", tone: "green", icon: "trend" },
    { label: "新增信号", value: stats.buyCount, helper: `卖出信号 ${stats.sellCount}`, tone: "green", icon: "signal" },
    { label: "风险警报", value: stats.riskAlertCount, helper: "需关注风险信号", tone: "red", icon: "risk" },
    { label: "待处理动作", value: stats.pendingCount, helper: "建议及时处理", tone: "amber", icon: "tasks" },
    { label: "更新时间", value: "收盘后", helper: `${updated} 更新`, tone: "blue", icon: "clock" },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderSignalSummary(events) {
  const confirmed = events.filter((event) => event.status === "confirmed").length;
  const pending = events.filter((event) => event.status === "pending" || event.status === "new").length;
  const risks = events.filter((event) => event.status === "warning" || event.type === "risk").length;
  const cards = [
    { label: "今日新增", value: "—", helper: "缺少事件日期", tone: "green", icon: "signal" },
    { label: "待确认", value: pending, helper: "当前快照派生", tone: "amber", icon: "pending" },
    { label: "已确认", value: confirmed, helper: "当前有效信号", tone: "green", icon: "check" },
    { label: "风险信号", value: risks, helper: "当前快照派生", tone: "red", icon: "risk" },
    { label: "今日失效", value: "—", helper: "缺少事件历史", tone: "slate", icon: "expired" },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function SummaryIcon(icon) {
  const icons = {
    trend: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M5 18.5 9.7 13l3.2 3.1L20 8.2v6.3c0 3.1-2.5 5.5-5.5 5.5h-7c-.9 0-1.8-.6-2.5-1.5Z" />
        <path d="M4.5 16.8 9.2 12l3.6 3.5L20 7.5" />
        <path d="M15.6 7.5H20V12" />
        <path d="M4 19h16" />
      </svg>
    `,
    signal: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M12 7.2a4.8 4.8 0 1 1 0 9.6 4.8 4.8 0 0 1 0-9.6Z" />
        <path d="M8.7 13.8a4.5 4.5 0 0 1 0-3.6" />
        <path d="M15.3 10.2a4.5 4.5 0 0 1 0 3.6" />
        <path d="M5.8 16.8a8 8 0 0 1 0-9.6" />
        <path d="M18.2 7.2a8 8 0 0 1 0 9.6" />
        <path d="M12 14.8V19" />
        <path d="M9.4 19h5.2" />
      </svg>
    `,
    risk: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M12 4.5 21 19H3L12 4.5Z" />
        <path d="M12 4.5 21 19H3L12 4.5Z" />
        <path d="M12 9v4.2" />
        <path d="M12 16.8h.01" />
      </svg>
    `,
    tasks: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M6 5.5h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z" />
        <path d="M8.4 8.2h9" />
        <path d="M8.4 12h9" />
        <path d="M8.4 15.8h6" />
        <path d="M5.6 8.2h.01" />
        <path d="M5.6 12h.01" />
        <path d="M5.6 15.8h.01" />
      </svg>
    `,
    clock: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <circle class="summary-icon-fill" cx="12" cy="12" r="7.5" />
        <path d="M12 8v4.4l3 1.8" />
        <path d="M7.4 6.4a7.5 7.5 0 1 0 9.2 0" />
        <path d="M18.5 5.5 20 4" />
        <path d="M5.5 5.5 4 4" />
      </svg>
    `,
    pending: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M6 5h12v14H6z" />
        <path d="M7 5.5h10" />
        <path d="M7 10h10" />
        <path d="M7 14.5h6" />
        <path d="M17.5 15.5 20 18l-2.5 2.5" />
      </svg>
    `,
    check: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <circle class="summary-icon-fill" cx="12" cy="12" r="8" />
        <path d="M7.5 12.2 10.5 15l6-6.3" />
        <circle cx="12" cy="12" r="8" />
      </svg>
    `,
    expired: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <circle class="summary-icon-fill" cx="12" cy="12" r="8" />
        <path d="m8.5 8.5 7 7" />
        <path d="m15.5 8.5-7 7" />
        <circle cx="12" cy="12" r="8" />
      </svg>
    `,
    monitor: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <rect class="summary-icon-fill" x="4" y="5" width="16" height="12" rx="2.2" />
        <rect x="4" y="5" width="16" height="12" rx="2.2" />
        <path d="M7 13h2.2l2-4 2.5 6 1.8-3H18" />
        <path d="M10 20h4" />
      </svg>
    `,
    volatility: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M4 15c2-5 4-5 6 0s4 5 6 0 3-5 4-1v5H4Z" />
        <path d="M4 15c2-5 4-5 6 0s4 5 6 0 3-5 4-1" />
        <path d="M4 19h16" />
      </svg>
    `,
    target: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <circle class="summary-icon-fill" cx="12" cy="12" r="8" />
        <circle cx="12" cy="12" r="8" />
        <circle cx="12" cy="12" r="4.5" />
        <path d="M12 9.5v2.5l2 1.2" />
      </svg>
    `,
    data: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M5 5h14v14H5z" />
        <path d="M5 5h14v14H5z" />
        <path d="M8 15V9" />
        <path d="M12 15v-4" />
        <path d="M16 15V7.5" />
      </svg>
    `,
    assetCount: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M6 6h5v5H6zM13 6h5v5h-5zM6 13h5v5H6zM13 13h5v5h-5z" />
        <path d="M6 6h5v5H6z" />
        <path d="M13 6h5v5h-5z" />
        <path d="M6 13h5v5H6z" />
        <path d="M13 13h5v5h-5z" />
      </svg>
    `,
    return: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M5 17 9 12l4 3 6-8v11H5z" />
        <path d="M5 17 9 12l4 3 6-8" />
        <path d="M5 19h14" />
        <path d="M17 7h2v2" />
      </svg>
    `,
    drawdown: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M5 7l5 5 3-2.5 6 6.5v3H5z" />
        <path d="M5 7l5 5 3-2.5 6 6.5" />
        <path d="M19 12v4h-4" />
        <path d="M5 19h14" />
      </svg>
    `,
    scale: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M7 9h10l-3 8H10Z" />
        <path d="M12 5v14" />
        <path d="M6 8h12" />
        <path d="M8 8 5 14h6Z" />
        <path d="M16 8 13 14h6Z" />
      </svg>
    `,
    benchmark: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M12 4 20 12l-8 8-8-8Z" />
        <path d="M12 4 20 12l-8 8-8-8Z" />
        <path d="M9 12h6" />
        <path d="M12 9v6" />
      </svg>
    `,
    portfolio: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <circle class="summary-icon-fill" cx="12" cy="12" r="8" />
        <path d="M12 4v8l6 4" />
        <path d="M12 12 6 17" />
        <path d="M12 12h8" />
        <circle cx="12" cy="12" r="8" />
      </svg>
    `,
    shield: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M12 4 19 7v5c0 4-2.8 6.5-7 8-4.2-1.5-7-4-7-8V7Z" />
        <path d="M12 4 19 7v5c0 4-2.8 6.5-7 8-4.2-1.5-7-4-7-8V7Z" />
        <path d="m8.5 12 2.2 2.2 4.8-5" />
      </svg>
    `,
    wallet: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M4 7h15a2 2 0 0 1 2 2v8H4Z" />
        <path d="M4 7h15a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4Z" />
        <path d="M17 12h4" />
        <path d="M7 7V5h9" />
      </svg>
    `,
    balance: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M6 6h12v12H6z" />
        <path d="M6 16h12" />
        <path d="M8 16V9" />
        <path d="M12 16v-5" />
        <path d="M16 16V7" />
      </svg>
    `,
    link: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M8 7h8v10H8z" />
        <path d="M9.5 14.5 8 16a3.5 3.5 0 0 1-5-5l2-2a3.5 3.5 0 0 1 5 0" />
        <path d="M14.5 9.5 16 8a3.5 3.5 0 0 1 5 5l-2 2a3.5 3.5 0 0 1-5 0" />
        <path d="M9 15 15 9" />
      </svg>
    `,
    version: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M5 5h14v14H5z" />
        <path d="M7 6h10" />
        <path d="M7 11h10" />
        <path d="M7 16h6" />
        <path d="M17 16h.01" />
      </svg>
    `,
    changes: `
      <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
        <path class="summary-icon-fill" d="M6 5h12v14H6z" />
        <path d="M8 7h8" />
        <path d="M8 12h8" />
        <path d="M8 17h4" />
        <path d="m15 16 1.5 1.5L20 14" />
      </svg>
    `,
  };
  return icons[icon] || escapeHtml(icon || "");
}

function SummaryCard({ label, value, helper, tone, icon }) {
  return `
    <article class="summary-card ${tone}">
      <div class="summary-icon" aria-hidden="true">${SummaryIcon(icon)}</div>
      <div>
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        <p>${escapeHtml(helper)}</p>
      </div>
    </article>
  `;
}

function MomentumBar(value, maxAbs) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return `<div class="momentum-cell"><span>—</span><div class="momentum-track"><i></i></div></div>`;
  }
  const width = maxAbs > 0 ? Math.max(8, Math.min(100, Math.abs(value) / maxAbs * 100)) : 8;
  const tone = value >= 0 ? "positive" : "negative";
  return `
    <div class="momentum-cell">
      <span class="${changeClass(value)}">${pct(value, { sign: true })}</span>
      <div class="momentum-track ${tone}"><i style="width:${width}%"></i></div>
    </div>
  `;
}

function StatusBadge(state) {
  return `<span class="status-badge ${state.className}">${escapeHtml(state.text)}</span>`;
}

function ActionBadge(action) {
  const base = actionBase(action);
  return `<span class="action-badge ${actionClass(action)}">${base}</span>`;
}

function SignalTypeBadge(type) {
  return `<span class="signal-type-badge ${type}">${signalTypeLabels[type] || type}</span>`;
}

function SignalStatusBadge(status) {
  return `<span class="signal-status-badge ${status}">${signalStatusLabels[status] || status}</span>`;
}

function ImportanceBadge(importance) {
  return `<span class="importance-badge ${importance}">${signalImportanceLabels[importance] || importance}</span>`;
}

function configValue(config, path, fallback = undefined) {
  if (!config || !path) return fallback;
  const value = path.split(".").reduce((acc, key) => (acc && Object.hasOwn(acc, key) ? acc[key] : undefined), config);
  return value === undefined || value === null ? fallback : value;
}

function settingValue(path, fallback = undefined) {
  if (Object.hasOwn(settingsDraft, path)) return settingsDraft[path];
  return configValue(currentConfig, path, fallback);
}

function normalizeSettingValue(path, value) {
  const base = configValue(currentConfig, path);
  if (typeof base === "number") return Number(value);
  if (typeof base === "boolean") return value === "true";
  return value;
}

function formatSettingValue(path, value) {
  if (value === undefined || value === null || value === "") return "未配置";
  if (path.includes("sma_days")) return `SMA${value}`;
  if (path.includes("momentum_days") || path.includes("short_momentum_days") || path.includes("window_days")) return `${value}D`;
  if (path.includes("hold_days")) return `${value} 个交易日`;
  if (path.includes("_pct") || path.includes("threshold_pct") || path.includes("buffer_pct")) return `${fmt.format(value)}%`;
  if (path.includes("volume_multiplier")) return `${fmt.format(value)}x`;
  if (typeof value === "boolean") return value ? "已启用" : "未启用";
  return String(value);
}

function settingChanged(path) {
  if (!Object.hasOwn(settingsDraft, path)) return false;
  return String(settingsDraft[path]) !== String(configValue(currentConfig, path));
}

function buildSettingsChanges() {
  return Object.keys(settingsDraft)
    .filter((path) => settingChanged(path))
    .map((path) => ({
      path,
      label: settingsFieldLabels[path] || path,
      previousValue: formatSettingValue(path, configValue(currentConfig, path)),
      nextValue: formatSettingValue(path, settingsDraft[path]),
      impacts: path.startsWith("execution.") ? ["总览"] : ["总览", "信号", "组合", "监控", "回测"],
      requiresBacktestValidation: !path.startsWith("execution."),
    }));
}

function instrumentType(item) {
  if (item.role === "stock") return "stock";
  if (item.role === "risk" || item.role === "defensive" || item.role === "cash") return "etf";
  return "other";
}

function instrumentTypeLabel(item) {
  if (instrumentType(item) === "stock") return "股票";
  if (instrumentType(item) === "etf") return "ETF";
  return "其他";
}

function instrumentUsage(item) {
  if (["QQQ", "SPY", "GLD", "SGOV"].includes(item.symbol)) return "strategy";
  if (item.role === "stock") return "watch_only";
  return "signal_monitoring";
}

function isBaselineStrategySymbol(symbol) {
  return ["QQQ", "SPY", "GLD", "SGOV"].includes(String(symbol || "").toUpperCase());
}

function defaultAssetPoolConfigForSymbol(symbol, type = "") {
  const normalized = String(symbol || "").toUpperCase();
  if (isBaselineStrategySymbol(normalized)) {
    return {
      groupId: "core_strategy",
      usage: "strategy",
      role: portfolioRoles[normalized]?.key || "custom",
      showInOverview: true,
      includeInMonitoring: true,
      includeInBacktest: true,
    };
  }
  const normalizedType = String(type || "").toLowerCase();
  const isEtf = normalizedType.includes("etf");
  return {
    groupId: isEtf ? "core_strategy" : "stock_watchlist",
    usage: isEtf ? "signal_monitoring" : "watch_only",
    role: isEtf ? "custom" : "single_stock_watch",
    showInOverview: true,
    includeInMonitoring: isEtf,
    includeInBacktest: false,
  };
}

function applyAddDefaultsForInstrument(instrument) {
  if (!instrument) return;
  const defaults = defaultAssetPoolConfigForSymbol(instrument.symbol, instrument.type || instrument.instrumentType);
  addInstrumentState.groupId = defaults.groupId;
  addInstrumentState.usage = defaults.usage;
  addInstrumentState.role = defaults.role;
  addInstrumentState.showInOverview = defaults.showInOverview;
  addInstrumentState.includeInMonitoring = defaults.includeInMonitoring;
  addInstrumentState.includeInBacktest = defaults.includeInBacktest;
}

function normalizeGroupId(value) {
  const raw = String(value || "").trim().toLowerCase();
  const cleaned = raw.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned.slice(0, 48) || `group_${Date.now()}`;
}

function uniqueSymbols(values) {
  const symbols = [];
  (values || []).forEach((value) => {
    const symbol = String(value || "").trim().toUpperCase();
    if (symbol && !symbols.includes(symbol) && symbols.length < MAX_ASSET_POOL_GROUP_SYMBOLS) {
      symbols.push(symbol);
    }
  });
  return symbols;
}

function normalizeAssetPoolGroups(config = assetPoolConfig) {
  const source = Array.isArray(config.groups) && config.groups.length ? config.groups : defaultAssetPoolGroups;
  const groups = [];
  const seen = new Set();
  source.forEach((group, index) => {
    if (!group || groups.length >= MAX_ASSET_POOL_GROUPS) return;
    const name = String(group.name || "").trim();
    if (!name) return;
    let id = normalizeGroupId(group.id || name || `group_${index + 1}`);
    const baseId = id;
    let suffix = 2;
    while (seen.has(id)) {
      id = `${baseId}_${suffix}`;
      suffix += 1;
    }
    seen.add(id);
    groups.push({
      id,
      name: name.slice(0, 40),
      symbols: uniqueSymbols(group.symbols),
      locked: Boolean(group.locked),
    });
  });
  return groups.length ? groups : defaultAssetPoolGroups.map((group) => ({ ...group, symbols: [...group.symbols] }));
}

function groupContainsSymbol(groupId, symbol) {
  const normalized = String(symbol || "").toUpperCase();
  const group = assetPoolGroups.find((item) => item.id === groupId);
  return Boolean(group && group.symbols.includes(normalized));
}

function groupsForSymbol(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return assetPoolGroups.filter((group) => group.symbols.includes(normalized));
}

function withSymbolInGroup(groups, groupId, symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return groups.map((group) => {
    if (group.id !== groupId) return { ...group, symbols: [...group.symbols] };
    if (group.symbols.includes(normalized)) return { ...group, symbols: [...group.symbols] };
    if (group.symbols.length >= MAX_ASSET_POOL_GROUP_SYMBOLS) return { ...group, symbols: [...group.symbols] };
    return { ...group, symbols: [...group.symbols, normalized] };
  });
}

function withoutSymbolInGroup(groups, groupId, symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return groups.map((group) => {
    if (group.id !== groupId) return { ...group, symbols: [...group.symbols] };
    return { ...group, symbols: group.symbols.filter((item) => item !== normalized) };
  });
}

function withoutSymbolInAllGroups(groups, symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return groups.map((group) => ({ ...group, symbols: group.symbols.filter((item) => item !== normalized) }));
}

function groupForSymbol(symbol) {
  return assetPoolGroups.find((group) => group.symbols.includes(symbol)) || {
    id: "ungrouped",
    name: "未分组",
    symbols: [symbol],
  };
}

function buildAssetPoolItems(items) {
  return items.map((item) => {
    const override = assetPoolConfig.instruments?.[item.symbol] || {};
    const state = getSystemState(item);
    const usage = ["watch_only", "signal_monitoring", "strategy"].includes(override.usage)
      ? override.usage
      : instrumentUsage(item);
    const group = assetPoolGroups.find((candidate) => candidate.id === override.groupId) || groupForSymbol(item.symbol);
    const roleKey = override.role || portfolioRoles[item.symbol]?.key || (item.role === "stock" ? "single_stock_watch" : item.role) || "custom";
    const roleOption = instrumentRoleOptions.find(([value]) => value === roleKey);
    const showInOverview = override.showInOverview ?? true;
    if (override.removed || showInOverview === false) return null;
    return {
      raw: item,
      id: item.symbol,
      symbol: item.symbol,
      name: etfDescriptions[item.symbol] || item.symbol,
      type: instrumentType(item),
      typeLabel: instrumentTypeLabel(item),
      groupId: group.id,
      groupName: group.name,
      usage,
      usageLabel: instrumentUsageLabels[usage],
      roleKey,
      roleLabel: roleOption?.[1] || portfolioRoles[item.symbol]?.label || roleLabels[item.role] || item.role,
      state,
      keyPrompt: getKeyPrompt(item),
      displayAction: usage === "strategy" ? actionBase(item.action) : usage === "signal_monitoring" ? "WATCH" : "—",
      showInOverview,
      includeInMonitoring: override.includeInMonitoring ?? usage !== "watch_only",
      includeInBacktest: override.includeInBacktest ?? usage === "strategy",
    };
  }).filter(Boolean);
}

function configuredInstrumentType(config) {
  const rawType = String(config?.type || config?.instrumentType || "").toLowerCase();
  if (rawType.includes("etf")) return "etf";
  if (rawType.includes("equity") || rawType.includes("stock")) return "stock";
  return "other";
}

function instrumentTypeLabelFromType(type) {
  if (type === "stock") return "股票";
  if (type === "etf") return "ETF";
  return "其他";
}

function placeholderRawFromConfig(symbol, config) {
  return {
    date: null,
    symbol,
    role: "stock",
    close: null,
    current_price: null,
    current_time: null,
    day_change_pct: null,
    ten_min_change_pct: null,
    momentum_63_pct: null,
    momentum_126_pct: null,
    trend_ok: false,
    structure_ok: false,
    near_support: false,
    near_resistance: false,
    breakout_hold: false,
    pullback_stand: false,
    risk_signal: false,
    risk_reasons: [],
    notes: [],
    target_pct: 0,
    current_pct: null,
    trade_delta_pct: null,
    action: "WATCH",
    limit_price: null,
    pending_asset_pool_data: true,
  };
}

function poolItemFromRaw(item, forcedGroup = null) {
  const override = assetPoolConfig.instruments?.[item.symbol] || {};
  const state = item.pending_asset_pool_data
    ? { text: "待计算", className: "pending" }
    : getSystemState(item);
  const usage = ["watch_only", "signal_monitoring", "strategy"].includes(override.usage)
    ? override.usage
    : instrumentUsage(item);
  const group = forcedGroup || assetPoolGroups.find((candidate) => candidate.id === override.groupId) || groupForSymbol(item.symbol);
  const roleKey = override.role || portfolioRoles[item.symbol]?.key || (item.role === "stock" ? "single_stock_watch" : item.role) || "custom";
  const roleOption = instrumentRoleOptions.find(([value]) => value === roleKey);
  const showInOverview = override.showInOverview ?? true;
  if (override.removed || showInOverview === false) return null;
  const type = item.pending_asset_pool_data ? configuredInstrumentType(override) : instrumentType(item);
  return {
    raw: item,
    id: `${group.id}:${item.symbol}`,
    symbol: item.symbol,
    name: override.name || etfDescriptions[item.symbol] || item.symbol,
    type,
    typeLabel: item.pending_asset_pool_data ? instrumentTypeLabelFromType(type) : instrumentTypeLabel(item),
    groupId: group.id,
    groupName: group.name,
    usage,
    usageLabel: instrumentUsageLabels[usage],
    roleKey,
    roleLabel: roleOption?.[1] || portfolioRoles[item.symbol]?.label || roleLabels[item.role] || item.role,
    state,
    keyPrompt: item.pending_asset_pool_data ? "等待首次计算" : getKeyPrompt(item),
    displayAction: usage === "strategy" ? actionBase(item.action) : usage === "signal_monitoring" ? "WATCH" : "—",
    showInOverview,
    includeInMonitoring: override.includeInMonitoring ?? usage !== "watch_only",
    includeInBacktest: override.includeInBacktest ?? usage === "strategy",
    pending: Boolean(item.pending_asset_pool_data),
  };
}

function buildAssetPoolItems(items) {
  const poolItems = items.flatMap((item) => {
    const override = assetPoolConfig.instruments?.[item.symbol] || {};
    if (override.removed || override.showInOverview === false) return [];
    const memberships = groupsForSymbol(item.symbol);
    const groups = memberships.length
      ? memberships
      : [assetPoolGroups.find((candidate) => candidate.id === override.groupId) || groupForSymbol(item.symbol)];
    return groups.map((group) => poolItemFromRaw(item, group)).filter(Boolean);
  });
  const seen = new Set(poolItems.map((item) => item.symbol));
  const configuredOnly = Object.entries(assetPoolConfig.instruments || {})
    .filter(([symbol, config]) => {
      if (seen.has(symbol) || config?.removed || config?.showInOverview === false) return false;
      return true;
    })
    .flatMap(([symbol, config]) => {
      const memberships = groupsForSymbol(symbol);
      const groups = memberships.length
        ? memberships
        : [assetPoolGroups.find((candidate) => candidate.id === config.groupId) || groupForSymbol(symbol)];
      return groups.map((group) => poolItemFromRaw(placeholderRawFromConfig(symbol, config), group));
    })
    .filter(Boolean);
  return [...poolItems, ...configuredOnly];
}

function filterAssetPoolItems(poolItems) {
  const search = assetPoolFilters.search.trim().toLowerCase();
  return poolItems.filter((item) => {
    const matchesSearch = !search || `${item.symbol} ${item.name}`.toLowerCase().includes(search);
    const matchesGroup = assetPoolFilters.group === "全部分组" || item.groupName === assetPoolFilters.group;
    const matchesUsage = assetPoolFilters.usage === "全部用途" || item.usageLabel === assetPoolFilters.usage;
    const matchesStatus = assetPoolFilters.status === "全部状态" || item.state.text === assetPoolFilters.status;
    return matchesSearch && matchesGroup && matchesUsage && matchesStatus;
  });
}

function renderOverview(items) {
  const poolItems = buildAssetPoolItems(items);
  const selectedPoolItem = poolItems.find((item) => item.symbol === selectedSymbol && item.groupId === selectedGroupId)
    || poolItems.find((item) => item.symbol === selectedSymbol)
    || poolItems[0];
  if (selectedPoolItem && !poolItems.some((item) => item.symbol === selectedSymbol && item.groupId === selectedGroupId)) {
    selectedSymbol = selectedPoolItem.symbol;
    selectedGroupId = selectedPoolItem.groupId;
  }
  const routeContent = document.getElementById("routeContent");
  routeContent.innerHTML = `
    <section class="asset-pool-layout">
      <div class="asset-pool-column">
        ${AssetPoolHeader(poolItems)}
        ${AssetPoolToolbar(poolItems)}
        ${AssetPoolAccountSyncBar()}
        <div id="assetGroups" class="asset-groups"></div>
        <div class="status-legend">
          <span>状态说明：</span>
          <i class="dot strong"></i>强势
          <i class="dot stable"></i>稳健
          <i class="dot watch"></i>观察
          <i class="dot damaged"></i>受损
          <i class="dot parked"></i>停泊
        </div>
      </div>
      ${AssetRightRail(selectedPoolItem)}
    </section>
    ${RemoveInstrumentConfirmDialog(poolItems.find((item) => item.symbol === removeConfirmInstrumentId && item.groupId === removeConfirmGroupId) || poolItems.find((item) => item.symbol === removeConfirmInstrumentId) || defaultPoolItemFromSnapshot(removeConfirmInstrumentId))}
  `;
  renderAssetPoolGroups(poolItems);
  bindOverviewRowEvents();
}

function AssetPoolHeader(poolItems) {
  return `
    <section class="asset-pool-header-card">
      <div>
        <h2>我的资产池</h2>
        <p>追踪自定义品种的趋势、动量与风险信号</p>
      </div>
      <div class="asset-pool-actions">
        <button class="asset-primary-button" type="button" data-asset-action="add">+ 添加品种</button>
        <button class="asset-secondary-button" type="button" data-asset-action="manage" title="资产池持久化管理尚未接入">管理资产池</button>
      </div>
    </section>
  `;
}

function AssetPoolToolbar(poolItems) {
  const groupOptions = ["全部分组", ...assetPoolGroups.map((group) => group.name)];
  const usageOptions = ["全部用途", ...Object.values(instrumentUsageLabels)];
  const statusOptions = ["全部状态", "强势", "稳健", "观察", "受损", "停泊"];
  return `
    <section class="asset-pool-toolbar">
      <label class="asset-search">
        <span aria-hidden="true">⌕</span>
        <input id="assetSearch" type="search" placeholder="搜索代码 / 名称" value="${escapeHtml(assetPoolFilters.search)}">
      </label>
      ${AssetFilterSelect("group", groupOptions, assetPoolFilters.group)}
      ${AssetFilterSelect("usage", usageOptions, assetPoolFilters.usage)}
      ${AssetFilterSelect("status", statusOptions, assetPoolFilters.status)}
    </section>
  `;
}

function AssetPoolAccountSyncBar() {
  const statusText = !binanceStatus.configured
    ? "账户未配置"
    : binanceAccount?.lastSyncedAt
      ? `账户已同步 ${formatDateTime(binanceAccount.lastSyncedAt)}`
      : binanceStatus.connected
        ? "账户已连接，待同步持仓"
        : "账户已配置，待测试";
  const matchCount = AccountHoldingMatchCount();
  const manualCount = Object.keys(manualHoldingsConfig.holdings || {}).length;
  const binanceCount = binanceAccount?.assets?.length || 0;
  const matchText = matchCount
    ? `${matchCount} 个资产池品种匹配持仓`
    : binanceCount || manualCount
      ? "暂无资产池品种匹配持仓"
      : "暂无持仓数据";
  return `
    <section class="asset-account-sync-bar">
      <div>
        <strong>${escapeHtml(statusText)}</strong>
        <span>${escapeHtml(matchText)}；手动持仓 ${manualCount} 条，Binance 非零资产 ${binanceCount} 条。</span>
      </div>
      <button class="asset-secondary-button" type="button" data-binance-refresh ${binanceStatus.configured && !binanceLoading ? "" : "disabled"}>
        ${binanceLoading ? "同步中..." : "同步账户"}
      </button>
    </section>
  `;
}

function AssetFilterSelect(key, options, value) {
  return `
    <select class="asset-filter-select" data-asset-filter="${key}">
      ${options.map((option) => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}
    </select>
  `;
}

function renderAssetPoolGroups(poolItems) {
  const filtered = filterAssetPoolItems(poolItems);
  const maxAbsMomentum = Math.max(1, ...poolItems.map((item) => Math.abs(item.raw.momentum_126_pct || 0)));
  const html = assetPoolGroups.map((group) => {
    const groupItems = filtered.filter((item) => item.groupId === group.id);
    return AssetGroupCard(group, groupItems, maxAbsMomentum);
  }).join("");

  const ungrouped = filtered.filter((item) => !assetPoolGroups.some((group) => group.id === item.groupId));
  document.getElementById("assetGroups").innerHTML = `
    ${html}
    ${ungrouped.length ? AssetGroupCard({ id: "ungrouped", name: "未分组" }, ungrouped, maxAbsMomentum) : ""}
    ${filtered.length ? "" : `<section class="asset-card"><div class="empty-state">当前筛选条件下暂无品种</div></section>`}
  `;
}

function AssetGroupCard(group, items, maxAbsMomentum) {
  const collapsed = Boolean(collapsedAssetGroups[group.id]);
  return `
    <section class="asset-card asset-pool-group-card" data-group-id="${escapeHtml(group.id)}">
      <div class="asset-card-header asset-pool-group-header">
        <div>
          <h2><span class="asset-group-dot ${group.id === "core_strategy" ? "green" : "blue"}"></span>${escapeHtml(group.name)}</h2>
        </div>
        <div class="asset-group-meta">
          <span>${items.length} 个品种</span>
          <button class="asset-collapse-button" type="button" data-delete-group="${escapeHtml(group.id)}" ${assetPoolGroups.length <= 1 ? "disabled" : ""}>\u5220\u9664\u7ec4</button>
          <button class="asset-collapse-button" type="button" data-collapse-group="${escapeHtml(group.id)}">${collapsed ? "展开" : "收起"}⌃</button>
        </div>
      </div>
      ${collapsed ? "" : AssetGroupTable(items, maxAbsMomentum)}
    </section>
  `;
}

function AssetGroupTable(items, maxAbsMomentum) {
  const rows = items.map((item) => {
    const raw = item.raw;
    const menuOpen = openMenuInstrumentId === item.id;
    const selected = raw.symbol === selectedSymbol && item.groupId === selectedGroupId && (rightRailMode === "detail" || rightRailMode === "edit") ? "selected" : "";
    return `
      <tr class="${selected} ${menuOpen ? "menu-open" : ""}" data-symbol="${raw.symbol}" data-group-id="${escapeHtml(item.groupId)}" tabindex="0">
        <td class="symbol-cell asset-col-symbol">${raw.symbol}</td>
        <td class="asset-col-type asset-col-optional">${escapeHtml(item.typeLabel)}</td>
        <td class="asset-col-usage asset-col-optional">${UsageBadge(item.usage)}</td>
        <td class="asset-col-state">${StatusBadge(item.state)}</td>
        <td class="asset-col-price">${price(raw.current_price ?? raw.close)}</td>
        <td class="asset-col-holding">${AccountHoldingCell(raw.symbol, raw.current_price ?? raw.close)}</td>
        <td class="asset-col-value">${AccountValueCell(raw.symbol, raw.current_price ?? raw.close)}</td>
        <td class="asset-col-pnl">${AccountPnlCell(raw.symbol, raw.current_price ?? raw.close)}</td>
        <td class="asset-col-day ${changeClass(raw.day_change_pct)}">${pct(raw.day_change_pct, { sign: true })}</td>
        <td class="asset-col-momentum asset-col-optional">${MomentumBar(raw.momentum_126_pct, maxAbsMomentum)}</td>
        <td class="asset-col-prompt asset-col-optional">${escapeHtml(item.keyPrompt)}</td>
        <td class="asset-col-action">${InstrumentActionBadge(item)}</td>
        <td class="row-menu-cell asset-col-menu">
          <button class="row-more-button" type="button" data-more-symbol="${raw.symbol}" data-more-group="${escapeHtml(item.groupId)}" aria-expanded="${menuOpen ? "true" : "false"}" title="更多操作">···</button>
          ${menuOpen ? InstrumentRowMenu(item) : ""}
        </td>
      </tr>
    `;
  }).join("");

  return `
    <div class="group-table-wrap">
      <table class="asset-table asset-pool-table">
        <thead>
          <tr>
            <th>品种</th>
            <th>类型</th>
            <th>用途</th>
            <th>系统状态</th>
            <th>当前价格</th>
            <th>账户持仓</th>
            <th>账户市值</th>
            <th>账户盈亏</th>
            <th>今日</th>
            <th>126D 动量</th>
            <th>关键提示</th>
            <th>行动</th>
            <th>更多</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="13"><div class="empty-state compact">当前分组暂无匹配品种</div></td></tr>`}</tbody>
      </table>
    </div>
  `;
}

function UsageBadge(usage) {
  return `<span class="usage-badge ${usage}">${instrumentUsageLabels[usage] || usage}</span>`;
}

function InstrumentActionBadge(item) {
  if (item.displayAction === "—") return `<span class="instrument-action-none">—</span>`;
  if (item.displayAction === "WATCH") return `<span class="instrument-watch-badge">WATCH</span>`;
  return ActionBadge(item.raw.action);
}

function InstrumentRowMenu(item) {
  const actionItems = item.usage === "strategy"
    ? [
        ["edit", "\u7f16\u8f91\u914d\u7f6e"],
        ["pause_strategy", "\u6682\u505c\u7b56\u7565", true],
        ["separator"],
        ["remove", "\u79fb\u51fa\u8d44\u4ea7\u6c60", false, true],
      ]
    : item.usage === "signal_monitoring"
      ? [
          ["edit", "\u7f16\u8f91\u914d\u7f6e"],
          ["to_watch", "\u6539\u4e3a\u4ec5\u89c2\u5bdf"],
          ["to_strategy", "\u7eb3\u5165\u7b56\u7565"],
          ["separator"],
          ["remove", "\u79fb\u51fa\u8d44\u4ea7\u6c60", false, true],
        ]
      : [
          ["edit", "\u7f16\u8f91\u914d\u7f6e"],
          ["to_monitor", "\u8f6c\u4e3a\u4fe1\u53f7\u76d1\u63a7"],
          ["to_strategy", "\u7eb3\u5165\u7b56\u7565"],
          ["separator"],
          ["remove", "\u79fb\u51fa\u8d44\u4ea7\u6c60", false, true],
        ];

  const menuStyle = openMenuPosition ? ` style="left: ${openMenuPosition.left}px; top: ${openMenuPosition.top}px;"` : "";

  return `
    <div class="instrument-row-menu" role="menu" aria-label="${escapeHtml(item.symbol)} \u66f4\u591a\u64cd\u4f5c"${menuStyle}>
      ${actionItems.map(([action, label, disabled, destructive]) => {
        if (action === "separator") return `<i class="menu-separator" aria-hidden="true"></i>`;
        return `
          <button
            type="button"
            role="menuitem"
            class="${destructive ? "destructive" : ""}"
            data-menu-action="${action}"
            data-menu-symbol="${escapeHtml(item.symbol)}"
            data-menu-group="${escapeHtml(item.groupId)}"
            ${disabled ? "disabled title=\"\\u6682\\u672a\\u63a5\\u5165\\u8be5\\u4e1a\\u52a1\\u80fd\\u529b\"" : ""}
          >${label}</button>
        `;
      }).join("")}
    </div>
  `;
}

function getFloatingMenuPosition(button) {
  const rect = button.getBoundingClientRect();
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 768;
  const menuWidth = 190;
  const menuHeight = 180;
  const gap = 8;
  const margin = 12;
  let left = rect.right - menuWidth;
  let top = rect.bottom + gap;

  left = Math.min(Math.max(margin, left), Math.max(margin, viewportWidth - menuWidth - margin));
  if (top + menuHeight > viewportHeight - margin) {
    top = rect.top - menuHeight - gap;
  }
  top = Math.min(Math.max(margin, top), Math.max(margin, viewportHeight - menuHeight - margin));

  return {
    left: Math.round(left),
    top: Math.round(top),
  };
}

function closeInstrumentRowMenu() {
  openMenuInstrumentId = null;
  openMenuPosition = null;
}

function AssetRightRail(selectedPoolItem) {
  const titles = {
    detail: "\u54c1\u79cd\u8be6\u60c5",
    add: "\u6dfb\u52a0\u54c1\u79cd",
    edit: "\u7f16\u8f91\u914d\u7f6e",
  };
  const title = titles[rightRailMode] || titles.detail;
  const subtitle = rightRailMode === "detail"
    ? (selectedPoolItem ? `${selectedPoolItem.symbol} \u00b7 ${selectedPoolItem.groupName}` : "\u8bf7\u9009\u62e9\u54c1\u79cd")
    : rightRailMode === "add"
      ? "\u6dfb\u52a0\u5230\u5f53\u524d\u8d44\u4ea7\u6c60\u5206\u7ec4"
      : (selectedPoolItem ? `${selectedPoolItem.symbol} \u00b7 ${selectedPoolItem.name}` : "\u4fee\u6539\u8d44\u4ea7\u6c60\u914d\u7f6e");
  return `
    <aside id="assetRightRail" class="asset-right-rail" aria-label="\u8d44\u4ea7\u6c60\u53f3\u4fa7\u529f\u80fd\u680f">
      <div class="right-rail-context-header">
        <div>
          <h2>${title}</h2>
          <p>${escapeHtml(subtitle)}</p>
        </div>
        <div class="right-rail-header-actions">
          ${rightRailMode === "detail" && selectedPoolItem ? `<button class="detail-edit-button" type="button" data-detail-action="edit" data-detail-symbol="${escapeHtml(selectedPoolItem.symbol)}">\u7f16\u8f91</button>` : ""}
          <button class="right-rail-close" type="button" data-rail-close aria-label="\u5173\u95ed\u9762\u677f">&times;</button>
        </div>
      </div>
      ${rightRailMode === "add" ? AddInstrumentPanel() : rightRailMode === "edit" ? EditInstrumentPanel(selectedPoolItem) : InstrumentDetailPanel(selectedPoolItem)}
    </aside>
  `;
}

function InstrumentDetailPanel(poolItem) {
  if (!poolItem) return `<div class="empty-detail">请选择一个品种查看详情</div>`;
  const item = poolItem.raw;
  const risks = item.risk_reasons?.length
    ? item.risk_reasons.map((risk) => labelFor(risk, riskLabels)).join("、")
    : "无";
  const structure = (item.notes || [])
    .filter((note) => note !== "trend_ok" && note !== "cash_parking")
    .map((note) => labelFor(note, noteLabels))
    .join("、") || "—";
  const signalText = buildSignalText(poolItem);

  return `
    <section class="instrument-detail-panel">
      <div class="detail-header detail-compact-header">
        <div>
          <h2>${item.symbol}</h2>
          <p>${poolItem.name}</p>
        </div>
        <div class="detail-header-status">
          ${InstrumentActionBadge(poolItem)}
        </div>
      </div>

      <div class="detail-price-row">
        <strong>${price(item.current_price ?? item.close)}</strong>
      </div>
      <div class="detail-subrow">
        <span>今日涨跌</span>
        <b class="${changeClass(item.day_change_pct)}">${pct(item.day_change_pct, { sign: true })}</b>
      </div>

      ${ManualHoldingPanel(poolItem)}

      <dl class="detail-list detail-list-compact">
        <div><dt>所属分组</dt><dd>${escapeHtml(poolItem.groupName)}</dd></div>
        <div><dt>用途</dt><dd>${UsageBadge(poolItem.usage)}</dd></div>
        <div><dt>系统角色</dt><dd>${escapeHtml(poolItem.roleLabel)}</dd></div>
        <div><dt>显示在总览</dt><dd>已启用</dd></div>
        <div><dt>趋势</dt><dd>${item.trend_ok ? "通过" : "未通过"}</dd></div>
        <div><dt>结构</dt><dd>${escapeHtml(structure)}</dd></div>
        <div><dt>10 分钟变化</dt><dd class="${changeClass(item.ten_min_change_pct)}">${pct(item.ten_min_change_pct, { sign: true })}</dd></div>
        <div><dt>风险</dt><dd>${escapeHtml(risks)}</dd></div>
        <div><dt>加入监控</dt><dd>${poolItem.includeInMonitoring ? "已启用" : "未启用"}</dd></div>
        <div><dt>参与回测</dt><dd>${poolItem.includeInBacktest ? "已启用" : "未启用"}</dd></div>
        <div><dt>目标仓位</dt><dd>${poolItem.usage === "strategy" ? pct(item.target_pct) : "非策略品种"}</dd></div>
        <div><dt>限价</dt><dd>${poolItem.usage === "strategy" ? price(item.limit_price) : "—"}</dd></div>
      </dl>

      <div class="detail-insight-grid">
        <div class="signal-note">
          <span>信号说明</span>
          <p>${escapeHtml(signalText)}</p>
        </div>

        <div class="detail-footer">
          <span>126D 动量</span>
          <strong class="${changeClass(item.momentum_126_pct)}">${pct(item.momentum_126_pct, { sign: true })}</strong>
        </div>
      </div>

      <div class="danger-zone detail-danger-zone">
        <h3>危险操作</h3>
        <p>移出资产池只会影响当前资产池展示，不会删除历史行情或历史信号记录。</p>
        <button type="button" data-detail-action="remove" data-detail-symbol="${escapeHtml(item.symbol)}">移出资产池</button>
      </div>
    </section>
  `;
}

function ManualHoldingPanel(poolItem) {
  const item = poolItem.raw;
  const symbol = item.symbol;
  const holding = ManualHoldingForSymbol(symbol) || {};
  const currentPrice = item.current_price ?? item.close;
  const position = AccountPositionForSymbol(symbol, currentPrice);
  const valueText = position?.valueUsdt === null || position?.valueUsdt === undefined ? "—" : formatUsdt(position.valueUsdt);
  const pnlText = position && position.avgCostUsdt && typeof currentPrice === "number"
    ? AccountPnlCell(symbol, currentPrice).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
    : "填写平均成本价后计算";
  return `
    <section class="manual-holding-panel" data-manual-holding-symbol="${escapeHtml(symbol)}">
      <div class="manual-holding-header">
        <div>
          <h3>手动持仓</h3>
          <p>适合 Binance 没返回的品种、券商 ETF/股票，数据只保存在本机。</p>
        </div>
        <span>${position ? escapeHtml(position.source === "manual" ? "手动" : "Binance") : "未持有"}</span>
      </div>
      <div class="manual-holding-grid">
        <label>
          <span>持仓数量</span>
          <input type="number" min="0" step="any" data-holding-field="quantity" value="${holding.quantity ?? ""}" placeholder="例如 10">
        </label>
        <label>
          <span>平均成本 USDT</span>
          <input type="number" min="0" step="any" data-holding-field="avgCostUsdt" value="${holding.avgCostUsdt ?? ""}" placeholder="例如 420.5">
        </label>
        <label class="wide">
          <span>备注</span>
          <input type="text" maxlength="160" data-holding-field="note" value="${escapeHtml(holding.note || "")}" placeholder="券商、账户或批次备注">
        </label>
      </div>
      <div class="manual-holding-summary">
        <span>估算市值 <strong>${escapeHtml(valueText)}</strong></span>
        <span>盈亏 <strong>${escapeHtml(pnlText)}</strong></span>
      </div>
      <div class="manual-holding-actions">
        <button class="asset-primary-button" type="button" data-save-holding="${escapeHtml(symbol)}">保存持仓</button>
        <button class="asset-secondary-button" type="button" data-clear-holding="${escapeHtml(symbol)}" ${holding.quantity ? "" : "disabled"}>清除</button>
      </div>
    </section>
  `;
}

function AddInstrumentPanel() {
  const query = addInstrumentState.query.trim().toLowerCase();
  const results = addInstrumentPreviewResults.filter((item) => {
    if (!query) return true;
    return `${item.symbol} ${item.name}`.toLowerCase().includes(query);
  });
  const selected = addInstrumentPreviewResults.find((item) => item.symbol === addInstrumentState.selectedSymbol);
  return `
    <section class="add-instrument-panel">
      <div class="preview-note">Development preview：当前仅预览添加流程，不会写入正式配置。</div>
      <label class="add-search">
        <span>搜索品种</span>
        <input id="addInstrumentSearch" type="search" placeholder="输入代码或名称，例如 AAPL、TLT" value="${escapeHtml(addInstrumentState.query)}">
      </label>
      <div class="instrument-search-results">
        ${results.map((item) => `
          <button class="${item.symbol === addInstrumentState.selectedSymbol ? "selected" : ""}" type="button" data-preview-symbol="${escapeHtml(item.symbol)}">
            <strong>${escapeHtml(item.symbol)}</strong>
            <span>${escapeHtml(item.name)}</span>
            <em>${escapeHtml(item.type)}</em>
          </button>
        `).join("") || `<div class="empty-state compact">暂无预览搜索结果</div>`}
      </div>
      <div class="selected-instrument">
        <span>已选择：</span>
        <strong>${selected ? `${selected.symbol} · ${selected.name}` : "未选择"}</strong>
        <button type="button" data-clear-preview-symbol>×</button>
      </div>
      <div class="add-form-grid">
        <label>
          <span>所属分组</span>
          <select data-add-field="groupId">
            ${assetPoolGroups.map((group) => `<option value="${group.id}" ${group.id === addInstrumentState.groupId ? "selected" : ""}>${group.name}</option>`).join("")}
          </select>
        </label>
        <button class="new-group-button" type="button" data-create-group>+ ????</button>
        <div class="usage-selector">
          <span>用途</span>
          ${[
            ["watch_only", "仅观察"],
            ["signal_monitoring", "信号监控"],
            ["strategy", "纳入策略"],
          ].map(([value, label]) => `
            <button class="${addInstrumentState.usage === value ? "active" : ""}" type="button" data-add-usage="${value}">${label}</button>
          `).join("")}
        </div>
        <label>
          <span>系统角色</span>
          <select data-add-field="role">
            ${[
              ["core_equity", "核心权益"],
              ["growth_driver", "成长驱动"],
              ["risk_breadth", "风险扩散"],
              ["defensive_hedge", "防御对冲"],
              ["duration_defense", "久期防御"],
              ["cash_parking", "现金停泊"],
              ["single_stock_watch", "单股观察"],
              ["custom", "自定义"],
            ].map(([value, label]) => `<option value="${value}" ${value === addInstrumentState.role ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </label>
      </div>
      <div class="add-switch-list">
        ${AddSwitch("showInOverview", "是否显示在总览")}
        ${AddSwitch("includeInMonitoring", "是否加入监控")}
        ${AddSwitch("includeInBacktest", "是否参与回测")}
      </div>
      <div class="${addInstrumentState.usage === "strategy" ? "strategy-risk-note" : "add-info-note"}">
        ${addInstrumentState.usage === "strategy"
          ? "纳入策略的品种可能影响组合分析、动作建议与回测结果；当前未接入真实发布流程。"
          : "观察或监控品种只用于展示与提醒预览，不会影响正式策略仓位。"}
      </div>
      <div class="add-panel-actions">
        <button class="asset-secondary-button" type="button" data-add-cancel>取消</button>
        <button class="asset-primary-button" type="button" disabled title="尚未接入新增品种持久化接口">添加品种</button>
      </div>
    </section>
  `;
}

function selectedAddInstrument() {
  return addInstrumentState.selectedInstrument;
}

function selectedInstrumentAlreadyInTargetGroup(selected) {
  return Boolean(selected && groupContainsSymbol(addInstrumentState.groupId, selected.symbol));
}

function searchStatusContent() {
  if (addInstrumentState.searchStatus === "loading") {
    return `<div class="empty-state compact">\u6b63\u5728\u641c\u7d22...</div>`;
  }
  if (addInstrumentState.searchStatus === "error") {
    return `<div class="empty-state compact">\u641c\u7d22\u5931\u8d25\uff1a${escapeHtml(addInstrumentState.searchError || "\u672a\u77e5\u9519\u8bef")}</div>`;
  }
  if (addInstrumentState.searchStatus === "empty") {
    return `<div class="empty-state compact">\u672a\u627e\u5230\u53ef\u7528\u7684\u771f\u5b9e\u884c\u60c5\u54c1\u79cd</div>`;
  }
  if (!addInstrumentState.results.length) {
    return `<div class="empty-state compact">\u8f93\u5165\u4ee3\u7801\u540e\u6309 Enter \u6216\u70b9\u51fb\u641c\u7d22\u3002</div>`;
  }
  return addInstrumentState.results.map((item) => {
    const alreadyInTargetGroup = groupContainsSymbol(addInstrumentState.groupId, item.symbol);
    const addedElsewhere = item.alreadyAdded && !alreadyInTargetGroup;
    const suffix = alreadyInTargetGroup ? " \u00b7 \u5df2\u5728\u672c\u7ec4" : addedElsewhere ? " \u00b7 \u53ef\u52a0\u5165\u672c\u7ec4" : item.manualFallback ? " \u00b7 \u624b\u52a8\u515c\u5e95" : "";
    return `
      <button
        class="${item.symbol === addInstrumentState.selectedInstrument?.symbol ? "selected" : ""}"
        type="button"
        data-search-symbol="${escapeHtml(item.symbol)}"
        ${alreadyInTargetGroup ? "disabled" : ""}
      >
        <strong>${escapeHtml(item.symbol)}</strong>
        <span>${escapeHtml(item.name || item.symbol)}</span>
        <em>${escapeHtml(instrumentTypeLabelFromType(item.type))}${suffix}</em>
      </button>
    `;
  }).join("");
}
function AddInstrumentPanel() {
  const selected = selectedAddInstrument();
  const isStrategy = addInstrumentState.usage === "strategy";
  const isRestoringBaselineStrategy = selected && isBaselineStrategySymbol(selected.symbol);
  const canPersist = assetPoolCapabilities.persistConfig;
  const alreadyInTargetGroup = selectedInstrumentAlreadyInTargetGroup(selected);
  const targetGroup = assetPoolGroups.find((group) => group.id === addInstrumentState.groupId);
  const targetGroupFull = Boolean(targetGroup && targetGroup.symbols.length >= MAX_ASSET_POOL_GROUP_SYMBOLS && !alreadyInTargetGroup);
  const canSubmit = Boolean(selected && !alreadyInTargetGroup && !targetGroupFull && canPersist && (!isStrategy || isRestoringBaselineStrategy) && !addInstrumentState.isSaving);
  return `
    <section class="add-instrument-panel">
      <div class="add-info-note">品种搜索使用 Yahoo 行情做真实代码校验；资产池配置会保存到本机 asset_pool.json。纳入策略仍需草稿、验证回测与发布流程，当前暂不允许直接提交。</div>
      <label class="add-search">
        <span>\u641c\u7d22\u54c1\u79cd</span>
        <div class="add-search-row">
          <input id="addInstrumentSearch" type="search" placeholder="\u8f93\u5165\u4ee3\u7801\u6216\u540d\u79f0\uff0c\u4f8b\u5982 AAPL\u3001TLT" value="${escapeHtml(addInstrumentState.query)}">
          <button class="asset-secondary-button add-search-button" type="button" data-search-submit ${addInstrumentState.query.trim() ? "" : "disabled"}>\u641c\u7d22</button>
        </div>
      </label>
      <div class="instrument-search-results">
        ${searchStatusContent()}
      </div>
      <div class="selected-instrument">
        <span>已选择：</span>
        <strong>${selected ? `${selected.symbol} · ${selected.name || selected.symbol}` : "未选择"}</strong>
        <button type="button" data-clear-search-symbol ${selected ? "" : "disabled"}>×</button>
      </div>
      <div class="add-form-grid">
        <label>
          <span>所属分组</span>
          <select data-add-field="groupId">
            ${assetPoolGroups.map((group) => `<option value="${group.id}" ${group.id === addInstrumentState.groupId ? "selected" : ""}>${group.name}</option>`).join("")}
          </select>
        </label>
        <button class="new-group-button" type="button" data-create-group>+ \u65b0\u5efa\u5206\u7ec4</button>
        <div class="usage-selector">
          <span>用途</span>
          ${[
            ["watch_only", "仅观察", false],
            ["signal_monitoring", "信号监控", false],
            ["strategy", "纳入策略", true],
          ].map(([value, label, disabled]) => `
            <button class="${addInstrumentState.usage === value ? "active" : ""}" type="button" data-add-usage="${value}" ${disabled ? "disabled title=\"暂未接入策略草稿、验证回测与发布流程\"" : ""}>${label}</button>
          `).join("")}
        </div>
        <label>
          <span>系统角色</span>
          <select data-add-field="role">
            ${instrumentRoleOptions.map(([value, label]) => `<option value="${value}" ${value === addInstrumentState.role ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </label>
      </div>
      <div class="add-switch-list">
        ${AddSwitch("showInOverview", "是否显示在总览")}
        ${AddSwitch("includeInMonitoring", "是否加入监控")}
        ${AddSwitch("includeInBacktest", "是否参与回测")}
      </div>
      <div class="${isStrategy ? "strategy-risk-note" : "add-info-note"}">
        ${isStrategy
          ? "纳入策略可能影响组合分析、动作建议与回测结果；当前缺少正式发布流程，因此不能直接保存为策略品种。"
          : "观察或信号监控品种只影响资产池展示与监控入口，不会改变正式交易规则或策略仓位目标。"}
      </div>
      ${addInstrumentState.saveError ? `<div class="preview-note">${escapeHtml(addInstrumentState.saveError)}</div>` : ""}
      <div class="add-panel-actions">
        <button class="asset-secondary-button" type="button" data-add-cancel>取消</button>
        <button class="asset-primary-button" type="button" data-add-submit ${canSubmit ? "" : "disabled"}>${addInstrumentState.isSaving ? "\u4fdd\u5b58\u4e2d..." : "\u6dfb\u52a0\u54c1\u79cd"}</button>
      </div>
    </section>
  `;
}

function AddSwitch(key, label) {
  return `
    <label class="add-switch">
      <span>${escapeHtml(label)}</span>
      <input type="checkbox" data-add-switch="${key}" ${addInstrumentState[key] ? "checked" : ""}>
      <i>${addInstrumentState[key] ? "开启" : "关闭"}</i>
    </label>
  `;
}

function assetPoolItemForSymbol(symbol) {
  if (!lastSnapshot?.symbols) return null;
  const items = buildAssetPoolItems(lastSnapshot.symbols);
  return items.find((item) => item.symbol === symbol && item.groupId === selectedGroupId)
    || items.find((item) => item.symbol === symbol)
    || null;
}

function defaultPoolItemFromSnapshot(symbol) {
  const raw = lastSnapshot?.symbols?.find((item) => item.symbol === symbol);
  if (!raw) return null;
  const override = assetPoolConfig.instruments?.[symbol];
  const state = getSystemState(raw);
  const usage = ["watch_only", "signal_monitoring", "strategy"].includes(override?.usage)
    ? override.usage
    : instrumentUsage(raw);
  const group = assetPoolGroups.find((candidate) => candidate.id === override?.groupId) || groupForSymbol(raw.symbol);
  const roleKey = override?.role || portfolioRoles[raw.symbol]?.key || (raw.role === "stock" ? "single_stock_watch" : raw.role) || "custom";
  const roleOption = instrumentRoleOptions.find(([value]) => value === roleKey);
  return {
    raw,
    id: raw.symbol,
    symbol: raw.symbol,
    name: etfDescriptions[raw.symbol] || raw.symbol,
    type: instrumentType(raw),
    typeLabel: instrumentTypeLabel(raw),
    groupId: group.id,
    groupName: group.name,
    usage,
    usageLabel: instrumentUsageLabels[usage],
    roleKey,
    roleLabel: roleOption?.[1] || portfolioRoles[raw.symbol]?.label || roleLabels[raw.role] || raw.role,
    state,
    keyPrompt: getKeyPrompt(raw),
    displayAction: usage === "strategy" ? actionBase(raw.action) : usage === "signal_monitoring" ? "WATCH" : "—",
    showInOverview: override?.showInOverview ?? true,
    includeInMonitoring: override?.includeInMonitoring ?? usage !== "watch_only",
    includeInBacktest: override?.includeInBacktest ?? usage === "strategy",
  };
}

function nextAssetPoolConfigForSymbol(symbol, patch) {
  return {
    version: assetPoolConfig.version || 1,
    groups: normalizeAssetPoolGroups(assetPoolConfig),
    instruments: {
      ...(assetPoolConfig.instruments || {}),
      [symbol]: {
        ...(assetPoolConfig.instruments?.[symbol] || {}),
        ...patch,
        updatedAt: new Date().toISOString(),
      },
    },
  };
}

async function persistAssetPoolConfig(nextConfig) {
  if (!assetPoolCapabilities.persistConfig) {
    setNotice("资产池保存接口暂未接入。");
    return false;
  }
  try {
    const response = await fetch("/api/asset-pool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: nextConfig }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "资产池配置保存失败");
    }
    assetPoolConfig = payload.config || nextConfig;
    assetPoolGroups = normalizeAssetPoolGroups(assetPoolConfig);
    assetPoolCapabilities = {
      ...assetPoolCapabilities,
      ...(payload.capabilities || {}),
    };
    setNotice("");
    return true;
  } catch (error) {
    setNotice(`资产池配置保存失败：${error.message}`);
    return false;
  }
}

function nextManualHoldingsConfigForSymbol(symbol, entry) {
  const normalized = String(symbol || "").toUpperCase();
  const holdings = { ...(manualHoldingsConfig.holdings || {}) };
  if (!entry || !entry.quantity || entry.quantity <= 0) {
    delete holdings[normalized];
  } else {
    holdings[normalized] = {
      symbol: normalized,
      quantity: Number(entry.quantity),
      avgCostUsdt: entry.avgCostUsdt === null || entry.avgCostUsdt === undefined || entry.avgCostUsdt === ""
        ? undefined
        : Number(entry.avgCostUsdt),
      note: entry.note || "",
      updatedAt: new Date().toISOString(),
    };
  }
  return {
    version: manualHoldingsConfig.version || 1,
    holdings,
  };
}

async function persistManualHoldingsConfig(nextConfig) {
  if (!manualHoldingsCapabilities.persistConfig) {
    setNotice("手动持仓保存接口暂未接入。");
    return false;
  }
  try {
    const response = await fetch("/api/manual-holdings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: nextConfig }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "手动持仓保存失败");
    }
    manualHoldingsConfig = payload.config || nextConfig;
    manualHoldingsCapabilities = {
      ...manualHoldingsCapabilities,
      ...(payload.capabilities || {}),
    };
    setNotice("");
    return true;
  } catch (error) {
    setNotice(`手动持仓保存失败：${error.message}`);
    return false;
  }
}

async function createAssetPoolGroup() {
  if (!assetPoolCapabilities.persistConfig) {
    setNotice("资产池保存接口暂未接入。");
    return;
  }
  if (assetPoolGroups.length >= MAX_ASSET_POOL_GROUPS) {
    setNotice("分组数量已达到 10 个上限。");
    return;
  }
  const name = window.prompt("请输入新分组名称（最多 40 个字）");
  if (!name || !name.trim()) return;
  let id = normalizeGroupId(name);
  const existing = new Set(assetPoolGroups.map((group) => group.id));
  const baseId = id;
  let suffix = 2;
  while (existing.has(id)) {
    id = `${baseId}_${suffix}`;
    suffix += 1;
  }
  const nextConfig = {
    ...assetPoolConfig,
    version: assetPoolConfig.version || 1,
    groups: [...normalizeAssetPoolGroups(assetPoolConfig), { id, name: name.trim().slice(0, 40), symbols: [] }],
    instruments: assetPoolConfig.instruments || {},
  };
  const saved = await persistAssetPoolConfig(nextConfig);
  if (saved) {
    addInstrumentState.groupId = id;
    collapsedAssetGroups[id] = false;
    render(lastSnapshot);
  }
}

async function deleteAssetPoolGroup(groupId) {
  const group = assetPoolGroups.find((item) => item.id === groupId);
  if (!group || assetPoolGroups.length <= 1) return;
  const ok = window.confirm(`删除分组「${group.name}」？\n\n这只会移除资产池分组，不会删除历史行情或历史信号。`);
  if (!ok) return;
  const remainingGroups = normalizeAssetPoolGroups(assetPoolConfig).filter((item) => item.id !== groupId);
  const fallbackGroupId = remainingGroups[0]?.id || "core_strategy";
  const nextInstruments = { ...(assetPoolConfig.instruments || {}) };
  Object.entries(nextInstruments).forEach(([symbol, entry]) => {
    if (entry?.groupId === groupId) {
      nextInstruments[symbol] = { ...entry, groupId: fallbackGroupId, updatedAt: new Date().toISOString() };
    }
  });
  const nextConfig = {
    ...assetPoolConfig,
    version: assetPoolConfig.version || 1,
    groups: remainingGroups,
    instruments: nextInstruments,
  };
  const saved = await persistAssetPoolConfig(nextConfig);
  if (saved) {
    if (selectedGroupId === groupId) selectedGroupId = fallbackGroupId;
    if (addInstrumentState.groupId === groupId) addInstrumentState.groupId = fallbackGroupId;
    delete collapsedAssetGroups[groupId];
    render(lastSnapshot);
  }
}

async function testBinanceConnection() {
  binanceLoading = true;
  binanceError = "";
  render(lastSnapshot);
  try {
    const response = await fetch("/api/integrations/binance/test-connection", {
      method: "POST",
      cache: "no-store",
    });
    const payload = await response.json();
    if (!payload.ok) {
      binanceStatus = { ...binanceStatus, ...(payload.status || {}) };
      throw new Error(payload.error || "Binance 连接测试失败");
    }
    binanceStatus = {
      ...binanceStatus,
      configured: true,
      connected: true,
      lastSyncedAt: payload.result?.checkedAt || null,
    };
    binanceError = "";
  } catch (error) {
    binanceError = error.message;
  } finally {
    binanceLoading = false;
    render(lastSnapshot);
  }
}

async function refreshBinanceAccount() {
  binanceLoading = true;
  binanceError = "";
  render(lastSnapshot);
  try {
    const response = await fetch("/api/integrations/binance/refresh", {
      method: "POST",
      cache: "no-store",
    });
    const payload = await response.json();
    if (!payload.ok) {
      binanceStatus = { ...binanceStatus, ...(payload.status || {}) };
      binanceAccount = null;
      throw new Error(payload.error || "Binance Spot 账户读取失败");
    }
    binanceAccount = payload.account;
    binanceStatus = {
      ...binanceStatus,
      configured: true,
      connected: true,
      lastSyncedAt: payload.account?.lastSyncedAt || null,
    };
  } catch (error) {
    binanceError = error.message;
  } finally {
    binanceLoading = false;
    render(lastSnapshot);
  }
}

async function loadBinanceAccountQuietly() {
  if (!binanceStatus.configured) {
    binanceAccount = null;
    return;
  }
  try {
    const response = await fetch("/api/integrations/binance/spot-account", { cache: "no-store" });
    const payload = await response.json();
    if (!payload.ok) {
      if (!binanceAccount) binanceAccount = null;
      binanceError = payload.error || "";
      return;
    }
    binanceAccount = payload.account;
    binanceStatus = {
      ...binanceStatus,
      configured: true,
      connected: true,
      lastSyncedAt: payload.account?.lastSyncedAt || binanceStatus.lastSyncedAt || null,
    };
    binanceError = "";
  } catch (error) {
    if (!binanceAccount) binanceAccount = null;
    binanceError = error.message;
  }
}

function scheduleInstrumentSearch() {
  runInstrumentSearchNow();
}

function runInstrumentSearchNow() {
  clearTimeout(addSearchTimer);
  const query = addInstrumentState.query.trim();
  addInstrumentState.selectedInstrument = null;
  addInstrumentState.saveError = "";
  if (!query) {
    addInstrumentState.results = [];
    addInstrumentState.searchStatus = "idle";
    addInstrumentState.searchError = "";
    render(lastSnapshot);
    return;
  }
  addInstrumentState.searchStatus = "loading";
  addInstrumentState.searchError = "";
  addInstrumentState.results = [];
  render(lastSnapshot);
  searchInstrument(query);
}

async function searchInstrument(query) {
  const requestId = ++addSearchRequestId;
  try {
    const response = await fetch(`/api/instrument-search?q=${encodeURIComponent(query)}`, { cache: "no-store" });
    const payload = await response.json();
    if (requestId !== addSearchRequestId) return;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "品种搜索失败");
    }
    addInstrumentState.results = payload.results || [];
    addInstrumentState.searchStatus = addInstrumentState.results.length ? "ready" : "empty";
    addInstrumentState.searchError = payload.error || "";
  } catch (error) {
    if (requestId !== addSearchRequestId) return;
    addInstrumentState.results = [];
    addInstrumentState.searchStatus = "error";
    addInstrumentState.searchError = error.message;
  }
  if (rightRailMode === "add" && lastSnapshot) render(lastSnapshot);
}

function resetAddInstrumentState() {
  addInstrumentState = {
    query: "",
    selectedInstrument: null,
    results: [],
    searchStatus: "idle",
    searchError: "",
    isSaving: false,
    saveError: "",
    groupId: "stock_watchlist",
    usage: "signal_monitoring",
    role: "single_stock_watch",
    showInOverview: true,
    includeInMonitoring: true,
    includeInBacktest: false,
  };
}

function currentInstrumentMetadata(symbol) {
  const item = lastSnapshot?.symbols?.find((entry) => entry.symbol === symbol);
  if (!item) return {};
  return {
    name: etfDescriptions[symbol] || symbol,
    instrumentType: instrumentType(item),
  };
}

async function submitAddedInstrument() {
  const selected = selectedAddInstrument();
  if (!selected) {
    addInstrumentState.saveError = "请先选择一个已校验的品种。";
    render(lastSnapshot);
    return;
  }
  if (selectedInstrumentAlreadyInTargetGroup(selected)) {
    addInstrumentState.saveError = "\u8be5\u54c1\u79cd\u5df2\u5728\u5f53\u524d\u5206\u7ec4\u4e2d\u3002";
    render(lastSnapshot);
    return;
  }
  const targetGroup = assetPoolGroups.find((group) => group.id === addInstrumentState.groupId);
  if (targetGroup && targetGroup.symbols.length >= MAX_ASSET_POOL_GROUP_SYMBOLS) {
    addInstrumentState.saveError = "\u8be5\u5206\u7ec4\u5df2\u8fbe\u5230 30 \u4e2a\u54c1\u79cd\u4e0a\u9650\u3002";
    render(lastSnapshot);
    return;
  }
  if (addInstrumentState.usage === "strategy" && !isBaselineStrategySymbol(selected.symbol)) {
    addInstrumentState.saveError = "新纳入策略需要草稿、验证回测与发布流程，当前暂不能直接保存。";
    render(lastSnapshot);
    return;
  }
  if (!assetPoolCapabilities.persistConfig) {
    addInstrumentState.saveError = "尚未接入资产池配置保存能力。";
    render(lastSnapshot);
    return;
  }

  addInstrumentState.isSaving = true;
  addInstrumentState.saveError = "";
  render(lastSnapshot);

  const symbol = selected.symbol.toUpperCase();
  const existingMetadata = currentInstrumentMetadata(symbol);
  const existingEntry = assetPoolConfig.instruments?.[symbol] || {};
  const nextConfig = nextAssetPoolConfigForSymbol(symbol, {
    symbol,
    name: selected.name || existingMetadata.name || symbol,
    instrumentType: selected.instrumentType || selected.type || existingMetadata.instrumentType || "",
    type: selected.type || existingMetadata.instrumentType || "",
    exchange: selected.exchange || "",
    currency: selected.currency || "",
    groupId: addInstrumentState.groupId,
    usage: addInstrumentState.usage,
    role: addInstrumentState.role,
    showInOverview: addInstrumentState.showInOverview,
    includeInMonitoring: addInstrumentState.includeInMonitoring,
    includeInBacktest: addInstrumentState.includeInBacktest,
    removed: false,
    createdAt: existingEntry.createdAt || new Date().toISOString(),
  });
  nextConfig.groups = withSymbolInGroup(normalizeAssetPoolGroups(nextConfig), addInstrumentState.groupId, symbol);
  const saved = await persistAssetPoolConfig(nextConfig);
  addInstrumentState.isSaving = false;
  if (saved) {
    selectedSymbol = symbol;
    selectedGroupId = addInstrumentState.groupId;
    rightRailMode = "detail";
    resetAddInstrumentState();
    await refresh();
    return;
  }
  addInstrumentState.saveError = "保存失败，请查看顶部错误提示。";
  render(lastSnapshot);
}

function defaultEditState(poolItem, overrides = {}) {
  return {
    symbol: poolItem.symbol,
    groupId: poolItem.groupId,
    usage: poolItem.usage,
    role: poolItem.roleKey,
    showInOverview: poolItem.showInOverview,
    includeInMonitoring: poolItem.includeInMonitoring,
    includeInBacktest: poolItem.includeInBacktest,
    ...overrides,
  };
}

function isDirectStrategyPromotion(poolItem) {
  return poolItem?.usage !== "strategy" && editInstrumentState?.usage === "strategy";
}

function beginEditInstrument(symbol, overrides = {}) {
  const poolItem = assetPoolItemForSymbol(symbol);
  if (!poolItem) return;
  selectedSymbol = symbol;
  selectedGroupId = poolItem.groupId || selectedGroupId;
  closeInstrumentRowMenu();
  editInstrumentState = defaultEditState(poolItem, overrides);
  if (editInstrumentState.usage === "watch_only") {
    editInstrumentState.includeInMonitoring = false;
    editInstrumentState.includeInBacktest = false;
  }
  if (editInstrumentState.usage === "signal_monitoring") {
    editInstrumentState.includeInMonitoring = true;
    editInstrumentState.includeInBacktest = false;
  }
  if (editInstrumentState.usage === "strategy") {
    editInstrumentState.includeInMonitoring = true;
  }
  rightRailMode = "edit";
  render(lastSnapshot);
}

function EditInstrumentPanel(poolItem) {
  if (!poolItem) return `<div class="empty-detail">请选择一个品种进行配置</div>`;
  if (!editInstrumentState || editInstrumentState.symbol !== poolItem.symbol) {
    editInstrumentState = defaultEditState(poolItem);
  }
  const selectedRole = instrumentRoleOptions.some(([value]) => value === editInstrumentState.role)
    ? editInstrumentState.role
    : "custom";
  const strategyPromotionBlocked = isDirectStrategyPromotion(poolItem);
  return `
    <section class="edit-instrument-panel">
      <div class="edit-panel-heading">
        <span>编辑品种配置</span>
        <h2>${escapeHtml(poolItem.symbol)} · ${escapeHtml(poolItem.name)}</h2>
        <p>Development preview：当前表单仅用于配置预览，尚未接入资产池持久化保存。</p>
      </div>

      <div class="edit-form-grid">
        <label>
          <span>所属分组</span>
          <select data-edit-field="groupId">
            ${assetPoolGroups.map((group) => `<option value="${group.id}" ${group.id === editInstrumentState.groupId ? "selected" : ""}>${group.name}</option>`).join("")}
          </select>
        </label>

        <div class="usage-selector edit-usage-selector">
          <span>用途</span>
          ${[
            ["watch_only", "仅观察"],
            ["signal_monitoring", "信号监控"],
            ["strategy", "纳入策略"],
          ].map(([value, label]) => `
            <button class="${editInstrumentState.usage === value ? "active" : ""}" type="button" data-edit-usage="${value}">${label}</button>
          `).join("")}
        </div>

        <label>
          <span>系统角色</span>
          <select data-edit-field="role">
            ${instrumentRoleOptions.map(([value, label]) => `<option value="${value}" ${value === selectedRole ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </label>
      </div>

      <div class="add-switch-list">
        ${EditSwitch("showInOverview", "是否显示在总览")}
        ${EditSwitch("includeInMonitoring", "是否加入监控")}
        ${EditSwitch("includeInBacktest", "是否参与回测")}
      </div>

      <div class="${editInstrumentState.usage === "strategy" ? "strategy-risk-note" : "add-info-note"}">
        ${editInstrumentState.usage === "strategy"
          ? "纳入策略会影响动作建议、组合分析和后续回测范围。当前缺少草稿、验证回测与发布流程，因此不能直接保存为正式配置。"
          : "观察/监控用途只作为前端资产池配置预览，不会改变当前策略计算或交易动作。"}
      </div>

      <div class="add-panel-actions">
        <button class="asset-secondary-button" type="button" data-edit-cancel>取消</button>
        <button class="asset-primary-button" type="button" data-edit-save ${assetPoolCapabilities.persistConfig && !strategyPromotionBlocked ? "" : "disabled title=\"纳入策略需接入发布流程；或当前无保存能力\""}>保存修改</button>
      </div>

      <div class="danger-zone">
        <h3>危险操作</h3>
        <p>移出资产池不会删除历史行情、历史信号或历史回测记录。</p>
        <button type="button" data-edit-remove="${escapeHtml(poolItem.symbol)}">移出资产池</button>
      </div>
    </section>
  `;
}

function EditSwitch(key, label) {
  return `
    <label class="add-switch">
      <span>${escapeHtml(label)}</span>
      <input type="checkbox" data-edit-switch="${key}" ${editInstrumentState[key] ? "checked" : ""}>
      <i>${editInstrumentState[key] ? "开启" : "关闭"}</i>
    </label>
  `;
}

function RemoveInstrumentConfirmDialog(poolItem) {
  if (!poolItem) return "";
  const isStrategy = poolItem.usage === "strategy";
  const canRemove = assetPoolCapabilities.removeInstrument;
  return `
    <div class="modal-backdrop" data-remove-backdrop>
      <section class="remove-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="removeTitle">
        <h2 id="removeTitle">移出 ${escapeHtml(poolItem.symbol)}？</h2>
        ${isStrategy ? `
          <p>${escapeHtml(poolItem.symbol)} 当前属于核心策略资产。移出后可能影响：</p>
          <ul>
            <li>组合分析</li>
            <li>动作建议</li>
            <li>监控规则</li>
            <li>后续回测范围</li>
          </ul>
          <p>已有历史数据不会被删除。</p>
        ` : `
          <p>${escapeHtml(poolItem.symbol)} 将从当前资产池中移除，不再出现在总览与监控列表中。</p>
          <p>已有历史行情与历史信号记录不会被删除。</p>
        `}
        <div class="preview-note">${canRemove
          ? "确认后只会从资产池配置中移出该品种，不会删除历史行情、历史信号或修改核心策略计算。"
          : "当前尚未接入资产池移出/保存接口，因此不会执行真实移出操作。"}</div>
        <div class="remove-dialog-actions">
          <button class="asset-secondary-button" type="button" data-remove-cancel>取消</button>
          <button class="danger-button" type="button" data-remove-confirm="${escapeHtml(poolItem.symbol)}" ${canRemove ? "" : "disabled title=\"暂未接入真实移出接口\""}>${isStrategy ? "继续移出" : "确认移出"}</button>
        </div>
      </section>
    </div>
  `;
}

function buildSignalText(poolItem) {
  const item = poolItem.raw;
  const action = actionBase(item.action);
  const prompt = poolItem.keyPrompt;
  if (poolItem.usage !== "strategy") {
    return `${item.symbol} 当前作为${poolItem.usageLabel}品种，仅展示趋势、动量与风险状态，不生成正式交易动作。`;
  }
  if (item.role === "cash") return "当前作为现金停泊位，用于等待更明确的风险资产机会。";
  if (poolItem.state.className === "damaged") return `当前存在风险信号：${prompt}，应优先按规则控制仓位。`;
  if (action === "BUY") return `${item.symbol} 当前趋势与结构较好，系统给出限价买入动作。`;
  if (action === "SELL") return `${item.symbol} 当前目标仓位下降，系统给出限价卖出动作。`;
  return `${item.symbol} 当前无需主动交易，重点观察：${prompt}。`;
}

function buildSignalEvents(items, snapshot) {
  const bySymbol = new Map(items.map((item) => [item.symbol, item]));
  const events = [];
  const snapshotTime = formatSnapshotLabel(snapshot);

  items.forEach((item) => {
    const notes = item.notes || [];
    const risks = item.risk_reasons || [];
    const shortTerm = item.short_term || null;
    const accountPosition = AccountPositionForSignalItem(item);

    if (shortTerm?.sell_signal && accountPosition) {
      const reasonText = shortTerm.sell_reasons?.[0] || "短线风控触发";
      events.push(createSignalEvent(item, {
        type: "short_sell",
        content: reasonText,
        title: "建议卖出",
        status: "warning",
        importance: "high",
        occurredAt: snapshotTime,
        shortTerm,
        accountPosition,
      }));
    }

    if (shortTerm?.buy_signal && item.role !== "cash" && !accountPosition) {
      const triggerText = shortTermTriggerLabel(shortTerm);
      events.push(createSignalEvent(item, {
        type: "short_buy",
        content: `${triggerText}，2-14 天短线机会`,
        title: "建议买入",
        status: "new",
        importance: Number(shortTerm.risk_reward || 0) >= 2 ? "high" : "medium",
        occurredAt: snapshotTime,
        shortTerm,
      }));
    }

    if (risks.length > 0) {
      const content = risks.includes("close_below_sma200")
        ? "跌破 SMA200"
        : labelFor(risks[0], riskLabels);
      events.push(createSignalEvent(item, {
        type: "risk",
        content,
        title: content,
        status: "warning",
        importance: "high",
        occurredAt: snapshotTime,
      }));
      return;
    }

    if (notes.includes("breakout_hold")) {
      events.push(createSignalEvent(item, {
        type: "breakout",
        content: "突破结构确认",
        title: "突破结构确认",
        status: "confirmed",
        importance: actionBase(item.action) === "BUY" ? "high" : "medium",
        occurredAt: snapshotTime,
      }));
      return;
    }

    if (notes.includes("near_resistance")) {
      events.push(createSignalEvent(item, {
        type: "resistance",
        content: "接近关键阻力",
        title: "接近关键阻力",
        status: "new",
        importance: "medium",
        occurredAt: snapshotTime,
      }));
      return;
    }

    if (notes.includes("near_support")) {
      events.push(createSignalEvent(item, {
        type: "support",
        content: "接近支撑区域",
        title: "接近支撑区域",
        status: "pending",
        importance: "medium",
        occurredAt: snapshotTime,
      }));
      return;
    }

    if (notes.includes("higher_high_higher_low")) {
      events.push(createSignalEvent(item, {
        type: "trend",
        content: "高低点抬升",
        title: "高低点抬升",
        status: item.trend_ok ? "confirmed" : "pending",
        importance: "medium",
        occurredAt: snapshotTime,
      }));
    }
  });

  const momentumLeader = [...items]
    .filter((item) => item.role !== "cash" && Number.isFinite(item.momentum_126_pct))
    .sort((a, b) => (b.momentum_126_pct || 0) - (a.momentum_126_pct || 0))[0];

  if (momentumLeader && !events.some((event) => event.etf === momentumLeader.symbol && event.type === "momentum")) {
    events.push(createSignalEvent(momentumLeader, {
      type: "momentum",
      content: "126D 动量当前领先",
      title: "126D 动量当前领先",
      status: momentumLeader.momentum_126_pct > 0 ? "confirmed" : "pending",
      importance: "medium",
      occurredAt: snapshotTime,
    }));
  }

  return events
    .map((event, index) => ({ ...event, order: index, source: "current_snapshot", relatedAsset: bySymbol.get(event.etf) }))
    .sort((a, b) => importanceRank(b.importance) - importanceRank(a.importance) || a.order - b.order);
}

function createSignalEvent(item, details) {
  const riskStatus = item.risk_reasons?.length
    ? item.risk_reasons.map((risk) => labelFor(risk, riskLabels)).join("、")
    : "无";
  return {
    id: `${item.symbol}-${details.type}-${details.status}`,
    etf: item.symbol,
    action: actionBase(item.action),
    assetDescription: etfDescriptions[item.symbol] || roleLabels[item.role] || item.role,
    trendStatus: item.trend_ok ? "通过" : "未通过",
    momentum126d: item.momentum_126_pct,
    riskStatus,
    explanation: buildSignalEventExplanation(item, details),
    timeline: [],
    ...details,
  };
}

function buildSignalEventExplanation(item, details) {
  if (details.type === "short_buy") {
    return `${item.symbol} 满足 ${shortTermTriggerLabel(details.shortTerm)} 的 2-14 天短线买入条件；入场、止损、止盈和 R/R 见下方短线交易计划。`;
  }
  if (details.type === "short_sell") {
    const reasonText = details.shortTerm?.sell_reasons?.join("、") || details.content;
    return `${item.symbol} 当前持仓触发短线风控：${reasonText}。该提示仅用于持仓风险处理，不代表自动下单。`;
  }
  if (details.type === "risk") {
    return `${item.symbol} 当前风险状态为${details.content}，趋势过滤${item.trend_ok ? "仍通过" : "未通过"}。`;
  }
  if (details.type === "breakout") {
    return `${item.symbol} 当前结构状态为${details.content}，趋势过滤${item.trend_ok ? "已通过" : "未通过"}。`;
  }
  if (details.type === "support" || details.type === "resistance") {
    return `${item.symbol} 当前价格行为提示为${details.content}，用于辅助判断买卖位置。`;
  }
  if (details.type === "momentum") {
    return `${item.symbol} 当前 126D 动量为 ${pct(item.momentum_126_pct, { sign: true })}。`;
  }
  return `${item.symbol} 当前信号为${details.content}。`;
}

function importanceRank(value) {
  if (value === "high") return 3;
  if (value === "medium") return 2;
  return 1;
}

function AccountPositionForSignalItem(item) {
  const currentPrice = typeof item.current_price === "number" ? item.current_price : item.close;
  const position = AccountPositionForSymbol(item.symbol, currentPrice);
  return position && Number.isFinite(position.quantity) && position.quantity > 0 ? position : null;
}

function shortTermTriggerLabel(shortTerm) {
  if (shortTerm?.trigger === "pullback") return "回踩站稳";
  if (shortTerm?.trigger === "breakout") return "有效突破";
  return "短线条件";
}

function renderSignalPage(items, snapshot) {
  const allEvents = buildSignalEvents(items, snapshot);
  renderSignalSummary(allEvents);
  const filteredEvents = filterSignalEvents(allEvents);
  const defaultEvent = filteredEvents[0] || allEvents[0] || null;

  if (!selectedSignalId || !allEvents.some((event) => event.id === selectedSignalId)) {
    selectedSignalId = defaultEvent?.id || null;
  }
  if (filteredEvents.length && !filteredEvents.some((event) => event.id === selectedSignalId)) {
    selectedSignalId = filteredEvents[0].id;
  }

  const selectedEvent = allEvents.find((event) => event.id === selectedSignalId) || filteredEvents[0] || null;

  document.getElementById("routeContent").innerHTML = `
    <section class="signal-filter-bar" aria-label="信号筛选">
      ${FilterSelect("range", "时间", ["今日", "近 7 日", "近 30 日", "全部"])}
      ${FilterSelect("etf", "ETF", ["全部", "QQQ", "SPY", "IWM", "GLD", "TLT", "SGOV"])}
      ${FilterSelect("type", "类型", ["全部", "建议买入", "建议卖出", "趋势", "突破", "支撑", "阻力", "动量", "风险"])}
      ${FilterSelect("status", "状态", ["全部", "新触发", "待确认", "已确认", "风险中", "已失效", "已解除"])}
      ${FilterSelect("importance", "重要性", ["全部", "高", "中", "低"])}
      <label class="filter-search">
        <span class="search-icon">⌕</span>
        <input id="signalSearch" type="search" placeholder="搜索 ETF / 信号" value="${escapeHtml(signalFilters.search)}">
      </label>
    </section>

    <section class="signal-layout">
      ${SignalEventsTable(filteredEvents)}
      ${SignalDetailPanel(selectedEvent)}
    </section>
  `;

  bindSignalEvents();
}

function FilterSelect(name, label, options) {
  const current = signalFilters[name];
  return `
    <label class="filter-field">
      <span>${label}：</span>
      <select data-filter="${name}">
        ${options.map((option) => `<option value="${option}" ${option === current ? "selected" : ""}>${option}</option>`).join("")}
      </select>
    </label>
  `;
}

function filterSignalEvents(events) {
  const search = signalFilters.search.trim().toLowerCase();
  return events.filter((event) => {
    const typeLabel = signalTypeLabels[event.type] || event.type;
    const statusLabel = signalStatusLabels[event.status] || event.status;
    const importanceLabel = signalImportanceLabels[event.importance] || event.importance;
    const matchesEtf = signalFilters.etf === "全部" || event.etf === signalFilters.etf;
    const matchesType = signalFilters.type === "全部" || typeLabel === signalFilters.type;
    const matchesStatus = signalFilters.status === "全部" || statusLabel === signalFilters.status;
    const matchesImportance = signalFilters.importance === "全部" || importanceLabel === signalFilters.importance;
    const matchesSearch = !search || `${event.etf} ${event.content} ${typeLabel}`.toLowerCase().includes(search);
    return matchesEtf && matchesType && matchesStatus && matchesImportance && matchesSearch;
  });
}

function SignalEventsTable(events) {
  const rows = events.map((event) => `
    <tr class="${event.id === selectedSignalId ? "selected" : ""}" data-signal-id="${escapeHtml(event.id)}" tabindex="0">
      <td>${escapeHtml(event.occurredAt)}</td>
      <td class="symbol-cell">${escapeHtml(event.etf)}</td>
      <td>${SignalTypeBadge(event.type)}</td>
      <td>${escapeHtml(event.content)}</td>
      <td>${SignalStatusBadge(event.status)}</td>
      <td>${ImportanceBadge(event.importance)}</td>
    </tr>
  `).join("");

  return `
    <section class="signal-card">
      <div class="signal-card-header">
        <div>
          <h2>信号事件列表</h2>
          <p>按时间倒序展示最新事件</p>
        </div>
        <span class="data-source-pill">当前快照派生</span>
      </div>
      <div class="signal-table-wrap">
        <table class="signal-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>ETF</th>
              <th>信号类型</th>
              <th>信号内容</th>
              <th>状态</th>
              <th>重要性</th>
            </tr>
          </thead>
          <tbody>
            ${rows || `<tr><td colspan="6"><div class="empty-state">当前筛选条件下暂无信号事件</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function SignalDetailPanel(event) {
  if (!event) {
    return `
      <aside class="signal-detail-panel">
        <div class="empty-detail">请选择一条信号查看详情</div>
      </aside>
    `;
  }

  return `
    <aside class="signal-detail-panel" aria-label="信号详情">
      <div class="signal-detail-header">
        <div>
          <h2>${escapeHtml(event.etf)} · ${escapeHtml(event.title)}</h2>
          <p>${escapeHtml(event.assetDescription)}</p>
        </div>
        ${SignalStatusBadge(event.status)}
      </div>
      <div class="signal-detail-action-row">
        ${event.action ? ActionBadge(event.action) : ""}
      </div>

      <dl class="signal-detail-list">
        <div><dt>信号类型</dt><dd>${escapeHtml(signalTypeLabels[event.type] || event.type)}</dd></div>
        <div><dt>当前阶段</dt><dd>${escapeHtml(signalStatusLabels[event.status] || event.status)}</dd></div>
        <div><dt>重要程度</dt><dd>${ImportanceBadge(event.importance)}</dd></div>
        <div><dt>当前趋势</dt><dd>${escapeHtml(event.trendStatus || "—")}</dd></div>
        <div><dt>126D 动量</dt><dd class="${changeClass(event.momentum126d)}">${pct(event.momentum126d, { sign: true })}</dd></div>
        <div><dt>风险状态</dt><dd>${escapeHtml(event.riskStatus || "无")}</dd></div>
      </dl>

      ${ShortTermSignalPlan(event)}

      <section class="signal-note">
        <span>信号说明</span>
        <p>${escapeHtml(event.explanation)}</p>
      </section>

      <section class="timeline-section">
        <h3>信号时间线</h3>
        ${SignalTimeline(event.timeline)}
      </section>
    </aside>
  `;
}

function ShortTermSignalPlan(event) {
  const shortTerm = event.shortTerm;
  if (!shortTerm) return "";
  const maxPositionText = shortTerm.account_equity_configured && Number.isFinite(shortTerm.max_position_value)
    ? formatUsdt(shortTerm.max_position_value)
    : "需配置账户净值后计算";
  const rejectText = shortTerm.reject_reasons?.length
    ? shortTerm.reject_reasons.slice(0, 3).join("、")
    : "当前短线条件通过";
  const sellReasonText = shortTerm.sell_reasons?.length
    ? shortTerm.sell_reasons.join("、")
    : "未触发持仓卖出条件";
  return `
    <section class="short-term-plan-card">
      <div class="short-term-plan-header">
        <div>
          <h3>2-14 天短线交易计划</h3>
          <p>${escapeHtml(shortTermTriggerLabel(shortTerm))} · ${escapeHtml(shortTerm.timeframe || "2-14D")} · 行业风险${escapeHtml(shortTerm.industry_risk_status === "not_connected" ? "未接入" : "已接入")}</p>
        </div>
        <span class="short-term-rr ${Number(shortTerm.risk_reward || 0) >= 1.8 ? "good" : "weak"}">R/R ${shortTerm.risk_reward === null || shortTerm.risk_reward === undefined ? "—" : fmt.format(shortTerm.risk_reward)}</span>
      </div>
      <dl class="short-term-plan-grid">
        <div><dt>参考入场</dt><dd>${price(shortTerm.entry_price)}</dd></div>
        <div><dt>止损位</dt><dd>${price(shortTerm.stop_price)}</dd></div>
        <div><dt>第一止盈</dt><dd>${price(shortTerm.target_price)}</dd></div>
        <div><dt>第二目标</dt><dd>${price(shortTerm.target2_price)}</dd></div>
        <div><dt>止损距离</dt><dd>${pct(shortTerm.stop_distance_pct)}</dd></div>
        <div><dt>仓位上限</dt><dd>${escapeHtml(maxPositionText)}</dd></div>
      </dl>
      <div class="short-term-plan-note">
        <span>${event.type === "short_sell" ? "卖出触发" : "买入校验"}</span>
        <p>${escapeHtml(event.type === "short_sell" ? sellReasonText : rejectText)}</p>
      </div>
      <div class="short-term-plan-note muted">
        <span>风控提示</span>
        <p>单笔风险按账户净值 ${pct(shortTerm.risk_per_trade_pct)} 估算；连续亏损 2-3 笔后建议降低仓位或暂停交易。</p>
      </div>
    </section>
  `;
}

function SignalTimeline(items) {
  if (!items?.length) {
    return `<div class="empty-state compact">暂无可用的信号历史记录</div>`;
  }

  return `
    <ol class="signal-timeline">
      ${items.map((item) => `
        <li class="${item.status || "confirmed"}">
          <time>${escapeHtml(item.time)}</time>
          <span>${escapeHtml(item.text)}</span>
        </li>
      `).join("")}
    </ol>
  `;
}

function MonitorStatusBadge(status) {
  return `<span class="monitor-status-badge ${status}">${monitorStatusLabels[status] || status}</span>`;
}

function AlertLevelBadge(severity) {
  return `<span class="alert-level-badge ${severity}">${alertSeverityLabels[severity] || severity}</span>`;
}

function getMonitorCurrentPrice(item) {
  return item.current_price ?? item.close;
}

function distanceToThresholdPct(item, thresholdValue, mode) {
  const current = getMonitorCurrentPrice(item);
  if (!Number.isFinite(current) || !Number.isFinite(thresholdValue) || thresholdValue <= 0) return null;
  if (mode === "above") return (current / thresholdValue - 1) * 100;
  if (mode === "below") return (thresholdValue / current - 1) * 100;
  return (current / thresholdValue - 1) * 100;
}

function formatThresholdDistance(value, status) {
  if (status === "triggered") return "已触发";
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${fmt.format(value)}%`;
}

function assetPoolOverrideFor(symbol) {
  return assetPoolConfig.instruments?.[symbol] || {};
}

function isMonitoringEnabledForSymbol(symbol) {
  const override = assetPoolOverrideFor(symbol);
  if (override.removed || override.showInOverview === false) return false;
  if (typeof override.includeInMonitoring === "boolean") return override.includeInMonitoring;
  const raw = lastSnapshot?.symbols?.find((item) => item.symbol === symbol);
  if (!raw) return true;
  return instrumentUsage(raw) !== "watch_only";
}

function buildMonitoringItems(items, snapshot) {
  const monitorItems = [];
  const snapshotLabel = formatSnapshotLabel(snapshot);

  items.forEach((item) => {
    if (!isMonitoringEnabledForSymbol(item.symbol)) return;
    const notes = item.notes || [];
    const risks = item.risk_reasons || [];

    if (risks.includes("close_below_sma200")) {
      monitorItems.push(createMonitoringItem(item, {
        category: "trend_risk",
        title: "SMA200 趋势风险",
        status: "triggered",
        conditionLabel: "跌破 SMA200",
        severity: "high",
        thresholdType: "SMA200",
        thresholdValue: item.sma200,
        thresholdMode: "above",
        relationText: "当前位于 SMA200 下方",
        latestChange: formatLatestChange(item, "当前触发"),
        handlingStatus: "未解除 / 持续监控",
        updatedAt: snapshotLabel,
      }));
      return;
    }

    if (risks.length > 0 || (!item.trend_ok && item.role !== "cash")) {
      const riskLabel = risks.length ? labelFor(risks[0], riskLabels) : "趋势未通过";
      monitorItems.push(createMonitoringItem(item, {
        category: "trend_risk",
        title: "趋势风险",
        status: "triggered",
        conditionLabel: riskLabel,
        severity: "high",
        thresholdType: riskLabel,
        thresholdValue: null,
        thresholdMode: "above",
        relationText: riskLabel,
        latestChange: formatLatestChange(item, "当前触发"),
        handlingStatus: "未解除 / 持续监控",
        updatedAt: snapshotLabel,
      }));
      return;
    }

    if (item.breakout_hold || notes.includes("breakout_hold")) {
      monitorItems.push(createMonitoringItem(item, {
        category: "breakout_hold",
        title: "突破保持",
        status: "normal",
        conditionLabel: "站稳突破区域",
        severity: "low",
        thresholdType: "突破参考位",
        thresholdValue: item.resistance,
        thresholdMode: "above",
        relationText: "当前维持在突破参考位上方",
        latestChange: "结构稳定",
        handlingStatus: "持续监控",
        updatedAt: snapshotLabel,
      }));
      return;
    }

    if (item.near_resistance || notes.includes("near_resistance")) {
      monitorItems.push(createMonitoringItem(item, {
        category: "resistance_watch",
        title: "阻力监控",
        status: "approaching",
        conditionLabel: "接近上方阻力",
        severity: "medium",
        thresholdType: "阻力位",
        thresholdValue: item.resistance,
        thresholdMode: "below",
        relationText: "当前接近上方阻力",
        latestChange: formatLatestChange(item, "观察阻力"),
        handlingStatus: "接近阈值 / 持续观察",
        updatedAt: snapshotLabel,
      }));
      return;
    }

    if (item.near_support || notes.includes("near_support")) {
      monitorItems.push(createMonitoringItem(item, {
        category: "support_watch",
        title: "支撑监控",
        status: "approaching",
        conditionLabel: "接近下方支撑",
        severity: "medium",
        thresholdType: "支撑位",
        thresholdValue: item.support,
        thresholdMode: "above",
        relationText: "当前接近下方支撑",
        latestChange: formatLatestChange(item, "观察支撑"),
        handlingStatus: "接近阈值 / 持续观察",
        updatedAt: snapshotLabel,
      }));
      return;
    }

  });

  const dailyErrors = snapshot.errors?.daily || {};
  const intradayErrors = snapshot.errors?.intraday || {};
  for (const [symbol, text] of [...Object.entries(dailyErrors), ...Object.entries(intradayErrors)]) {
    monitorItems.push({
      id: `${symbol}-data-error`,
      symbol,
      assetName: etfDescriptions[symbol] || "ETF",
      category: "data_issue",
      title: "数据异常",
      status: "data_error",
      conditionLabel: String(text),
      severity: "high",
      latestChange: "数据读取失败",
      currentPrice: null,
      momentum126d: null,
      thresholdType: "数据接口",
      thresholdValue: null,
      thresholdMode: "above",
      distanceToThresholdPct: null,
      relationText: "数据接口返回异常",
      handlingStatus: "等待下次刷新",
      updatedAt: snapshotLabel,
      timeline: [],
      source: null,
    });
  }

  return monitorItems.sort(compareMonitoringItems);
}

function createMonitoringItem(item, details) {
  const distance = distanceToThresholdPct(item, details.thresholdValue, details.thresholdMode);
  return {
    id: `${item.symbol}-${details.category}`,
    symbol: item.symbol,
    assetName: etfDescriptions[item.symbol] || roleLabels[item.role] || item.role,
    currentPrice: getMonitorCurrentPrice(item),
    momentum126d: item.momentum_126_pct,
    dayChangePct: item.day_change_pct,
    riskLabel: item.risk_reasons?.length ? item.risk_reasons.map((risk) => labelFor(risk, riskLabels)).join("、") : "无",
    distanceToThresholdPct: distance,
    timeline: [],
    source: item,
    ...details,
  };
}

function formatLatestChange(item, fallback) {
  if (Number.isFinite(item.day_change_pct)) return `今日 ${pct(item.day_change_pct, { sign: true })}`;
  return fallback;
}

function compareMonitoringItems(a, b) {
  const statusRank = { triggered: 5, data_error: 5, approaching: 4, pending: 3, normal: 2, resolved: 1 };
  const severityRank = { high: 3, medium: 2, low: 1 };
  return (statusRank[b.status] || 0) - (statusRank[a.status] || 0)
    || (severityRank[b.severity] || 0) - (severityRank[a.severity] || 0)
    || a.symbol.localeCompare(b.symbol);
}

function renderMonitoringSummary(items, snapshot, monitorItems) {
  const riskItems = monitorItems.filter((item) => item.status === "triggered" || item.status === "data_error");
  const nearItems = monitorItems.filter((item) => ["approaching", "triggered", "normal"].includes(item.status));
  const resistanceCount = monitorItems.filter((item) => item.category === "resistance_watch").length;
  const supportCount = monitorItems.filter((item) => item.category === "support_watch").length;
  const maCount = monitorItems.filter((item) => item.thresholdType === "SMA200").length;
  const errors = Object.keys(snapshot.errors?.daily || {}).length + Object.keys(snapshot.errors?.intraday || {}).length;
  const updated = formatTime(snapshot.generated_at);
  const monitorStatus = errors > 0 ? "部分异常" : "日频模式";
  const monitorTone = errors > 0 ? "amber" : "green";
  const dataStatus = errors > 0 ? "异常" : "已更新";
  const dataTone = errors > 0 ? "red" : "blue";
  const firstRisk = riskItems[0] ? `${riskItems[0].symbol} ${riskItems[0].conditionLabel}` : "当前无触发风险";

  const cards = [
    { label: "监控状态", value: monitorStatus, helper: errors > 0 ? "部分数据异常" : "收盘后日频监控", tone: monitorTone, icon: "monitor" },
    { label: "价格异动", value: "待接入", helper: "缺少波动规则", tone: "slate", icon: "volatility" },
    { label: "关键位接近", value: nearItems.length, helper: `阻力 ${resistanceCount} · 支撑 ${supportCount} · 均线 ${maCount}`, tone: nearItems.length ? "amber" : "green", icon: "target" },
    { label: "风险警报", value: riskItems.length, helper: firstRisk, tone: riskItems.length ? "red" : "green", icon: "risk" },
    { label: "数据状态", value: dataStatus, helper: `${updated} 更新`, tone: dataTone, icon: "data" },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderMonitorPage(items, snapshot) {
  const monitorItems = buildMonitoringItems(items, snapshot);
  renderMonitoringSummary(items, snapshot, monitorItems);

  if (!selectedMonitorId || !monitorItems.some((item) => item.id === selectedMonitorId)) {
    selectedMonitorId = monitorItems[0]?.id || null;
  }
  const selectedItem = monitorItems.find((item) => item.id === selectedMonitorId) || monitorItems[0] || null;

  document.getElementById("routeContent").innerHTML = `
    <section class="monitor-layout">
      <div class="monitor-main-column">
        ${MonitoringPriorityTable(monitorItems)}
        ${SystemRuntimeStatusCard(items, snapshot)}
      </div>
      ${MonitoringDetailPanel(selectedItem)}
    </section>
  `;

  bindMonitorEvents();
}

function MonitoringPriorityTable(items) {
  const rows = items.map((item) => `
    <tr class="${item.id === selectedMonitorId ? "selected" : ""}" data-monitor-id="${escapeHtml(item.id)}" tabindex="0">
      <td class="symbol-cell">${escapeHtml(item.symbol)}</td>
      <td>${escapeHtml(monitorCategoryLabels[item.category] || item.category)}</td>
      <td>${MonitorStatusBadge(item.status)}</td>
      <td>${escapeHtml(item.conditionLabel)}</td>
      <td>${escapeHtml(formatThresholdDistance(item.distanceToThresholdPct, item.status))}</td>
      <td>${AlertLevelBadge(item.severity)}</td>
      <td>${escapeHtml(item.latestChange || "—")}</td>
    </tr>
  `).join("");

  return `
    <section class="monitor-card">
      <div class="monitor-card-header">
        <div>
          <h2>重点监控列表</h2>
          <p>按风险优先级排序</p>
        </div>
      </div>
      <div class="monitor-table-wrap">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>ETF</th>
              <th>监控类别</th>
              <th>当前状态</th>
              <th>当前值 / 条件</th>
              <th>距离阈值</th>
              <th>等级</th>
              <th>最近变化</th>
            </tr>
          </thead>
          <tbody>
            ${rows || `<tr><td colspan="7"><div class="empty-state">当前没有需要重点关注的监控事项</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function SystemRuntimeStatusCard(items, snapshot) {
  const dailyErrors = snapshot.errors?.daily || {};
  const intradayErrors = snapshot.errors?.intraday || {};
  const errorEntries = [...Object.entries(dailyErrors), ...Object.entries(intradayErrors)];
  const rows = [
    { label: "行情数据刷新", value: `${items.length} 只 ETF 已返回`, tone: items.length ? "good" : "bad" },
    { label: "指标计算", value: snapshot.generated_at ? "本次快照已生成" : "未接入运行日志", tone: snapshot.generated_at ? "good" : "neutral" },
    { label: "信号生成", value: snapshot.symbols?.length ? "与信号快照同步" : "未接入运行日志", tone: snapshot.symbols?.length ? "good" : "neutral" },
    { label: "异常数据", value: errorEntries.length ? `${errorEntries.length} 项接口异常` : "未发现接口错误", tone: errorEntries.length ? "bad" : "good" },
    { label: "最近运行", value: formatTime(snapshot.generated_at), tone: "neutral" },
  ];

  return `
    <section class="monitor-card runtime-card">
      <div class="monitor-card-header compact">
        <h2>系统运行状态</h2>
      </div>
      <div class="runtime-list">
        ${rows.map((row) => `
          <div class="runtime-row">
            <span>${escapeHtml(row.label)}</span>
            <strong class="${row.tone}">${escapeHtml(row.value)}</strong>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function MonitoringDetailPanel(item) {
  if (!item) {
    return `
      <aside class="monitor-detail-panel">
        <div class="empty-detail">请选择一条监控事项查看详情</div>
      </aside>
    `;
  }

  return `
    <aside class="monitor-detail-panel" aria-label="监控详情">
      <div class="monitor-detail-header">
        <div>
          <h2>${escapeHtml(item.symbol)} · ${escapeHtml(item.title)}</h2>
          <p>${escapeHtml(item.assetName)}</p>
        </div>
        <div class="monitor-detail-badges">
          ${MonitorStatusBadge(item.status)}
          ${AlertLevelBadge(item.severity)}
        </div>
      </div>

      <dl class="monitor-detail-list">
        <div><dt>监控类别</dt><dd>${escapeHtml(monitorCategoryLabels[item.category] || item.category)}</dd></div>
        <div><dt>当前状态</dt><dd>${escapeHtml(monitorStatusLabels[item.status] || item.status)}</dd></div>
        <div><dt>当前价格</dt><dd>${price(item.currentPrice)}</dd></div>
        <div><dt>监控阈值</dt><dd>${escapeHtml(item.thresholdType || "—")}${Number.isFinite(item.thresholdValue) ? ` · ${price(item.thresholdValue)}` : ""}</dd></div>
        <div><dt>与阈值关系</dt><dd>${escapeHtml(item.relationText || "—")}</dd></div>
        <div><dt>126D 动量</dt><dd class="${changeClass(item.momentum126d)}">${pct(item.momentum126d, { sign: true })}</dd></div>
        <div><dt>最近变化</dt><dd class="${changeClass(item.dayChangePct)}">${escapeHtml(item.latestChange || "—")}</dd></div>
        <div><dt>处理状态</dt><dd>${escapeHtml(item.handlingStatus || "持续监控")}</dd></div>
      </dl>

      <section class="threshold-card">
        <div class="threshold-card-header">
          <h3>阈值关系图</h3>
          <span>${escapeHtml(item.thresholdType || "阈值")}</span>
        </div>
        ${ThresholdRelationChart(item)}
      </section>

      <section class="timeline-section monitor-timeline-section">
        <h3>监控记录</h3>
        ${MonitoringTimeline(item.timeline)}
      </section>
    </aside>
  `;
}

function ThresholdRelationChart(item) {
  return `
    <div class="empty-state compact">
      暂无可用的阈值历史数据
    </div>
  `;
}

function MonitoringTimeline(items) {
  if (!items?.length) {
    return `<div class="empty-state compact">暂无可用的监控历史记录</div>`;
  }
  return `
    <ol class="signal-timeline">
      ${items.map((item) => `
        <li class="${item.status || "pending"}">
          <time>${escapeHtml(item.time)}</time>
          <span>${escapeHtml(item.text)}</span>
        </li>
      `).join("")}
    </ol>
  `;
}

function buildBacktestModel(snapshot) {
  return {
    status: "not_run",
    statusLabel: "未运行",
    statusTone: "watch",
    updatedAt: snapshot?.generated_at || null,
    benchmarkSymbol: "SPY",
    frequency: "日频",
    startDate: null,
    endDate: null,
    transactionCostPct: null,
    slippagePct: null,
    includesDividends: null,
    executionConvention: null,
    summary: {},
    equityCurve: [],
    drawdownCurve: [],
    annualPerformance: [],
    trades: [],
    signalPerformance: [],
    robustness: [],
  };
}

function buildCurrentHoldingPerformanceModel(items) {
  const rawBySymbol = new Map((items || []).map((item) => [String(item.symbol || "").toUpperCase(), item]));
  const poolBySymbol = new Map();
  buildAssetPoolItems(items || []).forEach((item) => {
    if (!poolBySymbol.has(item.symbol)) poolBySymbol.set(item.symbol, item);
  });
  const symbols = new Set([
    ...poolBySymbol.keys(),
    ...Object.keys(manualHoldingsConfig.holdings || {}).map((symbol) => String(symbol).toUpperCase()),
    ...(binanceAccount?.assets || []).map((asset) => String(asset.asset || "").toUpperCase()),
  ]);

  const rows = [...symbols].sort().map((symbol) => {
    const raw = rawBySymbol.get(symbol);
    const asset = AccountAssetForSymbol(symbol);
    const rawPrice = raw?.current_price ?? raw?.close;
    const currentPrice = typeof rawPrice === "number"
      ? rawPrice
      : typeof asset?.priceUsdt === "number"
        ? asset.priceUsdt
        : null;
    const position = AccountPositionForSymbol(symbol, currentPrice);
    if (!position || !Number.isFinite(position.quantity) || position.quantity <= 0) return null;

    const poolItem = poolBySymbol.get(symbol) || defaultPoolItemFromSnapshot(symbol);
    const valueUsdt = Number.isFinite(position.valueUsdt)
      ? Number(position.valueUsdt)
      : currentPrice === null
        ? null
        : position.quantity * currentPrice;
    const avgCostUsdt = Number.isFinite(position.avgCostUsdt) && position.avgCostUsdt > 0
      ? Number(position.avgCostUsdt)
      : null;
    const costUsdt = avgCostUsdt === null ? null : avgCostUsdt * position.quantity;
    const pnlUsdt = costUsdt === null || currentPrice === null
      ? null
      : (currentPrice - avgCostUsdt) * position.quantity;
    const pnlPct = pnlUsdt === null || costUsdt <= 0 ? null : pnlUsdt / costUsdt * 100;
    const sourceLabel = position.source === "manual" ? "手动" : "Binance";
    const note = position.note
      || (!poolBySymbol.has(symbol) ? "账户持仓未加入资产池" : avgCostUsdt === null ? "需要平均成本" : "已覆盖成本");

    return {
      symbol,
      name: poolItem?.name || raw?.name || symbol,
      source: position.source,
      sourceLabel,
      quantity: position.quantity,
      avgCostUsdt,
      currentPrice,
      valueUsdt,
      costUsdt,
      pnlUsdt,
      pnlPct,
      poolItem,
      inAssetPool: poolBySymbol.has(symbol),
      note,
    };
  }).filter(Boolean);

  const valuedRows = rows.filter((row) => Number.isFinite(row.valueUsdt));
  const costRows = rows.filter((row) => Number.isFinite(row.costUsdt));
  const pnlRows = rows.filter((row) => Number.isFinite(row.pnlUsdt));
  const totalValueUsdt = valuedRows.length ? valuedRows.reduce((sum, row) => sum + row.valueUsdt, 0) : null;
  const totalCostUsdt = costRows.length ? costRows.reduce((sum, row) => sum + row.costUsdt, 0) : null;
  const totalPnlUsdt = pnlRows.length ? pnlRows.reduce((sum, row) => sum + row.pnlUsdt, 0) : null;
  const totalPnlPct = totalPnlUsdt === null || !totalCostUsdt ? null : totalPnlUsdt / totalCostUsdt * 100;
  const costCoveragePct = rows.length ? costRows.length / rows.length * 100 : null;
  const largestPosition = totalValueUsdt
    ? valuedRows.reduce((largest, row) => row.valueUsdt > (largest?.valueUsdt || 0) ? row : largest, null)
    : null;
  const manualUpdatedAt = Object.values(manualHoldingsConfig.holdings || {})
    .map((item) => item?.updatedAt)
    .filter(Boolean)
    .sort()
    .at(-1);
  const dataTime = [binanceAccount?.lastSyncedAt, manualUpdatedAt].filter(Boolean).sort().at(-1) || null;

  return {
    rows,
    totalValueUsdt,
    totalPnlUsdt,
    totalPnlPct,
    costCoveragePct,
    missingCostCount: rows.filter((row) => row.avgCostUsdt === null).length,
    unpricedCount: rows.filter((row) => row.valueUsdt === null).length,
    matchedCount: rows.filter((row) => row.inAssetPool).length,
    unmatchedCount: rows.filter((row) => !row.inAssetPool).length,
    largestPosition,
    largestPositionPct: largestPosition && totalValueUsdt ? largestPosition.valueUsdt / totalValueUsdt * 100 : null,
    dataTime,
  };
}

function renderBacktestSummary(model) {
  const cards = [
    { label: "累计收益", value: "待计算", helper: "策略总回报", tone: "slate", icon: "return" },
    { label: "年化收益", value: "待计算", helper: "CAGR", tone: "slate", icon: "trend" },
    { label: "最大回撤", value: "待计算", helper: "历史最大回撤", tone: "slate", icon: "drawdown" },
    { label: "夏普比率", value: "待计算", helper: "风险调整后收益", tone: "blue", icon: "scale" },
    { label: "相对基准", value: "待计算", helper: `相对 ${model.benchmarkSymbol} 超额`, tone: "amber", icon: "benchmark" },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderBacktestPage(items, snapshot) {
  const model = buildBacktestModel(snapshot);
  const holdingModel = buildCurrentHoldingPerformanceModel(items);
  renderBacktestSummary(model);

  document.getElementById("routeContent").innerHTML = `
    ${BacktestConfigBar(model)}
    ${CurrentHoldingPerformanceCard(holdingModel)}
    <section class="backtest-layout">
      <div class="backtest-main-column">
        ${BacktestChartCard({
          title: "策略净值 vs 基准",
          subtitle: "历史净值表现对比",
          legend: ["策略", model.benchmarkSymbol],
          emptyText: "尚无可用的回测净值数据，请先运行回测",
          sideMetrics: [
            { label: "最终净值", value: "待计算" },
            { label: "超额", value: "待计算" },
          ],
        })}
        ${BacktestChartCard({
          title: "回撤走势",
          subtitle: "策略回撤 vs 基准回撤",
          legend: ["策略回撤", `${model.benchmarkSymbol} 回撤`],
          emptyText: "尚无可用的回撤序列，请先运行回测",
          sideMetrics: [
            { label: "最大回撤", value: "待计算" },
            { label: "发生区间", value: "待计算" },
            { label: `同期 ${model.benchmarkSymbol}`, value: "待计算" },
          ],
          tone: "drawdown",
        })}
        <section class="backtest-bottom-grid">
          ${AnnualPerformanceTable(model.annualPerformance)}
          ${BacktestTradesTable(model.trades)}
        </section>
      </div>
      ${BacktestDiagnosisPanel(model)}
    </section>
  `;
}

function CurrentHoldingPerformanceCard(model) {
  const totalValueText = model.totalValueUsdt === null ? "暂无估值" : formatUsdt(model.totalValueUsdt);
  const pnlText = model.totalPnlUsdt === null ? "待成本" : formatSignedUsdt(model.totalPnlUsdt);
  const pnlPctText = model.totalPnlPct === null ? "—" : pct(model.totalPnlPct, { sign: true });
  const coverageText = model.costCoveragePct === null ? "—" : pct(model.costCoveragePct, { sign: false });
  const largestText = model.largestPosition
    ? `${model.largestPosition.symbol} · ${pct(model.largestPositionPct, { sign: false })}`
    : "—";

  return `
    <section class="backtest-card current-holding-card">
      <div class="backtest-card-header current-holding-header">
        <div>
          <h2>当前持仓表现</h2>
          <p>读取总览中的手动持仓与 Binance 只读账户；这里展示当前浮动表现，不代表历史回测收益。</p>
        </div>
        ${SettingsMiniBadge(model.rows.length ? `${model.rows.length} 个持仓` : "暂无持仓", model.rows.length ? "good" : "neutral")}
      </div>
      ${model.rows.length ? `
        <section class="current-holding-summary">
          ${CurrentHoldingStat("当前持仓市值", totalValueText, model.unpricedCount ? `${model.unpricedCount} 个未估值` : "可估值持仓汇总", "green")}
          ${CurrentHoldingStat("当前浮动盈亏", pnlText, pnlPctText, model.totalPnlUsdt === null ? "slate" : model.totalPnlUsdt >= 0 ? "green" : "red")}
          ${CurrentHoldingStat("成本覆盖率", coverageText, `${model.missingCostCount} 个待成本`, "blue")}
          ${CurrentHoldingStat("最大单一持仓", largestText, "按当前市值占比", "amber")}
        </section>
        <div class="backtest-table-wrap current-holding-table-wrap">
          <table class="backtest-small-table current-holding-table">
            <thead>
              <tr>
                <th>品种</th>
                <th>来源</th>
                <th>数量</th>
                <th>平均成本</th>
                <th>当前价格</th>
                <th>当前市值</th>
                <th>浮动盈亏</th>
                <th>收益率</th>
                <th>动作</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              ${model.rows.map(CurrentHoldingRow).join("")}
            </tbody>
          </table>
        </div>
        <div class="current-holding-quality">
          <span>资产池匹配 ${model.matchedCount} 个，账户外部持仓 ${model.unmatchedCount} 个。</span>
          <span>数据时间：${model.dataTime ? formatDateTime(model.dataTime) : "尚未同步"}</span>
        </div>
      ` : `
        <div class="empty-state compact">暂无当前持仓数据。请先在总览中保存手动持仓，或在设置中配置 Binance 只读账户后刷新。</div>
      `}
    </section>
  `;
}

function CurrentHoldingStat(label, value, helper, tone) {
  return `
    <div class="current-holding-stat ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(helper)}</small>
    </div>
  `;
}

function CurrentHoldingRow(row) {
  return `
    <tr>
      <td class="symbol-cell">
        ${escapeHtml(row.symbol)}
        <small>${escapeHtml(row.name)}</small>
      </td>
      <td><span class="holding-source-badge ${row.source}">${escapeHtml(row.sourceLabel)}</span></td>
      <td>${formatAssetQuantity(row.quantity)}</td>
      <td>${row.avgCostUsdt === null ? "待成本" : formatUsdt(row.avgCostUsdt)}</td>
      <td>${row.currentPrice === null ? "未估值" : formatUsdt(row.currentPrice)}</td>
      <td>${row.valueUsdt === null ? "—" : formatUsdt(row.valueUsdt)}</td>
      <td class="${changeClass(row.pnlUsdt)}">${row.pnlUsdt === null ? "待成本" : formatSignedUsdt(row.pnlUsdt)}</td>
      <td class="${changeClass(row.pnlPct)}">${row.pnlPct === null ? "—" : pct(row.pnlPct, { sign: true })}</td>
      <td>${row.poolItem ? InstrumentActionBadge(row.poolItem) : `<span class="instrument-action-none">—</span>`}</td>
      <td>${escapeHtml(row.note)}</td>
    </tr>
  `;
}

function renderPaperSummary(items) {
  const stats = paperAccountStats(items);
  const initialCash = Number(paperAccount.settings?.initialCashUsdt || 100000);
  const totalReturn = initialCash > 0 ? (stats.equityUsdt / initialCash - 1) * 100 : null;
  const cards = [
    { label: "模拟净值", value: formatUsdt(stats.equityUsdt), helper: `收益 ${pct(totalReturn, { sign: true })}`, tone: stats.equityUsdt >= initialCash ? "green" : "red", icon: "portfolio" },
    { label: "现金", value: formatUsdt(stats.cashUsdt), helper: "可用于新开仓", tone: "blue", icon: "wallet" },
    { label: "持仓数", value: stats.positionCount, helper: `${stats.tradeCount} 条模拟交易`, tone: "slate", icon: "assetCount" },
    { label: "已实现盈亏", value: formatSignedUsdt(stats.realizedPnlUsdt), helper: `${stats.closedTradeCount} 笔已闭合`, tone: stats.realizedPnlUsdt >= 0 ? "green" : "red", icon: "return" },
    { label: "胜率", value: stats.winRatePct === null ? "—" : pct(stats.winRatePct), helper: paperAccount.risk?.entryPaused ? "暂停新开仓" : `连亏 ${paperAccount.risk?.lossStreak || 0} 笔`, tone: paperAccount.risk?.entryPaused ? "red" : "amber", icon: "target" },
  ];
  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderPaperPage(items, snapshot) {
  renderPaperSummary(items);
  const stats = paperAccountStats(items);
  const positions = paperPositionRows(items);
  const trades = [...(paperAccount.trades || [])].reverse().slice(0, 80);
  document.getElementById("routeContent").innerHTML = `
    <section class="paper-account-toolbar">
      <div>
        <h2>模拟账户</h2>
        <p>仅用当前短线信号进行纸交易，不调用 Binance 交易接口，也不读取真实持仓作为模拟持仓。</p>
      </div>
      <div class="paper-account-actions">
        <button class="asset-secondary-button" type="button" data-paper-run ${paperAccountLoading || !paperAccountCapabilities.run ? "disabled" : ""}>
          ${paperAccountLoading ? "模拟中..." : "立即模拟一次"}
        </button>
        <button class="danger-button" type="button" data-paper-reset ${paperAccountLoading || !paperAccountCapabilities.reset ? "disabled" : ""}>重置模拟账户</button>
      </div>
    </section>
    <section class="paper-account-status ${paperAccount.risk?.entryPaused ? "danger" : "neutral"}">
      <div>
        <strong>${paperAccount.risk?.entryPaused ? "已暂停新开仓" : "自动纸交易已启用"}</strong>
        <span>刷新快照后自动执行一次；同一日同一品种同一信号不会重复开仓。</span>
      </div>
      <span>最近模拟：${paperAccount.lastRunAt ? formatDateTime(paperAccount.lastRunAt) : "尚未运行"}</span>
    </section>
    ${paperAccountError ? `<section class="notice bad paper-notice">${escapeHtml(paperAccountError)}</section>` : ""}
    <section class="paper-layout">
      <div class="paper-main-column">
        ${PaperPositionsTable(positions)}
        ${PaperTradesTable(trades)}
      </div>
      <aside class="paper-side-panel">
        ${PaperMetricsPanel(stats)}
        ${PaperRunLog(paperAccount.lastRunLog || [])}
      </aside>
    </section>
  `;
  bindPaperEvents();
}

function PaperMetricsPanel(stats) {
  const initialCash = Number(paperAccount.settings?.initialCashUsdt || 100000);
  const etfTargetPct = Number(paperAccount.settings?.targetEtfWeightPct ?? 60);
  const stockTargetPct = Number(paperAccount.settings?.targetStockWeightPct ?? 40);
  const singleCapPct = Number(paperAccount.settings?.maxSinglePositionPct ?? 15);
  const openRisk = paperPositionRows().reduce((sum, position) => {
    const stop = Number(position.stopPrice || 0);
    const current = Number(position.currentPrice || 0);
    const quantity = Number(position.quantity || 0);
    return stop > 0 && current > stop ? sum + (current - stop) * quantity : sum;
  }, 0);
  return `
    <section class="paper-panel-card">
      <div class="paper-panel-header">
        <h3>账户状态</h3>
        <span class="data-source-pill">模拟</span>
      </div>
      <dl class="paper-metric-list">
        <div><dt>初始资金</dt><dd>${formatUsdt(initialCash)}</dd></div>
        <div><dt>当前净值</dt><dd>${formatUsdt(stats.equityUsdt)}</dd></div>
        <div><dt>持仓市值</dt><dd>${formatUsdt(stats.positionValueUsdt)}</dd></div>
        <div><dt>ETF 仓位</dt><dd>${pct(stats.etfWeightPct)} / ${pct(etfTargetPct)}</dd></div>
        <div><dt>个股仓位</dt><dd>${pct(stats.stockWeightPct)} / ${pct(stockTargetPct)}</dd></div>
        <div><dt>单品种上限</dt><dd>${stats.largestPositionSymbol ? `${escapeHtml(stats.largestPositionSymbol)} ${pct(stats.largestPositionWeightPct)} / ${pct(singleCapPct)}` : `上限 ${pct(singleCapPct)}`}</dd></div>
        <div><dt>浮动盈亏</dt><dd class="${changeClass(stats.unrealizedPnlUsdt)}">${formatSignedUsdt(stats.unrealizedPnlUsdt)}</dd></div>
        <div><dt>估算开口风险</dt><dd>${formatUsdt(openRisk)}</dd></div>
        <div><dt>单笔风险</dt><dd>${pct(Number(paperAccount.settings?.riskPerTradePct || 1))}</dd></div>
        <div><dt>连续亏损</dt><dd>${paperAccount.risk?.lossStreak || 0} 笔</dd></div>
        <div><dt>执行模式</dt><dd>${paperAccount.settings?.autoRun === false ? "手动" : "自动"}</dd></div>
      </dl>
    </section>
  `;
}

function PaperPositionsTable(rows) {
  return `
    <section class="paper-card">
      <div class="paper-card-header">
        <div>
          <h2>模拟持仓</h2>
          <p>由建议买入信号开仓，止损/止盈和建议卖出信号负责退出。</p>
        </div>
        ${SettingsMiniBadge(rows.length ? `${rows.length} 个持仓` : "空仓", rows.length ? "good" : "neutral")}
      </div>
      <div class="paper-table-wrap">
        <table class="asset-table paper-table">
          <thead>
            <tr>
              <th>品种</th>
              <th>数量</th>
              <th>成本</th>
              <th>现价</th>
              <th>市值</th>
              <th>浮动盈亏</th>
              <th>止损</th>
              <th>止盈一</th>
              <th>止盈二</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            ${rows.length ? rows.map(PaperPositionRow).join("") : `<tr><td colspan="10"><div class="empty-state compact">暂无模拟持仓；出现建议买入信号后会自动建立纸交易仓位。</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function PaperPositionRow(row) {
  const status = row.partialTaken ? "已止盈一" : "跟踪中";
  return `
    <tr>
      <td class="symbol-cell">${escapeHtml(row.symbol)}</td>
      <td>${formatAssetQuantity(row.quantity)}</td>
      <td>${formatUsdt(row.avgCostUsdt)}</td>
      <td>${formatUsdt(row.currentPrice)}</td>
      <td>${formatUsdt(row.valueUsdt)}</td>
      <td class="${changeClass(row.pnlUsdt)}">
        ${formatSignedUsdt(row.pnlUsdt)}
        <small>${row.pnlPct === null ? "—" : pct(row.pnlPct, { sign: true })}</small>
      </td>
      <td>${price(row.stopPrice)}</td>
      <td>${price(row.targetPrice)}</td>
      <td>${price(row.target2Price)}</td>
      <td>${SettingsMiniBadge(status, row.partialTaken ? "good" : "neutral")}</td>
    </tr>
  `;
}

function PaperTradesTable(trades) {
  return `
    <section class="paper-card">
      <div class="paper-card-header">
        <div>
          <h2>模拟交易记录</h2>
          <p>最多展示最近 80 条；完整记录保存在本地模拟账户文件中。</p>
        </div>
        ${SettingsMiniBadge(trades.length ? `${trades.length} 条` : "暂无记录", "neutral")}
      </div>
      <div class="paper-table-wrap">
        <table class="asset-table paper-table trade">
          <thead>
            <tr>
              <th>时间</th>
              <th>品种</th>
              <th>方向</th>
              <th>数量</th>
              <th>价格</th>
              <th>金额</th>
              <th>实现盈亏</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            ${trades.length ? trades.map(PaperTradeRow).join("") : `<tr><td colspan="8"><div class="empty-state compact">暂无模拟交易记录。</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function PaperTradeRow(trade) {
  const pnl = Number(trade.realizedPnlUsdt || 0);
  return `
    <tr>
      <td>${escapeHtml(formatDateTime(trade.executedAt))}</td>
      <td class="symbol-cell">${escapeHtml(trade.symbol)}</td>
      <td>${SettingsMiniBadge(trade.side === "BUY" ? "买入" : "卖出", trade.side === "BUY" ? "good" : "bad")}</td>
      <td>${formatAssetQuantity(trade.quantity)}</td>
      <td>${formatUsdt(trade.price)}</td>
      <td>${formatUsdt(trade.valueUsdt)}</td>
      <td class="${changeClass(pnl)}">${trade.side === "SELL" ? formatSignedUsdt(pnl) : "—"}</td>
      <td>${escapeHtml(trade.reason || "模拟交易")}</td>
    </tr>
  `;
}

function PaperRunLog(logItems) {
  return `
    <section class="paper-panel-card">
      <div class="paper-panel-header">
        <h3>最近执行日志</h3>
        <span>${logItems.length ? `${logItems.length} 条` : "空"}</span>
      </div>
      ${logItems.length ? `
        <ul class="paper-run-log">
          ${logItems.slice(-12).reverse().map((item) => `
            <li class="${escapeHtml(item.action || "skip")}">
              <strong>${escapeHtml(item.symbol || "系统")}</strong>
              <span>${escapeHtml(item.reason || item.action || "已处理")}</span>
            </li>
          `).join("")}
        </ul>
      ` : `<div class="empty-state compact">刷新后如果有可执行信号，这里会显示买入、卖出或跳过原因。</div>`}
    </section>
  `;
}

function BacktestConfigBar(model) {
  const configItems = [
    { label: "区间", value: model.startDate && model.endDate ? `${model.startDate} - ${model.endDate}` : "未运行" },
    { label: "基准", value: model.benchmarkSymbol || "未配置" },
    { label: "频率", value: model.frequency || "未配置" },
    { label: "成本", value: Number.isFinite(model.transactionCostPct) ? `${fmt.format(model.transactionCostPct)}%` : "未配置" },
    { label: "滑点", value: Number.isFinite(model.slippagePct) ? `${fmt.format(model.slippagePct)}%` : "未配置" },
    { label: "分红", value: model.includesDividends === true ? "含分红" : model.includesDividends === false ? "不含分红" : "未接入" },
  ];

  return `
    <section class="backtest-config-bar">
      <div class="backtest-config-items">
        ${configItems.map((item) => `
          <span class="backtest-config-pill">
            <b>${escapeHtml(item.label)}：</b>${escapeHtml(item.value)}
          </span>
        `).join("")}
      </div>
      <div class="backtest-actions">
        <button class="icon-button" type="button" disabled title="尚未接入真实回测执行接口">重新运行回测</button>
        <button class="icon-button" type="button" disabled title="尚未生成真实回测报告">导出报告</button>
      </div>
    </section>
  `;
}

function BacktestChartCard({ title, subtitle, legend, emptyText, sideMetrics, tone = "equity" }) {
  return `
    <section class="backtest-card backtest-chart-card ${tone}">
      <div class="backtest-card-header">
        <div>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(subtitle)}</p>
        </div>
        <div class="backtest-legend">
          ${legend.map((item, index) => `<span class="${index === 0 ? "strategy" : "benchmark"}">${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
      <div class="backtest-chart-body">
        <div class="backtest-chart-empty">
          <div class="chart-grid-lines" aria-hidden="true"></div>
          <div class="empty-state compact">${escapeHtml(emptyText)}</div>
        </div>
        <aside class="backtest-chart-metrics">
          ${sideMetrics.map((item) => `
            <div>
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(item.value)}</strong>
            </div>
          `).join("")}
        </aside>
      </div>
    </section>
  `;
}

function AnnualPerformanceTable(rows) {
  return `
    <section class="backtest-card">
      <div class="backtest-card-header compact">
        <h2>年度表现</h2>
      </div>
      <div class="backtest-table-wrap">
        <table class="backtest-small-table">
          <thead>
            <tr>
              <th>年度</th>
              <th>策略</th>
              <th>基准</th>
              <th>超额</th>
            </tr>
          </thead>
          <tbody>
            ${rows.length ? rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.year)}</td>
                <td>${pct(row.strategyReturn, { sign: true })}</td>
                <td>${pct(row.benchmarkReturn, { sign: true })}</td>
                <td>${pct(row.excessReturn, { sign: true })}</td>
              </tr>
            `).join("") : `<tr><td colspan="4"><div class="empty-state compact">暂无年度回测汇总数据</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function BacktestTradesTable(rows) {
  return `
    <section class="backtest-card">
      <div class="backtest-card-header compact">
        <h2>交易记录</h2>
      </div>
      <div class="backtest-table-wrap">
        <table class="backtest-small-table trades">
          <thead>
            <tr>
              <th>日期</th>
              <th>ETF</th>
              <th>动作</th>
              <th>原因</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            ${rows.length ? rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.date)}</td>
                <td>${escapeHtml(row.symbol)}</td>
                <td>${escapeHtml(row.action)}</td>
                <td>${escapeHtml(row.reason || "—")}</td>
                <td>${pct(row.resultReturn, { sign: true })}</td>
              </tr>
            `).join("") : `<tr><td colspan="5"><div class="empty-state compact">尚未生成逐笔回测交易记录</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function BacktestDiagnosisPanel(model) {
  return `
    <aside class="backtest-diagnosis-panel">
      <div class="backtest-diagnosis-header">
        <div>
          <h2>回测诊断</h2>
          <p>趋势 + 动量 + 风险过滤 ETF 轮动策略</p>
        </div>
        ${StatusBadge({ text: "待评估", className: "watch" })}
      </div>

      <section class="backtest-stat-grid">
        ${[
          ["年化波动", "—"],
          ["年均换手率", "—"],
          ["Calmar", "—"],
          ["胜率", "—"],
          ["Sortino", "—"],
          ["盈亏比", "—"],
          ["总交易次数", "—"],
          ["基准超额", "待计算"],
        ].map(([label, value]) => `
          <div class="backtest-stat">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </section>

      <section class="backtest-two-column">
        <div>
          <h3>主要结论</h3>
          <ul class="diagnosis-list positive">
            <li>暂无真实回测结果，暂不生成绩效结论</li>
          </ul>
        </div>
        <div>
          <h3>主要关注</h3>
          <ul class="diagnosis-list warning">
            <li>尚未验证手续费、滑点与分红口径</li>
            <li>尚未验证参数稳健性</li>
          </ul>
        </div>
      </section>

      <section class="signal-performance-section">
        <h3>信号表现</h3>
        <div class="empty-state compact">暂无信号历史统计数据</div>
      </section>

      <section class="robustness-section">
        <h3>参数稳健性</h3>
        <div class="robustness-empty-grid" aria-hidden="true">
          <span>SMA150</span><span>SMA200</span><span>SMA250</span>
          <i></i><i></i><i></i>
          <i></i><i></i><i></i>
          <i></i><i></i><i></i>
        </div>
        <div class="empty-state compact">尚未运行参数稳健性测试</div>
      </section>
    </aside>
  `;
}

function buildPortfolioModel(items) {
  const bySymbol = new Map(items.map((item) => [item.symbol, item]));
  const riskAssets = ["QQQ", "SPY", "IWM"].map((symbol) => bySymbol.get(symbol)).filter(Boolean);
  const defensiveAssets = ["GLD", "TLT"].map((symbol) => bySymbol.get(symbol)).filter(Boolean);
  const cashAsset = bySymbol.get("SGOV");
  const riskPassed = riskAssets.filter((item) => item.trend_ok && !item.risk_signal).length;
  const defensiveHealthy = defensiveAssets.filter((item) => item.trend_ok && !item.risk_signal).length;
  const damagedCount = items.filter((item) => item.role !== "cash" && (item.risk_signal || !item.trend_ok)).length;
  const portfolioStatus = getPortfolioStatus(riskPassed, riskAssets.length, defensiveHealthy, damagedCount);
  const defenseAbility = getDefenseAbility(defensiveHealthy);
  const structureRows = ["QQQ", "SPY", "IWM", "GLD", "TLT", "SGOV"]
    .map((symbol) => bySymbol.get(symbol))
    .filter(Boolean)
    .map((item) => buildPortfolioAssetView(item));
  const concerns = buildPortfolioConcerns(bySymbol, riskPassed, defensiveHealthy);
  const advantages = buildPortfolioAdvantages(bySymbol, riskPassed, defensiveHealthy);
  const attentionCount = concerns.length;

  return {
    bySymbol,
    riskAssets,
    defensiveAssets,
    cashAsset,
    riskPassed,
    defensiveHealthy,
    portfolioStatus,
    defenseAbility,
    structureRows,
    concerns,
    advantages,
    attentionCount,
    concentrationText: "结构提示",
    concentrationHelper: "同类权益暴露",
  };
}

function getPortfolioStatus(riskPassed, riskTotal, defensiveHealthy, damagedCount) {
  if (damagedCount >= 3) {
    return { text: "风险受限", helper: "多类资产状态受损", tone: "red", badge: "damaged" };
  }
  if (riskPassed >= Math.max(2, riskTotal - 1) && defensiveHealthy >= 1) {
    return { text: "偏进攻", helper: "风险资产整体占优", tone: "green", badge: "strong" };
  }
  if (riskPassed >= 1 && defensiveHealthy >= 1) {
    return { text: "均衡", helper: "风险与防御均有效", tone: "green", badge: "stable" };
  }
  if (riskPassed === 0 && defensiveHealthy >= 1) {
    return { text: "偏防御", helper: "防御资产相对有效", tone: "amber", badge: "watch" };
  }
  return { text: "观察", helper: "等待结构更清晰", tone: "amber", badge: "watch" };
}

function getDefenseAbility(healthyCount) {
  if (healthyCount >= 2) {
    return { text: "有效", helper: "GLD 与 TLT 均健康", tone: "green", badge: "stable" };
  }
  if (healthyCount === 1) {
    return { text: "部分有效", helper: "GLD 有效 · TLT 受损", tone: "amber", badge: "watch" };
  }
  return { text: "弱化", helper: "防御资产均受损", tone: "red", badge: "damaged" };
}

function getPortfolioState(item) {
  if (item.role === "cash") return { text: "可用", className: "available" };
  return getSystemState(item);
}

function buildPortfolioAssetView(item) {
  const state = getPortfolioState(item);
  const hint = item.role === "cash" ? "—" : getKeyPrompt(item);
  const impactMap = {
    QQQ: state.className === "strong" ? "增强进攻" : "影响进攻层",
    SPY: state.className === "strong" ? "稳定风险暴露" : "核心风险观察",
    IWM: state.className === "watch" ? "等待确认" : "扩展风险广度",
    GLD: state.className === "stable" ? "提供分散" : "防御观察",
    TLT: state.className === "damaged" ? "防御弱化" : "久期防御",
    SGOV: "现金缓冲",
  };
  const attentionMap = {
    QQQ: "与 SPY 同向",
    SPY: "与 QQQ 同向",
    IWM: state.className === "watch" ? "突破待确认" : "—",
    GLD: "—",
    TLT: state.className === "damaged" ? "高关注" : "—",
    SGOV: "—",
  };

  return {
    symbol: item.symbol,
    role: portfolioRoles[item.symbol]?.label || roleLabels[item.role] || item.role,
    state,
    structuralHint: hint === "现金停泊" ? "—" : hint,
    portfolioImpact: impactMap[item.symbol] || "结构观察",
    attention: attentionMap[item.symbol] || "—",
    source: item,
  };
}

function buildPortfolioAdvantages(bySymbol, riskPassed, defensiveHealthy) {
  const advantages = [];
  const qqq = bySymbol.get("QQQ");
  const spy = bySymbol.get("SPY");
  const gld = bySymbol.get("GLD");
  if (riskPassed >= 2) advantages.push("风险资产趋势整体健康");
  if (qqq?.notes?.includes("breakout_hold") && spy?.notes?.includes("breakout_hold")) {
    advantages.push("QQQ 与 SPY 维持突破结构");
  }
  if (gld?.trend_ok && !gld?.risk_signal) advantages.push("GLD 当前防御状态健康");
  if (defensiveHealthy >= 1 && !advantages.some((text) => text.includes("GLD"))) {
    advantages.push("防御层仍有部分有效资产");
  }
  return advantages.slice(0, 3);
}

function buildPortfolioConcerns(bySymbol) {
  const concerns = ["QQQ 与 SPY 同属权益风险来源，建议关注重叠暴露"];
  const iwm = bySymbol.get("IWM");
  const tlt = bySymbol.get("TLT");
  if (iwm?.notes?.includes("near_resistance")) {
    concerns.push("IWM 接近阻力，广度仍待确认");
  }
  if (tlt?.risk_signal || !tlt?.trend_ok) {
    concerns.push("TLT 防御能力减弱");
  }
  return concerns.slice(0, 3);
}

function renderPortfolioSummary(model) {
  const cards = [
    {
      label: "组合状态",
      value: model.portfolioStatus.text,
      helper: model.portfolioStatus.helper,
      tone: model.portfolioStatus.tone,
      icon: "portfolio",
    },
    {
      label: "风险资产",
      value: `${model.riskPassed} / ${model.riskAssets.length || 3} 通过`,
      helper: "股票趋势整体健康",
      tone: "green",
      icon: "check",
    },
    {
      label: "防御能力",
      value: model.defenseAbility.text,
      helper: model.defenseAbility.helper,
      tone: model.defenseAbility.tone,
      icon: "shield",
    },
    {
      label: "集中风险",
      value: model.concentrationText,
      helper: model.concentrationHelper,
      tone: "amber",
      icon: "risk",
    },
    {
      label: "关注事项",
      value: model.attentionCount,
      helper: "需关注结构问题",
      tone: "amber",
      icon: "tasks",
    },
  ];
  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderPortfolioPage(items, snapshot) {
  const model = buildPortfolioModel(items, snapshot);
  if (selectedPortfolioMode === "actual") {
    renderActualAccountSummary();
  } else {
    renderPortfolioSummary(model);
  }

  const body = selectedPortfolioMode === "actual"
    ? ActualAccountPortfolioView(model)
    : `
      <section class="portfolio-layout">
        <div class="portfolio-main-column">
          ${PortfolioStructureCard(model)}
          ${PortfolioRelationshipCards(model)}
        </div>
        ${PortfolioDiagnosisPanel(model)}
      </section>
    `;

  document.getElementById("routeContent").innerHTML = `
    ${PortfolioModeTabs()}
    ${body}
  `;
  bindPortfolioEvents();
}

function PortfolioModeTabs() {
  return `
    <section class="portfolio-mode-bar" aria-label="组合视图切换">
      <div>
        <h2>组合视图</h2>
        <p>模型组合与 Binance 实际账户分开展示，避免把策略建议和真实持仓混在一起。</p>
      </div>
      <div class="portfolio-mode-actions">
        <button class="${selectedPortfolioMode === "model" ? "active" : ""}" type="button" data-portfolio-mode="model">模型组合</button>
        <button class="${selectedPortfolioMode === "actual" ? "active" : ""}" type="button" data-portfolio-mode="actual">实际账户</button>
      </div>
    </section>
  `;
}

function renderActualAccountSummary() {
  const totalValue = binanceAccount?.totalValueUsdt;
  const availableValue = BinanceAvailableValue();
  const assetCount = binanceAccount?.assets?.length ?? (binanceStatus.configured ? "—" : "未配置");
  const cards = [
    {
      label: "总资产估值",
      value: typeof totalValue === "number" ? formatUsdt(totalValue) : "待同步",
      helper: binanceAccount?.hasUnpricedAssets ? "仅汇总可估值资产" : "Binance Spot",
      tone: typeof totalValue === "number" ? "green" : "slate",
      icon: "wallet",
    },
    {
      label: "可用余额",
      value: typeof availableValue === "number" ? formatUsdt(availableValue) : "—",
      helper: "按可估值资产汇总",
      tone: typeof availableValue === "number" ? "blue" : "slate",
      icon: "balance",
    },
    {
      label: "持有资产数量",
      value: String(assetCount),
      helper: "非零余额资产",
      tone: binanceStatus.configured ? "green" : "slate",
      icon: "assetCount",
    },
    {
      label: "数据来源",
      value: "Binance Spot",
      helper: "只读账户余额",
      tone: "blue",
      icon: "link",
    },
    {
      label: "最近同步",
      value: binanceAccount?.lastSyncedAt ? formatDateTime(binanceAccount.lastSyncedAt) : "—",
      helper: "手动刷新",
      tone: binanceAccount?.lastSyncedAt ? "green" : "slate",
      icon: "clock",
    },
  ];
  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function ActualAccountPortfolioView(model) {
  const statusBlock = BinanceActualAccountStatusBlock();
  const table = BinanceActualAccountTable(model);
  const detail = BinanceActualAccountSidePanel(model);
  return `
    <section class="actual-account-layout">
      <div class="actual-account-main">
        <section class="portfolio-card actual-account-card">
          <div class="portfolio-card-header actual-account-header">
            <div>
              <h2>实际账户</h2>
              <p>读取 Binance Spot 非零余额；不执行任何交易操作。</p>
            </div>
            <div class="actual-account-actions">
              <button class="icon-button" type="button" data-binance-test ${binanceStatus.configured && !binanceLoading ? "" : "disabled"}>测试连接</button>
              <button class="primary-action" type="button" data-binance-refresh ${binanceStatus.configured && !binanceLoading ? "" : "disabled"}>
                ${binanceLoading ? "读取中..." : "刷新账户数据"}
              </button>
            </div>
          </div>
          ${statusBlock}
          ${table}
        </section>
      </div>
      ${detail}
    </section>
  `;
}

function BinanceActualAccountStatusBlock() {
  if (binanceLoading) {
    return `<div class="account-state-box neutral">正在从服务端读取 Binance Spot 账户，只请求只读余额接口。</div>`;
  }
  if (binanceError) {
    return `<div class="account-state-box bad">连接失败：${escapeHtml(binanceError)}</div>`;
  }
  if (!binanceStatus.configured) {
    return `
      <div class="account-state-box neutral">
        尚未配置 Binance 只读 API Key。请在服务端环境变量或 <code>.env.local</code> 中配置
        <code>BINANCE_API_KEY</code> 与 <code>BINANCE_API_SECRET</code>，不要把密钥放进浏览器端。
      </div>
    `;
  }
  if (!binanceAccount) {
    return `<div class="account-state-box neutral">账户连接已配置。点击“刷新账户数据”读取 Spot 非零余额。</div>`;
  }
  if (!binanceAccount.assets?.length) {
    return `<div class="account-state-box neutral">Binance Spot 当前没有非零余额资产。</div>`;
  }
  if (binanceAccount.hasUnpricedAssets) {
    return `<div class="account-state-box warn">存在未估值资产：没有可用 USDT 报价时不会伪造估值，总资产只汇总可估值资产。</div>`;
  }
  return `<div class="account-state-box good">只读账户余额已同步。当前仅展示持仓，不执行下单、撤单、提现或划转。</div>`;
}

function BinanceActualAccountTable(model) {
  if (!binanceAccount?.assets?.length) {
    return `<div class="empty-state">暂无可展示的实际账户资产。</div>`;
  }
  const rows = binanceAccount.assets.map((asset) => {
    const match = BinanceStrategyMatch(asset.asset, model);
    return `
      <tr>
        <td class="symbol-cell">${escapeHtml(asset.asset)}</td>
        <td>${formatAssetQuantity(asset.free)}</td>
        <td>${formatAssetQuantity(asset.locked)}</td>
        <td>${formatAssetQuantity(asset.total)}</td>
        <td>${asset.priceUsdt === null || asset.priceUsdt === undefined ? "未估值" : formatUsdt(asset.priceUsdt)}</td>
        <td>${asset.valueUsdt === null || asset.valueUsdt === undefined ? "—" : formatUsdt(asset.valueUsdt)}</td>
        <td>${asset.weightPct === null || asset.weightPct === undefined ? "—" : pct(asset.weightPct, { sign: false })}</td>
        <td>${SettingsMiniBadge(match.text, match.tone)}</td>
      </tr>
    `;
  }).join("");

  return `
    <div class="portfolio-table-wrap actual-account-table-wrap">
      <table class="portfolio-table actual-account-table">
        <thead>
          <tr>
            <th>资产</th>
            <th>可用数量</th>
            <th>冻结数量</th>
            <th>合计数量</th>
            <th>当前价 USDT</th>
            <th>市值 USDT</th>
            <th>账户占比</th>
            <th>策略匹配</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function BinanceActualAccountSidePanel(model) {
  const assets = binanceAccount?.assets || [];
  const unmatched = assets.filter((asset) => BinanceStrategyMatch(asset.asset, model).key === "unmatched").length;
  const unpriced = assets.filter((asset) => asset.valuationStatus === "unpriced").length;
  const connectionText = binanceStatus.configured
    ? (binanceAccount || binanceStatus.connected ? "只读已配置" : "已配置，待同步")
    : "未配置";
  return `
    <aside class="portfolio-diagnosis-panel actual-account-side">
      <div class="portfolio-diagnosis-header">
        <h2>账户摘要</h2>
        ${StatusBadge({ text: "只读账户", className: binanceStatus.configured ? "strong" : "parked" })}
      </div>
      <div class="settings-status-list compact">
        <div class="settings-status-row"><span>账户连接状态</span><strong>${escapeHtml(connectionText)}</strong></div>
        <div class="settings-status-row"><span>数据来源</span><strong>Binance Spot</strong></div>
        <div class="settings-status-row"><span>最后同步时间</span><strong>${binanceAccount?.lastSyncedAt ? escapeHtml(formatDateTime(binanceAccount.lastSyncedAt)) : "—"}</strong></div>
        <div class="settings-status-row"><span>未匹配策略资产</span><strong>${assets.length ? unmatched : "—"}</strong></div>
        <div class="settings-status-row"><span>未估值资产</span><strong class="${unpriced ? "amber" : "green"}">${assets.length ? `${unpriced} 个` : "—"}</strong></div>
      </div>
      <div class="readonly-account-notice">
        当前仅同步实际账户余额，不执行任何交易操作。模型组合、策略建议和 Binance 实际账户互相独立展示。
      </div>
      <div class="settings-side-block">
        <h3>安全边界</h3>
        <ul class="settings-change-list">
          <li>不开放 BUY / SELL 下单接口。</li>
          <li>不读取提现、划转、杠杆、借贷或合约仓位。</li>
          <li>Key 与 Secret 只由服务端环境变量读取，不返回前端。</li>
        </ul>
      </div>
    </aside>
  `;
}

function BinanceStrategyMatch(asset, model) {
  const symbol = String(asset || "").toUpperCase();
  const stablecoins = new Set(["USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP"]);
  if (stablecoins.has(symbol)) return { key: "stablecoin", text: "稳定币", tone: "blue" };
  if (model.bySymbol?.has(symbol)) return { key: "matched", text: "匹配策略", tone: "green" };
  return { key: "unmatched", text: "未匹配", tone: "slate" };
}

function BinanceAvailableValue() {
  if (!binanceAccount?.assets?.length) return null;
  let total = 0;
  let hasValue = false;
  binanceAccount.assets.forEach((asset) => {
    if (typeof asset.priceUsdt === "number" && typeof asset.free === "number") {
      total += asset.priceUsdt * asset.free;
      hasValue = true;
    }
  });
  return hasValue ? total : null;
}

function AccountAssetForSymbol(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  if (!normalized || !binanceAccount?.assets?.length) return null;
  return binanceAccount.assets.find((asset) => String(asset.asset || "").toUpperCase() === normalized) || null;
}

function ManualHoldingForSymbol(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return manualHoldingsConfig.holdings?.[normalized] || null;
}

function AccountPositionForSymbol(symbol, currentPrice = null) {
  const asset = AccountAssetForSymbol(symbol);
  const manual = ManualHoldingForSymbol(symbol);
  if (asset) {
    return {
      source: "binance",
      quantity: Number(asset.total || 0),
      locked: Number(asset.locked || 0),
      valueUsdt: asset.valueUsdt,
      weightPct: asset.weightPct,
      avgCostUsdt: manual?.avgCostUsdt ?? null,
      note: manual?.note || "",
    };
  }
  if (!manual) return null;
  const quantity = Number(manual.quantity || 0);
  const priceValue = typeof currentPrice === "number" ? currentPrice : null;
  return {
    source: "manual",
    quantity,
    locked: 0,
    valueUsdt: priceValue === null ? null : quantity * priceValue,
    weightPct: null,
    avgCostUsdt: typeof manual.avgCostUsdt === "number" ? manual.avgCostUsdt : null,
    note: manual.note || "",
  };
}

function AccountHoldingMatchCount() {
  if (!lastSnapshot?.symbols?.length) return 0;
  const poolSymbols = new Set(buildAssetPoolItems(lastSnapshot.symbols).map((item) => item.symbol));
  const matched = new Set();
  (binanceAccount?.assets || []).forEach((asset) => {
    const symbol = String(asset.asset || "").toUpperCase();
    if (poolSymbols.has(symbol)) matched.add(symbol);
  });
  Object.keys(manualHoldingsConfig.holdings || {}).forEach((symbol) => {
    if (poolSymbols.has(symbol)) matched.add(symbol);
  });
  return matched.size;
}

function AccountHoldingCell(symbol, currentPrice = null) {
  const position = AccountPositionForSymbol(symbol, currentPrice);
  if (!position) return `<span class="account-metric muted">—</span>`;
  return `
    <span class="account-metric strong">${formatAssetQuantity(position.quantity)}</span>
    <small>${position.source === "manual" ? "手动" : "Binance"}${position.locked > 0 ? ` · 冻结 ${formatAssetQuantity(position.locked)}` : ""}</small>
  `;
}

function AccountValueCell(symbol, currentPrice = null) {
  const position = AccountPositionForSymbol(symbol, currentPrice);
  if (!position) return `<span class="account-metric muted">—</span>`;
  if (position.valueUsdt === null || position.valueUsdt === undefined) {
    return `<span class="account-metric amber">未估值</span>`;
  }
  return `
    <span class="account-metric strong">${formatUsdt(position.valueUsdt)}</span>
    ${position.weightPct === null || position.weightPct === undefined ? "" : `<small>${pct(position.weightPct, { sign: false })}</small>`}
  `;
}

function AccountPnlCell(symbol, currentPrice = null) {
  const position = AccountPositionForSymbol(symbol, currentPrice);
  if (!position) return `<span class="account-metric muted">—</span>`;
  if (!position.avgCostUsdt || typeof currentPrice !== "number") {
    return `
      <span class="account-metric pending">待成本</span>
      <small>需成本价</small>
    `;
  }
  const pnl = (currentPrice - position.avgCostUsdt) * position.quantity;
  const cost = position.avgCostUsdt * position.quantity;
  const pnlPct = cost > 0 ? pnl / cost * 100 : null;
  return `
    <span class="account-metric ${pnl >= 0 ? "up" : "down"}">${formatSignedUsdt(pnl)}</span>
    <small>${pnlPct === null ? "—" : pct(pnlPct, { sign: true })}</small>
  `;
}

function formatUsdt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const digits = Math.abs(value) >= 1000 ? 2 : 4;
  return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: digits })} USDT`;
}

function formatSignedUsdt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatUsdt(value)}`;
}

function formatAssetQuantity(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function normalizePaperAccount(account) {
  if (!account || typeof account !== "object") return paperAccount;
  return {
    version: account.version || 1,
    settings: {
      initialCashUsdt: Number(account.settings?.initialCashUsdt || 100000),
      riskPerTradePct: Number(account.settings?.riskPerTradePct || 1),
      targetEtfWeightPct: Number(account.settings?.targetEtfWeightPct ?? 60),
      targetStockWeightPct: Number(account.settings?.targetStockWeightPct ?? 40),
      maxSinglePositionPct: Number(account.settings?.maxSinglePositionPct ?? 15),
      autoRun: account.settings?.autoRun !== false,
    },
    cashUsdt: Number(account.cashUsdt || 0),
    positions: account.positions && typeof account.positions === "object" ? account.positions : {},
    trades: Array.isArray(account.trades) ? account.trades : [],
    equityCurve: Array.isArray(account.equityCurve) ? account.equityCurve : [],
    processedSignals: Array.isArray(account.processedSignals) ? account.processedSignals : [],
    risk: account.risk && typeof account.risk === "object" ? account.risk : { lossStreak: 0, entryPaused: false },
    metrics: account.metrics && typeof account.metrics === "object" ? account.metrics : null,
    lastRunAt: account.lastRunAt || null,
    lastRunLog: Array.isArray(account.lastRunLog) ? account.lastRunLog : [],
    createdAt: account.createdAt || null,
    updatedAt: account.updatedAt || null,
  };
}

function snapshotItemMap(items = lastSnapshot?.symbols || []) {
  return new Map((items || []).map((item) => [item.symbol, item]));
}

function paperCurrentPrice(symbol, items = lastSnapshot?.symbols || []) {
  const item = snapshotItemMap(items).get(symbol);
  const value = item?.current_price ?? item?.close;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function paperAssetTypeForPosition(position, items = lastSnapshot?.symbols || []) {
  const item = snapshotItemMap(items).get(position?.symbol);
  if (item?.role === "stock") return "stock";
  if (item?.role === "cash") return "cash";
  const rawType = String(position?.assetType || position?.asset_type || "").toLowerCase();
  return ["stock", "cash"].includes(rawType) ? rawType : "etf";
}

function paperAccountStats(items = lastSnapshot?.symbols || []) {
  const positions = Object.values(paperAccount.positions || {});
  const cash = Number(paperAccount.cashUsdt || 0);
  let positionValue = 0;
  let unrealized = 0;
  let etfValue = 0;
  let stockValue = 0;
  let largestPositionValue = 0;
  let largestPositionSymbol = "";
  positions.forEach((position) => {
    const priceValue = paperCurrentPrice(position.symbol, items) ?? Number(position.lastPrice || position.avgCostUsdt || 0);
    const quantity = Number(position.quantity || 0);
    const avgCost = Number(position.avgCostUsdt || position.entryPrice || 0);
    const valueUsdt = quantity * priceValue;
    const assetType = paperAssetTypeForPosition(position, items);
    if (assetType === "stock") stockValue += valueUsdt;
    if (assetType === "etf") etfValue += valueUsdt;
    if (valueUsdt > largestPositionValue) {
      largestPositionValue = valueUsdt;
      largestPositionSymbol = position.symbol || "";
    }
    positionValue += valueUsdt;
    unrealized += (priceValue - avgCost) * quantity;
  });
  const closedTrades = (paperAccount.trades || []).filter((trade) => trade.side === "SELL" && trade.closesPosition);
  const wins = closedTrades.filter((trade) => Number(trade.realizedPnlUsdt || 0) > 0);
  const realized = (paperAccount.trades || []).reduce((sum, trade) => sum + Number(trade.realizedPnlUsdt || 0), 0);
  const equity = cash + positionValue;
  return {
    cashUsdt: cash,
    positionValueUsdt: positionValue,
    equityUsdt: equity,
    unrealizedPnlUsdt: unrealized,
    realizedPnlUsdt: realized,
    positionCount: positions.length,
    tradeCount: (paperAccount.trades || []).length,
    closedTradeCount: closedTrades.length,
    winRatePct: closedTrades.length ? wins.length / closedTrades.length * 100 : null,
    etfValueUsdt: etfValue,
    stockValueUsdt: stockValue,
    etfWeightPct: equity > 0 ? etfValue / equity * 100 : 0,
    stockWeightPct: equity > 0 ? stockValue / equity * 100 : 0,
    largestPositionSymbol,
    largestPositionValueUsdt: largestPositionValue,
    largestPositionWeightPct: equity > 0 ? largestPositionValue / equity * 100 : 0,
  };
}

function paperPositionRows(items = lastSnapshot?.symbols || []) {
  return Object.values(paperAccount.positions || {})
    .map((position) => {
      const currentPrice = paperCurrentPrice(position.symbol, items) ?? Number(position.lastPrice || position.avgCostUsdt || 0);
      const quantity = Number(position.quantity || 0);
      const avgCost = Number(position.avgCostUsdt || position.entryPrice || 0);
      const valueUsdt = quantity * currentPrice;
      const pnlUsdt = (currentPrice - avgCost) * quantity;
      const costUsdt = avgCost * quantity;
      return {
        ...position,
        currentPrice,
        valueUsdt,
        pnlUsdt,
        pnlPct: costUsdt > 0 ? pnlUsdt / costUsdt * 100 : null,
      };
    })
    .sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));
}

async function loadPaperAccountQuietly() {
  try {
    const response = await fetch("/api/paper-account", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "模拟账户读取失败");
    paperAccount = normalizePaperAccount(payload.account);
    paperAccountCapabilities = { ...paperAccountCapabilities, ...(payload.capabilities || {}) };
    paperAccountError = "";
  } catch (error) {
    paperAccountError = error.message || "模拟账户读取失败";
    paperAccountCapabilities = { read: false, reset: false, run: false };
  }
}

async function runPaperAccountForSnapshot(snapshot, options = {}) {
  if (!snapshot?.symbols?.length) return false;
  paperAccountLoading = true;
  try {
    const response = await fetch("/api/paper-account/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "模拟执行失败");
    paperAccount = normalizePaperAccount(payload.account);
    paperAccountCapabilities = { ...paperAccountCapabilities, run: true, reset: true, read: true };
    paperAccountError = "";
    return true;
  } catch (error) {
    paperAccountError = error.message || "模拟执行失败";
    if (!options.silent) setNotice(paperAccountError);
    return false;
  } finally {
    paperAccountLoading = false;
  }
}

async function resetPaperAccount() {
  paperAccountLoading = true;
  try {
    const response = await fetch("/api/paper-account/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initialCashUsdt: 100000 }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "模拟账户重置失败");
    paperAccount = normalizePaperAccount(payload.account);
    paperAccountError = "";
    if (lastSnapshot) render(lastSnapshot);
    setNotice("模拟账户已重置为 100,000 USDT。", "neutral");
  } catch (error) {
    paperAccountError = error.message || "模拟账户重置失败";
    setNotice(paperAccountError);
  } finally {
    paperAccountLoading = false;
  }
}

function PortfolioStructureCard(model) {
  const rows = model.structureRows.map((row, index) => `
    <tr class="${index === 0 ? "selected" : ""}">
      <td class="symbol-cell">${escapeHtml(row.symbol)}</td>
      <td>${escapeHtml(row.role)}</td>
      <td>${StatusBadge(row.state)}</td>
      <td>${escapeHtml(row.structuralHint)}</td>
      <td>${escapeHtml(row.portfolioImpact)}</td>
      <td>${PortfolioAttention(row.attention)}</td>
    </tr>
  `).join("");

  return `
    <section class="portfolio-card">
      <div class="portfolio-card-header">
        <div>
          <h2>组合结构</h2>
          <p>按资产角色展示组合结构与影响</p>
        </div>
      </div>
      <div class="portfolio-table-wrap">
        <table class="portfolio-table">
          <thead>
            <tr>
              <th>ETF</th>
              <th>组合角色</th>
              <th>当前状态</th>
              <th>结构提示</th>
              <th>组合影响</th>
              <th>关注项</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function PortfolioAttention(text) {
  if (!text || text === "—") return "—";
  const tone = text === "高关注" ? "high" : "medium";
  return `<span class="portfolio-attention ${tone}">${escapeHtml(text)}</span>`;
}

function PortfolioRelationshipCards(model) {
  const gld = model.bySymbol.get("GLD");
  const tlt = model.bySymbol.get("TLT");
  const gldHealthy = gld?.trend_ok && !gld?.risk_signal;
  const tltDamaged = tlt?.risk_signal || !tlt?.trend_ok;
  const cards = [
    {
      title: "QQQ / SPY：同类权益暴露",
      text: "均属于美国权益风险资产",
      tone: "amber",
      icon: "⌁",
    },
    {
      title: gldHealthy ? "GLD：防御状态健康" : "GLD：防御观察",
      text: gldHealthy ? "当前趋势健康，可提供防御观察" : "等待防御结构重新确认",
      tone: gldHealthy ? "green" : "amber",
      icon: "◉",
    },
    {
      title: tltDamaged ? "TLT：防御弱化" : "TLT：久期防御",
      text: tltDamaged ? "跌破 SMA200，长期趋势受损" : "久期防御仍处观察状态",
      tone: tltDamaged ? "red" : "green",
      icon: "⬡",
    },
  ];

  return `
    <section class="portfolio-card relationship-section">
      <div class="portfolio-card-header compact">
        <h2>结构关系 / 防御有效性</h2>
      </div>
      <div class="relationship-grid">
        ${cards.map((card) => `
          <article class="relationship-card ${card.tone}">
            <div class="relationship-icon">${escapeHtml(card.icon)}</div>
            <div>
              <h3>${escapeHtml(card.title)}</h3>
              <p>${escapeHtml(card.text)}</p>
            </div>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function PortfolioDiagnosisPanel(model) {
  const riskSymbols = model.riskAssets
    .filter((item) => item.trend_ok && !item.risk_signal)
    .map((item) => item.symbol)
    .join("、") || "暂无";
  const gld = model.bySymbol.get("GLD");
  const tlt = model.bySymbol.get("TLT");
  const defenseText = [
    gld ? `GLD ${gld.trend_ok && !gld.risk_signal ? "有效" : "观察"}` : null,
    tlt ? `TLT ${tlt.trend_ok && !tlt.risk_signal ? "有效" : "受损"}` : null,
  ].filter(Boolean).join("，");
  const cashText = model.cashAsset ? "SGOV 可用" : "暂无现金资产";
  const environmentText = buildPortfolioEnvironmentText(model, riskSymbols, defenseText, cashText);

  return `
    <aside class="portfolio-diagnosis-panel">
      <div class="portfolio-diagnosis-header">
        <h2>组合诊断</h2>
        ${StatusBadge({ text: model.portfolioStatus.text, className: model.portfolioStatus.badge })}
      </div>

      <section class="portfolio-diagnosis-block">
        <h3>当前结构状态</h3>
        <dl class="portfolio-diagnosis-list">
          <div><dt>风险偏好</dt><dd>${model.portfolioStatus.text === "偏进攻" ? "积极" : model.portfolioStatus.text}</dd></div>
          <div><dt>风险资产</dt><dd>${escapeHtml(riskSymbols)} 趋势通过</dd></div>
          <div><dt>防御层</dt><dd>${escapeHtml(defenseText || "暂无")}</dd></div>
          <div><dt>现金缓冲</dt><dd>${escapeHtml(cashText)}</dd></div>
          <div><dt>集中度</dt><dd>存在同类权益暴露提示</dd></div>
        </dl>
      </section>

      <section class="portfolio-two-column">
        <div>
          <h3>主要优势</h3>
          <ul class="diagnosis-list positive">
            ${model.advantages.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>暂无明确优势项</li>"}
          </ul>
        </div>
        <div>
          <h3>主要关注</h3>
          <ul class="diagnosis-list warning">
            ${model.concerns.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>暂无高优先级关注项</li>"}
          </ul>
        </div>
      </section>

      <section class="portfolio-note">
        <h3>组合环境说明</h3>
        <p>${escapeHtml(environmentText)}</p>
      </section>

      <section class="timeline-section">
        <h3>组合状态变化</h3>
        <div class="empty-state compact">暂无可用的组合状态历史记录</div>
      </section>
    </aside>
  `;
}

function buildPortfolioEnvironmentText(model, riskSymbols, defenseText, cashText) {
  const parts = [];
  parts.push(`当前组合整体为${model.portfolioStatus.text}，风险资产中 ${riskSymbols} 处于趋势通过状态。`);
  if (defenseText) parts.push(`防御层显示为${defenseText}。`);
  parts.push(`${cashText}，可作为组合缓冲。`);
  parts.push("QQQ 与 SPY 同属权益风险来源，当前仅作为结构提示，并非相关性或集中度的量化计算。");
  return parts.join("");
}

function buildSettingsModel(items, snapshot) {
  const config = currentConfig || {};
  const universe = config.universe || {};
  const enabledSymbols = [
    ...(universe.risk_assets || []),
    ...(universe.defensive_assets || []),
    ...(universe.cash_assets || []),
    ...(universe.stock_assets || []),
  ].filter((symbol, index, list) => symbol && list.indexOf(symbol) === index);
  const symbols = enabledSymbols.length ? enabledSymbols : items.map((item) => item.symbol);
  const dailyErrors = snapshot.errors?.daily || {};
  const intradayErrors = snapshot.errors?.intraday || {};
  const errorCount = Object.keys(dailyErrors).length + Object.keys(intradayErrors).length;
  const changes = buildSettingsChanges();
  const hasConfig = Boolean(currentConfig);

  return {
    config,
    hasConfig,
    configError: currentConfigError,
    symbols,
    assetCount: symbols.length,
    dataStatus: errorCount ? "存在异常" : snapshot.generated_at ? "可用" : "待确认",
    dataTone: errorCount ? "red" : snapshot.generated_at ? "green" : "slate",
    dataHelper: snapshot.latest_daily_date ? `${snapshot.latest_daily_date} 收盘后` : "收盘后更新",
    latestRun: formatTime(snapshot.generated_at),
    changes,
    capabilities: settingsCapabilities,
  };
}

function renderSettingsSummary(model) {
  const accountValue = binanceStatus.configured
    ? (binanceAccount || binanceStatus.connected ? "已连接" : "已配置")
    : "未配置";
  const accountTone = binanceStatus.configured
    ? (binanceError ? "red" : "green")
    : "slate";
  const cards = [
    { label: "当前策略版本", value: "未启用", helper: "未启用版本管理", tone: "slate", icon: "version" },
    { label: "资产池", value: `${model.assetCount} 只`, helper: model.assetCount ? "当前配置资产" : "未读取配置", tone: "blue", icon: "assetCount" },
    { label: "数据状态", value: model.dataStatus, helper: model.dataHelper, tone: model.dataTone, icon: "data" },
    { label: "账户连接", value: accountValue, helper: "Binance Spot 只读", tone: accountTone, icon: "link" },
    {
      label: "待发布变更",
      value: model.changes.length ? `${model.changes.length} 项` : "无草稿",
      helper: model.changes.length ? "本地草稿预览" : "未启用发布流程",
      tone: model.changes.length ? "amber" : "slate",
      icon: "changes",
    },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((card) => SummaryCard(card)).join("");
}

function renderSettingsPage(items, snapshot) {
  const model = buildSettingsModel(items, snapshot);
  renderSettingsSummary(model);

  document.getElementById("routeContent").innerHTML = `
    <section class="settings-layout">
      ${SettingsCategoryNav()}
      ${SettingsMainPanel(model, items, snapshot)}
      <aside class="settings-side-column">
        ${ConfigurationStatusCard(model)}
        ${DataNotificationSummaryCard(model, snapshot)}
      </aside>
    </section>
  `;

  bindSettingsEvents();
}

function SettingsCategoryNav() {
  return `
    <aside class="settings-category-card">
      <h2>设置分类</h2>
      <div class="settings-category-list">
        ${settingsCategories.map((category) => `
          <button class="settings-category-item ${category.key === selectedSettingsCategory ? "active" : ""}" type="button" data-settings-category="${category.key}">
            <span aria-hidden="true">${SettingsCategoryIcon(category.key)}</span>
            ${escapeHtml(category.label)}
          </button>
        `).join("")}
      </div>
    </aside>
  `;
}

function SettingsCategoryIcon(key) {
  const icons = {
    strategy: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M5 7h14" /><path d="M5 12h14" /><path d="M5 17h14" /><path d="M9 5v4" /><path d="M15 10v4" /><path d="M11 15v4" /></svg>`,
    assets: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M6 6h5v5H6z" /><path d="M13 6h5v5h-5z" /><path d="M6 13h5v5H6z" /><path d="M13 13h5v5h-5z" /></svg>`,
    data: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M5 19h14" /><path d="M8 16v-6" /><path d="M12 16V7" /><path d="M16 16v-4" /></svg>`,
    connections: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M9.5 14.5 8 16a3.5 3.5 0 0 1-5-5l2-2a3.5 3.5 0 0 1 5 0" /><path d="M14.5 9.5 16 8a3.5 3.5 0 0 1 5 5l-2 2a3.5 3.5 0 0 1-5 0" /><path d="M9 15 15 9" /></svg>`,
    alerts: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M12 4 20 18H4z" /><path d="M12 9v4" /><path d="M12 16h.01" /></svg>`,
    appearance: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M5 6h14" /><path d="M7 10h10" /><path d="M5 14h14" /><path d="M9 18h6" /></svg>`,
    version_security: `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M12 4 19 7v5c0 4-2.8 6.5-7 8-4.2-1.5-7-4-7-8V7z" /><path d="m8.5 12 2.2 2.2 4.8-5" /></svg>`,
  };
  return icons[key] || SummaryIcon("version");
}

function SettingsMainPanel(model, items, snapshot) {
  const selected = settingsCategories.find((category) => category.key === selectedSettingsCategory) || settingsCategories[0];
  return `
    <section class="settings-main-card">
      <div class="settings-card-header">
        <div>
          <h2>${escapeHtml(selected.label)}</h2>
          <p>${SettingsCategorySubtitle(selected.key)}</p>
        </div>
        ${model.changes.length ? `<span class="settings-dirty-pill">本地草稿预览</span>` : `<span class="data-source-pill">当前正式配置</span>`}
      </div>
      ${SettingsCategoryContent(selected.key, model, items, snapshot)}
    </section>
  `;
}

function SettingsCategorySubtitle(key) {
  const subtitles = {
    strategy: "展示当前策略参数；修改仅保存在本页本地草稿，不影响正式信号。",
    assets: "基于真实资产池配置展示 ETF 角色与启用状态。",
    data: "展示当前数据来源、计算周期与可用运行信息。",
    connections: "配置服务端只读账户连接；Secret 不进入浏览器端，也不保存到 localStorage。",
    alerts: "告警渠道尚未接入；当前仅展示可扩展结构。",
    appearance: "展示偏好尚未持久化；当前仅展示待接入项。",
    version_security: "当前没有策略版本、发布、回滚和审计记录能力。",
  };
  return subtitles[key] || "";
}

function SettingsCategoryContent(key, model, items, snapshot) {
  if (key === "connections") return AccountConnectionsPanel(model);
  if (!model.hasConfig) {
    return `<div class="settings-empty-state">未能读取配置文件：${escapeHtml(model.configError || "配置接口未返回数据")}</div>`;
  }
  if (key === "strategy") return StrategySettingsForm(model);
  if (key === "assets") return AssetPoolSettingsPanel(model, items, snapshot);
  if (key === "data") return DataComputationSettingsPanel(model, snapshot);
  if (key === "alerts") return AlertNotificationSettingsPanel();
  if (key === "appearance") return AppearanceSettingsPanel();
  if (key === "version_security") return VersionSecurityPanel();
  return `<div class="settings-empty-state">该设置分类尚未实现。</div>`;
}

function SettingsSection(title, rows) {
  return `
    <section class="settings-section">
      <h3>${escapeHtml(title)}</h3>
      <div class="settings-field-grid">
        ${rows.join("")}
      </div>
    </section>
  `;
}

function SettingsSelect({ label, path, options, helper, disabled = false }) {
  const value = settingValue(path);
  const optionValues = options.map((item) => String(item.value));
  const resolvedOptions = optionValues.includes(String(value)) || value === undefined
    ? options
    : [{ value, label: formatSettingValue(path, value) }, ...options];
  const dirty = settingChanged(path) ? " dirty" : "";
  return `
    <label class="settings-field${dirty}">
      <span>${escapeHtml(label)}</span>
      <select data-setting-path="${escapeHtml(path)}" ${disabled ? "disabled" : ""}>
        ${resolvedOptions.map((option) => `
          <option value="${escapeHtml(option.value)}" ${String(value) === String(option.value) ? "selected" : ""}>${escapeHtml(option.label)}</option>
        `).join("")}
      </select>
      ${helper ? `<small>${escapeHtml(helper)}</small>` : ""}
    </label>
  `;
}

function SettingsReadOnly({ label, value, helper, tone = "" }) {
  return `
    <div class="settings-field readonly ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "未配置")}</strong>
      ${helper ? `<small>${escapeHtml(helper)}</small>` : ""}
    </div>
  `;
}

function StrategySettingsForm(model) {
  const trendRows = [
    SettingsSelect({
      label: "长期趋势均线",
      path: "rules.trend_sma_days",
      options: [150, 200, 250].map((value) => ({ value, label: `SMA${value}` })),
      helper: "真实配置，当前用于趋势过滤",
    }),
    SettingsReadOnly({ label: "信号确认方式", value: "收盘确认", helper: "规则固定：只看日线收盘" }),
    SettingsReadOnly({ label: "跌破确认", value: "1 个交易日", helper: "收盘跌破即触发风险，非独立配置" }),
    SettingsReadOnly({ label: "恢复确认", value: "未配置", helper: "尚无恢复确认参数" }),
    SettingsReadOnly({ label: "缓冲区", value: "未配置", helper: "趋势过滤尚无独立缓冲参数" }),
  ];

  const momentumRows = [
    SettingsSelect({
      label: "主要周期",
      path: "rules.momentum_days",
      options: [63, 90, 126, 189].map((value) => ({ value, label: `${value}D` })),
      helper: "真实配置，当前用于候选排序",
    }),
    SettingsSelect({
      label: "辅助周期",
      path: "rules.short_momentum_days",
      options: [20, 63, 90, 126].map((value) => ({ value, label: `${value}D` })),
      helper: "真实配置，当前作为展示指标",
    }),
    SettingsReadOnly({ label: "排名模式", value: "126D 动量排序", helper: "当前核心排序未接入多周期加权" }),
    SettingsReadOnly({ label: "转正 / 转负信号", value: "未配置", helper: "尚无独立开关" }),
    SettingsReadOnly({ label: "排名提醒", value: "未配置", helper: "尚无排名变化提醒规则" }),
  ];

  const structureRows = [
    SettingsSelect({
      label: "突破站稳确认",
      path: "price_behavior.breakout_hold_days",
      options: [1, 2, 3, 5].map((value) => ({ value, label: `${value} 个交易日` })),
      helper: "真实配置，影响突破保持判断",
    }),
    SettingsSelect({
      label: "接近支撑阈值",
      path: "price_behavior.near_support_pct",
      options: [1, 1.5, 2, 3].map((value) => ({ value, label: `${value.toFixed(1)}%` })),
      helper: "真实配置",
    }),
    SettingsSelect({
      label: "接近阻力阈值",
      path: "price_behavior.near_resistance_pct",
      options: [1, 1.5, 2, 3].map((value) => ({ value, label: `${value.toFixed(1)}%` })),
      helper: "真实配置",
    }),
    SettingsSelect({
      label: "突破/失败监测窗口",
      path: "price_behavior.breakout_window_days",
      options: [20, 40, 60, 90].map((value) => ({ value, label: `${value}D` })),
      helper: "真实配置，非示意图中的固定日期",
    }),
    SettingsSelect({
      label: "假突破回落阈值",
      path: "price_behavior.failed_breakout_pct",
      options: [0.5, 1, 1.5, 2].map((value) => ({ value, label: `${value.toFixed(1)}%` })),
      helper: "真实配置",
    }),
  ];

  const riskRows = [
    SettingsSelect({
      label: "减仓回撤阈值",
      path: "rules.drawdown_reduce_pct",
      options: [6, 8, 10].map((value) => ({ value, label: `${value}%` })),
      helper: "真实配置，需账户权益后才触发",
    }),
    SettingsSelect({
      label: "现金防守阈值",
      path: "rules.drawdown_cash_pct",
      options: [10, 12, 15].map((value) => ({ value, label: `${value}%` })),
      helper: "真实配置，需账户权益后才触发",
    }),
    SettingsSelect({
      label: "放量风险倍数",
      path: "price_behavior.bearish_volume_multiplier",
      options: [1.1, 1.2, 1.5, 2].map((value) => ({ value, label: `${value.toFixed(1)}x` })),
      helper: "真实配置",
    }),
    SettingsReadOnly({ label: "ATR / 波动警报", value: "未配置", helper: "当前系统尚无 ATR 或波动率规则" }),
  ];

  return `
    <div class="settings-form-body">
      <div class="settings-guidance">
        策略类修改只会形成本地草稿预览；当前项目尚未接入草稿持久化、验证回测和发布流程。
      </div>
      ${SettingsSection("趋势过滤", trendRows)}
      ${SettingsSection("动量规则", momentumRows)}
      ${SettingsSection("价格结构", structureRows)}
      ${SettingsSection("波动与风险", riskRows)}
      ${SettingsActionBar(model)}
    </div>
  `;
}

function SettingsActionBar(model) {
  return `
    <div class="settings-action-bar">
      <button class="icon-button" type="button" data-settings-action="reset" ${model.changes.length ? "" : "disabled"}>重置</button>
      <button class="icon-button" type="button" disabled title="尚未接入草稿持久化接口">保存草稿</button>
      <button class="icon-button" type="button" disabled title="尚未接入真实验证回测入口">运行验证回测</button>
      <button class="icon-button primary" type="button" disabled title="尚未接入配置发布流程">发布配置</button>
    </div>
  `;
}

function AssetPoolSettingsPanel(model, items, snapshot) {
  const config = model.config;
  const universe = config.universe || {};
  const allSymbols = model.symbols;
  const rows = allSymbols.map((symbol) => {
    const item = items.find((entry) => entry.symbol === symbol);
    const role = universe.risk_assets?.includes(symbol)
      ? "风险资产"
      : universe.defensive_assets?.includes(symbol)
        ? "防御资产"
        : universe.cash_assets?.includes(symbol)
          ? "现金资产"
          : universe.stock_assets?.includes(symbol)
            ? "股票"
            : "未分类";
    const dataError = snapshot.errors?.daily?.[symbol] || snapshot.errors?.intraday?.[symbol];
    return `
      <tr>
        <td class="symbol-cell">${escapeHtml(symbol)}</td>
        <td>${escapeHtml(etfDescriptions[symbol] || "—")}</td>
        <td>${escapeHtml(role)}</td>
        <td>${escapeHtml(portfolioRoles[symbol]?.label || "未配置")}</td>
        <td>${SettingsMiniBadge("已启用", "good")}</td>
        <td>${SettingsMiniBadge("已启用", "good")}</td>
        <td>${SettingsMiniBadge("待接入", "neutral")}</td>
        <td>${SettingsMiniBadge(dataError ? "异常" : item ? "可用" : "待确认", dataError ? "bad" : item ? "good" : "neutral")}</td>
      </tr>
    `;
  }).join("");

  return `
    <div class="settings-form-body">
      <div class="settings-guidance">资产池来自当前真实配置；信号/监控启用状态为系统当前默认行为，回测启用尚未接入配置。</div>
      <div class="settings-table-wrap">
        <table class="settings-table">
          <thead>
            <tr>
              <th>ETF</th>
              <th>名称</th>
              <th>资产类别</th>
              <th>系统角色</th>
              <th>信号</th>
              <th>监控</th>
              <th>回测</th>
              <th>数据状态</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function DataComputationSettingsPanel(model, snapshot) {
  const rows = [
    ["行情数据源", "Yahoo chart endpoint；支持本地 CSV 备用", "good"],
    ["价格口径", "使用 Yahoo 返回价格；分红口径未单独配置", "neutral"],
    ["更新频率", `日频 · 收盘后；自动刷新 ${autoRefreshIntervalLabel()}`, autoRefreshIntervalMinutes ? "good" : "neutral"],
    ["最近成功计算", model.latestRun || "—", model.latestRun ? "good" : "neutral"],
    ["数据异常处理", "接口失败时展示错误，不生成伪数据", "neutral"],
    ["配置文件", snapshot.server?.config_path || "—", "neutral"],
  ];
  return `
    <div class="settings-form-body">
      <div class="settings-guidance">数据与计算当前只展示真实可追踪信息；没有任务日志的项目显示为待接入。</div>
      <div class="settings-status-list">
        ${rows.map(([label, value, tone]) => `
          <div class="settings-status-row">
            <span>${escapeHtml(label)}</span>
            <strong class="${escapeHtml(tone)}">${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
      <section class="settings-section">
        <h3>自动刷新</h3>
        <div class="settings-field-grid single">
          <label class="settings-field">
            <span>自动刷新间隔</span>
            <select data-auto-refresh-interval>
              ${AUTO_REFRESH_INTERVAL_OPTIONS.map((minutes) => `
                <option value="${minutes}" ${minutes === autoRefreshIntervalMinutes ? "selected" : ""}>
                  ${minutes ? `${minutes} 分钟` : "关闭"}
                </option>
              `).join("")}
            </select>
            <small>软件打开时先刷新一次；之后按此间隔后台刷新总览、信号和模拟盘。</small>
          </label>
        </div>
      </section>
    </div>
  `;
}

function AccountConnectionsPanel(model) {
  const connectionText = binanceStatus.configured
    ? (binanceAccount || binanceStatus.connected ? "已连接" : "已配置，待测试")
    : "未配置";
  const connectionTone = binanceStatus.configured
    ? (binanceError ? "bad" : "good")
    : "neutral";
  const rows = [
    ["用途", "仅读取账户资产与余额", "good"],
    ["账户类型", "Spot / 现货", "neutral"],
    ["连接状态", binanceError ? `连接失败：${binanceError}` : connectionText, connectionTone],
    ["权限要求", "仅允许读取", "good"],
    ["IP 白名单", "建议启用", "neutral"],
    ["最近同步", binanceAccount?.lastSyncedAt ? formatDateTime(binanceAccount.lastSyncedAt) : "—", binanceAccount?.lastSyncedAt ? "good" : "neutral"],
    ["API Key", binanceStatus.apiKeyMasked || "未配置", binanceStatus.apiKeyMasked ? "good" : "neutral"],
    ["Secret Key", binanceStatus.configured ? "已配置（不回显）" : "未配置", binanceStatus.configured ? "good" : "neutral"],
  ];

  return `
    <div class="settings-form-body account-connection-panel">
      <div class="settings-guidance">
        Binance 私有账户连接只在服务端读取环境变量；前端不保存 Secret，也不会把 Key / Secret 写入 localStorage、sessionStorage 或客户端 bundle。
      </div>
      <section class="settings-section">
        <h3>Binance 账户连接</h3>
        <div class="settings-status-list account-connection-status">
          ${rows.map(([label, value, tone]) => `
            <div class="settings-status-row with-dot">
              <span><i class="${tone}"></i>${escapeHtml(label)}</span>
              <strong class="${tone}">${escapeHtml(value)}</strong>
            </div>
          `).join("")}
        </div>
      </section>

      <section class="settings-section">
        <h3>服务端环境变量</h3>
        <div class="account-env-grid">
          <label class="settings-field readonly">
            <span>API Key</span>
            <input value="${escapeHtml(binanceStatus.apiKeyMasked || "从 BINANCE_API_KEY 读取")}" readonly>
            <small>仅显示掩码；真实值不返回前端。</small>
          </label>
          <label class="settings-field readonly">
            <span>Secret Key</span>
            <input value="${binanceStatus.configured ? "已配置（不回显）" : "从 BINANCE_API_SECRET 读取"}" readonly>
            <small>Secret 只存在服务端环境变量中。</small>
          </label>
        </div>
        <pre class="binance-env-example">BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_API_BASE_URL=https://api.binance.com</pre>
      </section>

      <section class="account-safety-box">
        <h3>安全提示</h3>
        <ul>
          <li>本连接仅用于读取账户资产，不执行交易。</li>
          <li>API Key 只需要读取权限，不需要交易、提现、划转或借贷权限。</li>
          <li>建议在 Binance 后台限制服务器固定 IP。</li>
          <li>错误提示会脱敏，不展示 Secret、签名或完整私有响应。</li>
        </ul>
      </section>

      <div class="settings-action-bar account-action-bar">
        <button class="icon-button" type="button" data-binance-test ${binanceStatus.configured && !binanceLoading ? "" : "disabled"}>
          ${binanceLoading ? "测试中..." : "测试连接"}
        </button>
        <button class="icon-button" type="button" data-binance-refresh ${binanceStatus.configured && !binanceLoading ? "" : "disabled"}>刷新账户数据</button>
        <button class="primary-action" type="button" disabled title="当前项目通过服务端环境变量配置 Binance Secret，不在页面保存密钥。">保存连接</button>
      </div>

      ${binanceError ? `<div class="account-state-box bad">${escapeHtml(binanceError)}</div>` : ""}
      ${!binanceStatus.configured ? `<div class="account-state-box neutral">请在本地或服务器环境变量中配置 Binance 只读 Key；不要把真实密钥粘贴到对话或前端页面。</div>` : ""}
    </div>
  `;
}

function AlertNotificationSettingsPanel() {
  const rows = [
    ["跌破 SMA200", "规则存在于风险判断；通知渠道未配置", "neutral"],
    ["突破确认", "信号标签存在；通知渠道未配置", "neutral"],
    ["接近支撑 / 阻力", "信号标签存在；通知渠道未配置", "neutral"],
    ["邮件提醒", "未配置", "neutral"],
    ["重复提醒抑制", "待接入", "neutral"],
  ];
  return SettingsStatusList(rows, "告警页只管理提醒方式，不改变策略判断；当前项目尚无告警持久化配置。");
}

function AppearanceSettingsPanel() {
  const rows = [
    ["默认页面", "未配置", "neutral"],
    ["界面语言", "中文主界面", "good"],
    ["主题", "浅色主题", "good"],
    ["表格密度", "沿用系统默认", "neutral"],
    ["数字精度", "最多 2 位小数", "good"],
    ["图表默认周期", "待接入", "neutral"],
  ];
  return SettingsStatusList(rows, "展示偏好目前没有持久化存储；后续可独立于策略发布流程保存。");
}

function VersionSecurityPanel() {
  const rows = [
    ["当前正式版本", "尚未启用策略版本管理", "neutral"],
    ["草稿配置", "未接入", "neutral"],
    ["验证回测", "未接入", "neutral"],
    ["发布配置", "未接入", "neutral"],
    ["回滚能力", "未接入", "neutral"],
    ["操作审计", "未接入", "neutral"],
  ];
  return SettingsStatusList(rows, "当前系统没有版本、草稿、发布、回滚和审计记录；不会伪造发布状态。");
}

function SettingsStatusList(rows, note) {
  return `
    <div class="settings-form-body">
      <div class="settings-guidance">${escapeHtml(note)}</div>
      <div class="settings-status-list">
        ${rows.map(([label, value, tone]) => `
          <div class="settings-status-row">
            <span>${escapeHtml(label)}</span>
            <strong class="${escapeHtml(tone)}">${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function ConfigurationStatusCard(model) {
  const pending = model.changes.length
    ? model.changes.map((change) => `<li>${escapeHtml(change.label)}：${escapeHtml(change.previousValue)} → ${escapeHtml(change.nextValue)}</li>`).join("")
    : `<li>当前无已保存草稿；${model.capabilities.save_draft ? "无待发布变更" : "尚未接入版本差异比较"}</li>`;
  const impacts = model.changes.length
    ? [...new Set(model.changes.flatMap((change) => change.impacts))]
    : [];
  const validation = model.changes.length ? "尚未运行回测" : "不适用";
  const validationTone = model.changes.length ? "amber" : "slate";

  return `
    <section class="settings-side-card">
      <div class="settings-side-header">
        <h2>配置状态</h2>
        ${StatusBadge({ text: model.changes.length ? "本地草稿" : "未启用版本", className: model.changes.length ? "watch" : "parked" })}
      </div>
      <div class="settings-status-list compact">
        <div class="settings-status-row"><span>当前正式版本</span><strong>未启用版本管理</strong></div>
        <div class="settings-status-row"><span>最近发布时间</span><strong>—</strong></div>
        <div class="settings-status-row"><span>资产池</span><strong>${model.assetCount} 只 ETF</strong></div>
        <div class="settings-status-row"><span>数据计算周期</span><strong>日频 · 收盘后</strong></div>
        <div class="settings-status-row"><span>账户连接</span><strong>${binanceStatus.configured ? "Binance Spot 只读" : "未配置"}</strong></div>
      </div>
      <div class="settings-side-block">
        <h3>待发布变更</h3>
        <ul class="settings-change-list">${pending}</ul>
      </div>
      <div class="settings-side-block">
        <h3>影响模块</h3>
        <div class="settings-impact-tags">
          ${impacts.length ? impacts.map((item) => `<span>${escapeHtml(item)}</span>`).join("") : "<span>暂无</span>"}
        </div>
      </div>
      <div class="settings-validation-row">
        <span>验证状态</span>
        <strong class="${validationTone}">${escapeHtml(validation)}</strong>
      </div>
      <div class="settings-side-actions">
        <button class="icon-button" type="button" ${model.changes.length ? "" : "disabled"}>查看差异</button>
        <button class="icon-button" type="button" data-settings-action="reset" ${model.changes.length ? "" : "disabled"}>放弃修改</button>
      </div>
    </section>
  `;
}

function DataNotificationSummaryCard(model, snapshot) {
  const hasErrors = Object.keys(snapshot.errors?.daily || {}).length + Object.keys(snapshot.errors?.intraday || {}).length > 0;
  const rows = [
    ["行情数据源", "Yahoo / CSV 备用", "good"],
    ["账户同步", binanceAccount?.lastSyncedAt ? formatDateTime(binanceAccount.lastSyncedAt) : (binanceStatus.configured ? "待同步" : "未配置"), binanceAccount?.lastSyncedAt ? "good" : "neutral"],
    ["最近成功计算", model.latestRun || "—", model.latestRun ? "good" : "neutral"],
    ["页面通知", "未配置", "neutral"],
    ["邮件提醒", "未配置", "neutral"],
    ["异常数据处理", hasErrors ? "存在接口异常" : "展示错误，不生成伪数据", hasErrors ? "bad" : "neutral"],
  ];

  return `
    <section class="settings-side-card">
      <div class="settings-side-header">
        <h2>数据与通知摘要</h2>
      </div>
      <div class="settings-status-list compact">
        ${rows.map(([label, value, tone]) => `
          <div class="settings-status-row with-dot">
            <span><i class="${tone}"></i>${escapeHtml(label)}</span>
            <strong class="${tone}">${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function SettingsMiniBadge(text, tone) {
  return `<span class="settings-mini-badge ${tone}">${escapeHtml(text)}</span>`;
}

function renderPlaceholder(route) {
  renderOverviewSummary(lastSnapshot?.symbols || [], lastSnapshot || {});
  document.getElementById("routeContent").innerHTML = `
    <section class="placeholder-card">
      <h2>${escapeHtml(routeTitles[route] || "页面")}</h2>
      <p>该页面暂未实现。当前任务已接入“总览”和“信号”两个页面的切换。</p>
    </section>
  `;
}

function formatTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatSnapshotLabel(snapshot) {
  if (snapshot?.latest_daily_date) {
    return `${snapshot.latest_daily_date} 收盘后`;
  }
  return "收盘后";
}

function setNotice(message, tone = "bad") {
  const notice = document.getElementById("notice");
  if (!message) {
    notice.hidden = true;
    notice.textContent = "";
    notice.className = "notice";
    return;
  }
  notice.hidden = false;
  notice.className = `notice ${tone}`;
  notice.textContent = message;
}

function sanitizeAutoRefreshInterval(value) {
  const minutes = Number(value);
  return AUTO_REFRESH_INTERVAL_OPTIONS.includes(minutes) ? minutes : DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES;
}

function loadAutoRefreshIntervalSetting() {
  try {
    const raw = window.localStorage?.getItem(AUTO_REFRESH_INTERVAL_KEY);
    if (raw === null || raw === undefined) return DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES;
    return sanitizeAutoRefreshInterval(raw);
  } catch (_) {
    return DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES;
  }
}

function saveAutoRefreshIntervalSetting(minutes) {
  autoRefreshIntervalMinutes = sanitizeAutoRefreshInterval(minutes);
  try {
    window.localStorage?.setItem(AUTO_REFRESH_INTERVAL_KEY, String(autoRefreshIntervalMinutes));
  } catch (_) {}
  scheduleAutoRefresh();
}

function autoRefreshIntervalLabel(minutes = autoRefreshIntervalMinutes) {
  const value = sanitizeAutoRefreshInterval(minutes);
  return value > 0 ? `${value} 分钟` : "关闭";
}

function scheduleAutoRefresh() {
  window.clearTimeout(autoRefreshTimer);
  autoRefreshTimer = null;
  if (!autoRefreshIntervalMinutes) return;
  autoRefreshTimer = window.setTimeout(async () => {
    await refresh({ background: true, auto: true });
    scheduleAutoRefresh();
  }, autoRefreshIntervalMinutes * 60 * 1000);
}

function plainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function dashboardCachePayload(snapshot = lastSnapshot) {
  if (!snapshot?.symbols?.length) return null;
  return {
    version: 1,
    savedAt: new Date().toISOString(),
    route: getRoute(),
    selectedSymbol,
    selectedGroupId,
    selectedSignalId,
    selectedMonitorId,
    selectedSettingsCategory,
    selectedPortfolioMode,
    rightRailMode: ["add", "edit"].includes(rightRailMode) ? "detail" : rightRailMode,
    assetPoolFilters,
    signalFilters,
    collapsedAssetGroups,
    snapshot,
    currentConfig,
    assetPoolConfig,
    assetPoolCapabilities,
    manualHoldingsConfig,
    manualHoldingsCapabilities,
    binanceStatus,
    binanceAccount,
  };
}

function saveDashboardCache(snapshot = lastSnapshot) {
  try {
    const payload = dashboardCachePayload(snapshot);
    if (!payload) return;
    if (window.localStorage) {
      window.localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify(payload));
    }
    queueServerDashboardCacheSave(payload);
  } catch (_) {
    // Local UI cache is best effort; never block the dashboard.
  }
}

function queueServerDashboardCacheSave(payload) {
  if (!payload) return;
  window.clearTimeout(dashboardCacheSaveTimer);
  dashboardCacheSaveTimer = window.setTimeout(() => {
    fetch("/api/ui-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cache: payload }),
    }).catch(() => {});
  }, 250);
}

function flushDashboardCache(snapshot = lastSnapshot) {
  const payload = dashboardCachePayload(snapshot);
  if (!payload) return;
  try {
    if (window.localStorage) {
      window.localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify(payload));
    }
  } catch (_) {}
  try {
    if (navigator.sendBeacon) {
      const body = new Blob([JSON.stringify({ cache: payload })], { type: "application/json" });
      navigator.sendBeacon("/api/ui-cache", body);
    }
  } catch (_) {}
}

function loadDashboardCache() {
  try {
    const raw = window.localStorage.getItem(DASHBOARD_CACHE_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    const savedAt = Date.parse(payload.savedAt || "");
    if (!payload?.snapshot?.symbols?.length || !savedAt || Date.now() - savedAt > DASHBOARD_CACHE_MAX_AGE_MS) {
      return null;
    }
    return payload;
  } catch (_) {
    return null;
  }
}

async function loadServerDashboardCache() {
  try {
    const response = await fetch("/api/ui-cache", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) return null;
    const cache = payload.cache;
    const savedAt = Date.parse(cache?.savedAt || "");
    if (!cache?.snapshot?.symbols?.length || !savedAt || Date.now() - savedAt > DASHBOARD_CACHE_MAX_AGE_MS) {
      return null;
    }
    return cache;
  } catch (_) {
    return null;
  }
}

function restoreDashboardCache(payload) {
  if (!payload?.snapshot?.symbols?.length) return false;
  if (!window.location.hash && payload.route) {
    window.history.replaceState(null, "", `#${payload.route}`);
  }
  selectedSymbol = payload.selectedSymbol || selectedSymbol;
  selectedGroupId = payload.selectedGroupId || selectedGroupId;
  selectedSignalId = payload.selectedSignalId || selectedSignalId;
  selectedMonitorId = payload.selectedMonitorId || selectedMonitorId;
  selectedSettingsCategory = payload.selectedSettingsCategory || selectedSettingsCategory;
  selectedPortfolioMode = payload.selectedPortfolioMode || selectedPortfolioMode;
  rightRailMode = payload.rightRailMode || rightRailMode;
  if (plainObject(payload.assetPoolFilters)) assetPoolFilters = { ...assetPoolFilters, ...payload.assetPoolFilters };
  if (plainObject(payload.signalFilters)) signalFilters = { ...signalFilters, ...payload.signalFilters };
  if (plainObject(payload.collapsedAssetGroups)) collapsedAssetGroups = payload.collapsedAssetGroups;
  if (plainObject(payload.currentConfig)) currentConfig = payload.currentConfig;
  if (plainObject(payload.assetPoolConfig)) {
    assetPoolConfig = payload.assetPoolConfig;
    assetPoolGroups = normalizeAssetPoolGroups(assetPoolConfig);
  }
  if (plainObject(payload.assetPoolCapabilities)) {
    assetPoolCapabilities = { ...assetPoolCapabilities, ...payload.assetPoolCapabilities };
  }
  if (plainObject(payload.manualHoldingsConfig)) manualHoldingsConfig = payload.manualHoldingsConfig;
  if (plainObject(payload.manualHoldingsCapabilities)) {
    manualHoldingsCapabilities = { ...manualHoldingsCapabilities, ...payload.manualHoldingsCapabilities };
  }
  if (plainObject(payload.binanceStatus)) {
    binanceStatus = { ...binanceStatus, ...payload.binanceStatus };
  }
  binanceAccount = plainObject(payload.binanceAccount) ? payload.binanceAccount : null;
  binanceError = "";
  render(payload.snapshot, { cache: "restored" });
  setNotice("已先显示上次关闭前的画面，正在后台刷新最新数据。", "neutral");
  return true;
}

function updateRouteChrome(route) {
  document.getElementById("pageSubtitle").textContent = routeTitles[route] || routeTitles.overview;
  const dataScopeLabel = document.querySelector(".header-meta .meta-item span");
  const dataScope = document.querySelector(".header-meta .meta-item strong");
  if (dataScopeLabel && dataScope) {
    if (route === "settings") {
      dataScopeLabel.textContent = "当前版本";
      dataScope.textContent = "未启用版本管理";
    } else if (route === "paper") {
      dataScopeLabel.textContent = "账户模式";
      dataScope.textContent = "模拟";
    } else {
      dataScopeLabel.textContent = "数据截至";
      dataScope.textContent = route === "backtest" ? "回测未运行" : "收盘后";
    }
  }
  document.querySelectorAll("[data-route]").forEach((item) => {
    item.classList.toggle("active", item.dataset.route === route);
  });
}

function render(snapshot, options = {}) {
  lastSnapshot = snapshot;
  const items = snapshot.symbols || [];
  const route = getRoute();
  updateRouteChrome(route);

  if (!items.length) {
    setNotice("没有可展示的数据。");
    return;
  }

  const selectedConfigured = assetPoolConfig.instruments?.[selectedSymbol]
    && !assetPoolConfig.instruments[selectedSymbol].removed
    && assetPoolConfig.instruments[selectedSymbol].showInOverview !== false;
  if (!items.some((item) => item.symbol === selectedSymbol) && !selectedConfigured) {
    selectedSymbol = items.find((item) => item.symbol === "QQQ")?.symbol || items[0].symbol;
  }

  document.getElementById("updatedTime").textContent = formatTime(snapshot.generated_at);

  if (route === "overview") {
    renderOverviewSummary(items, snapshot);
    renderOverview(items);
  } else if (route === "signals") {
    renderSignalPage(items, snapshot);
  } else if (route === "portfolio") {
    renderPortfolioPage(items, snapshot);
  } else if (route === "monitor") {
    renderMonitorPage(items, snapshot);
  } else if (route === "backtest") {
    renderBacktestPage(items, snapshot);
  } else if (route === "paper") {
    renderPaperPage(items, snapshot);
  } else if (route === "settings") {
    renderSettingsPage(items, snapshot);
  } else {
    renderPlaceholder(route);
  }

  const errors = [];
  const dailyErrors = snapshot.errors?.daily || {};
  const intradayErrors = snapshot.errors?.intraday || {};
  for (const [symbol, text] of Object.entries(dailyErrors)) errors.push(`${symbol} 日线数据失败：${text}`);
  for (const [symbol, text] of Object.entries(intradayErrors)) errors.push(`${symbol} 盘中数据失败：${text}`);
  if (paperAccountError) errors.push(`模拟账户：${paperAccountError}`);
  setNotice(errors.join("；"));
  if (options.cache !== "skip") {
    saveDashboardCache(snapshot);
  }
}

function bindOverviewRowEvents() {
  document.querySelector("[data-asset-action='add']")?.addEventListener("click", () => {
    rightRailMode = "add";
    closeInstrumentRowMenu();
    addInstrumentState.saveError = "";
    render(lastSnapshot);
  });

  document.querySelector("[data-asset-action='manage']")?.addEventListener("click", () => {
    selectedSettingsCategory = "assets";
    window.location.hash = "settings";
  });

  document.querySelectorAll("[data-binance-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshBinanceAccount());
  });

  document.getElementById("assetSearch")?.addEventListener("input", (event) => {
    assetPoolFilters.search = event.target.value;
    render(lastSnapshot);
  });

  document.querySelectorAll("[data-asset-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      assetPoolFilters[select.dataset.assetFilter] = select.value;
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-collapse-group]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const groupId = button.dataset.collapseGroup;
      collapsedAssetGroups[groupId] = !collapsedAssetGroups[groupId];
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-symbol]").forEach((row) => {
    row.addEventListener("click", () => selectSymbol(row.dataset.symbol, row.dataset.groupId));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSymbol(row.dataset.symbol, row.dataset.groupId);
      }
    });
  });

  document.querySelectorAll("[data-delete-group]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteAssetPoolGroup(button.dataset.deleteGroup);
    });
  });

  document.querySelectorAll("[data-more-symbol]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const symbol = button.dataset.moreSymbol;
      const groupId = button.closest("[data-symbol]")?.dataset.groupId || selectedGroupId;
      selectedSymbol = symbol;
      selectedGroupId = groupId;
      const rowId = `${groupId}:${symbol}`;
      const nextMenuId = openMenuInstrumentId === rowId ? null : rowId;
      openMenuInstrumentId = nextMenuId;
      openMenuPosition = nextMenuId ? getFloatingMenuPosition(button) : null;
      rightRailMode = "detail";
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-menu-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      handleInstrumentMenuAction(button.dataset.menuSymbol, button.dataset.menuAction, button.dataset.menuGroup);
    });
  });

  document.querySelectorAll("[data-rail-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.railMode === "edit") {
        beginEditInstrument(selectedSymbol);
        return;
      }
      rightRailMode = button.dataset.railMode;
      closeInstrumentRowMenu();
      render(lastSnapshot);
    });
  });

  document.querySelector("[data-rail-close]")?.addEventListener("click", () => {
    rightRailMode = "detail";
    closeInstrumentRowMenu();
    removeConfirmInstrumentId = null;
    render(lastSnapshot);
  });

  document.querySelector("[data-add-cancel]")?.addEventListener("click", () => {
    rightRailMode = "detail";
    render(lastSnapshot);
  });

  document.querySelectorAll("[data-detail-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const symbol = button.dataset.detailSymbol || selectedSymbol;
      if (button.dataset.detailAction === "edit") {
        beginEditInstrument(symbol);
      } else if (button.dataset.detailAction === "remove") {
        removeConfirmInstrumentId = symbol;
        removeConfirmGroupId = selectedGroupId;
        closeInstrumentRowMenu();
        render(lastSnapshot);
      }
    });
  });

  document.querySelector("[data-save-holding]")?.addEventListener("click", async (event) => {
    await saveManualHolding(event.currentTarget.dataset.saveHolding);
  });

  document.querySelector("[data-clear-holding]")?.addEventListener("click", async (event) => {
    await clearManualHolding(event.currentTarget.dataset.clearHolding);
  });

  document.getElementById("addInstrumentSearch")?.addEventListener("input", (event) => {
    addInstrumentState.query = event.target.value;
    addInstrumentState.selectedInstrument = null;
    addInstrumentState.saveError = "";
    addInstrumentState.results = [];
    addInstrumentState.searchStatus = "idle";
    addInstrumentState.searchError = "";
    render(lastSnapshot);
  });

  document.getElementById("addInstrumentSearch")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runInstrumentSearchNow();
    }
  });

  document.querySelector("[data-search-submit]")?.addEventListener("click", () => {
    runInstrumentSearchNow();
  });

  document.querySelectorAll("[data-search-symbol]").forEach((button) => {
    button.addEventListener("click", () => {
      addInstrumentState.selectedInstrument = addInstrumentState.results.find((item) => item.symbol === button.dataset.searchSymbol) || null;
      applyAddDefaultsForInstrument(addInstrumentState.selectedInstrument);
      render(lastSnapshot);
    });
  });

  document.querySelector("[data-clear-search-symbol]")?.addEventListener("click", () => {
    addInstrumentState.selectedInstrument = null;
    render(lastSnapshot);
  });

  document.querySelectorAll("[data-add-field]").forEach((field) => {
    field.addEventListener("change", () => {
      addInstrumentState[field.dataset.addField] = field.value;
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-add-usage]").forEach((button) => {
    button.addEventListener("click", () => {
      addInstrumentState.usage = button.dataset.addUsage;
      if (addInstrumentState.usage === "watch_only") {
        addInstrumentState.includeInMonitoring = false;
        addInstrumentState.includeInBacktest = false;
      } else if (addInstrumentState.usage === "signal_monitoring") {
        addInstrumentState.includeInMonitoring = true;
        addInstrumentState.includeInBacktest = false;
      } else if (addInstrumentState.usage === "strategy") {
        addInstrumentState.includeInMonitoring = true;
      }
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-add-switch]").forEach((field) => {
    field.addEventListener("change", () => {
      addInstrumentState[field.dataset.addSwitch] = field.checked;
      render(lastSnapshot);
    });
  });

  document.querySelector("[data-add-submit]")?.addEventListener("click", async () => {
    await submitAddedInstrument();
  });

  document.querySelector("[data-create-group]")?.addEventListener("click", async () => {
    await createAssetPoolGroup();
  });

  document.querySelectorAll("[data-edit-field]").forEach((field) => {
    field.addEventListener("change", () => {
      editInstrumentState[field.dataset.editField] = field.value;
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-edit-usage]").forEach((button) => {
    button.addEventListener("click", () => {
      editInstrumentState.usage = button.dataset.editUsage;
      if (editInstrumentState.usage === "watch_only") {
        editInstrumentState.includeInMonitoring = false;
        editInstrumentState.includeInBacktest = false;
      } else if (editInstrumentState.usage === "signal_monitoring") {
        editInstrumentState.includeInMonitoring = true;
        editInstrumentState.includeInBacktest = false;
      } else if (editInstrumentState.usage === "strategy") {
        editInstrumentState.includeInMonitoring = true;
      }
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-edit-switch]").forEach((field) => {
    field.addEventListener("change", () => {
      editInstrumentState[field.dataset.editSwitch] = field.checked;
      render(lastSnapshot);
    });
  });

  document.querySelector("[data-edit-cancel]")?.addEventListener("click", () => {
    rightRailMode = "detail";
    editInstrumentState = null;
    render(lastSnapshot);
  });

  document.querySelector("[data-edit-save]")?.addEventListener("click", async () => {
    if (!editInstrumentState?.symbol) return;
    const symbol = editInstrumentState.symbol;
    const poolItem = assetPoolItemForSymbol(symbol);
    if (isDirectStrategyPromotion(poolItem)) {
      setNotice("纳入策略需要草稿、验证回测与发布流程，当前不能直接保存为正式策略品种。");
      return;
    }
    const nextConfig = nextAssetPoolConfigForSymbol(symbol, {
      groupId: editInstrumentState.groupId,
      usage: editInstrumentState.usage,
      role: editInstrumentState.role,
      showInOverview: editInstrumentState.showInOverview,
      includeInMonitoring: editInstrumentState.includeInMonitoring,
      includeInBacktest: editInstrumentState.includeInBacktest,
      removed: false,
    });
    nextConfig.groups = withSymbolInGroup(
      withoutSymbolInGroup(normalizeAssetPoolGroups(nextConfig), selectedGroupId, symbol),
      editInstrumentState.groupId,
      symbol
    );
    const saved = await persistAssetPoolConfig(nextConfig);
    if (saved) {
      selectedGroupId = editInstrumentState.groupId;
      rightRailMode = "detail";
      editInstrumentState = null;
      closeInstrumentRowMenu();
      render(lastSnapshot);
    }
  });

  document.querySelector("[data-edit-remove]")?.addEventListener("click", (event) => {
    removeConfirmInstrumentId = event.currentTarget.dataset.editRemove;
    removeConfirmGroupId = selectedGroupId;
    render(lastSnapshot);
  });

  document.querySelector("[data-remove-cancel]")?.addEventListener("click", () => {
    removeConfirmInstrumentId = null;
    render(lastSnapshot);
  });

  document.querySelector("[data-remove-confirm]")?.addEventListener("click", async (event) => {
    const symbol = event.currentTarget.dataset.removeConfirm;
    if (!symbol) return;
    const existing = defaultPoolItemFromSnapshot(symbol);
    const sourceGroups = normalizeAssetPoolGroups(assetPoolConfig);
    const nextGroups = removeConfirmGroupId
      ? withoutSymbolInGroup(sourceGroups, removeConfirmGroupId, symbol)
      : withoutSymbolInAllGroups(sourceGroups, symbol);
    const stillInAnyGroup = nextGroups.some((group) => group.symbols.includes(symbol));
    const fallbackGroupId = nextGroups.find((group) => group.symbols.includes(symbol))?.id
      || nextGroups[0]?.id
      || existing?.groupId;
    const nextConfig = nextAssetPoolConfigForSymbol(symbol, {
      groupId: fallbackGroupId,
      usage: existing?.usage,
      role: existing?.roleKey,
      showInOverview: stillInAnyGroup ? existing?.showInOverview : false,
      includeInMonitoring: stillInAnyGroup ? existing?.includeInMonitoring : false,
      includeInBacktest: stillInAnyGroup ? existing?.includeInBacktest : false,
      removed: !stillInAnyGroup,
    });
    nextConfig.groups = nextGroups;
    const saved = await persistAssetPoolConfig(nextConfig);
    if (saved) {
      removeConfirmInstrumentId = null;
      removeConfirmGroupId = null;
      editInstrumentState = null;
      closeInstrumentRowMenu();
      rightRailMode = "detail";
      const remaining = buildAssetPoolItems(lastSnapshot.symbols || []);
      selectedSymbol = remaining[0]?.symbol || selectedSymbol;
      selectedGroupId = remaining[0]?.groupId || selectedGroupId;
      render(lastSnapshot);
    }
  });

  document.querySelector("[data-remove-backdrop]")?.addEventListener("click", (event) => {
    if (event.target.matches("[data-remove-backdrop]")) {
      removeConfirmInstrumentId = null;
      removeConfirmGroupId = null;
      render(lastSnapshot);
    }
  });

  document.querySelector(".detail-close")?.addEventListener("click", () => {
    rightRailMode = "detail";
    selectedSymbol = lastSnapshot?.symbols?.find((item) => item.symbol === "QQQ")?.symbol || "QQQ";
    render(lastSnapshot);
  });

  document.removeEventListener("click", closeAssetMenuOnDocumentClick);
  document.addEventListener("click", closeAssetMenuOnDocumentClick);
  document.removeEventListener("keydown", handleAssetPoolKeydown);
  document.addEventListener("keydown", handleAssetPoolKeydown);
}

function handleInstrumentMenuAction(symbol, action, groupId = selectedGroupId) {
  if (!symbol || !lastSnapshot) return;
  selectedSymbol = symbol;
  selectedGroupId = groupId || selectedGroupId;
  closeInstrumentRowMenu();
  if (action === "detail") {
    rightRailMode = "detail";
    render(lastSnapshot);
    return;
  }
  if (action === "edit" || action === "move_group") {
    beginEditInstrument(symbol);
    return;
  }
  if (action === "to_monitor") {
    beginEditInstrument(symbol, { usage: "signal_monitoring" });
    return;
  }
  if (action === "to_watch") {
    beginEditInstrument(symbol, { usage: "watch_only" });
    return;
  }
  if (action === "to_strategy") {
    beginEditInstrument(symbol, { usage: "strategy" });
    return;
  }
  if (action === "remove") {
    removeConfirmInstrumentId = symbol;
    removeConfirmGroupId = selectedGroupId;
    render(lastSnapshot);
  }
}

async function saveManualHolding(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  if (!normalized) return;
  const panel = document.querySelector(`[data-manual-holding-symbol="${CSS.escape(normalized)}"]`);
  if (!panel) return;
  const quantity = Number(panel.querySelector('[data-holding-field="quantity"]')?.value || 0);
  const avgCostRaw = panel.querySelector('[data-holding-field="avgCostUsdt"]')?.value || "";
  const note = panel.querySelector('[data-holding-field="note"]')?.value || "";
  if (!Number.isFinite(quantity) || quantity <= 0) {
    setNotice("请先输入大于 0 的持仓数量。");
    return;
  }
  const avgCostUsdt = avgCostRaw === "" ? null : Number(avgCostRaw);
  if (avgCostRaw !== "" && (!Number.isFinite(avgCostUsdt) || avgCostUsdt < 0)) {
    setNotice("平均成本必须是大于等于 0 的数字。");
    return;
  }
  const saved = await persistManualHoldingsConfig(nextManualHoldingsConfigForSymbol(normalized, {
    quantity,
    avgCostUsdt,
    note,
  }));
  if (saved) {
    render(lastSnapshot);
  }
}

async function clearManualHolding(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  if (!normalized) return;
  const saved = await persistManualHoldingsConfig(nextManualHoldingsConfigForSymbol(normalized, null));
  if (saved) {
    render(lastSnapshot);
  }
}

function closeAssetMenuOnDocumentClick(event) {
  if (!openMenuInstrumentId) return;
  if (event.target.closest(".instrument-row-menu") || event.target.closest("[data-more-symbol]")) return;
  closeInstrumentRowMenu();
  render(lastSnapshot);
}

function handleAssetPoolKeydown(event) {
  if (event.key !== "Escape") return;
  if (openMenuInstrumentId || removeConfirmInstrumentId || rightRailMode === "edit" || rightRailMode === "add") {
    closeInstrumentRowMenu();
    removeConfirmInstrumentId = null;
    if (rightRailMode === "edit" || rightRailMode === "add") rightRailMode = "detail";
    render(lastSnapshot);
  }
}

function bindSignalEvents() {
  document.querySelectorAll("[data-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      signalFilters[select.dataset.filter] = select.value;
      render(lastSnapshot);
    });
  });

  document.getElementById("signalSearch")?.addEventListener("input", (event) => {
    signalFilters.search = event.target.value;
    render(lastSnapshot);
  });

  document.querySelectorAll("[data-signal-id]").forEach((row) => {
    row.addEventListener("click", () => selectSignal(row.dataset.signalId));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSignal(row.dataset.signalId);
      }
    });
  });
}

function bindMonitorEvents() {
  document.querySelectorAll("[data-monitor-id]").forEach((row) => {
    row.addEventListener("click", () => selectMonitorItem(row.dataset.monitorId));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectMonitorItem(row.dataset.monitorId);
      }
    });
  });
}

function bindPortfolioEvents() {
  document.querySelectorAll("[data-portfolio-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedPortfolioMode = button.dataset.portfolioMode;
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-binance-test]").forEach((button) => {
    button.addEventListener("click", () => testBinanceConnection());
  });

  document.querySelectorAll("[data-binance-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshBinanceAccount());
  });
}

function bindPaperEvents() {
  document.querySelector("[data-paper-run]")?.addEventListener("click", async () => {
    if (!lastSnapshot) return;
    await runPaperAccountForSnapshot(lastSnapshot);
    render(lastSnapshot);
  });

  document.querySelector("[data-paper-reset]")?.addEventListener("click", async () => {
    if (!window.confirm("确认重置模拟账户？这会清空模拟持仓、净值曲线和交易记录。")) return;
    await resetPaperAccount();
  });
}

function bindSettingsEvents() {
  document.querySelectorAll("[data-settings-category]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedSettingsCategory = button.dataset.settingsCategory;
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-setting-path]").forEach((field) => {
    field.addEventListener("change", () => {
      const path = field.dataset.settingPath;
      const nextValue = normalizeSettingValue(path, field.value);
      if (String(nextValue) === String(configValue(currentConfig, path))) {
        delete settingsDraft[path];
      } else {
        settingsDraft[path] = nextValue;
      }
      render(lastSnapshot);
    });
  });

  document.querySelector("[data-auto-refresh-interval]")?.addEventListener("change", (event) => {
    saveAutoRefreshIntervalSetting(event.target.value);
    setNotice(`自动刷新间隔已设为 ${autoRefreshIntervalLabel()}`, "good");
    render(lastSnapshot);
  });

  document.querySelectorAll('[data-settings-action="reset"]').forEach((button) => {
    button.addEventListener("click", () => {
      settingsDraft = {};
      render(lastSnapshot);
    });
  });

  document.querySelectorAll("[data-binance-test]").forEach((button) => {
    button.addEventListener("click", () => testBinanceConnection());
  });

  document.querySelectorAll("[data-binance-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshBinanceAccount());
  });
}

function selectSymbol(symbol, groupId = selectedGroupId) {
  if (!symbol || !lastSnapshot) return;
  selectedSymbol = symbol;
  selectedGroupId = groupId || selectedGroupId;
  rightRailMode = "detail";
  render(lastSnapshot);
}

function selectSignal(id) {
  if (!id || !lastSnapshot) return;
  selectedSignalId = id;
  render(lastSnapshot);
}

function selectMonitorItem(id) {
  if (!id || !lastSnapshot) return;
  selectedMonitorId = id;
  render(lastSnapshot);
}

async function refresh(options = {}) {
  if (refreshInFlight) return false;
  refreshInFlight = true;
  const background = Boolean(options.background && lastSnapshot);
  const button = document.getElementById("refreshButton");
  if (button) {
    button.disabled = true;
    button.textContent = background ? "后台刷新中" : "读取中";
  }
  try {
    const [snapshotResult, configResult, assetPoolResult, manualHoldingsResult, binanceStatusResult, paperAccountResult] = await Promise.allSettled([
      fetch("/api/refresh", { cache: "no-store" }).then((response) => response.json()),
      fetch("/api/config", { cache: "no-store" }).then((response) => response.json()),
      fetch("/api/asset-pool", { cache: "no-store" }).then((response) => response.json()),
      fetch("/api/manual-holdings", { cache: "no-store" }).then((response) => response.json()),
      fetch("/api/integrations/binance/status", { cache: "no-store" }).then((response) => response.json()),
      fetch("/api/paper-account", { cache: "no-store" }).then((response) => response.json()),
    ]);

    if (configResult.status === "fulfilled" && configResult.value.ok) {
      currentConfig = configResult.value.config;
      currentConfigError = "";
      settingsCapabilities = configResult.value.capabilities || settingsCapabilities;
    } else {
      currentConfig = null;
      currentConfigError = configResult.status === "fulfilled"
        ? (configResult.value.error || "配置读取失败")
        : configResult.reason.message;
      settingsCapabilities = {
        read_config: false,
        save_draft: false,
        run_validation_backtest: false,
        publish_config: false,
        rollback_config: false,
      };
    }

    if (assetPoolResult.status === "fulfilled" && assetPoolResult.value.ok) {
      assetPoolConfig = assetPoolResult.value.config || { version: 1, instruments: {} };
      assetPoolGroups = normalizeAssetPoolGroups(assetPoolConfig);
      assetPoolCapabilities = {
        ...assetPoolCapabilities,
        ...(assetPoolResult.value.capabilities || {}),
      };
    } else {
      assetPoolConfig = { version: 1, instruments: {} };
      assetPoolGroups = normalizeAssetPoolGroups(assetPoolConfig);
      assetPoolCapabilities = {
        persistConfig: false,
        removeInstrument: false,
      };
    }

    if (manualHoldingsResult.status === "fulfilled" && manualHoldingsResult.value.ok) {
      manualHoldingsConfig = manualHoldingsResult.value.config || { version: 1, holdings: {} };
      manualHoldingsCapabilities = {
        ...manualHoldingsCapabilities,
        ...(manualHoldingsResult.value.capabilities || {}),
      };
    } else {
      manualHoldingsConfig = { version: 1, holdings: {} };
      manualHoldingsCapabilities = {
        read: false,
        persistConfig: false,
      };
    }

    if (binanceStatusResult.status === "fulfilled" && binanceStatusResult.value.ok) {
      binanceStatus = {
        ...binanceStatus,
        ...(binanceStatusResult.value.status || {}),
      };
      if (!binanceStatus.configured) {
        binanceAccount = null;
      }
    } else {
      binanceStatus = {
        configured: false,
        connected: false,
        accountType: "SPOT",
        readOnly: true,
        apiKeyMasked: null,
        lastSyncedAt: null,
      };
      binanceAccount = null;
    }

    if (paperAccountResult.status === "fulfilled" && paperAccountResult.value.ok) {
      paperAccount = normalizePaperAccount(paperAccountResult.value.account);
      paperAccountCapabilities = {
        ...paperAccountCapabilities,
        ...(paperAccountResult.value.capabilities || {}),
      };
      paperAccountError = "";
    } else {
      paperAccountError = paperAccountResult.status === "fulfilled"
        ? (paperAccountResult.value.error || "模拟账户读取失败")
        : paperAccountResult.reason.message;
      paperAccountCapabilities = { read: false, reset: false, run: false };
    }

    await loadBinanceAccountQuietly();

    if (snapshotResult.status !== "fulfilled") {
      throw new Error(snapshotResult.reason.message || "读取失败");
    }
    const payload = snapshotResult.value;
    if (!payload.ok) {
      throw new Error(payload.error || "读取失败");
    }
    if (paperAccount.settings?.autoRun !== false && paperAccountCapabilities.run) {
      await runPaperAccountForSnapshot(payload.snapshot, { silent: true });
    }
    render(payload.snapshot);
    return true;
  } catch (error) {
    setNotice(error.message);
    return false;
  } finally {
    refreshInFlight = false;
    if (button) {
      button.disabled = false;
      button.textContent = "刷新";
    }
    if (!options.auto) {
      scheduleAutoRefresh();
    }
  }
}

async function bootDashboard() {
  let restored = restoreDashboardCache(loadDashboardCache());
  if (!restored) {
    restored = restoreDashboardCache(await loadServerDashboardCache());
  }
  refresh({ background: restored });
}

document.getElementById("refreshButton").addEventListener("click", () => refresh());
window.addEventListener("hashchange", () => {
  if (lastSnapshot) render(lastSnapshot);
});
window.addEventListener("beforeunload", () => flushDashboardCache(lastSnapshot));
ensurePaperNavItem();
bootDashboard();
