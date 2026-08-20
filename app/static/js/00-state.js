/* MealKey UI — shared state, selectors, and constants (classic global script) */

const state = {
  stores: [],
  currentStoreId: null,
  dashboard: null,
  runtimeWorkspace: null,
  dailyPlan: null,
  managerBrief: null,
  operatingEvents: null,
  strategyMemory: null,
  competitionMap: null,
  collectionRuns: [],
  platformIntel: { items: [], last_run: null, sources: [] },
  platformLinks: [],
  publicConfig: null,
  settingsOverview: null,
  storefrontAiPlan: null,
  amapInstance: null,
  pendingPlatform: null,
  pendingPlatformKey: null,
  activeConnectCode: null,
  connectPollTimer: null,
  connectPollInFlight: false,
  pendingHomeAttachments: [],
  voiceInput: {
    recognition: null,
    listening: false,
    supported: null,
    interimText: "",
  },
  audioTranscription: {
    processing: false,
  },
  competitionFilter: "intensity",
  chatMessages: [],
  activeWorkspace: "section-overview",
  rightRailOpen: false,
  opsRailCollapsed: false,
  mobileTab: "today",
  focusOverrideCard: null,
  focusedWorkKey: null,
  focusedWorkSlot: null,
  pendingWorkThreadId: null,
  understanding: null,
  menuDeepDiagnosis: null,
  ownerProfile: null,
  enterpriseSettings: null,
  pendingAvatarDataUrl: null,
  commercialBoard: null,
  lastAuthError: null,  // { type: "network"|"token_expired"|"server", message: "..." }
  pendingImportType: null,  // "funnel"|"ads"|"reviews"|"campaigns"
};

const STORE_SELECTION_KEY = "mealky_current_store_id";

function persistedStoreId() {
  try {
    return String(window.localStorage.getItem(STORE_SELECTION_KEY) || "").trim();
  } catch (_) {
    return "";
  }
}

function persistStoreId(storeId) {
  const id = String(storeId || "").trim();
  try {
    if (!id) {
      window.localStorage.removeItem(STORE_SELECTION_KEY);
      return;
    }
    window.localStorage.setItem(STORE_SELECTION_KEY, id);
  } catch (_) {
    /* ignore */
  }
}

function isStoreSwitch(nextStoreId) {
  const next = String(nextStoreId || "").trim();
  const current = String(state.currentStoreId || "").trim();
  return Boolean(next && current && next !== current);
}

function resetStoreScopedUiState() {
  if (typeof stopConnectCodePolling === "function") stopConnectCodePolling();
  if (typeof clearHomeAttachments === "function") clearHomeAttachments();
  state.dashboard = null;
  state.runtimeWorkspace = null;
  state.dailyPlan = null;
  state.managerBrief = null;
  state.operatingEvents = null;
  state.strategyMemory = null;
  state.competitionMap = null;
  state.collectionRuns = [];
  state.platformIntel = { items: [], last_run: null, sources: [] };
  state.platformLinks = [];
  state.settingsOverview = null;
  state.storefrontAiPlan = null;
  state.pendingPlatform = null;
  state.pendingPlatformKey = null;
  state.activeConnectCode = null;
  state.connectPollInFlight = false;
  state.pendingHomeAttachments = [];
  state.chatMessages = [];
  state.focusOverrideCard = null;
  state.focusedWorkKey = null;
  state.focusedWorkSlot = null;
  state.pendingWorkThreadId = null;
  state.understanding = null;
  state.menuDeepDiagnosis = null;
  state.ownerProfile = null;
  state.enterpriseSettings = null;
  state.pendingAvatarDataUrl = null;
  state.commercialBoard = null;
  state.actionTraces = [];
  state.promoPoster = null;
  state._lastNotifId = null;
  state._fullDashboardLoaded = false;
  if (typeof renderChatMessages === "function") renderChatMessages();
}

function normalizeStoreFingerprintPart(value) {
  return String(value || "").trim().toLowerCase();
}

function storeFingerprint(store) {
  const name = normalizeStoreFingerprintPart(store?.name);
  const city = normalizeStoreFingerprintPart(store?.city);
  const category = normalizeStoreFingerprintPart(store?.category);
  return [name, city, category].filter(Boolean).join("|") || String(store?.id || "").trim();
}

function dedupeStores(stores, preferredId = "") {
  const keepFirstId = String(preferredId || "").trim();
  const list = Array.isArray(stores) ? [...stores] : [];
  if (keepFirstId) {
    list.sort((a, b) => {
      if (a?.id === keepFirstId) return -1;
      if (b?.id === keepFirstId) return 1;
      return 0;
    });
  }
  const seen = new Set();
  return list.filter((store) => {
    const key = storeFingerprint(store);
    if (!key) return false;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const qs = (selector) => document.querySelector(selector);

const qsa = (selector) => Array.from(document.querySelectorAll(selector));

const WORKSPACE_VIEWS = {
  "section-overview": {
    panel: "section-home",
    label: "今天",
    title: "AI 经营队列",
    summary: "现在需要你 · MealKey 正在做 · 结果 · 机会。",
    meta: "当前工作区：今天",
  },
  "section-collection": {
    panel: "section-collection",
    label: "门店",
    title: "数据采集 Agent：先看见再发生什么",
    summary: "平台连接、公开页快照与变化证据。",
    meta: "当前工作区：数据采集 Agent",
  },
  "section-diagnosis": {
    panel: "section-diagnosis",
    label: "经营",
    title: "先把问题讲明白，再决定今天做什么",
    summary: "多周期变化、根因排序和下一步动作。",
    meta: "当前工作区：经营诊断",
  },
  "section-competition-agent": {
    panel: "section-competition-agent",
    label: "经营",
    title: "先确认周边怎么变，再决定要不要跟动作",
    summary: "重点竞品、最近变化和建议动作。",
    meta: "当前工作区：商圈竞争",
  },
  "section-menu": {
    panel: "section-menu",
    label: "经营",
    title: "先把菜单结构补齐，再谈转化放大",
    summary: "菜单缺口、套餐机会和低效 SKU。",
    meta: "当前工作区：菜单结构",
  },
  "section-product": {
    panel: "section-product",
    label: "经营",
    title: "一次只处理一个商品动作，便于验证结果",
    summary: "主推商品、候选池和单变量方案。",
    meta: "当前工作区：商品优化",
  },
  "section-storefront": {
    panel: "section-storefront",
    label: "经营",
    title: "优先修第一眼和转化承接",
    summary: "店页装修、主图和分类承接。",
    meta: "当前工作区：线上装修",
  },
  "section-growth": {
    panel: "section-growth",
    label: "经营",
    title: "把跨 Agent 动作排成今天唯一主动作",
    summary: "判断值不值得做、好不好做、要不要延后。",
    meta: "当前工作区：增长主线",
  },
  "section-matrix": {
    panel: "section-matrix",
    label: "行动",
    title: "今天可并行落地的运营任务",
    summary: "待确认、实验中、已完成；有任务再进，无任务就回今日。",
    meta: "当前工作区：行动",
  },
  "section-promo": {
    panel: "section-promo",
    label: "行动",
    title: "活动值不值得参加，先过 Profit Gate",
    summary: "活动到期、补贴力度与到手率。",
    meta: "当前工作区：活动运营",
  },
  "section-ads": {
    panel: "section-ads",
    label: "经营",
    title: "预算与 ROI，不拿流水换亏损",
    summary: "投放预算、目标品与预估 ROI。",
    meta: "当前工作区：流量",
  },
  "section-crm": {
    panel: "section-crm",
    label: "经营",
    title: "理解谁在消费，再决定召回策略",
    summary: "复购率、客群分层与召回动作。",
    meta: "当前工作区：用户关系 Agent",
  },
  "section-service": {
    panel: "section-service",
    label: "行动",
    title: "IM 与差评积压后台处理",
    summary: "待回复、差评与主题拆解。",
    meta: "当前工作区：AI客服 Agent",
  },
  "section-review": {
    panel: "section-review",
    label: "经营",
    title: "从评价主题读懂用户偏好",
    summary: "评分、主题与回复动作。",
    meta: "当前工作区：评分评价 Agent",
  },
  "section-store_matrix": {
    panel: "section-store_matrix",
    label: "行动",
    title: "一店多线上店机会",
    summary: "兄弟店与新概念候选。",
    meta: "当前工作区：线上门店增长 Agent",
  },
  "section-ai": {
    panel: "section-ai",
    label: "做事",
    title: "你想让 MealKey 帮你做到什么？",
    summary: "说出目标或问题；AI 店长拆解并调度团队，你不用点功能。",
    meta: "当前工作区：做事",
  },
  "section-record": {
    panel: "section-record",
    label: "记录",
    title: "做过、正在做、已验证",
    summary: "实验回看与策略记忆；MealKey 会对自己的建议负责。",
    meta: "当前工作区：记录",
  },
  "section-settings": {
    panel: "section-settings",
    label: "能力与设置",
    title: "需要时再打开细节",
    summary: "门店资料、平台连接与专业 Agent 能力。",
    meta: "当前工作区：能力与设置",
  },
};

const HOME_SECTION_IDS = new Set([
  "section-overview",
  "section-home",
  "section-today-mainline",
  "section-worth-doing",
  "section-auto-activity",
  "section-verified-wins",
  "section-events",
  "section-actions",
  "section-home-links",
]);

/** 13 Agent 运营团队（老板只面对 AI 店长；以下为被调度的专业 Agent） */

const AGENT_TEAM = [
  {
    key: "collection",
    label: "数据采集",
    layer: 1,
    layerLabel: "数据感知",
    center: "sense",
    section: "section-collection",
    navGroup: "store",
    capability: "connect_scan",
    kicker: "Collection Agent",
    summary: "看见发生了什么：平台连接与公开页快照。",
    copy: "连接手机端只读页面，持续写入竞品与本店公开证据。",
  },
  {
    key: "competition",
    label: "商圈竞争",
    layer: 1,
    layerLabel: "数据感知",
    center: "sense",
    section: "section-competition-agent",
    navGroup: "ops",
    capability: "scan_advise",
    kicker: "Competition Agent",
    summary: "市场发生了什么？",
    copy: "重点竞品、价格与套餐变化、威胁信号。",
  },
  {
    key: "review",
    label: "评分评价",
    layer: 1,
    layerLabel: "数据感知",
    center: "sense",
    section: "section-review",
    navGroup: "ops",
    capability: "matrix_enable",
    kicker: "Review Agent",
    summary: "用户为什么喜欢/不喜欢？",
    copy: "评分主题、差评归因与回复策略。",
  },
  {
    key: "diagnosis",
    label: "经营诊断",
    layer: 2,
    layerLabel: "经营理解",
    center: "diagnose",
    section: "section-diagnosis",
    navGroup: "ops",
    capability: "run",
    kicker: "Diagnosis Agent",
    summary: "为什么发生？",
    copy: "多周期根因、Observation / Hypothesis 与下一步。",
  },
  {
    key: "crm",
    label: "用户关系",
    layer: 2,
    layerLabel: "经营理解",
    center: "diagnose",
    section: "section-crm",
    navGroup: "ops",
    capability: "matrix_create",
    kicker: "CRM Agent",
    summary: "谁在消费？生命周期如何？",
    copy: "复购、分层与召回动作。",
  },
  {
    key: "menu",
    label: "菜单分析",
    layer: 3,
    layerLabel: "商品能力",
    center: "product",
    section: "section-menu",
    navGroup: "ops",
    capability: "apply",
    kicker: "Menu Agent",
    summary: "卖什么结构？",
    copy: "菜单缺口、套餐与低效 SKU。",
  },
  {
    key: "product",
    label: "商品优化",
    layer: 3,
    layerLabel: "商品能力",
    center: "product",
    section: "section-product",
    navGroup: "ops",
    capability: "create",
    kicker: "Product Agent",
    summary: "单品怎么卖？",
    copy: "主推商品、候选池与单变量方案。",
  },
  {
    key: "storefront",
    label: "线上装修",
    layer: 3,
    layerLabel: "商品能力",
    center: "product",
    section: "section-storefront",
    navGroup: "ops",
    capability: "create_ai",
    kicker: "Storefront Agent",
    summary: "第一眼怎么承接？",
    copy: "店页主图、分类与转化承接。",
  },
  {
    key: "promo",
    label: "平台活动",
    layer: 4,
    layerLabel: "增长执行",
    center: "execute",
    section: "section-promo",
    navGroup: "execute",
    capability: "matrix_gated",
    kicker: "Promo Agent",
    summary: "活动值不值得参加？",
    copy: "活动到期、补贴与 Profit Gate。",
  },
  {
    key: "ads",
    label: "投流",
    layer: 4,
    layerLabel: "增长执行",
    center: "execute",
    section: "section-ads",
    navGroup: "ops",
    capability: "matrix_gated",
    kicker: "Ads Agent",
    summary: "预算与 ROI，不买流水。",
    copy: "投放预算、目标品与预估 ROI。",
  },
  {
    key: "service",
    label: "AI客服",
    layer: 4,
    layerLabel: "增长执行",
    center: "execute",
    section: "section-service",
    navGroup: "execute",
    capability: "matrix_enable",
    kicker: "Service Agent",
    summary: "用户沟通如何承接？",
    copy: "待回复、差评积压与话术。",
  },
  {
    key: "store_matrix",
    label: "线上门店增长",
    layer: 5,
    layerLabel: "规模化",
    center: "scale",
    section: "section-store_matrix",
    navGroup: "execute",
    capability: "matrix_unlock",
    kicker: "Store Matrix Agent",
    summary: "一店多线上店怎么放大？",
    copy: "工作餐/夜宵/性价比等概念店机会。",
  },
  {
    key: "growth",
    label: "增长策略",
    layer: 5,
    layerLabel: "规模化",
    center: "scale",
    section: "section-growth",
    navGroup: "ops",
    capability: "rebuild_rank",
    kicker: "Growth Agent",
    summary: "今天只做哪一件？",
    copy: "跨 Agent 排序、主实验与禁做清单。",
  },
];

const AGENT_SECTION_MAP = Object.fromEntries(AGENT_TEAM.map((agent) => [agent.key, agent.section]));

const MATRIX_AGENT_DEFS = AGENT_TEAM.filter((agent) =>
  ["matrix_create", "matrix_enable", "matrix_gated", "matrix_unlock"].includes(agent.capability),
).map((agent) => ({
  key: agent.key,
  label: agent.label,
  kicker: agent.kicker,
  summary: agent.summary,
  copy: agent.copy,
}));

const NAV_KEY_BY_SECTION = {
  "section-overview": "today",
  "section-home": "today",
  "section-today-mainline": "today",
  "section-worth-doing": "today",
  "section-auto-activity": "today",
  "section-verified-wins": "today",
  "section-events": "today",
  "section-actions": "today",
  "section-home-links": "today",
  "section-ai": "do",
  "section-record": "record",
  "section-diagnosis": "skills",
  "section-growth": "skills",
  "section-competition-agent": "skills",
  "section-menu": "skills",
  "section-product": "skills",
  "section-storefront": "skills",
  "section-crm": "skills",
  "section-review": "skills",
  "section-ads": "skills",
  "section-matrix": "skills",
  "section-promo": "skills",
  "section-service": "skills",
  "section-store_matrix": "skills",
  "section-collection": "skills",
  "section-settings": "skills",
};

function agentTeamDef(agentKey) {
  return AGENT_TEAM.find((agent) => agent.key === agentKey) || null;
}

function agentSectionId(agentKey) {
  return AGENT_SECTION_MAP[agentKey] || null;
}

function isMatrixWorkspace(id) {
  if (!id) return false;
  if (id === "section-matrix") return true;
  return MATRIX_AGENT_DEFS.some((item) => id === `section-${item.key}`);
}

function workspaceView(id) {
  return (
    WORKSPACE_VIEWS[id] || {
      panel: id,
      label: "当前工作台",
      title: "继续处理当前模块",
      summary: "专注当前模块，完成后可返回首页晨报。",
      meta: "当前工作区",
    }
  );
}

function isHomeWorkspace(id) {
  return HOME_SECTION_IDS.has(id || "section-overview");
}

function renderWorkspaceHeader(view, { isHome = false } = {}) {
  const label = qs("#workspaceLabel");
  const heading = qs("#workspaceHeading");
  const summary = qs("#workspaceSummary");
  const meta = qs("#workspaceMeta");
  const backHome = qs("#backHomeBtn");
  if (label) label.textContent = view.label;
  if (heading) heading.textContent = view.title;
  if (summary) summary.textContent = view.summary;
  if (meta) meta.textContent = view.meta;
  if (backHome) backHome.hidden = isHome;
}

let amapSdkPromise = null;

const DEFAULT_COMMAND_CHIPS = [
  { label: "这个月做到20万", prompt: "这个月做到20万营业额" },
  { label: "利润太低了", prompt: "利润太低了，先帮我找原因和动作" },
  { label: "牛肉饭做到前三", prompt: "把牛肉饭做到附近前三" },
];

const GAP_LABELS = {
  priority_style: "经营原则未确认",
  lunch_capacity: "午餐产能未确认",
  profit_floor: "利润底线未确认",
  hero_item_floor_price: "招牌菜成本/底价未确认",
  low_risk_auto: "低风险自动权限未确认",
  ads_daily_budget: "广告日预算未确认",
  weekend_strategy: "周末策略未确认",
  competitor_focus: "重点竞品未确认",
  key_constraint: "关键经营约束未确认",
  platform_connected: "平台尚未连接",
  risk_boundary: "低风险自动权限未确认",
  mos_gap: "经营底线未确认",
};
