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
  understanding: null,
  menuDeepDiagnosis: null,
  ownerProfile: null,
  pendingAvatarDataUrl: null,
};

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

function showToast(message, type = "info") {
  const host = qs("#toastHost");
  if (!host || !message) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = String(message);
  host.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  window.setTimeout(() => {
    toast.classList.remove("show");
    window.setTimeout(() => toast.remove(), 220);
  }, type === "error" ? 4200 : 2800);
}

function notifySuccess(message) {
  showToast(message, "success");
}

function notifyError(message) {
  showToast(message, "error");
}

function notifyInfo(message) {
  showToast(message, "info");
}

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

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatDelta(delta, digits = 1) {
  if (delta === null || delta === undefined || Number.isNaN(Number(delta))) return "--";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${Number(delta).toFixed(digits)}%`;
}

function formatMetricValue(key, value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  if (key === "gmv") return `¥${Math.round(value).toLocaleString("zh-CN")}`;
  if (key === "ctr" || key === "cvr") return `${(Number(value) * 100).toFixed(1)}%`;
  return Number(value).toLocaleString("zh-CN");
}

function formatStatus(status) {
  const map = {
    proposed: "等你确认",
    adopted: "准备执行",
    executed: "已经做了",
    pending: "等结果",
    positive: "有效，继续",
    neutral: "先继续看",
    negative: "先回退",
    archived: "已归档",
    aligned: "已对齐",
    partial: "部分对齐",
    conflict: "口径冲突",
    missing_documents: "缺资料",
    limited: "证据有限",
    ready: "现在能做",
    blocked: "先补条件",
  };
  return map[status] || status || "待处理";
}

function formatReadiness(value) {
  const map = {
    aligned: "已对齐",
    partial: "部分对齐",
    limited: "证据有限",
    blocked: "阻塞",
    ready: "可执行",
  };
  return map[value] || value || "--";
}

function actionQueueBrief(agent = {}) {
  const current = agent.current_action;
  const blocker = (agent.blockers || [])[0];
  const parts = [];
  if (current) {
    parts.push(
      `当前动作：${current.title || formatExecutionPhase(current.execution_phase)}${
        current.phase_reason || current.next_decision ? `（${current.phase_reason || current.next_decision}）` : ""
      }`,
    );
  }
  if (blocker) parts.push(`阻塞：${blocker}`);
  return parts.join(" · ");
}

function formatExecutionPhase(phase) {
  const map = {
    execute_now: "现在执行",
    observe: "观察中",
    review: "待复盘",
    deferred: "后备动作",
    archived: "已归档",
  };
  return map[phase] || phase || "待处理";
}

function executionPhaseClass(phase) {
  return String(phase || "execute_now").replace(/[^a-z_]/g, "");
}

function workflowNote(action) {
  return (
    action?.phase_reason ||
    action?.next_decision ||
    action?.generated_content?.deferred_reason ||
    (action?.generated_content ? Object.values(action.generated_content).filter(Boolean)[0] : null) ||
    action?.summary ||
    "先用单变量动作验证问题。"
  );
}

function statusClass(status) {
  return String(status || "proposed").replace(/[^a-z_]/g, "");
}

function takeTop(list, count = 3) {
  return (list || []).slice(0, count);
}

function greetingByHour() {
  const hour = new Date().getHours();
  if (hour < 6) return "凌晨好，老板";
  if (hour < 12) return "早上好，老板";
  if (hour < 18) return "下午好，老板";
  return "晚上好，老板";
}

function formatDisplayDate() {
  const now = new Date();
  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][now.getDay()];
  return `今天 ${now.getMonth() + 1} 月 ${now.getDate()} 日 ${weekday}`;
}

function formatShortDate(dateLike) {
  if (!dateLike) return "--";
  const date = new Date(dateLike);
  if (Number.isNaN(date.getTime())) return String(dateLike);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function imageForFood(name) {
  const storeId = state.currentStoreId || "demo";
  return `/stores/${encodeURIComponent(storeId)}/item-image?name=${encodeURIComponent(name || "中式快餐")}`;
}

function apiAuthHeaders(extra = {}) {
  const headers = { ...extra };
  const token = window.localStorage.getItem("mealky_api_token");
  if (token) headers["x-api-token"] = token;
  return headers;
}

function actionImpact(action) {
  const score = Number(action?.expected_lift_pct_high ?? action?.expected_lift_pct_low ?? 0);
  if (score >= 10) return { label: "高", className: "high" };
  if (score >= 6) return { label: "中", className: "medium" };
  return { label: "低", className: "low" };
}

function actionDifficulty(action) {
  const actionType = action?.action_type || "";
  if (actionType === "store_discount") return { label: "高", className: "high" };
  if (actionType === "add_set_meal") return { label: "中", className: "medium" };
  return { label: "低", className: "low" };
}

function cardTone(kind) {
  if (kind === "risk") return { className: "soft-red", icon: "↘", accent: "风险", footer: "查看昨日经营下滑原因" };
  if (kind === "action") return { className: "soft-orange", icon: "✦", accent: "机会", footer: "查看机会包" };
  return { className: "soft-blue", icon: "◌", accent: "资料", footer: "查看资料状态" };
}

async function fetchJson(url, options = {}) {
  const headers = apiAuthHeaders(
    options.headers instanceof Headers
      ? Object.fromEntries(options.headers.entries())
      : options.headers || {},
  );
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

function hasPendingHomeAttachments() {
  return Array.isArray(state.pendingHomeAttachments) && state.pendingHomeAttachments.length > 0;
}

function renderHomeAttachments() {
  const host = qs("#commandBarAttachments");
  if (!host) return;
  const files = state.pendingHomeAttachments || [];
  if (!files.length) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  host.hidden = false;
  host.innerHTML = files
    .map(
      (file, index) => `
        <div class="command-bar-attachment">
          <span class="name">${escapeHtml(file.name)}</span>
          <span class="meta">${Math.max(1, Math.round(file.size / 1024))}KB</span>
          <button type="button" data-remove-home-file="${index}" aria-label="移除 ${escapeHtml(file.name)}">×</button>
        </div>
      `,
    )
    .join("");
}

function queueHomeAttachments(fileList) {
  const nextFiles = Array.from(fileList || []);
  if (!nextFiles.length) return;
  const merged = [...(state.pendingHomeAttachments || [])];
  nextFiles.forEach((file) => {
    const exists = merged.some(
      (item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified,
    );
    if (!exists) merged.push(file);
  });
  state.pendingHomeAttachments = merged;
  renderHomeAttachments();
}

function setHomeChatDropState(active) {
  const dock = qs("#homeChatDock");
  const hint = qs("#commandBarDropHint");
  if (dock) dock.classList.toggle("is-dragover", !!active);
  if (hint) hint.hidden = !active;
}

function ingestHomeAttachments(files, { source = "upload" } = {}) {
  const nextFiles = Array.from(files || []);
  if (!nextFiles.length) return;
  queueHomeAttachments(nextFiles);
  const input = qs("#homeChatInput");
  if (input && !input.value.trim() && nextFiles[0]) {
    input.value = "请先读一下这些文件，告诉我最重要的问题和建议";
  }
  notifySuccess(
    source === "drop"
      ? `已接住 ${nextFiles.length} 个文件，发送后我会先解析再回答`
      : `已添加 ${nextFiles.length} 个文件，发送后我会先解析再回答`,
  );
  input?.focus();
}

function clearHomeAttachments() {
  state.pendingHomeAttachments = [];
  const input = qs("#commandBarFileInput");
  if (input) input.value = "";
  renderHomeAttachments();
}

function removeHomeAttachment(index) {
  state.pendingHomeAttachments = (state.pendingHomeAttachments || []).filter((_, i) => i !== index);
  renderHomeAttachments();
}

function setVoiceUiState(status, message = "") {
  const button = qs("#commandBarMicBtn");
  const liveButton = qs("#commandBarLiveVoiceBtn");
  const input = qs("#homeChatInput");
  if (button) {
    button.dataset.state = status;
    button.classList.toggle("is-listening", status === "listening");
    button.classList.toggle("is-processing", status === "processing");
    button.setAttribute("aria-pressed", status === "listening" ? "true" : "false");
    button.title =
      status === "listening" ? "点击结束语音输入" : status === "processing" ? "正在整理语音…" : "语音输入";
  }
  if (liveButton) {
    liveButton.dataset.state = status;
    liveButton.classList.toggle("is-active", status === "listening");
    liveButton.classList.toggle("is-processing", status === "processing");
    liveButton.textContent =
      status === "listening" ? "结束实时语音" : status === "processing" ? "正在整理语音…" : "实时说一句";
  }
  if (input && message) input.placeholder = message;
}

function resetVoiceUiState() {
  state.voiceInput.interimText = "";
  setVoiceUiState("idle", "直接告诉我你的目标或问题…");
}

function setAudioTranscriptionState(processing, message = "") {
  state.audioTranscription.processing = processing;
  const button = qs("#commandBarAudioToolBtn");
  const input = qs("#homeChatInput");
  if (button) {
    button.disabled = processing;
    button.classList.toggle("is-processing", processing);
    button.textContent = processing ? "正在转写录音…" : "上传音频转写";
  }
  if (input && message) input.placeholder = message;
}

function appendHomeInputText(text, { replace = false } = {}) {
  const input = qs("#homeChatInput");
  if (!input || !text) return;
  if (replace || !input.value.trim()) {
    input.value = text;
  } else {
    input.value = `${input.value.trim()} ${text}`.trim();
  }
  input.focus();
}

function speechRecognitionCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function stopVoiceInput() {
  const recognition = state.voiceInput?.recognition;
  if (recognition && state.voiceInput.listening) {
    state.voiceInput.listening = false;
    setVoiceUiState("processing", "正在整理你的语音…");
    recognition.stop();
    return true;
  }
  return false;
}

function startVoiceInput() {
  const SpeechRecognition = speechRecognitionCtor();
  if (!SpeechRecognition) {
    notifyError("当前浏览器暂不支持语音输入，请直接打字或上传音频文件");
    qs("#homeChatInput")?.focus();
    return;
  }
  const input = qs("#homeChatInput");
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;
  state.voiceInput.recognition = recognition;
  state.voiceInput.listening = true;
  state.voiceInput.interimText = input?.value || "";
  setVoiceUiState("listening", "正在听，点麦克风可结束…");
  recognition.onresult = (event) => {
    const results = Array.from(event.results || []);
    const interim = results.map((row) => row?.[0]?.transcript || "").join("").trim();
    if (interim) {
      state.voiceInput.interimText = interim;
      appendHomeInputText(interim, { replace: true });
    }
  };
  recognition.onerror = (event) => {
    state.voiceInput.listening = false;
    state.voiceInput.recognition = null;
    resetVoiceUiState();
    const reason =
      event?.error === "not-allowed"
        ? "麦克风权限未开启，请允许浏览器使用麦克风。"
        : "语音识别失败，请重试、直接打字，或上传音频文件。";
    notifyError(reason);
  };
  recognition.onend = () => {
    state.voiceInput.listening = false;
    state.voiceInput.recognition = null;
    resetVoiceUiState();
    if (state.voiceInput.interimText) {
      appendHomeInputText(state.voiceInput.interimText, { replace: true });
      notifySuccess("语音已写入输入框，可以直接发送。");
    }
  };
  recognition.start();
}

function toggleVoiceInput() {
  if (state.voiceInput.listening) {
    stopVoiceInput();
    return;
  }
  startVoiceInput();
}

async function transcribeAudioFiles(fileList) {
  const files = Array.from(fileList || []).filter(Boolean);
  if (!files.length) return;
  const input = qs("#homeChatInput");
  const audioInput = qs("#commandBarAudioInput");
  setAudioTranscriptionState(true, "正在转写录音文件…");
  try {
    const transcripts = [];
    const warnings = [];
    for (const file of files) {
      const form = new FormData();
      form.set("file", file, file.name);
      const response = await fetch(`/speech/transcribe`, {
        method: "POST",
        headers: apiAuthHeaders(),
        body: form,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `录音转写失败：${response.status}`);
      }
      const payload = await response.json();
      const text = String(payload.text || "").trim();
      if (text) {
        transcripts.push(
          files.length === 1 ? text : `【录音 ${file.name}】${text}`,
        );
      }
      (payload.warnings || []).forEach((warning) => {
        if (warning && !warnings.includes(warning)) warnings.push(warning);
      });
    }
    const merged = transcripts.join("\n\n").trim();
    if (!merged) {
      throw new Error("录音里没有转出可用文本");
    }
    appendHomeInputText(merged, { replace: !input?.value.trim() });
    if (audioInput) audioInput.value = "";
    notifySuccess(files.length === 1 ? "录音已转成文字，可以直接发送。" : `已完成 ${files.length} 段录音转写。`);
    if (warnings[0]) notifyInfo(warnings[0]);
    input?.focus();
  } catch (error) {
    notifyError(error.message || "录音转写失败");
  } finally {
    setAudioTranscriptionState(false, "直接告诉我你的目标或问题…");
  }
}

async function fetchDashboardBundle(storeId, { refresh = false } = {}) {
  return fetchJson(
    refresh ? `/workspace/stores/${storeId}/refresh` : `/workspace/stores/${storeId}/dashboard`,
    refresh ? { method: "POST" } : undefined,
  );
}

async function fetchRuntimeWorkspace(storeId) {
  return fetchJson(`/v1/stores/${storeId}/workspace`).catch(() => null);
}

async function fetchRuntimeDailyPlan(storeId) {
  return fetchJson(`/stores/${storeId}/daily-plan`).catch(() => null);
}

let amapSdkPromise = null;

function loadAmapSdk(config) {
  if (window.AMap) return Promise.resolve(window.AMap);
  if (!config?.js_api_key) return Promise.reject(new Error("未配置高德 JS API Key"));
  if (amapSdkPromise) return amapSdkPromise;
  if (config.security_code) {
    window._AMapSecurityConfig = { securityJsCode: config.security_code };
  }
  amapSdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.js_api_key)}`;
    script.async = true;
    script.onload = () => resolve(window.AMap);
    script.onerror = () => reject(new Error("高德地图 SDK 加载失败"));
    document.head.appendChild(script);
  });
  return amapSdkPromise;
}

function renderFallbackCompetitionMap(payload, message) {
  const container = qs("#competitionMap");
  if (!payload) {
    container.innerHTML = `<div class="map-empty">${escapeHtml(message || "缺少门店经纬度，暂时无法生成竞争地图。")}</div>`;
    return;
  }
  const latRange = Math.max(payload.radius_m / 111000, 0.005);
  const longitudeScale = Math.cos((payload.center_latitude * Math.PI) / 180) || 0.7;
  const lngRange = Math.max(payload.radius_m / (111000 * longitudeScale), 0.005);
  const points = [
    {
      name: payload.store_name,
      latitude: payload.center_latitude,
      longitude: payload.center_longitude,
      store: true,
    },
    ...(payload.competitors || []),
  ];
  container.innerHTML = `
    <div class="map-radius-ring"></div>
    ${points
      .map((point) => {
        const left = Math.max(8, Math.min(92, 50 + ((point.longitude - payload.center_longitude) / lngRange) * 40));
        const topPosition = Math.max(8, Math.min(92, 50 - ((point.latitude - payload.center_latitude) / latRange) * 40));
        return `
          <div class="fallback-map-point ${point.store ? "store" : ""}" style="left:${left}%;top:${topPosition}%;" title="${escapeHtml(point.name)}"></div>
          <div class="fallback-map-label" style="left:${left}%;top:${topPosition}%;">${escapeHtml(point.store ? "本店" : point.name)}</div>
        `;
      })
      .join("")}
  `;
  if (message) qs("#competitionCollectionStatus").textContent = message;
}

async function renderCompetitionMap() {
  const payload = state.competitionMap;
  const amapConfig = state.publicConfig?.amap;
  const collectionConfig = state.publicConfig?.competition_collection;
  const pointCount = payload?.competitors?.length || 0;
  const schedule = collectionConfig?.schedule || "07:30";
  const scanButton = qs("#scanCompetitionBtn");
  scanButton.disabled = !collectionConfig?.enabled;
  scanButton.title = collectionConfig?.enabled ? "立即执行一次竞品扫描" : "请先配置高德或授权数据源";

  if (!payload) {
    renderFallbackCompetitionMap(null);
    qs("#competitionCollectionStatus").textContent = "门店缺少经纬度或地图数据不可用。";
    return;
  }
  if (!amapConfig?.enabled) {
    renderFallbackCompetitionMap(
      payload,
      `已展示坐标降级地图｜每日 ${schedule} 自动采集｜当前 ${pointCount} 个竞品`,
    );
    return;
  }

  try {
    const AMap = await loadAmapSdk(amapConfig);
    if (state.amapInstance) state.amapInstance.destroy();
    qs("#competitionMap").innerHTML = "";
    const map = new AMap.Map("competitionMap", {
      zoom: 14,
      center: [payload.center_longitude, payload.center_latitude],
      viewMode: "2D",
    });
    state.amapInstance = map;
    const markers = [
      new AMap.Marker({
        position: [payload.center_longitude, payload.center_latitude],
        title: payload.store_name,
        label: { content: "本店", direction: "top" },
      }),
      ...(payload.competitors || []).map(
        (point) =>
          new AMap.Marker({
            position: [point.longitude, point.latitude],
            title: point.name,
            label: { content: escapeHtml(point.name), direction: "top" },
          }),
      ),
    ];
    map.add(markers);
    map.add(
      new AMap.Circle({
        center: [payload.center_longitude, payload.center_latitude],
        radius: payload.radius_m,
        strokeColor: "#2f7c60",
        strokeOpacity: 0.45,
        fillColor: "#2f7c60",
        fillOpacity: 0.06,
      }),
    );
    map.setFitView(markers, false, [40, 40, 40, 40]);
    qs("#competitionCollectionStatus").textContent = `高德真实地图｜每日 ${schedule} 自动采集｜当前 ${pointCount} 个竞品`;
  } catch (error) {
    renderFallbackCompetitionMap(payload, `地图服务异常，已降级展示坐标：${error.message}`);
  }
}

function setNavGroupOpen(groupKey, open) {
  const group = qs(`[data-nav-group="${groupKey}"]`);
  if (!group) return;
  const toggle = group.querySelector("[data-nav-toggle]");
  const sub = group.querySelector(".nav-sub");
  group.classList.toggle("open", open);
  if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  if (sub) sub.hidden = !open;
}

function syncSidebarNav(targetId, { stayHome = false } = {}) {
  const navKey = stayHome ? "today" : NAV_KEY_BY_SECTION[targetId] || null;
  qsa(".nav-item[data-nav-key]").forEach((item) => {
    const isActive = item.dataset.navKey === navKey;
    item.classList.toggle("active", isActive);
    item.setAttribute("aria-current", isActive ? "page" : "false");
  });
  qsa(".nav-sub-item").forEach((item) => {
    const isActive = !stayHome && item.dataset.scrollTarget === targetId;
    item.classList.toggle("active", isActive);
  });
  setNavGroupOpen("skills", navKey === "skills");
}

function setRightRailOpen(open) {
  state.rightRailOpen = Boolean(open);
  document.body.classList.toggle("right-rail-open", state.rightRailOpen);
  const rightColumn = qs("#rightColumn");
  if (rightColumn) {
    rightColumn.dataset.collapsed = state.rightRailOpen ? "false" : "true";
    const onHome = document.body.classList.contains("view-home");
    rightColumn.hidden = !onHome || !state.rightRailOpen;
    rightColumn.setAttribute("aria-hidden", rightColumn.hidden ? "true" : "false");
  }
  const toggle = qs("#toggleRightRailBtn");
  if (toggle) {
    toggle.setAttribute("aria-pressed", state.rightRailOpen ? "true" : "false");
    toggle.classList.toggle("active", state.rightRailOpen);
  }
}

function applyWorkspaceMode(targetId) {
  const stayHome = isHomeWorkspace(targetId);
  document.body.classList.toggle("view-home", stayHome);
  document.body.classList.toggle("view-module", !stayHome);
  document.body.classList.toggle("workspace-focus", !stayHome);

  const homeShell = qs("#homeShell");
  if (homeShell) {
    homeShell.hidden = !stayHome;
    homeShell.setAttribute("aria-hidden", stayHome ? "false" : "true");
  }

  const deck = qs("#section-workspace-deck");
  if (deck) {
    deck.hidden = stayHome;
    deck.setAttribute("aria-hidden", stayHome ? "true" : "false");
    deck.classList.toggle("module-focus", !stayHome);
  }

  // 首页：全宽状态页；模块页再显示侧栏
  setRightRailOpen(false);
  return stayHome;
}

function scrollToSection(id) {
  const requestedId = id || state.activeWorkspace || "section-overview";
  const stayHome = isHomeWorkspace(requestedId);
  const targetId = stayHome ? "section-overview" : requestedId;
  const view = workspaceView(targetId);
  state.activeWorkspace = targetId;

  applyWorkspaceMode(targetId);
  syncSidebarNav(requestedId === "section-home" ? "section-overview" : requestedId, { stayHome });

  qsa("[data-workspace-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.workspacePanel === view.panel);
  });

  renderWorkspaceHeader(view, { isHome: stayHome });
  renderTopbar();

  const stage = qs("#workspaceStage");
  if (stage) stage.scrollTop = 0;
  const panel = qs(`[data-workspace-panel="${view.panel}"]`);
  if (panel) panel.scrollTop = 0;
  const main = qs("#mainColumn");
  if (main) main.scrollTop = 0;

  if (stayHome && requestedId !== "section-overview" && requestedId !== "section-home") {
    const anchor = qs(`#${requestedId}`);
    if (anchor) {
      requestAnimationFrame(() => {
        anchor.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  if (window.matchMedia("(max-width: 860px)").matches) {
    setSidebarOpen(false);
  }
}

function sparklineSvg(points) {
  const values = (points || []).map((row) => Number(row.orders || row.value || 0));
  if (!values.length) {
    return `
      <rect x="0" y="0" width="480" height="180" rx="16" fill="transparent"></rect>
      <text x="18" y="90" fill="rgba(233,243,230,0.6)" font-size="14">暂无趋势数据</text>
    `;
  }

  const width = 480;
  const height = 180;
  const paddingX = 18;
  const paddingY = 18;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const spread = Math.max(1, max - min);
  const stepX = values.length > 1 ? (width - paddingX * 2) / (values.length - 1) : 0;

  const coords = values.map((value, index) => {
    const x = paddingX + index * stepX;
    const y = height - paddingY - ((value - min) / spread) * (height - paddingY * 2);
    return [x, y];
  });

  const polyline = coords.map((point) => point.join(",")).join(" ");
  const area = `${paddingX},${height - paddingY} ${polyline} ${width - paddingX},${height - paddingY}`;
  const grid = [0.2, 0.5, 0.8]
    .map((ratio) => {
      const y = paddingY + (height - paddingY * 2) * ratio;
      return `<line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4 8" />`;
    })
    .join("");
  const dots = coords
    .map(
      ([x, y], index) => `
        <circle cx="${x}" cy="${y}" r="${index === coords.length - 1 ? 5 : 3.5}" fill="#79d887" />
      `,
    )
    .join("");

  return `
    ${grid}
    <polygon points="${area}" fill="rgba(121,216,135,0.10)"></polygon>
    <polyline points="${polyline}" fill="none" stroke="#79d887" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"></polyline>
    ${dots}
  `;
}

function sparklineMini(values, { negative = false } = {}) {
  const nums = (values || []).map((value) => Number(value)).filter((value) => !Number.isNaN(value));
  const width = 88;
  const height = 28;
  if (nums.length < 2) {
    return `<svg class="pulse-sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><path d="M2 14 H86" stroke="rgba(255,255,255,0.2)" stroke-width="1.5" fill="none"/></svg>`;
  }
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  const spread = Math.max(1, max - min);
  const stepX = (width - 4) / (nums.length - 1);
  const points = nums
    .map((value, index) => {
      const x = 2 + index * stepX;
      const y = height - 3 - ((value - min) / spread) * (height - 6);
      return `${x},${y}`;
    })
    .join(" ");
  const stroke = negative ? "#ff8f82" : "#79d887";
  return `<svg class="pulse-sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}" fill="none" stroke="${stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function trendSeries(key) {
  const trend = state.dashboard?.trend || [];
  if (!trend.length) return [];
  if (key === "orders") return trend.map((row) => row.orders);
  if (key === "gmv") return trend.map((row) => row.gmv);
  if (key === "profit") {
    return trend.map((row) =>
      row.contribution_profit != null
        ? row.contribution_profit
        : Number(row.gmv || 0) * Number(state.managerBrief?.profit_summary?.take_home_rate || state.dashboard?.store_state?.profit?.take_home_rate || 0.7),
    );
  }
  return trend.map((row) => row.orders);
}

function formatMetricValue(key, value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  if (key === "gmv" || key === "profit") return `¥${Math.round(Number(value)).toLocaleString("zh-CN")}`;
  return Math.round(Number(value)).toLocaleString("zh-CN");
}

function actionButtonConfig(action) {
  if (!action?.id) return null;
  if (action.status === "proposed") {
    return { label: "先确认", endpoint: "adopt", className: "primary", canIgnore: true };
  }
  if (action.status === "adopted") {
    return { label: "我已做完", endpoint: "execute", className: "primary", canIgnore: true };
  }
  if (action.status === "executed") {
    return {
      label: "去看观察",
      endpoint: null,
      className: "",
      canIgnore: false,
      secondary: { label: "标记无效", endpoint: "no_effect" },
      scroll: "section-today-mainline",
    };
  }
  return { label: formatStatus(action.status), endpoint: null, className: "", canIgnore: false };
}

function resolveActionById(recommendationId) {
  if (!recommendationId) return null;
  const packages = state.dashboard?.action_packages || state.dashboard?.today_tasks || [];
  return packages.find((item) => item.id === recommendationId) || null;
}

function enrichBriefWithDashboard() {
  const brief = state.managerBrief;
  const dashboard = state.dashboard;
  if (!brief || !dashboard) return;
  // 后端 get_manager_brief 已 enrich；前端只做轻量补洞，避免错绑
  const actions = dashboard.action_packages || dashboard.today_tasks || [];
  const experiments = dashboard.experiments || [];
  let primary = brief.primary_experiment || null;
  if (!primary) return;
  if (!primary.recommendation_id) {
    const byTitle =
      (primary.title && actions.find((item) => item.title === primary.title)) ||
      (actions.length === 1 ? actions[0] : null);
    if (byTitle) {
      primary = {
        ...primary,
        title: byTitle.title || primary.title,
        recommendation_id: byTitle.id,
        status: byTitle.status,
        expected_metric: byTitle.expected_metric || primary.expected_metric || "",
        expected_lift_low: byTitle.expected_lift_pct_low ?? primary.expected_lift_low,
        expected_lift_high: byTitle.expected_lift_pct_high ?? primary.expected_lift_high,
        window_hours: byTitle.window_hours || primary.window_hours || 48,
      };
    }
  }
  if (primary.recommendation_id && !primary.experiment_id) {
    const experiment = experiments.find((item) => item.recommendation_id === primary.recommendation_id);
    if (experiment) {
      primary = {
        ...primary,
        experiment_id: experiment.id,
        result: experiment.result,
        can_evaluate: Boolean(experiment.can_evaluate),
        window_hours: experiment.window_hours || primary.window_hours || 48,
      };
    }
  }
  brief.primary_experiment = primary;
  state.managerBrief = brief;
}

function renderStoreSelector() {
  const select = qs("#storeSelect");
  select.innerHTML = state.stores
    .map((store) => `<option value="${store.id}" ${store.id === state.currentStoreId ? "selected" : ""}>${escapeHtml(store.name)}</option>`)
    .join("");
  qs("#bootstrapBtn").style.display = state.stores.length ? "none" : "";
}

function renderTopbar() {
  const dashboard = state.dashboard;
  const brief = state.managerBrief;
  const runtime = runtimeWorkspacePanels();
  const dailyPlan = state.dailyPlan || {};
  const store = dashboard?.store || {};
  const placeBits = [store.city, store.area, store.category].filter(Boolean);
  const storeName = runtime?.store?.store_name || brief?.store_name || store.name;
  const onHome = isHomeWorkspace(state.activeWorkspace);
  const view = workspaceView(state.activeWorkspace);
  const hello = greetingByHour();
  const greetingText = qs("#greetingText");
  const greetingTitle = qs("#greetingTitle");
  const greetingStore = qs("#greetingStore");
  const topbarEyebrow = qs("#topbarEyebrow");
  const topbarTitle = qs("#topbarTitle");
  const topbarSummary = qs("#topbarSummary");

  if (greetingText) greetingText.textContent = hello;
  if (onHome) {
    if (topbarEyebrow) topbarEyebrow.textContent = hello;
    if (topbarTitle) topbarTitle.textContent = storeName || "当下经营状态";
    if (topbarSummary) {
      const needCount = runtimeLeftItems("need_you").length || brief?.ops_queue?.need_you?.length || 0;
      const activeThreads =
        runtimeLeftItems("active").length ||
        runtimeLeftItems("threads").length ||
        brief?.ops_queue?.threads?.length ||
        0;
      const runtimeBits = [
        runtime?.store?.runtime_state ? `当前 ${runtime.store.runtime_state}` : "",
        dailyPlan?.current_meal_period ? `聚焦 ${dailyPlan.current_meal_period}` : "",
      ].filter(Boolean);
      topbarSummary.textContent =
        needCount > 0
          ? `MealKey 正在经营中，现在有 ${needCount} 件事需要你确认${runtimeBits.length ? ` · ${runtimeBits.join(" · ")}` : ""}`
          : activeThreads > 0
            ? `MealKey 继续推进 ${activeThreads} 条经营线程，你只在需要时出现${runtimeBits.length ? ` · ${runtimeBits.join(" · ")}` : ""}`
            : `MealKey 正在继续盯店，现在没有需要你处理的事情${runtimeBits.length ? ` · ${runtimeBits.join(" · ")}` : ""}`;
    }
    const focusStore = qs("#focusStoreName");
    if (focusStore) focusStore.textContent = storeName || "门店加载中";
  } else {
    if (topbarEyebrow) topbarEyebrow.textContent = "MealKey";
    if (topbarTitle) topbarTitle.textContent = storeName ? `${storeName} · ${view.label}` : view.label;
    if (topbarSummary) {
      topbarSummary.textContent = view.summary || placeBits.join(" · ") || "专注当前事项";
    }
  }
  const currentDate = qs("#currentDate");
  if (currentDate) currentDate.textContent = formatDisplayDate();
  const profileName = qs("#profileStoreName");
  if (profileName) profileName.textContent = storeName || "门店加载中";
  const metaAt =
    state.operatingEvents?.generated_at || dashboard?.meta?.generated_at || dashboard?.meta?.updated_at;
  const refreshMeta = qs("#sectionRefreshMeta");
  if (refreshMeta) {
    refreshMeta.textContent = metaAt
      ? `更新于 ${new Date(metaAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
      : "更新于 刚刚";
  }
}

function renderGuide() {
  const checklist = state.settingsOverview?.checklist;
  if (checklist) {
    const pending = (checklist.steps || []).find((step) => !step.done);
    qs("#guideStep").textContent = `已完成 ${checklist.completed}/${checklist.total}`;
    qs("#guideProgressBar").style.width = `${checklist.progress_pct || 0}%`;
    qs("#guideHint").textContent = pending
      ? `${pending.title}：${pending.hint}`
      : "基础设置已就绪，去执行今日动作或刷新诊断。";
    return;
  }
  const dashboard = state.dashboard;
  const alignment = dashboard?.document_alignment || {};
  const summary = dashboard?.execution_summary || {};
  const completed = [
    alignment.status === "aligned" || alignment.status === "partial",
    !!dashboard?.today_action?.id,
    (summary.executed || 0) > 0,
    (dashboard?.experiments || []).length > 0,
  ].filter(Boolean).length;
  qs("#guideStep").textContent = `已完成 ${completed}/4`;
  qs("#guideProgressBar").style.width = `${25 * Math.max(1, completed)}%`;
  qs("#guideHint").textContent = alignment.recommendations?.[0] || dashboard?.daily_brief?.reason || "先补齐资料，再执行今日动作。";
}

function formatTakeHomeRate(rate) {
  if (rate === null || rate === undefined || Number.isNaN(Number(rate))) return null;
  const value = Number(rate);
  return `${(value <= 1 ? value * 100 : value).toFixed(0)}%`;
}

function managerDecisionLabel(decision) {
  return (
    {
      ignore: "忽略",
      record: "记录",
      handle_today: "今天处理",
      alert_owner: "立即提醒老板",
    }[decision] || "待决策"
  );
}

function eventSeverityLabel(severity) {
  return (
    {
      info: "提示",
      low: "低",
      medium: "中",
      high: "高",
      critical: "紧急",
    }[severity] || "中"
  );
}

function agentLabel(agentKey) {
  return agentTeamDef(agentKey)?.label || agentKey;
}

function agentCapabilityStatus(agentKey) {
  const def = agentTeamDef(agentKey);
  if (!def) return { ready: false, meta: "未知 Agent" };
  if (agentKey === "collection") {
    const connected = (state.platformLinks || []).filter(
      (link) => link.status === "connected" || link.connected_at,
    ).length;
    const runs = state.collectionRuns || [];
    const latestOk = runs[0]?.status === "completed";
    return {
      ready: connected > 0 || latestOk,
      meta: connected ? `已连 ${connected} 平台` : latestOk ? "有采集记录" : "待连接",
      score: connected,
    };
  }
  const agent = state.dashboard?.agents?.[agentKey] || {};
  const score = agent.health_score;
  const actions = (agent.priority_actions || agent.recommendations || agent.actions || []).length;
  const ready =
    agent.readiness === "ready" ||
    agent.unlock_ready === true ||
    score != null ||
    actions > 0 ||
    Boolean(agent.conclusion);
  return {
    ready,
    meta: [
      score != null ? `${score}分` : "",
      formatReadiness(agent.readiness),
      agent.unlock_ready === false ? "未解锁" : "",
      actions ? `${actions}动作` : "",
    ]
      .filter(Boolean)
      .join(" · ") || def.summary,
    score,
  };
}

function renderAgentTeamRoster() {
  const host = qs("#agentTeamRoster");
  if (!host) return;
  host.innerHTML = AGENT_TEAM.map((agent) => {
    const status = agentCapabilityStatus(agent.key);
    return `
      <button type="button" class="agent-team-card ${status.ready ? "ready" : "idle"}" data-scroll-target="${agent.section}">
        <span class="agent-team-layer">L${agent.layer} · ${escapeHtml(agent.layerLabel)}</span>
        <strong>${escapeHtml(agent.label)}</strong>
        <span>${escapeHtml(status.meta)}</span>
      </button>
    `;
  }).join("");
}

function healthStatusLabel(score) {
  if (score == null || Number.isNaN(Number(score))) return "读取中";
  const value = Number(score);
  if (value >= 75) return "经营平稳";
  if (value >= 55) return "需要关注";
  return "需要优先处理";
}

function metricByKey(key) {
  const fromRows = (state.dashboard?.metrics || []).find((item) => item.key === key);
  if (fromRows) return fromRows;
  const kpi = state.dashboard?.store_state?.kpis?.[key];
  if (!kpi) return null;
  return { key, delta_pct: kpi.delta_pct, value: kpi.value };
}

function homePulseContext() {
  enrichBriefWithDashboard();
  const dashboard = state.dashboard || {};
  const brief = state.managerBrief;
  const events = state.operatingEvents;
  const storeState = dashboard.store_state || {};
  const diagnosis = dashboard.agents?.diagnosis || {};
  const market = diagnosis.market_comparison || {};
  const orders = metricByKey("orders");
  const gmv = metricByKey("gmv");
  const profit = brief?.profit_summary || storeState.profit || {};
  const orderDelta = orders?.delta_pct;
  const profitDelta =
    profit.contribution_profit_delta_pct ?? profit.take_home_rate_delta_pct ?? null;
  const marketDelta = market.market_orders_delta_pct;
  const ownDelta = market.own_orders_delta_pct ?? orderDelta;
  const shareLoss =
    ownDelta != null && marketDelta != null ? Number(ownDelta) - Number(marketDelta) : null;
  const openCount = brief?.open_event_count ?? events?.open_count ?? 0;
  const handleTodayCount = (events?.handle_today_count || 0) + (events?.alert_count || 0);
  const primaryExperiment = brief?.primary_experiment || null;
  const primaryAction =
    resolveActionById(primaryExperiment?.recommendation_id) ||
    (dashboard.action_packages || dashboard.today_tasks || []).find(Boolean) ||
    dashboard.today_action ||
    null;
  const pendingExperiment =
    (primaryExperiment?.experiment_id &&
      (dashboard.experiments || []).find((item) => item.id === primaryExperiment.experiment_id)) ||
    (dashboard.experiments || []).find((item) => !item.result || item.result === "pending") ||
    null;
  const root = (diagnosis.root_causes || [])[0];
  const problem = (brief?.problems || [])[0];
  const confidence =
    root?.confidence ??
    dashboard.hypothesis?.confidence ??
    primaryAction?.confidence ??
    null;
  const evidence = [
    ...(root?.evidence || []),
    ...(dashboard.hypothesis?.evidence_refs || []).slice(0, 2),
    ...(storeState.benchmark?.metrics || [])
      .slice(0, 2)
      .map((metric) => {
        if (metric.gap_vs_avg_pct == null) return null;
        return `${metric.label}较商圈均值 ${formatDelta(metric.gap_vs_avg_pct)}`;
      }),
    storeState.benchmark?.judgment,
    profit.judgment,
    profit.data_quality === "proxy" ? "利润为代理估算" : null,
  ]
    .filter(Boolean)
    .map((item) => String(item))
    .slice(0, 5);
  const parallelNotes = brief?.parallel_notes?.length
    ? brief.parallel_notes
    : (brief?.parallel_service_notes || []).map((note) => {
        const parsed = parseParallelNote(note);
        return { agent_key: parsed.agent, title: parsed.title, kind: "auto" };
      });
  const tasks = brief?.tasks || [];
  const problems = brief?.problems || [];
  return {
    dashboard,
    brief,
    events,
    storeState,
    diagnosis,
    market,
    orderDelta,
    profitDelta,
    marketDelta,
    ownDelta,
    shareLoss,
    openCount,
    handleTodayCount,
    primaryAction,
    primaryExperiment,
    pendingExperiment,
    confidence,
    evidence,
    parallelNotes,
    parallelCount: parallelNotes.length,
    hasMainExperiment: Boolean(primaryExperiment?.title || primaryAction?.title || brief?.primary_experiment_title),
    takeHome: formatTakeHomeRate(profit.take_home_rate ?? brief?.take_home_rate),
    healthScore: brief?.mealkey_score?.total ?? brief?.business_health_score ?? dashboard.health_score,
    mealkeyScore: brief?.mealkey_score || null,
    problems,
    problem,
    tasks,
    profit,
    gmv,
    orders,
  };
}

function renderManagerBrief() {
  const ctx = homePulseContext();
  const {
    brief,
    dashboard,
    healthScore,
    orderDelta,
    profitDelta,
    marketDelta,
    ownDelta,
    shareLoss,
    openCount,
    handleTodayCount,
    confidence,
    evidence,
    parallelCount,
    hasMainExperiment,
    takeHome,
    mealkeyScore,
    profit,
    gmv,
    orders,
    storeState,
  } = ctx;

  const judgment =
    mealkeyScore?.judgment ||
    brief?.business_judgment ||
    dashboard.daily_brief?.yesterday_change ||
    dashboard.daily_brief?.reason ||
    "正在读取经营判断…";

  const statusEl = qs("#storePulseStatus");
  if (statusEl) statusEl.textContent = healthStatusLabel(healthScore);
  const healthScoreEl = qs("#healthScore");
  if (healthScoreEl) healthScoreEl.textContent = healthScore ?? "--";
  const captionEl = qs("#healthCaption");
  if (captionEl) captionEl.textContent = judgment;

  const metricsEl = qs("#storePulseMetrics");
  if (metricsEl) {
    const profitValue = profit.contribution_profit ?? null;
    const chips = [
      {
        key: "orders",
        label: "订单",
        value: formatMetricValue("orders", orders?.value),
        delta: orderDelta,
        series: trendSeries("orders"),
      },
      {
        key: "gmv",
        label: "GMV",
        value: formatMetricValue("gmv", gmv?.value),
        delta: gmv?.delta_pct,
        series: trendSeries("gmv"),
      },
      {
        key: "profit",
        label: profit.data_quality === "proxy" ? "贡献利润(估)" : "贡献利润",
        value: formatMetricValue("profit", profitValue),
        delta: profitDelta,
        series: profitValue != null ? trendSeries("profit") : [],
      },
    ];
    metricsEl.innerHTML = chips
      .map((chip) => {
        const deltaText = chip.delta == null ? "--" : formatDelta(chip.delta);
        const negative = Number(chip.delta) < 0;
        return `
        <div class="pulse-metric ${negative ? "down" : "up"}">
          <span>${escapeHtml(chip.label)}</span>
          <strong>${escapeHtml(chip.value)}</strong>
          <em class="${negative ? "delta-negative" : "delta-positive"}">${escapeHtml(deltaText)}</em>
          ${sparklineMini(chip.series, { negative })}
        </div>`;
      })
      .join("");
  }

  const shareEl = qs("#storePulseShare");
  if (shareEl) {
    const benchmarkMetrics = storeState.benchmark?.metrics || [];
    if (ownDelta != null && marketDelta != null && shareLoss != null) {
      const losing = shareLoss < -0.5;
      shareEl.innerHTML = `
        <div class="pulse-share ${losing ? "losing" : "holding"}">
          <span>你的订单 ${escapeHtml(formatDelta(ownDelta))}</span>
          <span>商圈同类 ${escapeHtml(formatDelta(marketDelta))}</span>
          <strong>${
            losing
              ? `→ 你正在丢份额 ${escapeHtml(Math.abs(shareLoss).toFixed(1))}pct`
              : `→ 份额相对稳住（差 ${escapeHtml(shareLoss.toFixed(1))}pct）`
          }</strong>
        </div>`;
    } else if (benchmarkMetrics.length) {
      shareEl.innerHTML = `<div class="pulse-share">${benchmarkMetrics
        .slice(0, 2)
        .map((metric) => {
          const gap = metric.gap_vs_avg_pct == null ? "--" : formatDelta(metric.gap_vs_avg_pct);
          return `<span>${escapeHtml(metric.label)} ${escapeHtml(gap)} vs 商圈</span>`;
        })
        .join("")}${
        storeState.benchmark?.judgment
          ? `<strong>${escapeHtml(storeState.benchmark.judgment)}</strong>`
          : ""
      }</div>`;
    } else if (storeState.benchmark?.judgment) {
      shareEl.innerHTML = `<div class="pulse-share">${escapeHtml(storeState.benchmark.judgment)}</div>`;
    } else {
      shareEl.innerHTML = "";
    }
  }

  const evidenceEl = qs("#storePulseEvidence");
  if (evidenceEl) {
    const dimChips = (mealkeyScore?.dimensions || [])
      .slice()
      .sort((a, b) => a.weighted_score - b.weighted_score)
      .slice(0, 2)
      .map((dim) => `${dim.label} ${dim.score}`);
    const chips = [...dimChips, ...evidence].slice(0, 5);
    evidenceEl.innerHTML = chips.length
      ? chips.map((item) => `<span class="pulse-evidence-chip">${escapeHtml(item)}</span>`).join("")
      : `<span class="pulse-evidence-chip soft">Evidence 将随诊断与实验更新</span>`;
  }

  const confidenceEl = qs("#storePulseConfidence");
  if (confidenceEl) {
    confidenceEl.textContent =
      confidence == null ? "" : `Confidence ${Math.round(Number(confidence) * 100)}%`;
  }

  const sideEl = qs("#storePulseSide");
  if (sideEl) {
    const dims = (mealkeyScore?.dimensions || [])
      .map(
        (dim) =>
          `<div class="pulse-dim"><span>${escapeHtml(dim.label)}</span><strong>${dim.score}</strong></div>`,
      )
      .join("");
    sideEl.innerHTML = `
      <div class="pulse-side-kicker">今天</div>
      <div class="pulse-side-line"><strong>${hasMainExperiment ? 1 : 0}</strong> 个主实验</div>
      <div class="pulse-side-line"><strong>${parallelCount}</strong> 个后台动作</div>
      <div class="pulse-side-line"><strong>${handleTodayCount || openCount}</strong> 个异常待处理</div>
      ${dims ? `<div class="pulse-dim-grid">${dims}</div>` : ""}
      <p class="pulse-side-note">${
        takeHome ? `到手率 ${escapeHtml(takeHome)} · 平台健康 ${brief?.platform_health_score ?? "--"}` : "右侧看事件与验证结果"
      }</p>
    `;
  }

  const openCountEl = qs("#openEventCount");
  if (openCountEl) openCountEl.textContent = String(openCount);
  const alignEl = qs("#alignmentFoot");
  if (alignEl) {
    alignEl.textContent = [
      brief?.platform_health_score != null ? `平台健康 ${brief.platform_health_score}` : "",
      takeHome ? `到手率 ${takeHome}` : "",
      profit.data_quality ? `利润口径 ${profit.data_quality}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }

  const navActionCopy = qs("#navActionCopy");
  if (navActionCopy) {
    const summary = dashboard.execution_summary || {};
    navActionCopy.textContent = `待确认 ${summary.proposed || 0} · 实验中 ${summary.pending_verification || 0} · 已完成 ${summary.executed || 0}`;
  }

  renderOpsQueue();
  renderTodayMainline();
  renderWorthDoing();
  renderHomeEventFeed();
  renderAutoActivity();
  renderVerifiedWins();
  renderRecordWorkspace();
  renderStoreProfileCard();
}

function interruptReasonLabel(reason) {
  return (
    {
      time: "时间节点",
      anomaly: "异常",
      history: "未完事项",
      opportunity: "机会",
      goal: "目标",
      result: "结果",
      understanding: "需要你告诉我",
      confirm: "需要确认",
      assist: "需要协助",
    }[reason] || "需要你"
  );
}

function arbiterStateLabel(stateName) {
  return (
    {
      auto_do: "我自己做",
      confirm: "等你确认",
      need_input: "需要你协助",
      report_result: "汇报结果",
      noop: "先不打扰",
    }[stateName] || ""
  );
}

function decisionActionsHtml(actions) {
  return (actions || [])
    .map((action) => {
      const className = action.class_name || action.className || "";
      const label = action.label || "继续";
      if ((action.kind === "adopt" || action.kind === "execute" || action.kind === "ignore" || action.recommendation_id) && action.recommendation_id) {
        const endpoint = action.kind === "execute" || action.kind === "ignore" || action.kind === "adopt" ? action.kind : action.endpoint || "adopt";
        return `<button class="action-button ${escapeHtml(className)}" type="button" data-recommendation-id="${escapeHtml(
          action.recommendation_id,
        )}" data-recommendation-action="${escapeHtml(endpoint)}">${escapeHtml(label)}</button>`;
      }
      if (action.kind === "evaluate" || action.experiment_id) {
        return `<button class="action-button ${escapeHtml(className || "primary")}" type="button" data-experiment-evaluate="${escapeHtml(
          action.experiment_id,
        )}">${escapeHtml(label)}</button>`;
      }
      if (action.kind === "event_decision" || (action.event_fingerprint && action.event_decision)) {
        return `<button class="action-button ${escapeHtml(className)}" type="button" data-event-decision="${escapeHtml(
          action.event_decision,
        )}" data-event-fingerprint="${escapeHtml(action.event_fingerprint)}">${escapeHtml(label)}</button>`;
      }
      if (action.kind === "focus_intent" || action.focusIntent) {
        return `<button class="action-button ${escapeHtml(className || "ghost")}" type="button" data-focus-intent="1">${escapeHtml(
          label,
        )}</button>`;
      }
      if (action.scroll_target || action.scroll) {
        return `<button class="action-button ${escapeHtml(className || "ghost")}" type="button" data-scroll-target="${escapeHtml(
          action.scroll_target || action.scroll,
        )}">${escapeHtml(label)}</button>`;
      }
      return "";
    })
    .filter(Boolean)
    .join("");
}

function decisionCardHtml(card, { compact = false } = {}) {
  const tone =
    card.queue_bucket === "result"
      ? card.meta?.includes("无效")
        ? "negative"
        : card.meta?.includes("有效")
          ? "positive"
          : "neutral"
      : card.arbiter_state === "confirm" || card.arbiter_state === "need_input"
        ? "need"
        : card.queue_bucket || "";
  const actions = decisionActionsHtml(card.actions);
  const fiveQs =
    !compact && (card.why_now || card.ai_judgment || card.need_from_owner)
      ? `
      <dl class="decision-qs">
        ${card.why_now ? `<div><dt>为什么现在</dt><dd>${escapeHtml(card.why_now)}</dd></div>` : ""}
        ${card.ai_judgment ? `<div><dt>AI 判断</dt><dd>${escapeHtml(card.ai_judgment)}</dd></div>` : ""}
        ${card.ai_already_did ? `<div><dt>我已做</dt><dd>${escapeHtml(card.ai_already_did)}</dd></div>` : ""}
        ${card.need_from_owner ? `<div><dt>需要你</dt><dd>${escapeHtml(card.need_from_owner)}</dd></div>` : ""}
        ${card.success_metric ? `<div><dt>如何算有效</dt><dd>${escapeHtml(card.success_metric)}</dd></div>` : ""}
        ${card.evidence && card.evidence.length ? `<div><dt>证据</dt><dd>${card.evidence.slice(0,3).map(e => escapeHtml(e)).join("；")}</dd></div>` : ""}
        ${card.business_impact ? `<div><dt>经营影响</dt><dd>${escapeHtml(card.business_impact)}${card.estimated_loss ? `（预计损失约${card.estimated_loss}单）` : ""}</dd></div>` : ""}
        ${card.goal_relevance ? `<div><dt>目标相关</dt><dd>${escapeHtml(card.goal_relevance)}</dd></div>` : ""}
        ${card.observation_window_hours ? `<div><dt>观察窗</dt><dd>${card.observation_window_hours}小时</dd></div>` : ""}
        ${card.safe_mode_blocked ? `<div class="safe-mode-warn"><dt>⚠️</dt><dd>Safe Mode：关键信息未确认，此动作暂不自动执行。</dd></div>` : ""}
      </dl>`
      : card.summary || card.ai_judgment
        ? `<p>${escapeHtml(card.summary || card.ai_judgment || "")}</p>`
        : "";

  return `
    <article class="ops-queue-card decision-card ${escapeHtml(tone)}">
      <div class="ops-queue-card-kicker">${escapeHtml(interruptReasonLabel(card.interrupt_reason))}${
        card.meta ? ` · ${escapeHtml(card.meta)}` : ""
      }${card.arbiter_state ? ` · ${escapeHtml(arbiterStateLabel(card.arbiter_state))}` : ""}</div>
      <h3>${escapeHtml(card.title)}</h3>
      ${fiveQs}
      ${actions ? `<div class="ops-queue-actions">${actions}</div>` : ""}
    </article>`;
}

function goalCardHtml(goal, threads) {
  if (!goal) {
    return `<div class="ops-queue-empty">还没有长期目标。在下方告诉我：你想让 MealKey 帮你做到什么？</div>`;
  }
  const thread = (threads || [])[0];
  const done = (thread?.done || []).map((item) => `<li class="done">${escapeHtml(item)}</li>`).join("");
  const doing = (thread?.doing || []).map((item) => `<li class="doing">${escapeHtml(item)}</li>`).join("");
  return `
    <article class="ops-queue-card decision-card goal-card">
      <div class="ops-queue-card-kicker">Goal · 经营线程</div>
      <h3>${escapeHtml(goal.title)}</h3>
      <p><strong>当前</strong> ${escapeHtml(goal.current_status || "推进中")}</p>
      <div style="margin-top:8px;display:flex;gap:8px;">
        <button class="ghost" type="button" data-goal-action="achieved" data-goal-id="${escapeHtml(goal.id || "")}" style="font-size:12px;padding:4px 10px;">标记达成</button>
        <button class="ghost" type="button" data-goal-action="abandoned" data-goal-id="${escapeHtml(goal.id || "")}" style="font-size:12px;padding:4px 10px;">放弃目标</button>
      </div>
      ${goal.progress_summary ? `<p><strong>进度</strong> ${escapeHtml(goal.progress_summary)}</p>` : ""}
      ${goal.next_step ? `<p><strong>下一步</strong> ${escapeHtml(goal.next_step)}</p>` : ""}
      ${goal.blocked_by ? `<p><strong>阻塞</strong> ${escapeHtml(goal.blocked_by)}</p>` : ""}
      ${goal.ai_judgment ? `<p class="goal-judgment">${escapeHtml(goal.ai_judgment)}</p>` : ""}
      ${
        done || doing
          ? `<ul class="thread-progress">${done}${doing}</ul>`
          : ""
      }
      <div class="ops-queue-actions">
        <button class="action-button primary" type="button" data-focus-intent="1">调整目标</button>
        <button class="action-button ghost" type="button" data-scroll-target="section-record">看经营线程</button>
      </div>
    </article>`;
}

function focusChartSvg() {
  // 设计稿叙事：本店 CTR 连续下滑，商圈平稳
  const own = [9.1, 7.6, 6.2, 4.8, 3.6, 3.1];
  const market = [7.8, 7.7, 7.6, 7.5, 7.4, 7.4];
  const width = 260;
  const height = 120;
  const pad = 10;
  const all = [...own, ...market];
  const max = Math.max(...all, 1);
  const min = Math.min(...all, 0);
  const spread = Math.max(0.5, max - min);
  const pathOf = (nums) =>
    nums
      .map((value, index) => {
        const x = pad + (index * (width - pad * 2)) / Math.max(1, nums.length - 1);
        const y = height - pad - ((value - min) / spread) * (height - pad * 2);
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  return `
    <div class="mk-diag-chart-head">
      <div class="mk-chart-title">点击率（近 3 天）</div>
      <div class="mk-chart-filter">午餐时段</div>
    </div>
    <svg class="mk-focus-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${pathOf(market)}" fill="none" stroke="#b7bdb5" stroke-width="2" stroke-dasharray="4 4"/>
      <path d="${pathOf(own)}" fill="none" stroke="#1f6b3a" stroke-width="2.8" stroke-linecap="round"/>
    </svg>
    <div class="mk-chart-legend"><span class="own">你的店</span><span class="market">商圈均值</span></div>
    <div class="mk-chart-axis"><span>05-08</span><span>05-09</span><span>今天</span></div>`;
}

function pickPrimaryAction(actions = []) {
  return (
    actions.find((action) => ["adopt", "execute", "evaluate"].includes(action.kind) || action.recommendation_id) ||
    actions[0] ||
    null
  );
}

function pickSecondaryAction(actions = [], primary) {
  return (
    actions.find(
      (action) =>
        action !== primary &&
        (action.kind === "focus_intent" ||
          action.kind === "event_decision" ||
          /顾虑|详情|方案|为什么|看看|先不/.test(String(action.label || ""))),
    ) || { label: "先说说你的顾虑", kind: "focus_intent" }
  );
}

function ctaButtonHtml(action, variant, title, subtitle) {
  if (!action) return "";
  const label = title || action.label || "继续";
  const className = `mk-cta-${variant}`;
  const body = `<strong>${escapeHtml(label)}</strong>${subtitle ? `<span>${escapeHtml(subtitle)}</span>` : ""}`;
  if ((action.kind === "adopt" || action.kind === "execute" || action.kind === "ignore") && action.recommendation_id) {
    return `<button class="${className}" type="button" data-recommendation-id="${escapeHtml(
      action.recommendation_id,
    )}" data-recommendation-action="${escapeHtml(action.kind)}">${body}</button>`;
  }
  if (action.kind === "evaluate" && action.experiment_id) {
    return `<button class="${className}" type="button" data-experiment-evaluate="${escapeHtml(
      action.experiment_id,
    )}">${body}</button>`;
  }
  if (action.kind === "event_decision" && action.event_fingerprint) {
    return `<button class="${className}" type="button" data-event-decision="${escapeHtml(
      action.event_decision,
    )}" data-event-fingerprint="${escapeHtml(action.event_fingerprint)}">${body}</button>`;
  }
  if (action.kind === "focus_intent") {
    return `<button class="${className}" type="button" data-focus-intent="1">${body}</button>`;
  }
  return `<button class="${className}" type="button" data-task-route="${escapeHtml(
    action.scroll_target || "section-diagnosis",
  )}" data-task-title="${escapeHtml(action.label || label)}">${body}</button>`;
}

function synthesizeFocusCard() {
  // 空 need_you 不再前端合成「需要你」——尊重 POIE 少打扰；走 clear 态
  return null;
}

function isUnderstandingCard(card) {
  return (
    card?.guide_type === "QUESTION" ||
    card?.interrupt_reason === "understanding" ||
    card?.trigger === "understanding" ||
    (card?.arbiter_state === "need_input" && (card?.meta || "").includes("understanding"))
  );
}

function interviewKind(card) {
  const blob = `${card?.id || ""} ${card?.title || ""} ${card?.ai_judgment || ""}`;
  if (/产能|多少单|厨房|一小时|lunch_capacity/.test(blob)) return "lunch_capacity";
  if (/好评|监控|直接处理|售罄|活动到期|low_risk/.test(blob)) return "low_risk_auto";
  if (/到手|利润底线|profit_floor/.test(blob)) return "profit_floor";
  if (/最低多少钱|不会亏|hero_item|招牌/.test(blob)) return "hero_item_floor_price";
  if (/广告|投流|预算|ads_daily/.test(blob)) return "ads_daily_budget";
  if (/周末|weekend_strategy/.test(blob)) return "weekend_strategy";
  if (/竞品|competitor_focus/.test(blob)) return "competitor_focus";
  return "priority_style";
}

function interviewChipsForCard(card) {
  const kind = interviewKind(card);
  if (kind === "lunch_capacity") {
    return [
      { label: "一小时大约 80 单", fill: "午餐一小时大概80单" },
      { label: "一小时大约 100 单", fill: "午餐一小时大概100单" },
      { label: "一小时大约 150 单", fill: "午餐一小时大概150单" },
    ];
  }
  if (kind === "low_risk_auto") {
    return [
      { label: "普通好评你直接回", fill: "可以，普通好评你直接回，差评还是先给我确认" },
      { label: "都先让我确认", fill: "先不要自动处理，先都问我" },
    ];
  }
  if (kind === "profit_floor") {
    return [
      { label: "到手率别低于 15%", fill: "到手率底线15%" },
      { label: "到手率别低于 18%", fill: "到手率底线18%" },
      { label: "到手率别低于 20%", fill: "到手率底线20%" },
    ];
  }
  if (kind === "hero_item_floor_price") {
    return [
      { label: "大概 22 块", fill: "招牌菜最低22块不会亏" },
      { label: "大概 25 块", fill: "招牌菜最低25块不会亏" },
      { label: "我不太清楚，你帮我算", fill: "最低价我不太清楚，你根据成本慢慢帮我算" },
    ];
  }
  if (kind === "ads_daily_budget") {
    return [
      { label: "¥100 以内你处理", fill: "广告每天100以内你自己决定" },
      { label: "¥200 以内你处理", fill: "广告每天200以内你自己决定" },
      { label: "¥300 以内你处理", fill: "广告每天300以内你自己决定" },
    ];
  }
  if (kind === "weekend_strategy") {
    return [
      { label: "和工作日一样", fill: "周末和工作日一样" },
      { label: "周末可以激进一点", fill: "周末可以大胆一点" },
      { label: "周末保守一点", fill: "周末保守一点" },
    ];
  }
  if (kind === "competitor_focus") {
    return [
      { label: "你先帮我判断", fill: "竞品你先帮我判断谁最危险" },
      { label: "稍后再说", fill: "竞品稍后告诉你" },
    ];
  }
  return [
    { label: "多一点订单", fill: "多一点订单" },
    { label: "提高利润", fill: "提高利润" },
    { label: "提高排名", fill: "提高排名" },
    { label: "你帮我平衡", fill: "你帮我平衡" },
  ];
}

function interviewCopy(card) {
  const kind = interviewKind(card);
  const presets = {
    lunch_capacity: {
      intro: "还差一个关键约束。",
      title: "午餐高峰时，厨房一小时大概最多能稳妥做多少单？",
      subtitle: "接近上限时，我会主动收一收激进投流。",
    },
    low_risk_auto: {
      intro: "我准备把低风险动作接过去。",
      title: "普通好评以后我可以直接替你回复。差评仍然先给你确认，可以吗？",
      subtitle: "这样我能先接住评价回复、售罄和活动到期这类低风险动作。",
    },
    profit_floor: {
      intro: "还差一个利润底线。",
      title: "一笔订单最低赚多少，你才愿意接？",
      subtitle: "有了底线，我才能判断哪些活动是买流水。",
    },
    hero_item_floor_price: {
      intro: "我准备继续算活动方案，但还差一个信息。",
      title: "你的招牌菜最低到手多少钱，你可以接受？",
      subtitle: "不知道也没关系，我可以先按成本帮你算，再慢慢校正。",
    },
    ads_daily_budget: {
      intro: "最近投流效果稳定，可以往前走一步。",
      title: "以后每天预算调整，我可以在上限内自己处理吗？",
      subtitle: "你给我一个上限，额度内我自己调；超过再问你。",
    },
    weekend_strategy: {
      intro: "还差一个周末节奏。",
      title: "周末要和工作日一样，还是可以更激进/更保守？",
      subtitle: "我会按周几调整策略强度。",
    },
    competitor_focus: {
      intro: "还差一个重点对手。",
      title: "有没有你特别在意的竞品？",
      subtitle: "告诉我最危险的那一两家，我重点盯。",
    },
    priority_style: {
      intro: "还差最后一个问题。",
      title: "经营这家店，你现在最在乎什么？",
      subtitle: "我以后会按这个原则替你做判断。",
    },
  };
  const base = presets[kind] || presets.priority_style;
  return {
    ...base,
    title: base.title,
    why: card.ai_judgment || card.why_now || base.subtitle,
  };
}

function renderInterviewFocus(card) {
  const copy = interviewCopy(card);
  const chipHtml = interviewChipsForCard(card)
    .map(
      (c) =>
        `<button class="mk-interview-chip" type="button" data-intent-fill="${escapeHtml(c.fill)}">${escapeHtml(
          c.label,
        )}</button>`,
    )
    .join("");

  return `
    <article class="mk-focus-card interview plain">
      <p class="mk-focus-intro">${escapeHtml(copy.intro)}</p>
      <h2 class="mk-interview-title">${escapeHtml(copy.title)}</h2>
      <p class="mk-interview-subtitle">${escapeHtml(copy.subtitle)}</p>
      <div class="mk-interview-chips decision-grid">${chipHtml}</div>
      <details class="mk-why-ask">
        <summary>为什么要问这个？</summary>
        <p>${escapeHtml(copy.why)}</p>
      </details>
    </article>`;
}

function renderNeedYouFocus(card) {
  if (isUnderstandingCard(card)) {
    return renderInterviewFocus(card);
  }

  const detected = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  const primaryAction = pickPrimaryAction(card.actions || []);
  const secondaryAction = pickSecondaryAction(card.actions || [], primaryAction);
  const reason = interruptReasonLabel(card.interrupt_reason);
  const stateLabel = arbiterStateLabel(card.arbiter_state);

  return `
    <article class="mk-focus-card need slim">
      <div class="mk-focus-head">
        <div class="mk-focus-title-row">
          <span class="mk-alert-dot" aria-hidden="true">!</span>
          <h2>现在有 1 件事需要你</h2>
        </div>
        <span class="mk-focus-time">今天 ${escapeHtml(detected)}</span>
      </div>
      <div class="mk-issue-row">
        <strong>${escapeHtml(card.title)}</strong>
        <span class="mk-tag warn">${escapeHtml(stateLabel || "需你确认")}</span>
      </div>
      <p class="mk-band-kicker">${escapeHtml(reason)}${card.meta ? ` · ${escapeHtml(card.meta)}` : ""}</p>
      ${card.why_now ? `<p class="mk-diag-copy"><em>为什么现在</em>${escapeHtml(card.why_now)}</p>` : ""}
      ${card.ai_judgment ? `<p class="mk-diag-copy"><em>我的判断</em>${escapeHtml(card.ai_judgment)}</p>` : ""}
      ${card.ai_already_did ? `<p class="mk-diag-copy muted"><em>我已做</em>${escapeHtml(card.ai_already_did)}</p>` : ""}
      ${card.evidence && card.evidence.length ? `<p class="mk-diag-copy muted"><em>证据</em>${card.evidence.slice(0,2).map(e => escapeHtml(e)).join("；")}</p>` : ""}
      ${card.business_impact ? `<p class="mk-diag-copy"><em>经营影响</em>${escapeHtml(card.business_impact)}${card.estimated_loss ? `（约${card.estimated_loss}单）` : ""}</p>` : ""}
      ${card.goal_relevance ? `<p class="mk-diag-copy muted"><em>目标相关</em>${escapeHtml(card.goal_relevance)}</p>` : ""}
      ${
        card.success_metric
          ? `<p class="mk-success-line">怎样算有效：${escapeHtml(card.success_metric)}${card.observation_window_hours ? `（${card.observation_window_hours}小时观察窗）` : ""}</p>`
          : ""
      }
      ${card.safe_mode_blocked ? `<p class="mk-diag-copy" style="color:var(--warn,#e8a200);">⚠️ Safe Mode：关键经营信息未确认，此动作暂不自动执行。</p>` : ""}
      <div class="mk-cta-row">
        ${ctaButtonHtml(primaryAction, "primary", primaryAction?.label || "交给 MealKey 执行", "确认后我继续推进并盯结果")}
        ${ctaButtonHtml(secondaryAction, "secondary", secondaryAction?.label || "先说说你的顾虑", "留在对话里说就行")}
        <button class="mk-cta-ghost" type="button" data-focus-intent="1">
          <strong>暂不处理</strong>
          <span>稍后再说</span>
        </button>
      </div>
    </article>`;
}

function renderClearFocus() {
  return `
    <article class="mk-focus-card clear">
      <div class="mk-focus-intro">目前没有需要你处理的事情。</div>
      <p class="mk-clear-lead">我继续盯着。有需要你决定的事情时，我会来找你。</p>
    </article>`;
}

function humanizeWorkingTitle(raw) {
  const text = String(raw || "").trim();
  if (!text) return "我在持续盯店";
  if (/菜单|sku|主图|标题|装修|首屏/.test(text)) return "我在盯：商品与店铺";
  if (/用户|复购|召回|流失|高价值/.test(text)) return "我在盯：用户经营";
  if (/评分|差评|好评|申诉|客服|回复/.test(text)) return "我在盯：评价与客服";
  if (/第二线上店|一店多开|矩阵|新店/.test(text)) return "我在盯：线上店增长";
  if (/竞品/.test(text)) return "我在盯：竞品变化";
  if (/评价|好评|差评|回评/.test(text)) return "我在盯：评价与回复";
  if (/活动|补贴|促销/.test(text)) return "我在盯：活动是否到期";
  if (/售罄|库存|断货/.test(text)) return "我在盯：核心商品是否售罄";
  if (/投流|广告|ROI/.test(text)) return "我在盯：投流表现";
  if (/扫描|已扫描/.test(text)) return text.replace(/^已?扫描/, "我在盯：").replace(/(\d+)项/, "$1 处变化");
  return text.length > 28 ? `${text.slice(0, 28)}…` : text;
}

function renderWorkingBand(queue) {
  const working = (queue?.working || []).slice(0, 5);
  const threads = (queue?.threads || []).slice(0, 2);
  const items = working.length
    ? working
    : threads.map((t) => ({ title: t.title, summary: t.next_step || t.doing?.[0] || "" }));
  const lines = items.length
    ? items
        .slice(0, 3)
        .map((item) => humanizeWorkingTitle(item.title).replace(/^我在盯：/, ""))
        .join(" · ")
    : "竞品变化 · 菜单表现 · 评价动态";
  return `
    <p class="mk-activity">
      <span class="mk-activity-dot" aria-hidden="true"></span>
      <span><strong>MealKey 还在后台工作</strong>正在分析 ${escapeHtml(lines)}</span>
    </p>`;
}

function renderResultsBand(queue, { interviewing = false } = {}) {
  if (interviewing) return "";
  const results = (queue?.results || []).slice(0, 3);
  const opps = (queue?.opportunities || []).slice(0, 1);
  if (!results.length && !opps.length) return "";
  return `
    <section class="mk-band results">
      <div class="mk-band-head"><h3>有结果了</h3><span>看一眼即可</span></div>
      <ul class="mk-band-list">
        ${results
          .map(
            (item) =>
              `<li><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(
                item.summary || item.ai_judgment || item.success_metric || "",
              )}</span></li>`,
          )
          .join("")}
        ${opps
          .map(
            (item) =>
              `<li class="opp"><strong>机会 · ${escapeHtml(item.title)}</strong><span>${escapeHtml(
                item.summary || item.why_now || "",
              )}</span></li>`,
          )
          .join("")}
      </ul>
    </section>`;
}

function renderGoalStrip(queue, { interviewing = false } = {}) {
  if (interviewing) return "";
  const goal = queue?.active_goal;
  const deviations = state.managerBrief?.deviation_alerts || [];
  let html = "";
  if (goal?.title) {
    html += `
    <div class="mk-goal-strip">
      <span>你的目标</span>
      <strong>${escapeHtml(goal.title)}</strong>
      <em>${escapeHtml(goal.ai_judgment || goal.progress_summary || "进度正常，暂时不需要你介入。")}</em>
    </div>`;
  }
  // 偏差预警
  if (deviations.length) {
    html += deviations.map(d => `
      <div class="mk-goal-strip" style="border-color:rgba(232,80,80,0.3);background:rgba(232,80,80,0.05);">
        <span style="color:#e85050;">⚠️ 目标偏离</span>
        <strong>${escapeHtml(d.raw_text || "目标")}</strong>
        <em>${escapeHtml(`当前 ${d.current_value ?? "--"}，预测 ${d.forecast_value ?? "--"}，目标 ${d.target_value ?? "--"}${d.gap_pct != null ? `，缺口 ${d.gap_pct}%` : ""}`)}</em>
      </div>`).join("");
  }
  return html;
}

const DEFAULT_COMMAND_CHIPS = [
  { label: "这个月做到20万", prompt: "这个月做到20万营业额" },
  { label: "利润太低了", prompt: "利润太低了，先帮我找原因和动作" },
  { label: "牛肉饭做到前三", prompt: "把牛肉饭做到附近前三" },
];

const GAP_LABELS = {
  priority_style: "经营原则未确认",
  lunch_capacity: "午餐产能为确认",
  profit_floor: "利润底线未确认",
  hero_item_floor_price: "招牌菜成本/底价未确认",
  low_risk_auto: "低风险自动权限未确认",
  ads_daily_budget: "广告日预算未确认",
  weekend_strategy: "周末策略未确认",
  competitor_focus: "重点竞品未确认",
};

function runtimeWorkspacePanels() {
  return state.runtimeWorkspace || null;
}

function runtimeBridgeMeta() {
  return runtimeWorkspacePanels()?.meta?.runtime_bridge || {};
}

function currentRuntimeGuide() {
  return runtimeWorkspacePanels()?.center?.guide || null;
}

function runtimeGuideChoices(guide) {
  return Array.isArray(guide?.choices) ? guide.choices : [];
}

function runtimeGuideToCard(guide) {
  if (!guide) return null;
  const choices = runtimeGuideChoices(guide).map((choice) => ({
    label: choice.label || choice.title || choice.id || "选项",
    fill: choice.prompt || choice.value || choice.label || choice.id || "",
  }));
  return {
    id: guide.id || guide.guide_id || "runtime_guide",
    guide_type: guide.type || "INFO",
    title: guide.prompt || guide.title || "",
    guide_title: guide.title || "",
    guide_prompt: guide.prompt || guide.title || "",
    guide_explanation: guide.explanation || guide.summary || "",
    guide_choices: choices,
    guide_allow_free_text: Boolean(guide.allow_free_text),
    guide_allow_file: Boolean(guide.allow_file),
    guide_request_label: guide.request_label || "",
    guide_status: guide.status || "",
    guide_cta_label: guide.cta_label || "",
    interrupt_reason:
      guide.type === "QUESTION" && choices.length ? "understanding" : guide.trigger_reason?.toLowerCase?.() || "confirm",
    arbiter_state:
      guide.type === "QUESTION"
        ? "need_input"
        : guide.type === "APPROVAL"
          ? "confirm"
          : "report_result",
    meta: guide.type || "",
    why_now: guide.explanation || guide.summary || "",
    ai_judgment: guide.summary || "",
    actions: Array.isArray(guide.actions) ? guide.actions : [],
  };
}

function runtimeLeftItems(key) {
  const left = runtimeWorkspacePanels()?.left || {};
  const items = left[key];
  return Array.isArray(items) ? items : [];
}

function runtimeFeedItems() {
  const right = runtimeWorkspacePanels()?.right || {};
  const feed = right.proactive_feed;
  return Array.isArray(feed) ? feed : [];
}

function currentNeedCard() {
  const runtimeGuide = currentRuntimeGuide();
  if (runtimeGuide) return runtimeGuideToCard(runtimeGuide);
  const needYou = state.managerBrief?.ops_queue?.need_you || [];
  return [...needYou].sort((a, b) => {
    const aw = isUnderstandingCard(a) ? 0 : 1;
    const bw = isUnderstandingCard(b) ? 0 : 1;
    return aw - bw;
  })[0] || null;
}

function compactChipLabel(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  return normalized.length > 14 ? `${normalized.slice(0, 14).trim()}…` : normalized;
}

function commandChipsForFocus(card) {
  if (card?.guide_type === "QUESTION" && Array.isArray(card.guide_choices) && card.guide_choices.length) {
    return takeTop(card.guide_choices, 4).map((item) => ({
      label: compactChipLabel(item.label),
      prompt: item.fill || item.label,
    }));
  }
  if (isUnderstandingCard(card)) {
    return takeTop(interviewChipsForCard(card), 3).map((item) => ({
      label: compactChipLabel(item.label),
      prompt: item.fill,
    }));
  }
  const examples = takeTop(state.dashboard?.question_examples || [], 3)
    .map((question) => ({
      label: compactChipLabel(question),
      prompt: question,
    }))
    .filter((item) => item.label && item.prompt);
  return examples.length ? examples : DEFAULT_COMMAND_CHIPS;
}

function syncCommandBarForFocus(card) {
  const host = qs("#commandBarChips");
  const input = qs("#homeChatInput");
  if (!host) return;
  const interviewing = isUnderstandingCard(card);
  if (input) {
    input.placeholder = interviewing
      ? "也可以直接告诉我，例如：利润优先"
      : "直接告诉 MealKey 你的目标或把资料发给我";
  }
  host.hidden = false;
  host.innerHTML = commandChipsForFocus(card)
    .map(
      (c) =>
        `<button type="button" data-assist-prompt="${escapeHtml(c.prompt)}">${escapeHtml(c.label)}</button>`,
    )
    .join("");
}

function platformConnected() {
  const links = state.platformLinks || [];
  return links.some((link) => link.status === "connected" || link.connected_at);
}

function renderGuideProgressLine(steps) {
  return `<p class="mk-guide-progress-line">${steps
    .map((s, i) => {
      const mark = s.state === "done" ? " ✓" : s.state === "now" ? " ←现在" : "";
      const piece = `<span class="step ${escapeHtml(s.state)}">${escapeHtml(s.label)}${mark}</span>`;
      return i === 0 ? piece : `<span class="sep">·</span>${piece}`;
    })
    .join("")}</p>`;
}

function guideStepState(label, state) {
  return { label, state };
}

function guideBlockerLabel(key) {
  return GAP_LABELS[key] || key || "待确认";
}

function buildGuideProgressModel(card) {
  const understanding = state.understanding || {};
  const thread = (state.managerBrief?.ops_queue?.threads || [])[0];
  if (understanding.onboarding_stage === "connect" && !platformConnected()) {
    return {
      title: "接管这家店",
      steps: [
        guideStepState("平台数据", "now"),
        guideStepState("经营原则", "next"),
        guideStepState("经营边界", "next"),
        guideStepState("自动权限", "next"),
      ],
      foot: "先连平台，后面的事我再带你一步步确认。",
    };
  }

  if (isUnderstandingCard(card)) {
    const blockers = Array.from(new Set(understanding.mos_blocking_fields || []));
    const mapping = {
      priority_style: "经营原则",
      lunch_capacity: "经营边界",
      profit_floor: "经营边界",
      hero_item_floor_price: "经营边界",
      ads_daily_budget: "经营边界",
      weekend_strategy: "经营原则",
      competitor_focus: "经营原则",
      low_risk_auto: "自动权限",
    };
    const currentKind = interviewKind(card);
    const currentLabel = mapping[currentKind] || guideBlockerLabel(blockers[0]);
    const donePrinciple =
      !blockers.includes("priority_style") &&
      !blockers.includes("weekend_strategy") &&
      !blockers.includes("competitor_focus");
    const doneBoundary =
      !blockers.includes("profit_floor") &&
      !blockers.includes("hero_item_floor_price") &&
      !blockers.includes("ads_daily_budget") &&
      !blockers.includes("lunch_capacity");
    const doneAutomation = !blockers.includes("low_risk_auto");
    return {
      title: "接管这家店",
      steps: [
        guideStepState("平台数据", "done"),
        guideStepState("经营原则", currentLabel === "经营原则" ? "now" : donePrinciple ? "done" : "next"),
        guideStepState("经营边界", currentLabel === "经营边界" ? "now" : doneBoundary ? "done" : "next"),
        guideStepState("自动权限", currentLabel === "自动权限" ? "now" : doneAutomation ? "done" : "next"),
      ],
      foot: blockers.length ? `还有 ${blockers.length} 项待确认，完成这些我就开始经营。` : "完成这些，我就开始经营。",
    };
  }

  if (thread) {
    const done = (thread.done || []).slice(0, 2).map((label) => guideStepState(label, "done"));
    const doing = (thread.doing || []).slice(0, 1).map((label) => guideStepState(label, "now"));
    const next = thread.next_step ? [guideStepState(thread.next_step, "next")] : [];
    const steps = [...done, ...doing, ...next].slice(0, 4);
    if (steps.length) {
      return {
        title: thread.title || "当前经营线程",
        steps,
        foot: thread.current_result || thread.ai_judgment || "MealKey 正在继续推进这件事。",
      };
    }
  }
  return null;
}

function renderGuideProgress(card) {
  const host = qs("#mkGuideProgress");
  if (!host) return;
  const understanding = state.understanding || {};
  const model = buildGuideProgressModel(card);

  // Safe Mode 提示：关键信息未确认时告知老板
  const safeBanner = qs("#mkSafeModeBanner");
  if (safeBanner) {
    if (isUnderstandingCard(card)) {
      safeBanner.style.display = "none";
    } else if (understanding.system_mode === "safe" || understanding.mos_satisfied === false) {
      const blockers = understanding.mos_blocking_fields || [];
      const blockerLabels = Array.from(new Set(blockers.map((b) => guideBlockerLabel(b)).filter(Boolean)));
      safeBanner.style.display = "";
      safeBanner.innerHTML = `
        <strong>Safe Mode</strong>
        <span>还差 ${blockers.length} 项确认</span>
        ${blockerLabels.length ? `<em>${escapeHtml(blockerLabels.slice(0, 2).join(" / "))}</em>` : ""}
        <span class="mk-safe-mode-hint">利润相关动作暂不自动执行</span>`;
    } else {
      safeBanner.style.display = "none";
    }
  }

  host.hidden = !model;
  if (!model) {
    host.innerHTML = "";
    return;
  }
  if (isUnderstandingCard(card)) {
    host.innerHTML = `
      <div class="mk-guide-progress-meta interview">
        <p class="mk-guide-progress-kicker">开始接管这家店</p>
      </div>
    `;
    return;
  }
  host.innerHTML = `
    <div class="mk-guide-progress-meta">
      ${renderGuideProgressLine(model.steps || [])}
      ${model.foot ? `<p class="mk-guide-progress-foot">${escapeHtml(model.foot || "")}</p>` : ""}
    </div>
  `;
}

function renderRuntimeGuideHost(card) {
  const choices = Array.isArray(card?.guide_choices) ? card.guide_choices : [];
  const choiceHtml = choices.length
    ? `<div class="mk-choice-grid">
        ${choices
          .map(
            (c) =>
              `<button type="button" class="mk-choice-card" data-intent-fill="${escapeHtml(
                c.fill || c.label || "",
              )}">${escapeHtml(c.label || "选项")}</button>`,
          )
          .join("")}
      </div>`
    : "";
  const freeText = card?.guide_allow_free_text
    ? `<p class="mk-support">也可以直接输入一句话告诉我。</p>`
    : "";
  const fileHint = card?.guide_allow_file
    ? `<p class="mk-guide-watch">也可以直接把文件拖到下方输入框，我会把它当作这件事的补充资料。</p>`
    : "";
  const title = card?.guide_prompt || card?.title || "还差一步";
  const intro = card?.guide_title || "MealKey 需要你补一个关键信息";
  const explanation = card?.guide_explanation || card?.why_now || "确认后我继续推进。";
  if (card?.guide_type === "QUESTION" || card?.guide_type === "FILE_REQUEST") {
    return `
      <div class="mk-guide interview">
        <div class="mk-ai-intro">
          <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
          <p><strong>${escapeHtml(intro)}</strong><span>${escapeHtml(explanation)}</span></p>
        </div>
        <div class="mk-ai-status"><span>${escapeHtml(card?.guide_request_label || "现在需要你")}</span></div>
        <h2 class="mk-question">${escapeHtml(title)}</h2>
        ${card?.guide_title ? `<p class="mk-support">${escapeHtml(card.guide_title)}</p>` : ""}
        ${choiceHtml}
        ${freeText}
        ${fileHint}
      </div>`;
  }
  if (card?.guide_type === "APPROVAL") {
    return `
      <div class="mk-guide need">
        <div class="mk-ai-intro">
          <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
          <p>我已经把方案收敛好了，现在等你拍板。</p>
        </div>
        <h2 class="mk-question">${escapeHtml(title)}</h2>
        <p class="mk-support">${escapeHtml(explanation)}</p>
        ${choiceHtml}
        ${freeText}
      </div>`;
  }
  return `
    <div class="mk-guide clear">
      <div class="mk-ai-status quiet"><i></i><span>${escapeHtml(card?.guide_status || "经营进展")}</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      <p class="mk-support">${escapeHtml(explanation)}</p>
    </div>`;
}

function renderDecisionHost(card) {
  const host = qs("#mkDecisionHost");
  if (!host) return;
  renderGuideProgress(card);

  if (state.understanding?.onboarding_stage === "connect" && !platformConnected()) {
    host.innerHTML = `
      <div class="mk-guide">
        <p class="ai-line">先把美团店铺接进来。</p>
        <p class="mk-interview-subtitle">连接后订单、商品、活动、评价这些我自己读取，你不用填。</p>
        <div class="mk-cta-row">
          <button class="action-button primary" type="button" data-task-route="section-settings" data-task-title="授权美团">授权美团</button>
        </div>
      </div>`;
    return;
  }

  if (!card) {
    host.innerHTML = `
      <div class="mk-guide clear">
        <div class="mk-ai-status quiet"><i></i><span>目前没有需要你处理的事情</span></div>
        <h2 class="mk-question">我继续盯着。</h2>
        <p class="mk-support">你也可以直接告诉我目标、问题，或把资料发给我。</p>
      </div>`;
    return;
  }

  if (card?.guide_type) {
    host.innerHTML = renderRuntimeGuideHost(card);
    return;
  }

  if (isUnderstandingCard(card)) {
    const copy = interviewCopy(card);
    const chips = interviewChipsForCard(card);
    const isPriority = interviewKind(card) === "priority_style";
    const blockers = Array.from(new Set(state.understanding?.mos_blocking_fields || []));
    const blockerCount = Math.max(blockers.length || 0, 1);
    const statusText = blockerCount <= 1 ? "还差最后一个问题" : `还差 ${blockerCount} 个问题`;
    const title = isPriority ? "经营这家店，你现在最在乎什么？" : copy.title;
    const subtitle = isPriority
      ? "我以后会按照这个原则替你做判断。"
      : copy.subtitle || "我会按这条信息继续判断。";
    const introLead = isPriority ? "先把这家店交给我。" : "这件事还需要你确认。";
    const introBody = isPriority
      ? "我已经从平台读到了菜单、订单、评价和活动。还有几件只有你知道的事情，确认后我就可以开始经营。"
      : copy.intro || "我先把你的判断补齐，再继续往下推进。";
    const whyAsk = isPriority
      ? "平台数据能告诉我发生了什么，但订单、利润、排名这三件事，优先级只能由你来定。"
      : copy.intro || copy.subtitle || "这会影响我后续怎么替你做判断。";
    host.innerHTML = `
      <div class="mk-guide interview">
        <div class="mk-ai-intro">
          <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
          <p><strong>${escapeHtml(introLead)}</strong><span>${escapeHtml(introBody)}</span></p>
        </div>
        <div class="mk-ai-status"><span>${escapeHtml(statusText)}</span></div>
        <h2 class="mk-question">${escapeHtml(title)}</h2>
        <p class="mk-support">${escapeHtml(subtitle)}</p>
        <div class="mk-choice-grid">
          ${chips
            .map(
              (c) =>
                `<button type="button" class="mk-choice-card" data-intent-fill="${escapeHtml(
                  c.fill,
                )}">${escapeHtml(c.label)}</button>`,
            )
            .join("")}
        </div>
        <details class="mk-why-ask">
          <summary>为什么要问这个？</summary>
          <p>${escapeHtml(whyAsk)}</p>
        </details>
      </div>`;
    return;
  }

  const primaryAction = pickPrimaryAction(card.actions || []);
  const secondaryAction = pickSecondaryAction(card.actions || [], primaryAction);
  const didLine = card.ai_already_did || card.ai_judgment || "";
  const noteLine = [card.why_now, card.business_impact, card.success_metric].filter(Boolean)[0] || "";
  const watchLine =
    card.observation_window_hours && Number(card.observation_window_hours) > 0
      ? `建议先观察 ${card.observation_window_hours} 小时，再决定是否进入下一步。`
      : "";
  host.innerHTML = `
    <div class="mk-guide need">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p>现在有一件事需要你。</p>
      </div>
      <h2 class="mk-question">${escapeHtml(card.title || "")}</h2>
      ${didLine ? `<p class="mk-support">${escapeHtml(didLine)}</p>` : ""}
      ${noteLine ? `<p class="mk-guide-note">${escapeHtml(noteLine)}</p>` : ""}
      ${watchLine ? `<p class="mk-guide-watch">${escapeHtml(watchLine)}</p>` : ""}
      <div class="mk-cta-row">
        ${ctaButtonHtml(primaryAction, "primary", primaryAction?.label || "交给 MealKey", "确认后我继续推进")}
        ${ctaButtonHtml(secondaryAction, "secondary", secondaryAction?.label || "看看方案", "先看细节")}
      </div>
    </div>`;
}

function renderWorkRail() {
  const rail = qs("#mkWorkRail");
  if (!rail) return;
  const runtimeLeft = runtimeWorkspacePanels()?.left || {};
  const queue = state.managerBrief?.ops_queue || {};
  const card = currentNeedCard();
  const working = (queue.working || []).slice(0, 4);
  const threads = (queue.threads || []).slice(0, 3);
  const results = (queue.results || []).slice(0, 3);
  const experiments = (state.dashboard?.experiments || []).filter(
    (item) => !item.result || item.result === "pending",
  );

  const runtimeNeedItems = runtimeLeftItems("need_you").slice(0, 4).map((item) => ({
    title: item.title || item.name || "需要你确认",
    meta: item.summary || item.status || item.next_step || "待你拍板",
    work: "need",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，现在需要我做什么？` : ""),
    active: true,
  }));
  const runtimeActiveItems = runtimeLeftItems("active").slice(0, 4).map((item, idx) => ({
    title: item.title || item.name || "经营线程",
    meta: item.summary || item.phase || item.status || (idx === 0 ? "AI 处理中" : "进行中"),
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，现在进展怎样？` : ""),
  }));
  const runtimeWaitingItems = runtimeLeftItems("waiting").slice(0, 3).map((item) => ({
    title: item.title || item.name || "等待结果",
    meta: item.summary || item.status || "观察中",
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，结果出来了吗？` : ""),
  }));
  const runtimeDoneItems = runtimeLeftItems("completed").slice(0, 3).map((item) => ({
    title: item.title || item.name || "最近完成",
    meta: item.summary || item.status || "已完成",
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，帮我复盘下一步` : ""),
  }));

  const needItems = runtimeNeedItems.length
    ? runtimeNeedItems
    : card
    ? [
        {
          title:
            isUnderstandingCard(card)
              ? {
                  priority_style: "经营原则确认",
                  lunch_capacity: "午高峰产能确认",
                  low_risk_auto: "自动处理授权",
                  profit_floor: "利润底线确认",
                  hero_item_floor_price: "招牌菜底价确认",
                  ads_daily_budget: "投流额度授权",
                  weekend_strategy: "周末经营节奏",
                  competitor_focus: "重点竞品确认",
                }[interviewKind(card)] || "经营信息确认"
              : card.title || "需要你处理",
          meta:
            isUnderstandingCard(card)
              ? {
                  priority_style: "告诉我更偏订单、利润还是排名",
                  lunch_capacity: "避免午高峰把后厨打爆",
                  low_risk_auto: "低风险动作先由我接住",
                  profit_floor: "活动和投流不能穿透利润线",
                  hero_item_floor_price: "活动前还差最低可接受价",
                  ads_daily_budget: "先给我一个自动调整上限",
                  weekend_strategy: "我会按周几切换强度",
                  competitor_focus: "告诉我最该盯的对手",
                }[interviewKind(card)] || "这句会影响我接下来怎么经营"
              : card.meta || "待你拍板",
          work: isUnderstandingCard(card) ? "talk" : "need",
          active: true,
        },
      ]
    : [];

  const workingSource = runtimeActiveItems.length ? runtimeActiveItems : working.length ? working : threads;
  const workingItems = workingSource.slice(0, 3).map((item, idx) => ({
    title: humanizeWorkingTitle(item.title).replace(/^我在盯：/, "") || item.title,
    meta: item.meta || item.summary || item.next_step || (idx === 0 ? "AI 处理中" : "进行中"),
    work: item.work || "ask",
    prompt: item.prompt || `关于「${item.title || ""}」，现在进展怎样？`,
  }));

  const waitingItems = runtimeWaitingItems.length
    ? runtimeWaitingItems
    : experiments.slice(0, 2).map((exp) => ({
    title: exp.action_title || "实验观察中",
    meta: exp.notes || "等待结果",
    work: "ask",
    prompt: `实验「${exp.action_title || ""}」现在怎样了？`,
  }));

  const doneItems = runtimeDoneItems.length
    ? runtimeDoneItems
    : results.slice(0, 2).map((item) => ({
    title: item.title || "已完成",
    meta: item.summary || "已完成",
    work: "ask",
    prompt: `关于结果「${item.title || ""}」，帮我复盘下一步`,
  }));

  const section = (title, items, { empty = "暂无" } = {}) => `
      <div class="mk-work-group">
        <p class="mk-work-group-title">${escapeHtml(title)}</p>
        ${
          items.length
            ? items
                .map(
                  (item) => `
          <button type="button" class="mk-work-item${item.active ? " active" : ""}"
            data-rail-work="${escapeHtml(item.work || "talk")}"
            data-rail-prompt="${escapeHtml(item.prompt || "")}">
            <span class="mk-work-copy">
              <strong>${escapeHtml(item.title)}</strong>
              <span>${escapeHtml(item.meta || "")}</span>
            </span>
            ${item.active ? `<span class="mk-work-arrow" aria-hidden="true">›</span>` : ""}
          </button>`,
                )
                .join("")
            : `<p class="mk-work-empty">${escapeHtml(empty)}</p>`
        }
      </div>`;

  rail.innerHTML = `
    <div class="mk-work-head">工作线程</div>
    <div class="mk-work-body">
      ${section(`需要你 ${needItems.length || ""}`.trim(), needItems, { empty: "今天没有要你拍板的事" })}
      ${section(`正在进行 ${workingItems.length || ""}`.trim(), workingItems, { empty: "暂无" })}
      ${section(`等待结果 ${waitingItems.length || ""}`.trim(), waitingItems, { empty: "暂无" })}
      ${section(`最近完成 ${doneItems.length || ""}`.trim(), doneItems, { empty: "暂无" })}
    </div>
  `;
}

function proactiveStatusLabel(status) {
  return (
    {
      auto_done: "已处理",
      AUTO: "已自动执行",
      AUTO_REPORT: "已自动执行",
      AUTO_AND_REPORT: "已自动执行",
      AUTO_EXECUTED: "已自动执行",
      need_you: "需要你",
      ASK_INFORMATION: "需要你",
      ASK_APPROVAL: "等你确认",
      observing: "跟进中",
      OBSERVE: "观察中",
      analyzing: "分析中",
      done: "已验证",
      RESULT: "已验证",
      no_action: "已记录",
      DROP: "已过滤",
    }[status] || status
  );
}

function proactiveDomainLabel(domain) {
  return (
    {
      PLATFORM: "平台与数据",
      PRODUCT: "商品与店铺",
      COMPETITION: "竞争与排名",
      TRAFFIC: "流量与活动",
      PROFIT: "订单与利润",
      CUSTOMER: "用户经营",
      REVIEW: "评价与客服",
      STORE_GROWTH: "线上店增长",
    }[domain] || ""
  );
}

function formatFeedTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return "";
  }
}

function renderContextRail() {
  const rail = qs("#mkContextRail");
  if (!rail) return;
  const brief = state.managerBrief || {};
  let feed = runtimeFeedItems();
  if (!feed.length) feed = brief.proactive_feed || [];
  const focus = currentNeedCard();
  const focusId = focus?.id;

  // 兼容：无 feed 时从 ops_queue 轻量投影
  if (!feed.length) {
    const queue = brief.ops_queue || {};
    const mapReason = {
      time: "TIME",
      anomaly: "ANOMALY",
      history: "CONTINUATION",
      opportunity: "OPPORTUNITY",
      goal: "GOAL_DEVIATION",
      result: "RESULT",
      understanding: "UNDERSTANDING",
    };
    const label = {
      TIME: "时间节点",
      ANOMALY: "异常发现",
      CONTINUATION: "继续上次的事",
      OPPORTUNITY: "机会出现",
      GOAL_DEVIATION: "目标偏差",
      RESULT: "结果出来了",
      UNDERSTANDING: "需要你告诉我",
    };
    const pack = (card, status) =>
      card
        ? {
            id: card.id,
            reason: mapReason[card.interrupt_reason] || "ANOMALY",
            label: label[mapReason[card.interrupt_reason] || "ANOMALY"],
            domain: "PRODUCT",
            domain_label: "商品与店铺",
            summary: card.title,
            why_now: card.why_now || "",
            finding: card.why_now || card.summary || "",
            decision: card.ai_judgment || card.summary || "",
            action: card.ai_already_did || card.need_from_owner || "",
            status,
            occurred_at: card.updated_at || card.created_at || new Date().toISOString(),
            human_required: status === "need_you",
            next_check:
              card.next_check ||
              (card.observation_window_hours ? `${card.observation_window_hours} 小时后复看` : ""),
            related_workthread: card.id,
          }
        : null;
    feed = [
      ...(queue.need_you || []).map((c) => pack(c, "need_you")),
      ...(queue.results || []).map((c) => pack(c, "done")),
      ...(queue.working || []).map((c) => pack(c, c.arbiter_state === "auto_do" ? "auto_done" : "observing")),
      ...(queue.opportunities || []).map((c) => pack(c, "analyzing")),
    ].filter(Boolean);
  }

  // 中栏正在问的事，右栏不再重复一条
  feed = feed.filter((ev) => {
    if (focusId && ev.id === focusId) return false;
    if (isUnderstandingCard(focus) && (ev.reason === "UNDERSTANDING" || ev.label === "需要你告诉我")) {
      return false;
    }
    return true;
  });

  let itemsHtml = feed.length
    ? feed
        .slice(0, 8)
        .map((ev) => {
          const status = ev.status || "observing";
          const time = formatFeedTime(ev.occurred_at) || "刚刚";
          const reasonLabel = ev.label || {
            TIME: "时间节点",
            ANOMALY: "异常发现",
            CONTINUATION: "继续上次的事",
            OPPORTUNITY: "机会出现",
            GOAL_DEVIATION: "目标偏差",
            RESULT: "结果出来了",
            UNDERSTANDING: "需要你告诉我",
          }[ev.reason || "ANOMALY"];
          const domainLabel = ev.domain_label || proactiveDomainLabel(ev.domain);
          const kicker = [reasonLabel, domainLabel].filter(Boolean).join(" · ");
          const lines = [ev.finding || ev.why_now, ev.decision, ev.action].filter(Boolean).slice(0, 3);
          const impactLine = [ev.business_impact, ev.next_check].filter(Boolean).join(" · ");
          return `
          <article class="mk-feed-item ${escapeHtml(status)} clickable"
            data-rail-work="${status === "need_you" ? "need" : "ask"}"
            data-rail-prompt="${escapeHtml(ev.summary ? `关于「${ev.summary}」，现在怎样了？` : "")}"
            data-feed-id="${escapeHtml(ev.id || "")}">
            <div class="mk-feed-top">
              <time>${escapeHtml(`${time} · ${kicker}`)}</time>
              <span class="mk-feed-status">${escapeHtml(proactiveStatusLabel(status))}</span>
            </div>
            <strong>${escapeHtml(ev.summary || "经营动态")}</strong>
            ${
              lines.length
                ? `<div class="mk-feed-lines">${lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</div>`
                : ""
            }
            ${impactLine ? `<em class="mk-feed-impact">${escapeHtml(impactLine)}</em>` : ""}
          </article>`;
        })
        .join("")
    : `<article class="mk-feed-item observing">
        <div class="mk-feed-top"><time>今日</time><span class="mk-feed-status">观察中</span></div>
        <strong>我在持续盯店</strong>
        <p>有结果、机会或需要你时，会出现在这里。</p>
      </article>`;

  // 动作追踪（Tracing）：老板问"为什么 AI 做了这个"时可以追溯
  const traces = (state.actionTraces || []).slice(0, 5);
  if (traces.length) {
    itemsHtml += '<div class="mk-feed-divider">AI 动作记录</div>';
    traces.forEach(function(t) {
      var tTime = t.executed_at ? new Date(t.executed_at).toLocaleTimeString("zh-CN", {hour:"2-digit",minute:"2-digit"}) : "刚刚";
      var costText = t.cost ? " · ¥" + t.cost : "";
      var statusLabel = t.status === "success" ? "已完成" : t.status === "failed" ? "失败" : "执行中";
      itemsHtml += '<article class="mk-feed-item auto_done" data-explain-trace="' + escapeHtml(t.id) + '">'
        + '<div class="mk-feed-top"><time>' + escapeHtml(tTime + costText) + '</time>'
        + '<span class="mk-feed-status">' + escapeHtml(statusLabel) + '</span></div>'
        + '<strong>' + escapeHtml(t.action_type || t.trigger || "AI 动作") + '</strong>'
        + (t.diagnosis ? '<p>' + escapeHtml(t.diagnosis.slice(0, 80)) + '</p>' : '')
        + '<button class="mk-feed-why" type="button" data-explain-trace="' + escapeHtml(t.id) + '" style="font-size:11px;color:var(--mk-accent,#4a90d9);background:none;border:none;cursor:pointer;padding:4px 0;">为什么？</button>'
        + '</article>';
    });
  }

  rail.innerHTML = `
    <div class="mk-feed-head">
      <strong>MealKey · 今天</strong>
      <span>${escapeHtml(runtimeFeedSubtitle())}</span>
    </div>
    <div class="mk-feed-list">${itemsHtml}</div>
    <button type="button" class="mk-feed-more-link" data-scroll-target="section-events">查看全部经营事件 ›</button>
  `;
}

function runtimeFeedSubtitle() {
  const meta = runtimeBridgeMeta();
  const skills = Array.isArray(meta.selected_skills) ? meta.selected_skills.filter(Boolean) : [];
  if (skills.length) return `主动经营流 · ${skills.slice(0, 3).join(" / ")} 正在推进`;
  if (meta.candidate_count) return `主动经营流 · 已收敛 ${meta.candidate_count} 个经营候选`;
  return "主动经营流";
}

function renderOpsQueue() {
  const brief = state.managerBrief || {};
  const storeName = brief.store_name || state.dashboard?.store?.name || "门店";
  const storeEl = qs("#focusStoreName");
  if (storeEl) storeEl.textContent = storeName;
  applyOwnerProfileUI(state.ownerProfile || state.settingsOverview?.owner);

  const card = currentNeedCard();
  const interviewing = isUnderstandingCard(card);
  document.body.classList.toggle("interviewing", interviewing);
  document.body.classList.toggle(
    "home-chat-open",
    document.body.classList.contains("home-chat-open") || Boolean((state.chatMessages || []).length),
  );

  const badge = qs("#mkNeedBadge");
  if (badge) {
    badge.hidden = !card;
    badge.textContent = card ? "1" : "0";
  }

  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) {
    analyzing.hidden = !(state.chatMessages || []).some((m) => m.pending);
  }

  renderDecisionHost(card);
  renderHomeChatThread();
  renderWorkRail();
  renderContextRail();
  syncCommandBarForFocus(card);
}

function renderRecordWorkspace() {
  const host = qs("#recordWorkspaceBody");
  if (!host) return;
  const summary = state.dashboard?.execution_summary || {};
  const experiments = state.dashboard?.experiments || [];
  const memory = state.strategyMemory?.items || [];
  const pending = experiments.filter((item) => !item.result || item.result === "pending");
  const done = experiments.filter((item) => item.result && item.result !== "pending");

  host.innerHTML = `
    <div class="record-summary-row">
      <article><span>待确认</span><strong>${summary.proposed || 0}</strong></article>
      <article><span>实验中</span><strong>${summary.pending_verification || pending.length || 0}</strong></article>
      <article><span>已完成</span><strong>${summary.executed || done.length || 0}</strong></article>
      <article><span>策略记忆</span><strong>${memory.length}</strong></article>
    </div>
    <div class="record-columns">
      <section>
        <h3>正在做 / 待评估</h3>
        ${
          pending.length
            ? pending
                .slice(0, 6)
                .map(
                  (exp) => `
            <article class="record-row">
              <strong>${escapeHtml(exp.action_title || "实验")}</strong>
              <p>${escapeHtml(exp.notes || "观察中，有结果会主动告诉你。")}</p>
              ${
                exp.can_evaluate
                  ? `<button class="action-button primary" type="button" data-experiment-evaluate="${escapeHtml(
                      exp.id,
                    )}">评估结果</button>`
                  : `<span class="record-meta">观察中</span>`
              }
            </article>`,
                )
                .join("")
            : `<div class="empty-state soft">暂无进行中实验。</div>`
        }
      </section>
      <section>
        <h3>已有结果</h3>
        ${
          [...memory, ...done]
            .slice(0, 8)
            .map((item) => {
              const title = item.lesson || item.action_title || item.action_type || "结果";
              const copy =
                item.result_summary ||
                item.reuse_when ||
                item.avoid_when ||
                item.notes ||
                "已写入策略记忆";
              const lift =
                item.lift_pct == null ? "" : ` · ${formatDelta(item.lift_pct)}`;
              return `
              <article class="record-row">
                <strong>${escapeHtml(title)}</strong>
                <p>${escapeHtml(copy)}${escapeHtml(lift)}</p>
              </article>`;
            })
            .join("") || `<div class="empty-state soft">做完并评估后，结果会出现在这里。</div>`
        }
      </section>
    </div>
  `;
}

function renderStoreProfileCard() {
  const dashboard = state.dashboard || {};
  const brief = state.managerBrief;
  const runtime = runtimeWorkspacePanels();
  const store = dashboard.store || {};
  const name = runtime?.store?.store_name || brief?.store_name || store.name || "门店加载中";
  const metaBits = [store.city, store.area, store.category].filter(Boolean);
  const nameEl = qs("#sidebarStoreName");
  const metaEl = qs("#sidebarStoreMeta");
  const platformEl = qs("#sidebarPlatformTag");
  const openEl = qs("#sidebarOpenTag");
  if (nameEl) nameEl.textContent = name;
  if (metaEl) metaEl.textContent = metaBits.join(" · ") || "AI 店长工作台";
  if (platformEl) {
    const linked = (state.platformLinks || []).find((link) => link.status === "connected" || link.connected_at);
    platformEl.textContent = linked?.platform_label || linked?.platform || "未连接平台";
  }
  if (openEl) {
    const openStatus = dashboard.store_state?.platform_health?.open_status;
    openEl.textContent = openStatus === "closed" ? "休息中" : "营业中";
    openEl.classList.toggle("is-open", openStatus !== "closed");
  }
  applyOwnerProfileUI(state.ownerProfile || state.settingsOverview?.owner);
}

function renderHomeEventFeed() {
  const host = qs("#homeEventFeed");
  const tag = qs("#homeEventTag");
  if (!host) return;
  const events = state.operatingEvents?.events || [];
  const visible = events
    .filter((item) => !["ignored", "resolved"].includes(item.status))
    .slice(0, 5);
  if (tag) tag.textContent = `${visible.length} 条`;
  if (!visible.length) {
    host.innerHTML = `<div class="empty-state soft">今天暂无需要升级的实时事件。</div>`;
    return;
  }
  host.innerHTML = visible
    .map((event) => {
      const fingerprint =
        event.fingerprint || `${event.event_type}|${event.affected_metric || ""}|${event.title}`;
      const agentHint = event.recommended_agent
        ? agentLabel(event.recommended_agent)
        : "AI 店长";
      const conf =
        event.confidence == null ? "" : `置信 ${(Number(event.confidence) * 100).toFixed(0)}%`;
      return `
      <article class="home-event-row actionable">
        <div class="home-event-dot ${escapeHtml(event.severity || "medium")}"></div>
        <div>
          <strong>${escapeHtml(event.title)}</strong>
          <p>${escapeHtml(event.estimated_impact || event.detail || "")}</p>
          <div class="home-event-meta">${escapeHtml(agentHint)}${conf ? ` · ${conf}` : ""} · ${escapeHtml(
            managerDecisionLabel(event.manager_decision),
          )}</div>
          <div class="event-decision-actions compact">
            <button type="button" data-event-decision="handle_today" data-event-fingerprint="${escapeHtml(fingerprint)}">今天处理</button>
            <button type="button" data-event-decision="record" data-event-fingerprint="${escapeHtml(fingerprint)}">记录</button>
            <button type="button" data-event-decision="ignore" data-event-fingerprint="${escapeHtml(fingerprint)}">忽略</button>
          </div>
        </div>
      </article>`;
    })
    .join("");
}

function renderTodayMainline() {
  const host = qs("#todayMainlineFlow");
  const meta = qs("#mainlineMeta");
  if (!host) return;

  const ctx = homePulseContext();
  const {
    brief,
    dashboard,
    primaryAction,
    primaryExperiment,
    pendingExperiment,
    confidence,
    handleTodayCount,
    problem,
    problems,
  } = ctx;

  const problemTitle =
    problem?.title ||
    brief?.top_problem_title ||
    dashboard.today_risk?.title ||
    dashboard.observations?.[0]?.what_happened ||
    "暂无高优先级异常";
  const problemDetail =
    problem?.detail ||
    brief?.top_problem_detail ||
    dashboard.today_risk?.impact ||
    dashboard.daily_brief?.reason ||
    "经营信号平稳，可先观察。";
  const diagnoseTitle =
    problems[1]?.title ||
    dashboard.agents?.diagnosis?.root_cause ||
    dashboard.hypothesis?.root_cause ||
    dashboard.daily_brief?.yesterday_change ||
    "正在定位流量 / 点击 / 转化";
  const diagnoseDetail =
    problems[1]?.detail ||
    (dashboard.agents?.diagnosis?.root_causes || [])[0]?.explanation ||
    dashboard.agents?.diagnosis?.executive_summary ||
    dashboard.agents?.growth?.reason ||
    "曝光、点击、转化将分别核对，避免误伤价格。";
  const experimentTitle =
    primaryExperiment?.title ||
    brief?.primary_experiment_title ||
    primaryAction?.title ||
    dashboard.agents?.growth?.today_priority ||
    "等待生成今日主实验";
  const windowHours =
    primaryExperiment?.window_hours ||
    primaryAction?.window_hours ||
    pendingExperiment?.window_hours ||
    48;
  const button = actionButtonConfig(primaryAction);
  const liftHint =
    primaryExperiment?.expected_lift_high != null
      ? `预计提升 ${primaryExperiment.expected_lift_low || 0}-${primaryExperiment.expected_lift_high}%`
      : primaryAction?.expected_lift_pct_high
        ? `预计提升 ${primaryAction.expected_lift_pct_low || 0}-${primaryAction.expected_lift_pct_high}%`
        : brief?.primary_experiment_window || `窗口 ${windowHours}h · ${primaryExperiment?.expected_metric || "核心指标"}`;
  const canEvaluate = Boolean(primaryExperiment?.can_evaluate || pendingExperiment?.can_evaluate);
  const observeState = pendingExperiment
    ? canEvaluate
      ? "观察窗已到，可以评估结果"
      : `观察中 · ${pendingExperiment.action_title || experimentTitle}`
    : primaryAction?.status === "executed" || primaryExperiment?.status === "executed"
      ? "已开始，自动追踪中"
      : "等待开始";

  if (meta) {
    meta.textContent = handleTodayCount
      ? `今天只处理 ${handleTodayCount} 个需要处理的异常`
      : "今天没有需要打断你的异常";
  }

  const experimentId = primaryExperiment?.experiment_id || pendingExperiment?.id;
  const recId = primaryExperiment?.recommendation_id || primaryAction?.id;

  host.innerHTML = `
    <article class="mainline-step discover">
      <div class="mainline-step-label">1 发现异常</div>
      <h3>${escapeHtml(problemTitle)}</h3>
      <p>${escapeHtml(problemDetail)}</p>
      <div class="mainline-step-meta">${problem?.severity || (handleTodayCount ? "关键" : "平稳")}${
        problem?.source_agent ? ` · ${escapeHtml(agentLabel(problem.source_agent))}` : ""
      }</div>
    </article>
    <article class="mainline-step diagnose">
      <div class="mainline-step-label">2 判断原因</div>
      <h3>${escapeHtml(diagnoseTitle)}</h3>
      <p>${escapeHtml(diagnoseDetail)}</p>
      <div class="mainline-step-meta">${
        confidence == null ? "置信度待更新" : `置信度 ${Math.round(Number(confidence) * 100)}%`
      }</div>
    </article>
    <article class="mainline-step execute">
      <div class="mainline-step-label">3 主实验</div>
      <h3>${escapeHtml(experimentTitle)}</h3>
      <p>${escapeHtml(liftHint)}</p>
      <div class="mainline-step-actions">
        ${
          button?.endpoint && recId
            ? `<button class="action-button primary" data-recommendation-id="${escapeHtml(
                recId,
              )}" data-recommendation-action="${escapeHtml(button.endpoint)}">${escapeHtml(
                button.label === "先确认" ? "开始实验" : button.label,
              )}</button>`
            : `<button class="action-button primary" type="button" data-scroll-target="section-growth">查看增长策略</button>`
        }
        ${
          button?.canIgnore && recId
            ? `<button class="action-button ghost" data-recommendation-id="${escapeHtml(
                recId,
              )}" data-recommendation-action="ignore">忽略</button>`
            : ""
        }
        ${
          button?.secondary?.endpoint && recId
            ? `<button class="action-button ghost" data-recommendation-id="${escapeHtml(
                recId,
              )}" data-recommendation-action="${escapeHtml(button.secondary.endpoint)}">${escapeHtml(
                button.secondary.label,
              )}</button>`
            : ""
        }
      </div>
    </article>
    <article class="mainline-step observe">
      <div class="mainline-step-label">4 观察结果</div>
      <h3>${windowHours}h 自动追踪</h3>
      <p>${escapeHtml(observeState)}</p>
      <div class="mainline-step-actions">
        ${
          experimentId && canEvaluate
            ? `<button class="action-button primary" data-experiment-evaluate="${escapeHtml(
                experimentId,
              )}">评估结果</button>`
            : experimentId
              ? `<div class="mainline-step-meta">观察窗未到，先不要评估</div>`
              : `<div class="mainline-step-meta">开始实验后进入观察</div>`
        }
      </div>
    </article>
  `;
}

function renderWorthDoing() {
  const host = qs("#worthDoingList");
  if (!host) return;
  const ctx = homePulseContext();
  const { brief, tasks, dashboard } = ctx;
  const secondaryTasks = (tasks || []).slice(1, 3);
  const fallbackActions = (dashboard.action_packages || dashboard.today_tasks || []).slice(1, 3);

  const rows = secondaryTasks.length
    ? secondaryTasks.map((task) => {
        const action = resolveActionById(task.recommendation_id);
        const lift =
          task.expected_lift_high != null
            ? `预计 ${task.expected_lift_low || 0}-${task.expected_lift_high}%`
            : task.expected_metric
              ? `盯 ${task.expected_metric}`
              : agentLabel(task.agent_key);
        return {
          title: task.title,
          copy: task.detail || "可与主实验并行",
          impact: lift,
          action,
          scroll: agentSectionId(task.agent_key) || "section-growth",
        };
      })
    : fallbackActions.map((action) => ({
        title: action.title,
        copy: action.summary || actionImpact(action).label,
        impact: actionImpact(action).label,
        action,
        scroll: "section-growth",
      }));

  if (!rows.length && brief?.top_opportunity_title) {
    rows.push({
      title: brief.top_opportunity_title,
      copy: brief.top_opportunity_detail || "可与主实验并行观察",
      impact: "机会并行",
      scroll: "section-growth",
    });
  }

  const titleEl = qs("#worthDoingTitle");
  if (titleEl) titleEl.textContent = rows.length ? `今天还有 ${rows.length} 件值得做` : "今天先盯主实验";

  if (!rows.length) {
    host.innerHTML = `<div class="empty-state">今天先盯主实验即可，暂无并行事项。</div>`;
    return;
  }

  host.innerHTML = rows
    .map((row) => {
      const button = row.action ? actionButtonConfig(row.action) : null;
      return `
      <article class="worth-doing-card">
        <div>
          <strong>${escapeHtml(row.title)}</strong>
          <p>${escapeHtml(row.copy)}</p>
          ${row.impact ? `<span class="worth-doing-impact">${escapeHtml(row.impact)}</span>` : ""}
        </div>
        ${
          button?.endpoint && row.action?.id
            ? `<button class="action-button" data-recommendation-id="${escapeHtml(
                row.action.id,
              )}" data-recommendation-action="${escapeHtml(button.endpoint)}">${escapeHtml(
                button.label,
              )}</button>`
            : `<button class="link-button" type="button" data-scroll-target="${escapeHtml(
                row.scroll || "section-matrix",
              )}">查看</button>`
        }
      </article>`;
    })
    .join("");
}

function renderAutoActivity() {
  const hosts = [qs("#homeAutoActivityList"), qs("#autoActivityList")].filter(Boolean);
  if (!hosts.length) return;
  const ctx = homePulseContext();
  const { parallelNotes } = ctx;
  const collectionRuns = state.collectionRuns || [];
  const items = [];

  (parallelNotes || []).forEach((note) => {
    items.push({
      tone: note.kind === "confirm" ? "warn" : "ok",
      text: note.title,
      scroll: agentSectionId(note.agent_key) || "section-matrix",
    });
  });

  if (collectionRuns[0]?.status === "completed") {
    items.push({
      tone: "ok",
      text: `数据采集最近一次已完成`,
      scroll: "section-collection",
    });
  }

  const merged = items.slice(0, 6);
  const html = !merged.length
    ? `<div class="empty-state soft">后台尚无自动完成记录；有扫描/回复结果后会出现在这里。</div>`
    : merged
        .map(
          (item) => `
      <button type="button" class="auto-activity-row ${item.tone}" data-scroll-target="${escapeHtml(item.scroll)}">
        <span>${item.tone === "warn" ? "⚠" : "✓"}</span>
        <span>${escapeHtml(item.text)}</span>
      </button>`,
        )
        .join("");
  hosts.forEach((host) => {
    host.innerHTML = html;
  });
}

function renderVerifiedWins() {
  const listHost = qs("#verifiedWinsList");
  const feedHost = qs("#homeWinsFeed");
  const meta = qs("#verifiedWinsMeta");
  const tag = qs("#homeWinsTag");
  if (!listHost && !feedHost) return;

  const memoryItems = (state.strategyMemory?.items || []).filter((item) =>
    ["positive", "neutral"].includes(item.result),
  );
  const experiments = (state.dashboard?.experiments || []).filter((item) =>
    ["positive", "effective", "success"].includes(String(item.result || "").toLowerCase()),
  );
  const rows = [];

  memoryItems.forEach((item) => {
    rows.push({
      title: item.lesson || item.action_type || "策略经验",
      badges: [
        item.lift_pct == null ? null : `指标 ${formatDelta(item.lift_pct)}`,
        item.result === "positive" ? "已验证有效" : "继续观察",
      ].filter(Boolean),
      copy: item.reuse_when || item.avoid_when || "可复用于相似场景",
      tone: item.result === "positive" ? "positive" : "neutral",
    });
  });

  experiments.forEach((exp) => {
    if (rows.some((row) => row.title === exp.action_title)) return;
    rows.push({
      title: exp.action_title || "实验",
      badges: [
        exp.lift_pct == null ? null : `${exp.metric_name || "指标"} ${formatDelta(exp.lift_pct)}`,
        "已验证有效",
      ].filter(Boolean),
      copy: exp.result_summary || exp.notes || "已沉淀到学习循环",
      tone: "positive",
    });
  });

  if (!rows.length) {
    (state.strategyMemory?.positive_patterns || []).slice(0, 3).forEach((pattern) => {
      rows.push({
        title: pattern,
        badges: ["策略记忆"],
        copy: "已加入本店策略记忆",
        tone: "positive",
      });
    });
  }

  if (meta) meta.textContent = `${rows.length} 条`;
  if (tag) tag.textContent = String(rows.length);

  const empty = `<div class="empty-state soft">评估实验后，有效结果会出现在这里。</div>`;
  const cardHtml = rows.length
    ? takeTop(rows, 3)
        .map(
          (row) => `
      <article class="verified-win-card ${row.tone}">
        <strong>${escapeHtml(row.title)}</strong>
        <p>${escapeHtml(row.copy)}</p>
        <div class="verified-win-badges">
          ${row.badges.map((badge) => `<span>${escapeHtml(badge)}</span>`).join("")}
        </div>
      </article>`,
        )
        .join("")
    : empty;
  const feedHtml = rows.length
    ? takeTop(rows, 3)
        .map(
          (row) => `
      <article class="home-win-row ${row.tone}">
        <strong>${escapeHtml(row.title)}</strong>
        <div>${row.badges.map((badge) => `<span>${escapeHtml(badge)}</span>`).join("")}</div>
        <p>${escapeHtml(row.copy)}</p>
      </article>`,
        )
        .join("")
    : empty;

  if (listHost) listHost.innerHTML = cardHtml;
  if (feedHost) feedHost.innerHTML = feedHtml;
}

function renderEventDigest() {
  const events = state.operatingEvents;
  const digest = qs("#eventDigest");
  const meta = qs("#eventSectionMeta");
  if (!digest) return;

  if (!events) {
    if (meta) meta.textContent = "感知层未返回";
    digest.innerHTML = `<div class="empty-state">异常事件尚未加载，刷新看板后重试。</div>`;
    return;
  }

  const actionable = (events.events || []).filter(
    (item) =>
      ["handle_today", "alert_owner"].includes(item.manager_decision) &&
      !["ignored", "resolved"].includes(item.status),
  );
  const visible = (actionable.length ? actionable : events.events || [])
    .filter((item) => !["ignored", "resolved"].includes(item.status))
    .slice(0, 6);
  if (meta) {
    meta.textContent = events.summary || `待处理 ${events.handle_today_count || 0} · 提醒 ${events.alert_count || 0}`;
  }

  if (!visible.length) {
    digest.innerHTML = `<div class="empty-state">今天没有需要你处理的异常。AI 店长会继续盯着营业、商品、活动与商圈变化。</div>`;
    return;
  }

  digest.innerHTML = visible
    .map((event) => {
      const severity = event.severity || "medium";
      const sectionId = agentSectionId(event.recommended_agent);
      const fingerprint = event.fingerprint || `${event.event_type}|${event.affected_metric || ""}|${event.title}`;
      const agentHint = event.recommended_agent
        ? `建议交给 ${agentLabel(event.recommended_agent)}`
        : "由 AI 店长统筹";
      return `
        <article class="event-row">
          <div class="event-severity ${escapeHtml(severity)}">${escapeHtml(eventSeverityLabel(severity))}</div>
          <div>
            <div class="event-row-title">${escapeHtml(event.title)}</div>
            <div class="event-row-copy">${escapeHtml(event.estimated_impact || event.detail || "")}</div>
            <div class="event-row-meta">${escapeHtml(agentHint)}${
              event.affected_metric ? ` · 影响 ${escapeHtml(event.affected_metric)}` : ""
            }${
              event.confidence != null ? ` · 置信 ${(Number(event.confidence) * 100).toFixed(0)}%` : ""
            }</div>
            <div class="event-decision-actions">
              <button type="button" data-event-decision="handle_today" data-event-fingerprint="${escapeHtml(fingerprint)}">今天处理</button>
              <button type="button" data-event-decision="record" data-event-fingerprint="${escapeHtml(fingerprint)}">记录</button>
              <button type="button" data-event-decision="ignore" data-event-fingerprint="${escapeHtml(fingerprint)}">忽略</button>
              <button type="button" data-event-decision="resolved" data-event-fingerprint="${escapeHtml(fingerprint)}">已解决</button>
            </div>
          </div>
          <div class="event-decision-stack">
            <div class="event-decision">${escapeHtml(managerDecisionLabel(event.manager_decision))}</div>
            ${
              sectionId
                ? `<button class="link-button" type="button" data-scroll-target="${sectionId}">去处理</button>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function renderActionCenter() {
  const dashboard = state.dashboard;
  const brief = state.managerBrief;
  const actions = takeTop(dashboard.action_packages || dashboard.today_tasks || [], 3);
  const execution = dashboard.execution_summary || {};
  qs("#actionSummaryMeta").textContent = brief?.primary_experiment_title
    ? `主实验：${brief.primary_experiment_title}`
    : `已做 ${execution.executed || 0} 条｜还在看 ${execution.pending_verification || 0} 条`;
  qs("#actionTableFoot").textContent = `共 ${(dashboard.action_packages || dashboard.today_tasks || []).length || 0} 条候选，今天只盯主实验`;

  if (!actions.length) {
    qs("#actionCenter").innerHTML = `<div class="empty-state">今天还没有主实验，先看上面的判断，或刷新增长策略。</div>`;
    return;
  }

  qs("#actionCenter").innerHTML = actions
    .map((action, index) => {
      const button = actionButtonConfig(action);
      const signal = workflowNote(action);
      const impact = actionImpact(action);
      const difficulty = actionDifficulty(action);
      const metricHint = action.expected_lift_pct_high
        ? `做好后预计提升 ${action.expected_lift_pct_low || 0}-${action.expected_lift_pct_high}%`
        : "先做小动作试一试";
      return `
        <article class="action-row">
          <div class="action-rank">${index + 1}</div>
          <div class="action-thumb-wrap">
            <img class="thumb" src="${imageForFood(action.object_name || action.title)}" alt="${escapeHtml(action.object_name || action.title)}" />
            <div class="thumb-caption">${escapeHtml(action.object_name || "门店")}</div>
          </div>
          <div>
            <div class="action-row-head">
              <div class="action-row-title">${escapeHtml(action.title)}</div>
              ${
                action.execution_phase
                  ? `<span class="phase-pill ${executionPhaseClass(action.execution_phase)}">${escapeHtml(formatExecutionPhase(action.execution_phase))}</span>`
                  : ""
              }
            </div>
            <div class="action-row-copy">${escapeHtml(action.summary || "先用单变量动作验证问题。")}</div>
            <div class="action-row-meta">
              <span>${escapeHtml(action.object_name || "门店整体")}</span>
              <span>${escapeHtml(metricHint)}</span>
              <span>窗口 ${escapeHtml(action.window_hours || "--")}h</span>
            </div>
            ${signal ? `<div class="action-signal">${escapeHtml(signal)}</div>` : ""}
          </div>
          <div class="action-impact ${impact.className}">${impact.label}</div>
          <div class="action-difficulty ${difficulty.className}">${difficulty.label}</div>
          <div class="action-button-stack">
            <div class="row-status ${statusClass(action.status)}">${escapeHtml(formatStatus(action.status))}</div>
            ${
              button?.endpoint
                ? `<button class="action-button ${button.className}" data-recommendation-id="${action.id}" data-recommendation-action="${button.endpoint}">${escapeHtml(button.label)}</button>`
                : ""
            }
            ${
              button?.secondary?.endpoint
                ? `<button class="action-button ghost" data-recommendation-id="${action.id}" data-recommendation-action="${button.secondary.endpoint}">${escapeHtml(button.secondary.label)}</button>`
                : button?.secondary?.scroll
                  ? `<button class="action-button" data-scroll-target="${button.secondary.scroll}">${escapeHtml(button.secondary.label)}</button>`
                  : !button?.endpoint
                    ? `<button class="action-button" data-scroll-target="${button?.scroll || "section-growth"}">${escapeHtml(button?.label || "查看增长策略")}</button>`
                    : ""
            }
            ${
              button?.canIgnore
                ? `<button class="action-button ghost" data-recommendation-id="${action.id}" data-recommendation-action="ignore">忽略</button>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function productPreview(content = {}) {
  if (content.suggested_title) {
    return `<div class="product-preview-line"><span>建议标题</span><strong>${escapeHtml(content.suggested_title)}</strong></div>`;
  }
  if (content.visual_brief) {
    return `<div class="product-preview-line"><span>主图 Brief</span><strong>${escapeHtml(content.visual_brief)}</strong></div>`;
  }
  if (content.bundle_name) {
    return `<div class="product-preview-line"><span>套餐方案</span><strong>${escapeHtml(content.bundle_name)}${
      content.suggested_price ? ` · ¥${content.suggested_price}` : ""
    }</strong></div>`;
  }
  if (Array.isArray(content.value_points)) {
    return `<div class="product-preview-line"><span>价值表达</span><strong>${escapeHtml(content.value_points.join(" · "))}</strong></div>`;
  }
  return "";
}

function menuRoleLabel(role) {
  const labels = {
    "Hero Product": "主推款",
    "Traffic Product": "引流款",
    "Profit Product": "利润款",
    "Basket Builder": "搭配品",
    "Zombie SKU": "低效 SKU",
    "Experimental Product": "实验款",
    traffic: "引流款",
    hero: "主推款",
    profit: "利润款",
    add_on: "搭配品",
    low_efficiency: "低效 SKU",
    unknown: "待判断",
  };
  return labels[role] || role || "待判断";
}

function menuRoleClass(role = "") {
  if (role.includes("Traffic") || role === "traffic") return "traffic";
  if (role.includes("Hero") || role === "hero") return "hero";
  if (role.includes("Profit") || role === "profit") return "profit";
  if (role.includes("Basket") || role === "add_on") return "add_on";
  if (role.includes("Zombie") || role === "low_efficiency") return "low_efficiency";
  return "unknown";
}

function renderMenuAgent() {
  const menu = state.dashboard?.agents?.menu || {};
  const roles = menu.role_distribution || {};
  const current = menu.current_action;
  const queueBrief = actionQueueBrief(menu);
  qs("#menuHealthTag").textContent = menu.readiness
    ? `菜单健康度 ${menu.menu_health_score ?? "--"} 分 · ${formatReadiness(menu.readiness)}`
    : `菜单健康度 ${menu.menu_health_score ?? "--"} 分`;
  qs("#menuWorkflowSummary").textContent =
    queueBrief ||
    (current
      ? `${formatExecutionPhase(current.execution_phase)}｜${current.phase_reason || current.next_decision || menu.workflow_summary || "先继续看菜单反馈。"}`
      : menu.workflow_summary || "菜单证据还不够，先补齐商品和订单数据。");
  qs("#menuItemCount").textContent = `${(menu.items || []).length} 个商品`;
  qs("#menuRoleGrid").innerHTML = Object.entries(roles).length
    ? Object.entries(roles)
        .map(
          ([role, count]) => `
            <div>
              <strong>${count}</strong>
              <span>${escapeHtml(menuRoleLabel(role))}</span>
            </div>
          `,
        )
        .join("")
    : `<div><strong>--</strong><span>等待角色识别</span></div>`;

  const ladder = menu.pricing_ladder || {};
  qs("#menuPriceRange").textContent =
    ladder.anchor_min === null || ladder.anchor_min === undefined
      ? "价格锚点待建立"
      : `¥${ladder.anchor_min} — ¥${ladder.anchor_max}`;
  qs("#menuPriceBands").innerHTML = [
    ["低价带", ladder.low_band_count || 0],
    ["主价格带", ladder.mid_band_count || 0],
    ["高价带", ladder.high_band_count || 0],
  ]
    .map(([label, count]) => `<div><strong>${count}</strong><span>${label}</span></div>`)
    .join("");
  qs("#menuPriceGap").textContent = ladder.gap_note || "当前价格梯度没有明显缺口。";

  qs("#menuItemList").innerHTML = (menu.items || []).length
    ? takeTop(menu.items, 8)
        .map(
          (item) => `
            <article class="menu-item-row">
              <img src="${imageForFood(item.name)}" alt="${escapeHtml(item.name)}" />
              <div>
                <strong>${escapeHtml(item.name)}</strong>
                <p>${escapeHtml(item.rationale)}</p>
              </div>
              <span class="menu-role ${menuRoleClass(item.role)}">${escapeHtml(menuRoleLabel(item.role))}</span>
              <div class="menu-item-metrics">
                <strong>${item.price === null || item.price === undefined ? "--" : `¥${item.price}`}</strong>
                <small>${item.order_share_pct === null || item.order_share_pct === undefined ? "占比 --" : `订单占比 ${item.order_share_pct.toFixed(1)}%`}</small>
            </div>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无菜单商品，请先导入菜单。</div>`;

  const gaps = [
    ...(menu.structural_gaps || []),
    ...(menu.document_gaps || []),
    ...(menu.blockers || []),
    ...(menu.evidence || []),
    ...(menu.category_summary || []).map(
      (row) => `${row.category}：${row.health_note || `${row.item_count} 个商品`}`,
    ),
  ];
  qs("#menuGapList").innerHTML = gaps.length
    ? takeTop(gaps, 8).map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>当前没有明显菜单结构缺口。</span></div>`;

  renderMenuDeepDiagnosis();

  qs("#menuPatchList").innerHTML = (menu.suggested_patches || []).length
    ? takeTop(menu.suggested_patches, 3)
        .map(
          (patch, index) => `
            <article class="menu-action-card">
              <span>${escapeHtml(menuRoleLabel(patch.target_role) || patch.patch_type)}</span>
              <h3>${escapeHtml(patch.item_name)}${patch.suggested_price ? ` · ¥${patch.suggested_price}` : ""}</h3>
              <p>${escapeHtml(patch.reason)}</p>
              <small>${escapeHtml(patch.expected_outcome)}</small>
              <button data-menu-action="patches" data-menu-index="${index}">生成并加入菜单</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无需要补齐的菜单缺口。</div>`;
  qs("#menuBundleList").innerHTML = (menu.bundle_opportunities || []).length
    ? takeTop(menu.bundle_opportunities, 3)
        .map(
          (bundle, index) => `
            <article class="menu-action-card">
              <span>套餐组合</span>
              <h3>${escapeHtml(bundle.primary_item_name)} + ${escapeHtml(bundle.attach_item_name)}</h3>
              <p>${escapeHtml(bundle.reason)}</p>
              <small>${escapeHtml(bundle.expected_outcome)}</small>
              <button data-menu-action="bundles" data-menu-index="${index}">生成套餐动作</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂未发现高置信度套餐机会。</div>`;
  qs("#menuCleanupList").innerHTML = (menu.cleanup_candidates || []).length
    ? takeTop(menu.cleanup_candidates, 3)
        .map(
          (candidate, index) => `
            <article class="menu-action-card warning">
              <span>${escapeHtml(candidate.action || "低效商品")}</span>
              <h3>${escapeHtml(candidate.name)}</h3>
              <p>${escapeHtml(candidate.reason)}</p>
              <small>${escapeHtml(menuRoleLabel(candidate.role))} · 建议先创建清理实验再决定是否下架</small>
              <button data-menu-action="cleanup" data-menu-index="${index}">创建清理实验</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前没有需要清理的商品。</div>`;
}

function renderCompetitionAgent() {
  const competition = state.dashboard?.agents?.competition || state.dashboard?.competition || {};
  qs("#competitionAgentScore").textContent = competition.competition_score ?? "--";
  qs("#competitionReadiness").textContent = `准备度 ${formatReadiness(competition.readiness)}`;
  qs("#competitionBenchmark").textContent = `基准组 ${competition.benchmark_group || "--"}`;
  qs("#competitionAgentConclusion").textContent =
    competition.conclusion || "当前还没有足够竞品证据，先完成商圈采集。";
  qs("#competitionExpectedImpact").textContent =
    competition.expected_impact || "完成快照后会给出预期影响。";
  qs("#competitionFocusList").innerHTML = (competition.market_focus || []).length
    ? competition.market_focus.map((row) => `<span>${escapeHtml(row)}</span>`).join("")
    : `<span>等待商圈焦点</span>`;

  qs("#competitionAgentList").innerHTML = (competition.top_competitors || []).length
    ? takeTop(competition.top_competitors, 4)
        .map(
          (competitor) => `
            <article class="competition-agent-card">
              <div class="competition-agent-card-top">
                <strong>${escapeHtml(competitor.name)}</strong>
                <span>${competitor.score ?? "--"} 分</span>
              </div>
              <p>${escapeHtml(competitor.positioning || "同商圈竞品")} · ${
                competitor.distance_m ? `${Math.round(competitor.distance_m)}m` : "同商圈"
              }</p>
              <div class="competition-agent-tags">
                ${(competitor.strengths || []).slice(0, 2).map((row) => `<span>优 ${escapeHtml(row)}</span>`).join("")}
                ${(competitor.weaknesses || []).slice(0, 2).map((row) => `<span class="weak">弱 ${escapeHtml(row)}</span>`).join("")}
            </div>
              <small>${
                competitor.recent_move
                  ? `最近变化：${escapeHtml(competitor.recent_move)}`
                  : `主推：${escapeHtml((competitor.featured_products || []).slice(0, 2).join(" / ") || "暂无")}`
              }</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无重点竞品，请先更新商圈快照。</div>`;

  qs("#competitionChangeGrid").innerHTML = (competition.changes || []).length
    ? takeTop(competition.changes, 6)
        .map(
          (change) => `
            <div class="competition-change-card">
              <strong>${escapeHtml(change.type || "变化")}</strong>
              <p>${escapeHtml(change.summary)}</p>
              <small>${change.price === null || change.price === undefined ? "价格未变" : `¥${change.price}`}</small>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">近期没有可追踪的竞品变化。</div>`;

  const threats = [
    ...(competition.threat_signals || []),
    ...(competition.blockers || []),
    ...(competition.evidence || []),
    ...(competition.reasons || []),
  ];
  qs("#competitionThreatList").innerHTML = threats.length
    ? takeTop(threats, 6).map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>暂无威胁信号，继续保持日常监测。</span></div>`;
  const actionRows = competition.actions || [];
  qs("#competitionActionList").innerHTML = actionRows.length
    ? actionRows
        .map((row) => {
          const text = String(row || "");
          let scroll = "section-growth";
          let label = "交给增长策略排序";
          if (/主图|装修|店页|第一眼|图片/.test(text)) {
            scroll = "section-storefront";
            label = "去线上装修";
          } else if (/套餐|菜单|SKU|价格带/.test(text)) {
            scroll = "section-menu";
            label = "去菜单分析";
          } else if (/商品|CTR|CVR|主推/.test(text)) {
            scroll = "section-product";
            label = "去商品优化";
          } else if (/活动|补贴/.test(text)) {
            scroll = "section-promo";
            label = "去平台活动";
          } else if (/采集|快照|连接/.test(text)) {
            scroll = "section-collection";
            label = "去数据采集";
          }
          return `
            <div class="agent-action-row">
              <strong>→</strong>
              <span>${escapeHtml(text)}</span>
              <button class="link-button" type="button" data-scroll-target="${scroll}">${label}</button>
            </div>
          `;
        })
        .join("")
    : `<div class="agent-action-row"><strong>→</strong><span>先更新快照，再决定响应动作。</span><button class="link-button" type="button" data-scroll-target="section-collection">去数据采集</button></div>`;
}

function renderStorefrontAgent() {
  const storefront = state.dashboard?.agents?.storefront || {};
  const impact = storefront.sales_impact || {};
  qs("#storefrontScore").textContent = storefront.health_score ?? "--";
  qs("#storefrontHealthTag").textContent = `装修健康度 ${storefront.health_score ?? "--"} 分 · ${formatReadiness(storefront.readiness)}`;
  qs("#storefrontConclusion").textContent = storefront.conclusion || "暂无线上装修结论。";
  qs("#storefrontImpact").textContent = impact.narrative || storefront.expected_impact || "完成诊断后给出销售影响预估。";
  qs("#storefrontReadiness").textContent = `准备度 ${formatReadiness(storefront.readiness)}`;
  const queueBrief = actionQueueBrief(storefront);
  qs("#storefrontCurrentAction").textContent =
    queueBrief || "先创建一条装修动作，再进入采纳→执行→验证。";

  qs("#storefrontDimensionList").innerHTML = (storefront.dimensions || []).length
    ? storefront.dimensions
        .map(
          (dim) => `
            <article class="storefront-dimension-card status-${escapeHtml(dim.status || "watch")}">
              <div class="storefront-dimension-top">
                <strong>${escapeHtml(dim.label)}</strong>
                <span>${dim.score ?? "--"}</span>
              </div>
              <p>${escapeHtml(dim.summary || "")}</p>
              <small>销售杠杆：${escapeHtml((dim.sales_lever || "ctr").toUpperCase())}</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无装修维度结果。</div>`;

  qs("#storefrontIssueList").innerHTML = (storefront.issues || []).length
    ? storefront.issues
        .map(
          (issue) => `
            <article class="storefront-issue-card severity-${escapeHtml(issue.severity || "medium")}">
              <div class="storefront-issue-top">
                <strong>${escapeHtml(issue.title)}</strong>
                <span>${escapeHtml(issue.severity === "high" ? "高优" : issue.severity === "low" ? "观察" : "中优")}</span>
              </div>
              <p>${escapeHtml(issue.detail || "")}</p>
              <small>${escapeHtml(issue.sales_impact_est || "")}</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无高优先级装修漏洞，维持主图与套餐观察即可。</div>`;

  qs("#storefrontActionGrid").innerHTML = (storefront.priority_actions || []).length
    ? storefront.priority_actions
        .map(
          (action, index) => `
            <article class="storefront-action-card">
              <div class="storefront-action-top">
                <strong>${escapeHtml(action.title)}</strong>
                <span>${escapeHtml((action.expected_metric || "ctr").toUpperCase())} +${Number(action.expected_lift_pct_low || 0).toFixed(0)}~${Number(action.expected_lift_pct_high || 0).toFixed(0)}%</span>
              </div>
              <p>${escapeHtml(action.detail || "")}</p>
              <small>${escapeHtml((action.generated_content && (action.generated_content.visual_brief || action.generated_content.ia_brief || action.generated_content.bundle_brief || action.generated_content.trust_brief)) || "可回退的店页改造")}</small>
              <button class="topbar-button primary" data-storefront-action-index="${index}">AI 生成并落库动作</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前没有可落库的装修动作。</div>`;
}

function renderStorefrontAiPanel(payload) {
  const panel = qs("#storefrontAiPanel");
  const title = qs("#storefrontAiTitle");
  const body = qs("#storefrontAiBody");
  if (!panel || !body) return;
  const plan = payload?.plan || payload || {};
  const assistType = payload?.assist_type || plan.assist_type || "decorate";
  state.storefrontAiPlan = plan;
  title.textContent =
    assistType === "image_optimize"
      ? plan.title || "AI 主图优化方案"
      : plan.title || "AI 装修协助方案";

  if (assistType === "image_optimize") {
    body.innerHTML = `
      <p class="storefront-ai-summary">${escapeHtml(plan.goal || "")}</p>
      <div class="storefront-ai-block"><strong>问题</strong><p>${escapeHtml(plan.problem || "")}</p></div>
      <div class="storefront-ai-block"><strong>拍摄清单</strong><ul>${(plan.shot_list || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-block"><strong>中文提示词</strong><code>${escapeHtml(plan.prompt_zh || "")}</code></div>
      <div class="storefront-ai-block"><strong>英文提示词</strong><code>${escapeHtml(plan.prompt_en || "")}</code></div>
      <div class="storefront-ai-block"><strong>验收清单</strong><ul>${(plan.checklist || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-meta">模式：${escapeHtml(plan.mode || "--")}${
        plan.llm ? ` · ${escapeHtml(plan.llm.provider)}/${escapeHtml(plan.llm.model)}` : ""
      }</div>
    `;
  } else {
    body.innerHTML = `
      <p class="storefront-ai-summary">${escapeHtml(plan.summary || "")}</p>
      <div class="storefront-ai-block"><strong>销售重点</strong><p>${escapeHtml(plan.sales_focus || "")}</p></div>
      <div class="storefront-ai-steps">${(plan.steps || [])
        .map(
          (step) => `
            <article>
              <strong>${step.order || ""}. ${escapeHtml(step.title || "")}</strong>
              <p>${escapeHtml(step.why || "")}</p>
              <p>怎么做：${escapeHtml(step.how || "")}</p>
              <small>验证：${escapeHtml(step.verify || "")}</small>
            </article>
          `,
        )
        .join("")}</div>
      <div class="storefront-ai-block"><strong>店页文案包</strong>
        <p>店招：${escapeHtml(plan.copy_pack?.store_tagline || "--")}</p>
        <p>招牌：${escapeHtml(plan.copy_pack?.signature_title || "--")}</p>
        <p>套餐：${escapeHtml(plan.copy_pack?.set_meal_title || "--")}</p>
      </div>
      <div class="storefront-ai-block"><strong>不要做</strong><ul>${(plan.do_not_do || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-meta">下一步：${escapeHtml(plan.next_action || "--")} · 模式 ${escapeHtml(plan.mode || "--")}</div>
    `;
  }
  panel.hidden = false;
  scrollToSection("section-storefront");
}

async function runStorefrontAiDecorate() {
  if (!state.currentStoreId) return;
  const button = qs("#aiStorefrontDecorateBtn");
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "AI 生成中…";
  }
  try {
    const payload = await fetchJson(`/stores/${state.currentStoreId}/agents/storefront/ai/decorate`, {
      method: "POST",
    });
    renderStorefrontAiPanel(payload);
  } catch (error) {
    notifyError(error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function runStorefrontAiImage() {
  if (!state.currentStoreId) return;
  const button = qs("#aiStorefrontImageBtn");
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "AI 优化中…";
  }
  try {
    const payload = await fetchJson(`/stores/${state.currentStoreId}/agents/storefront/ai/optimize-image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    renderStorefrontAiPanel(payload);
  } catch (error) {
    notifyError(error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function createStorefrontAction(index, button) {
  if (!state.currentStoreId) return;
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "AI 生成中…";
  }
  try {
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/agents/storefront/actions/${index}/create`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ with_ai: true }),
      },
    );
    await loadDashboard(state.currentStoreId);
    const content = result.action?.generated_content || {};
    if (content.image_prompt_zh || content.execution_brief || content.ai_image_plan || content.ai_decorate_plan) {
      renderStorefrontAiPanel({
        assist_type: content.ai_image_plan ? "image_optimize" : "decorate",
        plan: content.ai_image_plan || {
          title: result.action?.title || "装修动作已生成",
          summary: content.execution_brief || result.message,
          sales_focus: content.verify_plan || "",
          steps: [
            {
              order: 1,
              title: result.action?.title,
              why: result.action?.detail,
              how: content.execution_brief || content.visual_brief || "",
              verify: content.verify_plan || "",
            },
          ],
          copy_pack: content.ai_decorate_plan?.copy_pack || {},
          do_not_do: ["一次只改一个变量，便于验证"],
          next_action: "去行动中心采纳并执行",
          mode: result.action?.generated_content ? "llm" : "heuristic",
        },
      });
    } else {
      notifySuccess(result.message || "装修动作已生成");
    }
  } catch (error) {
    notifyError(error.message);
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

function renderProductAgent() {
  const product = state.dashboard?.agents?.product || {};
  const itemId = product.focus_item_id;
  const current = product.current_action;
  const queueBrief = actionQueueBrief(product);
  qs("#productHealthTag").textContent = product.readiness
    ? `健康度 ${product.health_score ?? "--"} 分 · ${formatReadiness(product.readiness)}`
    : `健康度 ${product.health_score ?? "--"} 分`;
  qs("#productCandidateMeta").textContent = `已扫描 ${(product.item_candidates || []).length} 个候选商品`;
  qs("#productGuardrail").textContent = product.experiment_guardrail || "一次只执行一个商品动作。";
  qs("#productCurrentAction").innerHTML = current
    ? `<span class="inline-phase"><span class="phase-pill ${executionPhaseClass(current.execution_phase)}">${escapeHtml(formatExecutionPhase(current.execution_phase))}</span><span>${escapeHtml(current.title)}</span></span><span class="inline-note">${escapeHtml(current.phase_reason || current.next_decision || `窗口 ${current.window_hours || "--"}h`)}${product.blockers?.[0] ? ` · 阻塞：${escapeHtml(product.blockers[0])}` : ""}</span>`
    : escapeHtml(queueBrief || product.blockers?.[0] || "现在还没有商品动作，先看今天该盯哪一个商品。");

  qs("#productFocusCard").innerHTML = itemId
    ? `
      <img src="${imageForFood(product.focus_item_name)}" alt="${escapeHtml(product.focus_item_name)}" />
      <div class="product-focus-overlay">
        <div>
          <div class="section-kicker">当前优先商品</div>
          <h3>${escapeHtml(product.focus_item_name)}</h3>
          <p>${escapeHtml(product.why_now || product.issue || "正在建立商品证据")}</p>
        </div>
        <strong>${product.health_score ?? "--"}<small>分</small></strong>
      </div>
    `
    : `<div class="empty-state">当前没有可分析的商品，请先接入菜单和商品经营数据。</div>`;

  qs("#productDimensionList").innerHTML = (product.health_dimensions || [])
        .map(
          (row) => `
        <div class="product-dimension-row">
          <div class="product-dimension-meta">
            <span>${escapeHtml(row.label)}</span>
            <strong>${row.score} 分</strong>
              </div>
          <div class="product-dimension-track"><i class="${escapeHtml(row.status)}" style="width:${Math.max(
            4,
            Math.min(100, row.score),
          )}%"></i></div>
          <div class="product-dimension-foot">${row.delta_pct === null || row.delta_pct === undefined ? "等待对比数据" : `较基线 ${formatDelta(row.delta_pct)}`}</div>
            </div>
      `,
    )
    .join("");

  const rootCause = (product.root_causes || [])[0];
  qs("#productDiagnosisPanel").innerHTML = `
    <div class="product-panel-title">AI 根因诊断</div>
    <div class="product-stage">${escapeHtml(product.diagnosis_stage || "unknown")}</div>
    <h3>${escapeHtml(product.issue || "等待诊断")}</h3>
    <p>${escapeHtml(product.diagnosis || "接入更多商品漏斗数据后生成根因。")}</p>
    ${
      rootCause
        ? `<div class="product-root-cause"><strong>${escapeHtml(rootCause.title)}</strong><span>${escapeHtml(
            rootCause.explanation,
          )}</span><small>置信度 ${Math.round((rootCause.confidence || 0) * 100)}%</small></div>`
        : ""
    }
    <div class="product-decision-path">${(product.decision_path || [])
      .map((step, index) => `<span>${index + 1}. ${escapeHtml(step)}</span>`)
      .join("")}</div>
  `;

  qs("#productCandidateGrid").innerHTML = (product.item_candidates || []).length
    ? takeTop(product.item_candidates, 4)
        .map(
          (candidate) => `
            <article class="product-candidate-card ${candidate.item_id === itemId ? "selected" : ""}">
              <div class="product-candidate-top">
                <strong>${escapeHtml(candidate.name)}</strong>
                <span>${candidate.opportunity_score ?? candidate.health_score ?? "--"}</span>
              </div>
              <p>${escapeHtml(candidate.issue || "等待诊断")}</p>
              <small>${escapeHtml(menuRoleLabel(candidate.role))} · ${escapeHtml(candidate.diagnosis_stage || "--")}</small>
              <button data-product-suggestion-index="0" data-product-item-id="${escapeHtml(candidate.item_id)}">
                ${escapeHtml(candidate.recommended_action || "生成动作")}
              </button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无候选商品。</div>`;

  qs("#productRecommendationGrid").innerHTML = (product.recommendations || []).length
    ? product.recommendations
        .map(
          (suggestion, index) => `
            <article class="product-recommendation-card">
              <div class="product-recommendation-top">
                <span>优先级 ${suggestion.priority || index + 1}</span>
                <span>${escapeHtml(suggestion.risk_level || "low")} risk</span>
              </div>
              <h3>${escapeHtml(suggestion.title)}</h3>
              <p>${escapeHtml(suggestion.detail)}</p>
              ${productPreview(suggestion.generated_content)}
              <div class="product-recommendation-foot">
                <span>${escapeHtml(suggestion.expected_metric || "指标")} · ${
                  suggestion.expected_lift_pct_high
                    ? `预计 +${suggestion.expected_lift_pct_low || 0}~${suggestion.expected_lift_pct_high}%`
                    : `${suggestion.window_hours || 24}h`
                }</span>
                <button data-product-suggestion-index="${index}" data-product-item-id="${escapeHtml(itemId || "")}">生成动作</button>
                <button class="ghost" data-product-apply-index="${index}" data-product-item-id="${escapeHtml(itemId || "")}">直接执行</button>
            </div>
              ${suggestion.rollback_rule ? `<small class="product-rollback">回滚：${escapeHtml(suggestion.rollback_rule)}</small>` : ""}
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前证据不足，暂不生成商品动作。</div>`;
}

function diagnosisMetricValue(metric, value) {
  if (value === null || value === undefined) return "--";
  if (["ctr", "cvr", "repurchase_rate", "refund_rate"].includes(metric)) return `${(Number(value) * 100).toFixed(1)}%`;
  if (["gmv", "aov"].includes(metric)) return `¥${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
  if (metric === "rating") return Number(value).toFixed(1);
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function renderDiagnosisAgent() {
  const diagnosis = state.dashboard?.agents?.diagnosis || {};
  qs("#diagnosisScore").textContent = diagnosis.diagnosis_score ?? "--";
  qs("#diagnosisSummary").textContent =
    diagnosis.executive_summary || diagnosis.root_cause || diagnosis.primary_problem || "当前没有明确诊断结论";
  qs("#diagnosisDailySummary").textContent = [
    diagnosis.daily_summary ||
      (diagnosis.primary_problem ? `主问题：${diagnosis.primary_problem}` : "等待多周期指标对比。"),
    diagnosis.readiness ? `准备度 ${formatReadiness(diagnosis.readiness)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  qs("#diagnosisComparisonGrid").innerHTML = (diagnosis.comparisons || []).length
    ? diagnosis.comparisons
        .map(
          (row) => `
        <article class="diagnosis-comparison-card ${escapeHtml(row.status)}">
          <div class="diagnosis-comparison-top">
            <strong>${escapeHtml(row.label)}</strong>
            <span>${escapeHtml(row.status)}</span>
              </div>
          <div class="diagnosis-comparison-values">
            <div><span>订单</span><strong>${row.orders_delta_pct === null ? "--" : formatDelta(row.orders_delta_pct)}</strong></div>
            <div><span>营业额</span><strong>${row.gmv_delta_pct === null ? "--" : formatDelta(row.gmv_delta_pct)}</strong></div>
            </div>
          <p>${escapeHtml(row.note)}</p>
        </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无周期对比结果，完成诊断后会显示同星期 / 7 日 / 30 日对比。</div>`;

  qs("#diagnosisSignalList").innerHTML = (diagnosis.metric_signals || []).length
    ? diagnosis.metric_signals
        .map(
          (signal) => `
        <div class="diagnosis-signal-row">
          <div>
            <strong>${escapeHtml(signal.label)}</strong>
            <span>${diagnosisMetricValue(signal.metric, signal.observed_value)}</span>
                </div>
          <span class="diagnosis-severity ${escapeHtml(signal.severity)}">${escapeHtml(signal.severity)}</span>
          <strong class="diagnosis-signal-delta">${
            signal.delta_pct === null || signal.delta_pct === undefined ? "--" : formatDelta(signal.delta_pct)
          }</strong>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无指标信号，等待经营数据进入诊断窗口。</div>`;

  qs("#diagnosisRootList").innerHTML = (diagnosis.root_causes || []).length
    ? diagnosis.root_causes
        .map(
          (cause) => `
        <article class="diagnosis-root-card">
          <div class="diagnosis-root-rank">${cause.rank}</div>
          <div>
            <div class="diagnosis-root-head">
              <strong>${escapeHtml(cause.title)}</strong>
              <span>${Math.round((cause.confidence || 0) * 100)}%</span>
              </div>
            <p>${escapeHtml(cause.explanation)}</p>
            <small>${escapeHtml((cause.evidence || []).join(" · "))}</small>
            </div>
        </article>
      `,
        )
        .join("")
    : `<div class="empty-state">暂无根因结论，先补齐诊断证据再复盘。</div>`;

  const market = diagnosis.market_comparison || {};
  qs("#diagnosisMarketCard").innerHTML = `
    <div class="diagnosis-market-head">
      <div class="product-panel-title">本店 vs 商圈</div>
      <span>${escapeHtml(market.relative_status || market.data_type || "unavailable")}</span>
    </div>
    <div class="diagnosis-market-value">
      <span>本店订单变化</span>
      <strong>${market.own_orders_delta_pct === null || market.own_orders_delta_pct === undefined ? "--" : formatDelta(market.own_orders_delta_pct)}</strong>
    </div>
    <div class="diagnosis-market-value">
      <span>商圈订单变化</span>
      <strong>${market.market_orders_delta_pct === null || market.market_orders_delta_pct === undefined ? "--" : formatDelta(market.market_orders_delta_pct)}</strong>
    </div>
    <p>${escapeHtml(market.note || "尚未接入商圈趋势。")}</p>
  `;
  qs("#diagnosisGapList").innerHTML = (diagnosis.data_gaps || []).length
    ? diagnosis.data_gaps.map((gap) => `<div><i></i><span>${escapeHtml(gap)}</span></div>`).join("")
    : `<div><i></i><span>当前核心诊断数据已满足要求。</span></div>`;

  const observationList = qs("#diagnosisObservationList");
  if (observationList) {
    observationList.innerHTML = (diagnosis.observations || []).length
      ? diagnosis.observations
          .map(
            (obs) => `
          <article class="diagnosis-observation-row">
            <strong>${escapeHtml(obs.metric || "指标")}</strong>
            <p>${escapeHtml(obs.what_happened || "")}</p>
            <span>${
              obs.delta_pct === null || obs.delta_pct === undefined ? "--" : formatDelta(obs.delta_pct)
            } · 置信 ${
              obs.confidence == null ? "--" : `${Math.round(Number(obs.confidence) * 100)}%`
            }</span>
          </article>
        `,
          )
          .join("")
      : `<div class="empty-state soft">暂无 Observation，先跑一次诊断。</div>`;
  }

  const hypothesisCard = qs("#diagnosisHypothesisCard");
  if (hypothesisCard) {
    const reasons = diagnosis.reasons || [];
    hypothesisCard.innerHTML = `
      <div class="diagnosis-hypothesis-kicker">主假设</div>
      <h3>${escapeHtml(diagnosis.root_cause || diagnosis.primary_problem || "等待形成假设")}</h3>
      <p>${escapeHtml(diagnosis.executive_summary || diagnosis.daily_summary || "先看 Observation，再收敛 Hypothesis。")}</p>
      ${
        reasons.length
          ? `<ul class="diagnosis-hypothesis-reasons">${reasons
              .slice(0, 3)
              .map((row) => `<li>${escapeHtml(row)}</li>`)
              .join("")}</ul>`
          : ""
      }
      <button class="link-button" type="button" data-scroll-target="section-growth">用这个假设去排今日动作</button>
    `;
  }

  const nextActions = [
    ...(diagnosis.action_priorities || []),
    ...(diagnosis.next_actions || []),
    ...(diagnosis.blockers || []).map((row) => `先处理：${row}`),
  ];
  qs("#diagnosisNextActions").innerHTML = nextActions.length
    ? takeTop(nextActions, 5)
        .map((row) => {
          const text = String(row || "");
          let scroll = "section-growth";
          let label = "交给增长策略";
          if (/评价|差评|评分/.test(text)) {
            scroll = "section-review";
            label = "去评分评价";
          } else if (/客服|回复|IM/.test(text)) {
            scroll = "section-service";
            label = "去AI客服";
          } else if (/装修|主图|店页/.test(text)) {
            scroll = "section-storefront";
            label = "去线上装修";
          } else if (/商品|CTR|CVR/.test(text)) {
            scroll = "section-product";
            label = "去商品优化";
          } else if (/菜单|套餐/.test(text)) {
            scroll = "section-menu";
            label = "去菜单分析";
          } else if (/竞争|竞品/.test(text)) {
            scroll = "section-competition-agent";
            label = "去商圈竞争";
          } else if (/采集|连接|数据/.test(text)) {
            scroll = "section-collection";
            label = "去数据采集";
          }
          return `
            <div class="agent-action-row">
              <strong>→</strong>
              <span>${escapeHtml(text)}</span>
              <button class="link-button" type="button" data-scroll-target="${scroll}">${label}</button>
            </div>
          `;
        })
        .join("")
    : `<div class="agent-action-row"><strong>→</strong><span>先完成诊断复盘，再进入增长策略排序。</span><button class="link-button" type="button" data-scroll-target="section-growth">去增长策略</button></div>`;
}

function renderGrowthAgent() {
  const growth = state.dashboard?.agents?.growth || {};
  const selectedKey = growth.selected_opportunity?.key;
  const sourceLabels = Object.fromEntries(AGENT_TEAM.map((agent) => [agent.key, agent.label]));
  qs("#growthStrategyScore").textContent = growth.strategy_score ?? "--";
  qs("#growthTodayPriority").textContent = growth.today_priority || "当前没有可执行动作";
  qs("#growthReason").textContent = [
    growth.reason || "等待核心 Agent 与运营矩阵汇总。",
    growth.readiness ? `准备度 ${formatReadiness(growth.readiness)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  qs("#growthWeeklyGoal").textContent = `本周目标 · ${growth.weekly_goal || "--"}`;
  qs("#growthExecutionMode").textContent =
    growth.execution_mode === "alignment_first" ? "先对齐资料" : "单变量实验";
  qs("#growthPoolMeta").textContent = `${(growth.opportunity_pool || []).length} 个候选 · 只选 1 个执行`;
  qs("#growthProgressTag").textContent = `已复盘 ${growth.plan_progress_pct || 0}%`;
  const learningNote = qs("#growthLearningNote");
  if (learningNote) {
    learningNote.textContent =
      growth.learning_summary || "OHRE 的 Result 会沉淀成下次决策经验，避免重复买流水。";
  }

  const current = growth.current_action;
  const summary = growth.experiments_summary || {};
  const queueBrief = actionQueueBrief(growth);
  qs("#growthCurrentActionCard").innerHTML = current
    ? `
      <div class="product-panel-title">当前执行中</div>
      <div class="inline-phase" style="margin-top:8px;">
        <span class="phase-pill ${executionPhaseClass(current.execution_phase)}">${escapeHtml(formatExecutionPhase(current.execution_phase))}</span>
        <span>${escapeHtml(current.expected_metric)} · ${current.window_hours || "--"}h</span>
      </div>
      <h3>${escapeHtml(current.title)}</h3>
      <p>${escapeHtml(current.phase_reason || current.next_decision || "保持单变量观察。")}</p>
      <small>${escapeHtml(
        [current.next_decision || "等待下一步判断。", growth.blockers?.[0] ? `阻塞：${growth.blockers[0]}` : ""]
          .filter(Boolean)
          .join(" · "),
      )}</small>
    `
    : `
      <div class="product-panel-title">当前执行中</div>
      <h3>${escapeHtml(growth.today_priority || "等待主动作")}</h3>
      <p>${escapeHtml(queueBrief || growth.blockers?.[0] || "还没进入执行阶段，先把今天唯一主动作定下来。")}</p>
    `;
  qs("#growthExperimentSummary").innerHTML = `
    <div class="product-panel-title">实验反馈</div>
    <div class="growth-experiment-pills">
      <span>待验证 ${summary.pending || 0}</span>
      <span>有效 ${summary.positive || 0}</span>
      <span>中性 ${summary.neutral || 0}</span>
      <span>无效 ${summary.negative || 0}</span>
    </div>
    <p>${escapeHtml(growth.learning_summary || "做完的结果会回写，下次排序会更准。")}</p>
  `;

  const sourceScroll = { ...AGENT_SECTION_MAP };

  qs("#growthOpportunityGrid").innerHTML = (growth.opportunity_pool || []).length
    ? takeTop(growth.opportunity_pool, 6)
        .map((opportunity, index) => {
          const factors = opportunity.factors || {};
          const isSelected = opportunity.key === selectedKey;
          const nextAction =
            opportunity.status === "proposed"
              ? "adopt"
              : opportunity.status === "adopted"
                ? "execute"
                : null;
          return `
            <article class="growth-opportunity-card ${isSelected ? "selected" : ""}">
              <div class="growth-opportunity-top">
                <span>${escapeHtml(sourceLabels[opportunity.source_agent] || opportunity.source_agent)}</span>
                <strong>${Number(opportunity.score || 0).toFixed(1)}</strong>
              </div>
              <div class="growth-opportunity-rank">${isSelected ? "今日主动作" : `机会 ${index + 1}`}</div>
              <h3>${escapeHtml(opportunity.title)}</h3>
              <p>${escapeHtml(opportunity.problem)}</p>
              <div class="growth-factor-row">
                <span>影响 ${factors.expected_impact ?? "--"}</span>
                <span>置信 ${factors.confidence ?? "--"}</span>
                <span>易执行 ${factors.ease_of_execution ?? "--"}</span>
                <span>契合 ${factors.strategic_fit ?? "--"}</span>
                <span>风险 ${factors.risk ?? "--"}</span>
              </div>
              <div class="growth-opportunity-foot">
                <span>${escapeHtml(opportunity.expected_metric)} · ${
                  opportunity.expected_lift_pct_high
                    ? `预计 +${opportunity.expected_lift_pct_low || 0}~${opportunity.expected_lift_pct_high}%`
                    : "待验证"
                }</span>
                ${
                  nextAction && opportunity.recommendation_id
                    ? `<button data-recommendation-id="${opportunity.recommendation_id}" data-recommendation-action="${nextAction}">${
                        nextAction === "adopt" ? "采纳主动作" : "标记执行"
                      }</button>`
                    : sourceScroll[opportunity.source_agent]
                      ? `<button data-scroll-target="${sourceScroll[opportunity.source_agent]}">去对应 Agent</button>`
                      : `<em>${opportunity.executable ? escapeHtml(formatStatus(opportunity.status)) : "待生成动作"}</em>`
                }
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="empty-state">当前没有足够证据建立增长机会池。</div>`;

  qs("#growthPlanGrid").innerHTML = (growth.weekly_plan || []).length
    ? growth.weekly_plan
        .map(
          (step) => `
        <article class="growth-plan-step ${escapeHtml(step.status || "planned")}">
          <div class="growth-plan-day">D${step.day}</div>
          <div>
            <span>${escapeHtml(step.goal)}</span>
            <h3>${escapeHtml(step.title)}</h3>
            <p>${escapeHtml(step.instruction)}</p>
            <small>${escapeHtml(step.verify)}</small>
            ${step.stop_condition ? `<em>停止：${escapeHtml(step.stop_condition)}</em>` : ""}
              </div>
        </article>
          `,
        )
        .join("")
    : `<div class="empty-state">本周增长计划尚未生成，确认主动作后会排出 7 日节奏。</div>`;
  qs("#growthEvidenceList").innerHTML = (growth.evidence || []).length
    ? growth.evidence.map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>等待可展开的经营依据。</span></div>`;
  qs("#growthStopList").innerHTML = (growth.do_not_do || []).length
    ? growth.do_not_do.map((row) => `<div><strong>×</strong><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><strong>×</strong><span>不要同时改动多个经营变量。</span></div>`;
}

function renderInsightTiles() {
  const dashboard = state.dashboard;
  const alignment = dashboard.document_alignment || {};
  const growth = dashboard.agents?.growth || {};
  const diagnosis = dashboard.agents?.diagnosis || {};
  const examples = takeTop(dashboard.question_examples || [], 3);
  const tiles = [
    {
      tone: "green",
      icon: "T",
      title: "资料对齐优先",
      copy: alignment.recommendations?.[0] || alignment.summary || "把资料补齐后，5 个 Agent 才能共享同一事实源。",
      button: { label: alignment.status === "aligned" ? "查看资料状态" : "先修资料", question: "现在最需要补什么资料？" },
      metric: alignment.alignment_score ? `对齐分 ${alignment.alignment_score}` : "等待资料",
    },
    {
      tone: "orange",
      icon: "✦",
      title: "诊断结论",
      copy: diagnosis.workflow_summary || dashboard.daily_brief?.reason || "优先看昨日主问题，再决定动作。",
      button: { label: "问 AI 店长", question: examples[0] || "为什么最近订单下降？" },
      metric: dashboard.daily_brief?.yesterday_change || "诊断中",
    },
    {
      tone: "violet",
      icon: "◍",
      title: "增长节奏",
      copy: growth.reason || "先锁定主动作，再推进备选动作。",
      button: { label: "打开增长策略", scroll: "section-growth" },
      metric: growth.today_priority || `实验 ${(dashboard.experiments || []).length} 条`,
    },
  ];

  qs("#insightTiles").innerHTML = tiles
    .map(
      (tile) => `
        <article class="insight-tile ${tile.tone}">
          <div class="insight-icon">${escapeHtml(tile.icon)}</div>
          <div class="insight-metric">${escapeHtml(tile.metric)}</div>
          <div class="insight-title">${escapeHtml(tile.title)}</div>
          <div class="insight-copy">${escapeHtml(tile.copy)}</div>
          <button class="insight-button" ${
            tile.button.question ? `data-ask-question="${escapeHtml(tile.button.question)}"` : ""
          } ${tile.button.scroll ? `data-scroll-target="${tile.button.scroll}"` : ""}>${escapeHtml(tile.button.label)}</button>
        </article>
      `,
    )
    .join("");
}

function renderCompetition() {
  const dashboard = state.dashboard;
  const competition = dashboard.agents?.competition || dashboard.competition || {};
  const competitorPool = [...(competition.top_competitors || [])];
  if (state.competitionFilter === "change") {
    competitorPool.sort(
      (left, right) =>
        Number(Boolean(right.recent_move)) - Number(Boolean(left.recent_move)) ||
        (right.score || 0) - (left.score || 0),
    );
  } else {
    competitorPool.sort((left, right) => (right.score || 0) - (left.score || 0));
  }
  const competitors = takeTop(competitorPool, 3);
  renderCompetitionMap();
  qs("#competitionSummary").textContent =
    competition.conclusion || competition.strategy || "周边证据还不够，先按商圈和价格带做稳妥判断。";
  const nearbyTotal = competition.nearby_total ?? (competition.top_competitors || []).length;
  qs("#competitionFootnote").textContent = nearbyTotal
    ? `这会儿重点盯着周边 ${nearbyTotal} 家同类商家`
    : "周边竞品数据还在慢慢补齐";

  if (!competitors.length) {
    const evidence = takeTop([...(competition.evidence || []), ...(competition.reasons || [])], 3);
    qs("#competitorList").innerHTML = `
      <div class="competition-evidence-card">
        <div class="competition-evidence-head">
          <strong>竞品快照待补齐</strong>
          <span>${evidence.length || 0} 条基础依据</span>
      </div>
        <div class="competition-evidence-list">
          ${
            evidence.length
              ? evidence.map((item) => `<div><i></i><span>${escapeHtml(item)}</span></div>`).join("")
              : `<div><i></i><span>连接采集平台后，将自动建立竞品商品与价格变化快照。</span></div>`
          }
      </div>
    </div>
  `;
    return;
  }

  qs("#competitorList").innerHTML = competitors
    .map(
      (competitor, index) => `
        <div class="competitor-row">
          <div class="competitor-media">
            <img class="thumb small" src="${imageForFood((competitor.featured_products || [competitor.name])[0])}" alt="${escapeHtml(competitor.name)}" />
            <div class="competitor-rank">${index + 1}</div>
          </div>
          <div>
            <div class="competitor-title">${escapeHtml(competitor.name)}｜${escapeHtml(competitor.positioning || "同商圈竞品")}</div>
            <div class="competitor-meta">${
              competitor.price_band ? `¥${escapeHtml(competitor.price_band)}｜` : ""
            }${competitor.rating ? `评分 ${competitor.rating}｜` : ""}菜单 ${competitor.menu_item_count || 0} 个 / 套餐 ${competitor.set_meal_count || 0} 个</div>
            <div class="competitor-meta">优势：${escapeHtml((competitor.strengths || [competitor.advantage]).filter(Boolean).join("；") || "证据不足")}</div>
          </div>
          <div>
            <div class="competitor-distance">${competitor.distance_m ? `${Math.round(competitor.distance_m)}m` : "同商圈"}</div>
            <div class="competitor-score">${competitor.score || "--"} 分</div>
        </div>
      </div>
    `,
    )
    .join("");
}

function collectionTime(value) {
  if (!value) return "尚未运行";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function collectionChangeLabel(type) {
  const labels = {
    product_added: "竞品上新",
    product_removed: "竞品下架",
    product_price_changed: "菜品调价",
    image_changed: "更换主图",
    price_down: "价格带下探",
    price_up: "价格带上探",
    rating_up: "评分上升",
    rating_down: "评分下降",
  };
  return labels[type] || "公开页面变化";
}

function renderCollectionCenter() {
  const runs = state.collectionRuns || [];
  const latestRun = runs[0];
  const competition = state.dashboard?.agents?.competition || state.dashboard?.competition || {};
  const changes = competition.changes || [];
  const monitoredCount = state.competitionMap?.competitors?.length || 0;
  const configuredProviders = state.publicConfig?.competition_collection?.providers || [];
  const schedule = state.publicConfig?.competition_collection?.schedule || "07:30";
  const teamStatus = agentCapabilityStatus("collection");

  qs("#collectionLiveStatus").textContent = latestRun
    ? `${latestRun.status === "completed" ? "采集正常" : "需要处理"} · ${collectionTime(latestRun.completed_at || latestRun.started_at)}`
    : "等待首次手机授权";

  const connectedLinks = (state.platformLinks || []).filter(
    (link) => link.status === "connected" || link.connected_at,
  );
  const connectedCount = Math.min(4, connectedLinks.length);

  const collectionHero = qs("#collectionAgentHero");
  if (collectionHero) {
    collectionHero.innerHTML = `
      <div class="matrix-hero-score">
        <span>连接度</span>
        <strong>${connectedCount}/4</strong>
      </div>
      <div class="matrix-hero-copy">
        <div class="product-panel-title">数据采集 Agent · L1 感知</div>
        <h3>${
          connectedCount
            ? "公开页证据正在流入经营大脑"
            : "先连接手机端，店长才能看见市场变化"
        }</h3>
        <p>输入：外卖后台可见页、菜单、评价与竞品公开信息。输出：统一快照，供诊断 / 竞争 / 增长调度。</p>
        <small>${escapeHtml(teamStatus.meta)} · 每日 ${schedule} 补采</small>
      </div>
      <div class="matrix-hero-side">
        <div class="product-panel-title">下一步</div>
        <strong>${connectedCount ? "保持更新" : "连接平台"}</strong>
        <p>${
          connectedCount
            ? "有变化时会进入商圈竞争与今日异常。"
            : "密码留在手机本地；云端只收公开页证据。"
        }</p>
        <button class="topbar-button primary" type="button" id="collectionHeroConnectBtn">${
          connectedCount ? "连接更多平台" : "开始连接"
        }</button>
      </div>
    `;
    qs("#collectionHeroConnectBtn")?.addEventListener("click", () => openCollectionModal());
  }
  const summary = [
    {
      label: "手机平台连接",
      value: `${connectedCount} / 4`,
      meta: connectedCount ? "已有平台完成手机端连接" : "等待移动端 Connector 回传",
    },
    { label: "重点竞品", value: monitoredCount, meta: "已进入门店竞争观察集合" },
    { label: "最近写入快照", value: latestRun?.snapshot_count || 0, meta: `每日 ${schedule} 更新` },
    { label: "公开页面变化", value: changes.length, meta: "Observed / Derived 证据" },
  ];
  qs("#collectionSummaryGrid").innerHTML = summary
    .map(
      (item) => `
        <article class="collection-summary-card">
          <div class="collection-summary-label">${escapeHtml(item.label)}</div>
          <div class="collection-summary-value">${escapeHtml(item.value)}</div>
          <div class="collection-summary-meta">${escapeHtml(item.meta)}</div>
        </article>
      `,
    )
    .join("");

  const platforms = [
    { key: "meituan", mark: "美", name: "美团外卖", scope: "菜品 · 价格 · 月售", copy: "采集公开菜单、价格、页面月售、套餐和配送信息。" },
    { key: "dianping", mark: "点", name: "大众点评", scope: "评分 · 评价 · 榜单", copy: "采集推荐菜、评分、公开评价和榜单位置变化。" },
    { key: "eleme", mark: "饿", name: "饿了么", scope: "菜品 · 价格 · 销量", copy: "采集公开菜单、价格、销量、活动和配送信息。" },
    { key: "douyin", mark: "抖", name: "抖音生活服务", scope: "团购 · 价格 · 已售", copy: "采集团购套餐、价格、公开已售和评价内容。" },
  ];
  qs("#platformConnectionGrid").innerHTML = platforms
    .map((platform) => {
      const linked = (state.platformLinks || []).some((link) => {
        if (!(link.status === "connected" || link.connected_at)) return false;
        const value = String(link.platform || "").toLowerCase();
        return value === platform.key || value.includes(platform.key) || String(link.platform || "") === platform.name;
      });
      return `
        <article class="platform-card">
          <div class="platform-card-head">
            <div class="platform-mark ${platform.key}">${platform.mark}</div>
            <div>
              <div class="platform-title">${platform.name}</div>
              <div class="platform-status">${linked ? "已连接" : "待商家手机授权"}</div>
        </div>
      </div>
          <div class="platform-card-copy">${platform.copy}</div>
          <div class="platform-card-foot">
            <span class="platform-scope">${platform.scope}</span>
            <button class="platform-connect-button" data-platform-connect="${platform.key}" data-platform-label="${platform.name}">${linked ? "重新连接" : "连接"}</button>
          </div>
        </article>
      `;
    })
    .join("");

  qs("#collectionRunList").innerHTML = runs.length
    ? takeTop(runs, 4)
        .map(
          (run) => `
            <div class="collection-run-row">
              <span class="run-dot ${run.status === "failed" ? "failed" : ""}"></span>
              <div>
                <div class="collection-row-title">${escapeHtml(run.provider === "amap" ? "高德周边发现" : run.provider === "licensed_partner" ? "授权数据供应商" : run.provider)}</div>
                <div class="collection-row-meta">${run.status === "completed" ? `发现 ${run.discovered_count} 家，写入 ${run.snapshot_count} 份快照` : escapeHtml(run.error || "采集失败")}</div>
              </div>
              <div class="collection-row-time">${collectionTime(run.completed_at || run.started_at)}</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">尚无采集记录。配置高德或在手机端连接平台后开始更新。</div>`;

  qs("#collectionChangeCount").textContent = `${changes.length} 条`;
  qs("#collectionChangeList").innerHTML = changes.length
    ? takeTop(changes, 4)
        .map(
          (change) => `
            <div class="collection-change-row">
              <span class="change-dot"></span>
              <div>
                <div class="collection-row-title">${escapeHtml(collectionChangeLabel(change.type))}</div>
                <div class="collection-row-meta">${escapeHtml(change.summary)}</div>
              </div>
              <div class="collection-row-time">有证据</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">至少完成两次快照后，系统会在这里展示菜品变化。</div>`;

  const providerText = configuredProviders.length
    ? `服务端已配置：${configuredProviders.join(" / ")}`
    : "服务端尚未配置自动采集源";
  qs("#collectionLiveStatus").title = providerText;
}

function renderDailyBoard() {
  const dashboard = state.dashboard;
  const metrics = dashboard.metrics || [];
  const gmv = metrics.find((item) => item.key === "gmv");
  const orders = metrics.find((item) => item.key === "orders");
  const ctr = metrics.find((item) => item.key === "ctr");
  const cvr = metrics.find((item) => item.key === "cvr");
  const aov = gmv?.value && orders?.value ? gmv.value / orders.value : null;
  const aovBaseline = gmv?.baseline_value && orders?.baseline_value ? gmv.baseline_value / orders.baseline_value : null;
  const aovDelta = aov !== null && aovBaseline ? ((aov - aovBaseline) / aovBaseline) * 100 : null;
  const trend = dashboard.trend || [];
  const lastDay = trend[trend.length - 1];
  const prevDay = trend[trend.length - 2];
  qs("#yesterdayDate").textContent = lastDay && prevDay ? `${formatShortDate(lastDay.day)} vs ${formatShortDate(prevDay.day)}` : "昨日";

  const dailyCards = [
    { label: "订单量", key: "orders", value: orders?.value, delta: orders?.delta_pct },
    { label: "营业额", key: "gmv", value: gmv?.value, delta: gmv?.delta_pct },
    { label: "客单价", key: "gmv", value: aov, delta: aovDelta, formatter: (value) => (value === null ? "--" : `¥${value.toFixed(1)}`) },
    { label: "点击率", key: "ctr", value: ctr?.value, delta: ctr?.delta_pct },
    { label: "转化率", key: "cvr", value: cvr?.value, delta: cvr?.delta_pct },
    { label: "资料对齐", key: "score", value: dashboard.document_alignment?.alignment_score, delta: null, formatter: (value) => (value === null || value === undefined ? "--" : `${value} 分`) },
  ];

  qs("#yesterdayMetrics").innerHTML = dailyCards
        .map(
          (item) => `
        <div class="mini-metric">
          <div class="mini-metric-label">${escapeHtml(item.label)}</div>
          <div class="mini-metric-value">${escapeHtml(item.formatter ? item.formatter(item.value) : formatMetricValue(item.key, item.value))}</div>
          <div class="mini-metric-delta ${item.delta !== null && item.delta !== undefined && item.delta < 0 ? "delta-negative" : "delta-positive"}">${escapeHtml(item.delta === null || item.delta === undefined ? "观察中" : formatDelta(item.delta))}</div>
            </div>
          `,
        )
    .join("");

  const reasons = takeTop(dashboard.agents?.diagnosis?.reasons || dashboard.observations?.map((item) => item.what_happened) || [], 3);
  qs("#yesterdayReasons").innerHTML = reasons.length
    ? reasons
        .map(
          (reason, index) => `
            <div class="reason-item">
              <div class="reason-item-title"><span class="reason-rank">${index + 1}</span><span>原因 ${index + 1}</span></div>
              <div class="reason-item-copy">${escapeHtml(reason)}</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">还没有昨日归因结果。</div>`;
}

function experimentWindowBounds(experiment) {
  const window = experiment?.window || {};
  const from = experiment?.observe_from || window.from || window.observe_from || window.from_day;
  const to = experiment?.observe_to || window.to || window.observe_to || window.to_day;
  return { from, to };
}

function experimentProgress(experiment) {
  const { from, to } = experimentWindowBounds(experiment);
  if (from && to) {
    const start = new Date(from).getTime();
    const end = new Date(to).getTime();
    if (!Number.isNaN(start) && !Number.isNaN(end) && end > start) {
      const now = Date.now();
      const pct = Math.round(((Math.min(Math.max(now, start), end) - start) / (end - start)) * 100);
      return Math.max(0, Math.min(100, pct));
    }
  }
  if (experiment?.result && experiment.result !== "pending") return 100;
  return 0;
}

function parseParallelNote(note) {
  const text = String(note || "");
  const match = text.match(/^\[([a-z_]+)\]\s*(.+)$/i);
  if (!match) return { agent: null, title: text };
  return { agent: match[1], title: match[2] };
}

function parallelScrollTarget(notes) {
  const first = (notes || []).map(parseParallelNote).find((item) => item.agent && agentSectionId(item.agent));
  return first ? agentSectionId(first.agent) : "section-matrix";
}

function renderStrategyMemory() {
  const memory = state.strategyMemory;
  const grid = qs("#strategyMemoryGrid");
  const meta = qs("#strategyMemoryMeta");
  const side = qs("#strategyMemorySide");
  const items = memory?.items || [];
  if (meta) meta.textContent = `${items.length} 条经验`;

  if (grid) {
    if (!items.length) {
      grid.innerHTML = `<div class="empty-state">还没有沉淀经验。评估实验 Result 后，会自动写入 Strategy Memory。</div>`;
    } else {
      grid.innerHTML = takeTop(items, 4)
        .map(
          (item) => `
          <article class="strategy-memory-card ${escapeHtml(item.result || "unknown")}">
            <div class="strategy-memory-top">
              <span>${escapeHtml(item.action_type || "动作")}</span>
              <strong>${escapeHtml(formatStatus(item.result || "unknown"))}${
                item.lift_pct == null ? "" : ` · ${formatDelta(item.lift_pct)}`
              }</strong>
            </div>
            <h3>${escapeHtml(item.lesson || "暂无 lesson")}</h3>
            <p><strong>复用：</strong>${escapeHtml(item.reuse_when || "--")}</p>
            <p><strong>避免：</strong>${escapeHtml(item.avoid_when || "无")}</p>
          </article>
        `,
        )
        .join("");
    }
  }

  if (side) {
    const positives = memory?.positive_patterns || [];
    const negatives = memory?.negative_patterns || [];
    if (!positives.length && !negatives.length && !items.length) {
      side.innerHTML = `<div class="empty-state soft">评估实验后会出现可复用经验。</div>`;
    } else {
      side.innerHTML = `
        ${positives.slice(0, 2).map((row) => `<div class="memory-pattern positive">✓ ${escapeHtml(row)}</div>`).join("")}
        ${negatives.slice(0, 2).map((row) => `<div class="memory-pattern negative">× ${escapeHtml(row)}</div>`).join("")}
        ${
          !positives.length && !negatives.length
            ? takeTop(items, 2)
                .map((item) => `<div class="memory-pattern">${escapeHtml(item.lesson)}</div>`)
                .join("")
            : ""
        }
      `;
    }
  }
}

function renderExperiments() {
  const dashboard = state.dashboard;
  const summary = dashboard.execution_summary || {};
  const experiments = takeTop(dashboard.experiments || [], 3);
  const pills = [
    { label: `待执行 ${summary.proposed || 0}`, className: "proposed" },
    { label: `已执行 ${summary.executed || 0}`, className: "executed" },
    { label: `待验证 ${summary.pending_verification || 0}`, className: "pending" },
    { label: `总实验 ${(dashboard.experiments || []).length}`, className: "total" },
  ];

  qs("#executionSummary").innerHTML = pills
    .map((pill) => `<div class="summary-pill ${pill.className}">${escapeHtml(pill.label)}</div>`)
    .join("");
  qs("#experimentTag").textContent = (dashboard.experiments || []).length ? "还在观察" : "还没开始";

  qs("#experimentTracker").innerHTML = experiments.length
    ? experiments
        .map((experiment) => {
          const { from, to } = experimentWindowBounds(experiment);
          const isPending = !experiment.result || experiment.result === "pending";
          const canEvaluate = isPending && experiment.can_evaluate !== false;
          const liftText =
            experiment.lift_pct === null || experiment.lift_pct === undefined
              ? ""
              : `｜提升 ${formatDelta(experiment.lift_pct)}`;
          return `
            <div class="experiment-row">
              <div class="experiment-headline">
                <div class="experiment-title">${escapeHtml(experiment.action_title || "动作实验")}</div>
                <div class="row-status ${statusClass(experiment.result || "pending")}">${escapeHtml(formatStatus(experiment.result || "pending"))}</div>
              </div>
              <div class="experiment-copy">${escapeHtml(experiment.notes || experiment.result_summary || "等待观察窗完成。")}</div>
              <div class="experiment-copy">指标 ${escapeHtml(experiment.metric_name || "--")}｜基线 ${experiment.baseline_value ?? "--"}${experiment.observed_value !== null && experiment.observed_value !== undefined ? `｜当前 ${experiment.observed_value}` : ""}${liftText}${from && to ? `｜窗口 ${escapeHtml(formatShortDate(from))}-${escapeHtml(formatShortDate(to))}` : ""}</div>
              <div class="experiment-copy">归因质量 ${escapeHtml(experiment.attribution_quality || "medium")}${
                experiment.ads_budget != null ? `｜预算 ¥${Number(experiment.ads_budget).toFixed(0)}` : ""
              }${
                experiment.ads_roi != null ? `｜预估 ROI ${Number(experiment.ads_roi).toFixed(2)}` : ""
              }</div>
              <div class="progress-track"><div class="progress-bar" style="width:${experimentProgress(experiment)}%"></div></div>
              ${
                canEvaluate
                  ? `<button class="action-button" data-experiment-evaluate="${escapeHtml(experiment.id)}">评估结果</button>`
                  : isPending
                    ? `<div class="experiment-copy">观察窗未到，先不要评估。</div>`
                    : `<button class="link-button" type="button" data-scroll-target="section-growth">查看经验沉淀</button>`
              }
            </div>
          `;
        })
        .join("")
    : `<div class="empty-state">当前还没有实验记录，动作执行后会自动进入追踪。</div>`;
}

function buildMatrixWorkspaceHtml() {
  const hubCards = MATRIX_AGENT_DEFS.map(
    (item) => `
      <article class="matrix-hub-card" data-matrix-hub-key="${item.key}">
        <div class="matrix-hub-top">
          <span>${escapeHtml(item.kicker)}</span>
          <strong id="matrix-hub-score-${item.key}">--</strong>
        </div>
        <h3>${escapeHtml(item.label)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="matrix-hub-meta" id="matrix-hub-meta-${item.key}">等待读取</div>
        <button class="action-button" type="button" data-scroll-target="section-${item.key}">进入工作台</button>
      </article>
    `,
  ).join("");

  const panels = MATRIX_AGENT_DEFS.map(
    (item) => `
      <section class="dashboard-section matrix-agent-section workspace-panel" id="section-${item.key}" data-workspace-panel="section-${item.key}" data-matrix-key="${item.key}">
        <div class="section-head">
          <div>
            <div class="section-kicker">${escapeHtml(item.kicker)}</div>
            <h2>${escapeHtml(item.label)}工作台</h2>
            <p>${escapeHtml(item.copy)}</p>
          </div>
          <div class="matrix-head-actions">
            <button class="link-button" type="button" data-scroll-target="section-matrix">返回矩阵</button>
            <div class="product-health-tag" id="matrix-tag-${item.key}">健康度 --</div>
          </div>
        </div>
        <div class="matrix-hero" id="matrix-hero-${item.key}"></div>
        <div class="matrix-grid">
          <div class="matrix-panel">
            <div class="product-panel-title">关键信号</div>
            <div class="matrix-signal-list" id="matrix-signals-${item.key}"></div>
          </div>
          <div class="matrix-panel">
            <div class="product-panel-title">专属洞察</div>
            <div class="matrix-extra" id="matrix-extra-${item.key}"></div>
          </div>
        </div>
        <div class="matrix-section-head">
          <div>
            <div class="product-panel-title">优先动作</div>
            <p>生成后进入 OHRE，并通过 Profit Gate 约束活动/投流。</p>
          </div>
          <div class="section-meta" id="matrix-action-meta-${item.key}">0 条动作</div>
        </div>
        <div class="matrix-action-grid" id="matrix-actions-${item.key}"></div>
      </section>
    `,
  ).join("");

  return `
    <section class="dashboard-section matrix-hub-section workspace-panel" id="section-matrix" data-workspace-panel="section-matrix">
      <div class="section-head">
        <div>
          <div class="section-kicker">行动中心 · 由 AI 店长调度</div>
          <h2>增长执行与规模化 Agent</h2>
          <p>平台活动 / 投流 / AI客服 / 用户关系 / 评分评价 / 线上门店增长：有任务再进。</p>
        </div>
        <button class="topbar-button" type="button" data-scroll-target="section-growth">回增长策略</button>
      </div>
      <div class="matrix-hub-grid" id="matrixHubGrid">${hubCards}</div>
    </section>
    ${panels}
  `;
}

function ensureMatrixWorkspace() {
  if (qs("#section-matrix")) return;
  const stage = qs("#workspaceStage");
  if (!stage) return;
  const ai = qs("#section-ai");
  if (ai) ai.insertAdjacentHTML("beforebegin", buildMatrixWorkspaceHtml());
  else stage.insertAdjacentHTML("beforeend", buildMatrixWorkspaceHtml());
}

function renderMatrixExtras(key, agent) {
  if (key === "promo") {
    const unlock = agent.unlock_ready ? "可解锁活动动作" : "暂未达到解锁条件";
    const opportunities = (agent.opportunities || []).slice(0, 4);
    return `
      <div class="matrix-kv"><span>解锁状态</span><strong>${unlock}</strong></div>
      <div class="matrix-kv"><span>预期影响</span><strong>${escapeHtml(agent.expected_impact || "--")}</strong></div>
      ${
        opportunities.length
          ? `<ul class="matrix-bullet-list">${opportunities
              .map((row) => `<li>${escapeHtml(row)}</li>`)
              .join("")}</ul>`
          : `<div class="empty-state soft">暂无活动机会，先观察到手率与活动到期事件。</div>`
      }
    `;
  }
  if (key === "ads") {
    return `
      <div class="matrix-kv"><span>建议预算</span><strong>${
        agent.recommended_budget != null ? `¥${Number(agent.recommended_budget).toFixed(0)}` : "--"
      }</strong></div>
      <div class="matrix-kv"><span>目标商品</span><strong>${escapeHtml(agent.target_item_name || "--")}</strong></div>
      <div class="matrix-kv"><span>预估 ROI</span><strong>${
        agent.estimated_roi != null ? Number(agent.estimated_roi).toFixed(2) : "--"
      }</strong></div>
      <div class="matrix-kv"><span>解锁状态</span><strong>${agent.unlock_ready ? "可试验投流" : "先补转化证据"}</strong></div>
      <p class="matrix-extra-copy">${escapeHtml(agent.expected_impact || "投流动作必须过 Profit Gate。")}</p>
    `;
  }
  if (key === "crm") {
    const segments = agent.segments || [];
    return `
      <div class="matrix-kv"><span>复购率</span><strong>${
        agent.repurchase_rate != null ? `${(Number(agent.repurchase_rate) * 100).toFixed(1)}%` : "--"
      }</strong></div>
      <div class="matrix-kv"><span>复购变化</span><strong>${
        agent.repurchase_delta_pct == null ? "--" : formatDelta(agent.repurchase_delta_pct)
      }</strong></div>
      ${
        segments.length
          ? segments
              .map(
                (seg) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(seg.label)}</strong>
              <span>${seg.estimated_count ?? "--"} 人${
                  seg.share_pct != null ? ` · ${(Number(seg.share_pct) * 100).toFixed(0)}%` : ""
                }</span>
              <p>${escapeHtml(seg.note || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">客群分层证据不足。</div>`
      }
    `;
  }
  if (key === "service") {
    const themes = Object.entries(agent.theme_breakdown || {}).slice(0, 4);
    return `
      <div class="matrix-kv"><span>待处理回复</span><strong>${agent.pending_replies ?? 0}</strong></div>
      <div class="matrix-kv"><span>差评数</span><strong>${agent.negative_review_count ?? 0}</strong></div>
      ${
        themes.length
          ? `<ul class="matrix-bullet-list">${themes
              .map(([label, count]) => `<li>${escapeHtml(label)} · ${count}</li>`)
              .join("")}</ul>`
          : `<p class="matrix-extra-copy">${escapeHtml(agent.expected_impact || "客服积压会在首页后台并行区汇总。")}</p>`
      }
    `;
  }
  if (key === "review") {
    const themes = agent.themes || [];
    return `
      <div class="matrix-kv"><span>均分</span><strong>${
        agent.avg_rating != null ? Number(agent.avg_rating).toFixed(1) : "--"
      }</strong></div>
      <div class="matrix-kv"><span>评分变化</span><strong>${
        agent.rating_delta_pct == null ? "--" : formatDelta(agent.rating_delta_pct)
      }</strong></div>
      <div class="matrix-kv"><span>评价数</span><strong>${agent.review_count ?? 0}</strong></div>
      ${
        themes.length
          ? themes
              .slice(0, 4)
              .map(
                (theme) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(theme.label)}</strong>
              <span>${theme.count} · ${(Number(theme.share_pct || 0) * 100).toFixed(0)}%</span>
              <p>${escapeHtml(theme.sample || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">暂无评价主题。</div>`
      }
    `;
  }
  if (key === "store_matrix") {
    const concepts = agent.concepts || [];
    return `
      <div class="matrix-kv"><span>兄弟店</span><strong>${agent.sibling_store_count ?? 0}</strong></div>
      <div class="matrix-kv"><span>解锁状态</span><strong>${agent.unlock_ready ? "可规划新店概念" : "先稳住本店"}</strong></div>
      <p class="matrix-extra-copy">${escapeHtml((agent.sibling_stores || []).slice(0, 3).join("、") || "暂无兄弟店清单")}</p>
      ${
        concepts.length
          ? concepts
              .slice(0, 3)
              .map(
                (concept) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(concept.name)}</strong>
              <span>${escapeHtml(concept.daypart)} · ${escapeHtml(concept.readiness)}</span>
              <p>${escapeHtml(concept.rationale || concept.positioning || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">暂无多店概念候选。</div>`
      }
    `;
  }
  return `<div class="empty-state soft">暂无专属洞察。</div>`;
}

function renderMatrixAgent(key) {
  const def = MATRIX_AGENT_DEFS.find((item) => item.key === key);
  const agent = state.dashboard?.agents?.[key] || {};
  if (!def || !qs(`#section-${key}`)) return;

  const score = agent.health_score ?? "--";
  const tag = qs(`#matrix-tag-${key}`);
  if (tag) tag.textContent = `健康度 ${score}`;

  const hubScore = qs(`#matrix-hub-score-${key}`);
  if (hubScore) hubScore.textContent = score;
  const hubMeta = qs(`#matrix-hub-meta-${key}`);
  if (hubMeta) {
    hubMeta.textContent = [
      formatReadiness(agent.readiness),
      agent.unlock_ready === true ? "可解锁" : agent.unlock_ready === false ? "未解锁" : "",
      (agent.blockers || [])[0] || "",
      (agent.priority_actions || []).length ? `${agent.priority_actions.length} 个动作` : "暂无动作",
    ]
      .filter(Boolean)
      .join(" · ");
  }

  const hero = qs(`#matrix-hero-${key}`);
  if (hero) {
    const current = agent.current_action;
    const blockers = agent.blockers || [];
    hero.innerHTML = `
      <div class="matrix-hero-score">
        <span>健康度</span>
        <strong>${score}</strong>
      </div>
      <div class="matrix-hero-copy">
        <div class="product-panel-title">AI 判断</div>
        <h3>${escapeHtml(agent.conclusion || def.summary)}</h3>
        <p>${escapeHtml((agent.reasons || [])[0] || agent.expected_impact || def.copy)}</p>
        <small>${escapeHtml(actionQueueBrief(agent) || blockers[0] || "等待更多经营证据。")}</small>
        ${
          blockers.length
            ? `<ul class="matrix-blocker-list">${blockers
                .slice(0, 4)
                .map((row) => `<li>${escapeHtml(row)}</li>`)
                .join("")}</ul>`
            : ""
        }
      </div>
      <div class="matrix-hero-side">
        <div class="product-panel-title">当前动作</div>
        <strong>${escapeHtml(current?.title || "暂无进行中动作")}</strong>
        <p>${escapeHtml(current?.phase_reason || current?.next_decision || "优先动作确认后进入 OHRE。")}</p>
        <div class="matrix-unlock-tag ${agent.unlock_ready === false ? "locked" : "ready"}">${
          agent.unlock_ready === false ? "未解锁" : "可执行"
        }</div>
      </div>
    `;
  }

  const signals = qs(`#matrix-signals-${key}`);
  if (signals) {
    signals.innerHTML = (agent.signals || []).length
      ? agent.signals
          .slice(0, 5)
          .map(
            (signal) => `
          <article class="matrix-signal-row">
            <div>
              <strong>${escapeHtml(signal.title)}</strong>
              <p>${escapeHtml(signal.detail)}</p>
            </div>
            <span class="diagnosis-severity ${escapeHtml(signal.severity || "medium")}">${escapeHtml(
              eventSeverityLabel(signal.severity || "medium"),
            )}</span>
          </article>
        `,
          )
          .join("")
      : `<div class="empty-state soft">暂无新增信号。</div>`;
  }

  const extra = qs(`#matrix-extra-${key}`);
  if (extra) extra.innerHTML = renderMatrixExtras(key, agent);

  const actions = qs(`#matrix-actions-${key}`);
  const actionMeta = qs(`#matrix-action-meta-${key}`);
  const priorityActions = agent.priority_actions || [];
  if (actionMeta) actionMeta.textContent = `${priorityActions.length} 条动作`;
  if (actions) {
    actions.innerHTML = priorityActions.length
      ? priorityActions
          .map((action, index) => {
            const gated = action.create_enabled === false;
            const gateReason =
              action.create_block_reason ||
              action.profit_gate_reason ||
              (agent.unlock_ready === false ? (agent.blockers || [])[0] : "") ||
              "暂不可创建";
            return `
          <article class="matrix-action-card ${gated ? "gated" : ""}">
            <div class="matrix-action-top">
              <span>${escapeHtml(action.risk_level || "low")} risk</span>
              <span>${escapeHtml(action.expected_metric || "指标")} · ${action.window_hours || 24}h</span>
            </div>
            <h3>${escapeHtml(action.title)}</h3>
            <p>${escapeHtml(action.detail)}</p>
            ${
              action.profit_gate_reason
                ? `<div class="matrix-gate-note ${action.profit_gate_allowed === false ? "blocked" : ""}">${escapeHtml(
                    action.profit_gate_reason,
                  )}</div>`
                : ""
            }
            <div class="matrix-action-foot">
              <span>${
                action.expected_lift_pct_high
                  ? `预计 +${action.expected_lift_pct_low || 0}~${action.expected_lift_pct_high}%`
                  : escapeHtml(action.object_name || "门店")
              }</span>
              ${
                gated
                  ? `<button type="button" disabled title="${escapeHtml(gateReason)}">暂不可创建</button>`
                  : ["service", "review"].includes(key)
                    ? `<button type="button" class="primary" data-matrix-agent="${key}" data-matrix-action-index="${index}" data-matrix-enable="1">一键启用</button>`
                    : `<button type="button" data-matrix-agent="${key}" data-matrix-action-index="${index}">生成动作</button>`
              }
            </div>
            ${gated ? `<small class="matrix-gate-reason">${escapeHtml(gateReason)}</small>` : ""}
          </article>
        `;
          })
          .join("")
      : `<div class="empty-state">当前没有可执行优先动作。${
          (agent.blockers || [])[0] ? `阻塞：${escapeHtml(agent.blockers[0])}` : "先补证据或回增长策略排序。"
        }</div>`;
  }
}

function renderMatrixAgents() {
  ensureMatrixWorkspace();
  MATRIX_AGENT_DEFS.forEach((item) => renderMatrixAgent(item.key));
}

async function createMatrixAgentAction(agentKey, index, button, { enable = false } = {}) {
  if (!state.currentStoreId || !agentKey) return;
  const originalLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = enable ? "启用中…" : "处理中…";
  }
  try {
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/agents/${agentKey}/actions/${index}/create`,
      { method: "POST" },
    );
    if (enable && result.recommendation_id && ["proposed", "adopted"].includes(result.status)) {
      if (result.status === "proposed") {
        await fetchJson(`/workspace/recommendations/${result.recommendation_id}/adopt`, {
          method: "POST",
        });
      }
    }
    await loadDashboard(state.currentStoreId);
    notifySuccess(
      enable
        ? `${agentLabel(agentKey)}协议已启用，进入 OHRE 队列`
        : result.message || `${agentLabel(agentKey)}动作已生成`,
    );
  } catch (error) {
    notifyError(`${agentLabel(agentKey)}动作失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel || (enable ? "一键启用" : "生成动作");
    }
  }
}

function renderDashboard() {
  // 如果 runtime workspace（/v1/workspace）有数据，优先合并进 managerBrief
  // 让首页三栏直接吃 Runtime Bridge POC 链的产出
  if (state.runtimeWorkspace) {
    const rw = state.runtimeWorkspace;
    if (rw.left) {
      // 用 runtime workspace 的 need_you/working/results 覆盖
      if (!state.managerBrief) state.managerBrief = {};
      const mb = state.managerBrief;
      if (!mb.ops_queue) mb.ops_queue = {};
      const oq = mb.ops_queue;
      // 只在 runtime workspace 有更丰富数据时覆盖
      if (rw.left.need_you?.length) oq.need_you = rw.left.need_you;
      if (rw.left.active?.length) oq.working = rw.left.active;
      if (rw.left.completed?.length) oq.results = rw.left.completed;
      if (rw.left.opportunities?.length) oq.opportunities = rw.left.opportunities;
      if (rw.left.active_goal) oq.active_goal = rw.left.active_goal;
      if (rw.left.threads?.length) oq.threads = rw.left.threads;
      // guide
      if (rw.center?.guide) {
        mb.ops_queue.principle = rw.center.principle || oq.principle;
      }
      // meta
      if (rw.meta?.runtime_bridge) {
        if (!mb.runtime_bridge) mb.runtime_bridge = {};
        mb.runtime_bridge = rw.meta.runtime_bridge;
      }
    }
  }
  ensureMatrixWorkspace();
  applyWorkspaceMode(state.activeWorkspace || "section-overview");
  renderStoreSelector();
  renderTopbar();
  renderGuide();
  renderManagerBrief();
  renderEventDigest();
  renderActionCenter();
  renderCompetitionAgent();
  renderMenuAgent();
  renderProductAgent();
  renderStorefrontAgent();
  renderDiagnosisAgent();
  renderGrowthAgent();
  renderMatrixAgents();
  renderStrategyMemory();
  renderInsightTiles();
  renderCompetition();
  renderCollectionCenter();
  renderAgentTeamRoster();
  renderDailyBoard();
  renderExperiments();
  renderSettingsOverview();
  renderHomeEventFeed();
  renderWorthDoing();
  renderAutoActivity();
  renderVerifiedWins();
  renderStoreProfileCard();
}

async function fetchSensingBundle(storeId) {
  const [managerBrief, operatingEvents, strategyMemory, understanding, notifications, dailyPlan, actionTraces] = await Promise.all([
    fetchJson(`/stores/${storeId}/manager_brief`).catch(() => null),
    fetchJson(`/stores/${storeId}/events`).catch(() => null),
    fetchJson(`/stores/${storeId}/strategy_memory`).catch(() => null),
    fetchJson(`/stores/${storeId}/understanding`).catch(() => null),
    fetchJson(`/public/notifications/${storeId}`).catch(() => null),
    fetchRuntimeDailyPlan(storeId),
    fetchJson(`/stores/${storeId}/action-traces?limit=10`).catch(() => null),
  ]);
  state.managerBrief = managerBrief;
  state.operatingEvents = operatingEvents;
  state.strategyMemory = strategyMemory;
  state.understanding = understanding;
  state.actionTraces = (actionTraces?.traces || []);
  state.dailyPlan = dailyPlan?.plan || dailyPlan || state.dailyPlan;
  // 渲染未读通知
  const unread = (notifications?.notifications || []).filter(n => !n.read);
  if (unread.length) {
    const latest = unread[0];
    if (!state._lastNotifId || state._lastNotifId !== latest.id) {
      state._lastNotifId = latest.id;
      notifySuccess(`${latest.title}${latest.body ? "：" + latest.body.slice(0, 60) : ""}`);
      fetch(`/public/notifications/${latest.id}/read`, { method: "POST" }).catch(() => null);
    }
  }
}

async function loadStores() {
  const payload = await fetchJson("/workspace/stores");
  state.stores = payload.stores || [];
  if (!state.currentStoreId && state.stores.length) {
    state.currentStoreId = state.stores[0].id;
  }
  renderStoreSelector();
}

async function bootstrapWorkspace() {
  const payload = await fetchJson("/workspace/bootstrap", { method: "POST" });
  await loadStores();
  if (payload.default_store_id) {
    state.currentStoreId = payload.default_store_id;
  }
  if (state.currentStoreId) {
    await loadDashboard(state.currentStoreId);
  }
}

async function loadDashboard(storeId) {
  state.currentStoreId = storeId;
  const [dashboard, competitionMap, collectionRuns, platformLinks, settingsOverview, runtimeWorkspace] = await Promise.all([
    fetchDashboardBundle(storeId),
    fetchJson(`/stores/${storeId}/competition/map`).catch(() => null),
    fetchJson(`/stores/${storeId}/competition/collection-runs`).catch(() => ({ runs: [] })),
    fetchJson(`/workspace/stores/${storeId}/platform-links`).catch(() => ({ links: [] })),
    fetchJson(`/settings/overview?store_id=${encodeURIComponent(storeId)}`).catch(() => null),
    fetchRuntimeWorkspace(storeId),
  ]);
  state.dashboard = dashboard;
  state.runtimeWorkspace = runtimeWorkspace;
  state.competitionMap = competitionMap;
  state.collectionRuns = collectionRuns.runs || [];
  state.platformLinks = platformLinks.links || [];
  state.settingsOverview = settingsOverview;
  state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
  await fetchSensingBundle(storeId);
  renderDashboard();
}

async function refreshDashboard() {
  if (!state.currentStoreId) return;
  const button = qs("#refreshBtn");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "刷新中…";
  try {
    const [dashboard, competitionMap, collectionRuns, platformLinks, settingsOverview, runtimeWorkspace] = await Promise.all([
      fetchDashboardBundle(state.currentStoreId, { refresh: true }),
      fetchJson(`/stores/${state.currentStoreId}/competition/map`).catch(() => null),
      fetchJson(`/stores/${state.currentStoreId}/competition/collection-runs`).catch(() => ({ runs: [] })),
      fetchJson(`/workspace/stores/${state.currentStoreId}/platform-links`).catch(() => ({ links: [] })),
      fetchJson(`/settings/overview?store_id=${encodeURIComponent(state.currentStoreId)}`).catch(() => null),
      fetchRuntimeWorkspace(state.currentStoreId),
    ]);
    state.dashboard = dashboard;
    state.runtimeWorkspace = runtimeWorkspace;
    state.competitionMap = competitionMap;
    state.collectionRuns = collectionRuns.runs || [];
    state.platformLinks = platformLinks.links || [];
    state.settingsOverview = settingsOverview;
    state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
    await fetchSensingBundle(state.currentStoreId);
    renderDashboard();
  } catch (error) {
    notifyError(`看板刷新失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function mutateRecommendation(action, id) {
  if (!id || !action) return;
  await fetchJson(`/workspace/recommendations/${id}/${action}`, { method: "POST" });
  await loadDashboard(state.currentStoreId);
}

async function applyMenuAction(action, index, button) {
  if (!state.currentStoreId || !action) return;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "处理中…";
  try {
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/agents/menu/${action}/${index}/apply`,
      { method: "POST" },
    );
    await loadDashboard(state.currentStoreId);
    notifySuccess(result.message || "菜单动作已生成");
  } catch (error) {
    notifyError(`菜单动作失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function createProductAction(index, itemId, button) {
  if (!state.currentStoreId) return;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "生成中…";
  try {
    const query = itemId ? `?item_id=${encodeURIComponent(itemId)}` : "";
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/agents/product/suggestions/${index}/create${query}`,
      { method: "POST" },
    );
    await loadDashboard(state.currentStoreId);
    notifySuccess(result.message);
  } catch (error) {
    notifyError(`商品动作生成失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function applyProductAction(index, itemId, button) {
  if (!state.currentStoreId) return;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "执行中…";
  try {
    const query = itemId ? `?item_id=${encodeURIComponent(itemId)}` : "";
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/agents/product/suggestions/${index}/apply${query}`,
      { method: "POST" },
    );
    await loadDashboard(state.currentStoreId);
    notifySuccess(result.message || "商品优化已执行");
  } catch (error) {
    notifyError(`商品执行失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function renderMenuDeepDiagnosis() {
  const host = qs("#menuDeepDiagnosisResult");
  if (!host) return;
  const result = state.menuDeepDiagnosis;
  if (!result) {
    host.innerHTML = `<div class="empty-state">点「深度诊断」运行 12 引擎，查看结构与定价发现。</div>`;
    return;
  }
  const findings = result.findings || [];
  const counts = result.finding_count_by_severity || {};
  const countBits = Object.entries(counts)
    .map(([sev, n]) => `${sev} ${n}`)
    .join(" · ");
  host.innerHTML = `
    <p class="menu-dx-summary">${escapeHtml(
      result.summary || `共 ${findings.length} 条发现 · 数据成熟度 ${result.data_level || "--"}`,
    )}${countBits ? ` · ${escapeHtml(countBits)}` : ""}</p>
    <div class="menu-dx-findings">
      ${
        findings.length
          ? findings
              .slice(0, 12)
              .map(
                (finding) => `
                  <article class="menu-action-card">
                    <div class="product-recommendation-top">
                      <span>${escapeHtml(finding.severity || "info")}</span>
                      <span>${escapeHtml(finding.engine_id || "")}</span>
                    </div>
                    <h3>${escapeHtml(finding.title || "发现")}</h3>
                    <p>${escapeHtml(finding.description || finding.impact || "")}</p>
                    ${
                      (finding.suggested_actions || []).length
                        ? `<small>${(finding.suggested_actions || [])
                            .map((action) => escapeHtml(action))
                            .join(" · ")}</small>`
                        : ""
                    }
                  </article>
                `,
              )
              .join("")
          : `<div class="empty-state">本次诊断没有发现。</div>`
      }
    </div>
  `;
}

async function runMenuDeepDiagnosis() {
  if (!state.currentStoreId) return;
  const button = qs("#runMenuDiagnosisBtn");
  const originalLabel = button?.textContent || "深度诊断";
  if (button) {
    button.disabled = true;
    button.textContent = "诊断中…";
  }
  try {
    const result = await fetchJson(`/stores/${state.currentStoreId}/menu-diagnosis`);
    state.menuDeepDiagnosis = result;
    renderMenuDeepDiagnosis();
    notifySuccess(result.summary || `深度诊断完成：${(result.findings || []).length} 条发现`);
  } catch (error) {
    notifyError(`深度诊断失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

async function runDiagnosisNow() {
  if (!state.currentStoreId) return;
  const button = qs("#runDiagnosisBtn");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "诊断中…";
  try {
    await fetchJson(`/stores/${state.currentStoreId}/agents/diagnosis/run`, { method: "POST" });
    await loadDashboard(state.currentStoreId);
  } catch (error) {
    notifyError(`经营诊断失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function rebuildGrowthPlan() {
  if (!state.currentStoreId) return;
  const button = qs("#rebuildGrowthBtn");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "排序中…";
  try {
    await fetchJson(`/stores/${state.currentStoreId}/agents/growth/rebuild`, { method: "POST" });
    await loadDashboard(state.currentStoreId);
  } catch (error) {
    notifyError(`增长策略生成失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function renderHomeChatThread() {
  const container = qs("#homeChatThread");
  if (!container) return;
  const runtimeMeta = runtimeOutputMetaHtml();
  if (!state.chatMessages.length) {
    if (document.body.classList.contains("home-chat-open")) {
      container.innerHTML = `
        <section class="mk-chat-output-shell">
          <div class="mk-chat-output-head">
            <span class="mk-chat-output-kicker">任务输出</span>
            <strong>MealKey 会在这里持续更新</strong>
            ${runtimeMeta}
          </div>
          <div class="mk-chat-output-empty">
            <p>你发起任务后，我会在这里持续输出判断、进展、结果和下一步。</p>
          </div>
        </section>`;
      return;
    }
    container.innerHTML = "";
    return;
  }
  container.innerHTML = `
    <section class="mk-chat-output-shell">
      <div class="mk-chat-output-head">
        <span class="mk-chat-output-kicker">任务输出</span>
        <strong>当前路径的判断、进展和结果</strong>
        ${runtimeMeta}
      </div>
      <div class="mk-chat-output-body">
        ${state.chatMessages.map((message) => renderChatBubble(message, { home: true })).join("")}
      </div>
    </section>`;
  container.scrollTop = container.scrollHeight;
  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) analyzing.hidden = !state.chatMessages.some((m) => m.pending);
}

function runtimeOutputMetaHtml() {
  const runtime = runtimeWorkspacePanels();
  const meta = runtimeBridgeMeta();
  const dailyPlan = state.dailyPlan || {};
  const guide = currentRuntimeGuide();
  const items = [
    runtime?.store?.runtime_state ? `当前 ${runtime.store.runtime_state}` : "",
    dailyPlan?.current_meal_period ? `聚焦 ${dailyPlan.current_meal_period}` : "",
    guide?.status || "",
    meta.candidate_count ? `候选 ${meta.candidate_count}` : "",
    Array.isArray(meta.selected_skills) && meta.selected_skills.length
      ? `调用 ${meta.selected_skills.slice(0, 3).join(" / ")}`
      : "",
  ].filter(Boolean);
  if (!items.length) return "";
  return `<div class="mk-chat-output-meta">${items
    .map((item) => `<span>${escapeHtml(item)}</span>`)
    .join("")}</div>`;
}

function applyOwnerProfileUI(profile) {
  const data = profile || state.ownerProfile || {};
  const name = String(data.display_name || "老板").trim() || "老板";
  const initial = String(data.avatar_initial || name.slice(0, 1) || "王").slice(0, 1);
  const photo = data.avatar_data_url || "";

  const sidebarName = qs("#sidebarOwnerName");
  if (sidebarName) sidebarName.textContent = name;
  const topName = qs("#mkOwnerName");
  if (topName) topName.textContent = name;

  const face = qs("#mkOwnerAvatarFace") || qs("#mkOwnerAvatar");
  if (face) {
    if (photo) {
      face.classList.add("has-photo");
      face.style.backgroundImage = `url("${photo}")`;
      face.textContent = "";
    } else {
      face.classList.remove("has-photo");
      face.style.backgroundImage = "";
      face.textContent = initial;
    }
  }

  const sidebarAvatar = qs("#sidebarOwnerAvatar");
  if (sidebarAvatar) {
    if (photo) {
      sidebarAvatar.classList.add("has-photo");
      sidebarAvatar.style.backgroundImage = `url("${photo}")`;
      sidebarAvatar.textContent = "";
    } else {
      sidebarAvatar.classList.remove("has-photo");
      sidebarAvatar.style.backgroundImage = "";
      sidebarAvatar.textContent = initial;
    }
  }
}

function fillOwnerProfileForm(profile) {
  const data = profile || {};
  const nameInput = qs("#ownerDisplayNameInput");
  const phoneInput = qs("#ownerPhoneInput");
  const roleSelect = qs("#ownerRoleSelect");
  const storeHint = qs("#ownerProfileStoreName");
  const preview = qs("#ownerAvatarPreview");
  if (nameInput) nameInput.value = data.display_name || "老板";
  if (phoneInput) phoneInput.value = data.phone || "";
  if (roleSelect) {
    const role = data.role || "老板";
    const options = Array.from(roleSelect.options).map((o) => o.value);
    roleSelect.value = options.includes(role) ? role : "其他";
  }
  if (storeHint) {
    storeHint.textContent =
      data.store_name || state.dashboard?.store?.name || state.managerBrief?.store_name || "当前门店";
  }
  state.pendingAvatarDataUrl = data.avatar_data_url || null;
  if (preview) {
    const name = data.display_name || "老板";
    const initial = (data.avatar_initial || name.slice(0, 1) || "王").slice(0, 1);
    if (state.pendingAvatarDataUrl) {
      preview.classList.add("has-photo");
      preview.style.backgroundImage = `url("${state.pendingAvatarDataUrl}")`;
      preview.textContent = "";
    } else {
      preview.classList.remove("has-photo");
      preview.style.backgroundImage = "";
      preview.textContent = initial;
    }
  }
}

function openOwnerProfileModal() {
  const modal = qs("#ownerProfileModal");
  if (!modal) return;
  fillOwnerProfileForm(state.ownerProfile || state.settingsOverview?.owner || {});
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  qs("#ownerDisplayNameInput")?.focus();
}

function closeOwnerProfileModal() {
  const modal = qs("#ownerProfileModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  state.pendingAvatarDataUrl = null;
}

async function loadOwnerProfile(storeId = state.currentStoreId) {
  if (!storeId) return null;
  try {
    const profile = await fetchJson(`/settings/stores/${storeId}/owner`);
    state.ownerProfile = profile;
    applyOwnerProfileUI(profile);
    return profile;
  } catch (_) {
    return null;
  }
}

function readAvatarFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file || !file.type.startsWith("image/")) {
      reject(new Error("请选择图片文件"));
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      reject(new Error("图片请小于 2MB"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const maxSide = 240;
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", 0.82));
      };
      img.onerror = () => reject(new Error("图片读取失败"));
      img.src = String(reader.result || "");
    };
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

async function saveOwnerProfile(event) {
  event?.preventDefault?.();
  if (!state.currentStoreId) {
    notifyError("请先选择门店");
    return;
  }
  const saveBtn = qs("#ownerProfileSaveBtn");
  const original = saveBtn?.textContent || "保存";
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中…";
  }
  try {
    const displayName = (qs("#ownerDisplayNameInput")?.value || "").trim() || "老板";
    const phone = (qs("#ownerPhoneInput")?.value || "").trim();
    const role = (qs("#ownerRoleSelect")?.value || "老板").trim() || "老板";
    const profile = await fetchJson(`/settings/stores/${state.currentStoreId}/owner`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: displayName,
        phone,
        role,
        avatar_data_url: state.pendingAvatarDataUrl || null,
      }),
    });
    state.ownerProfile = profile;
    if (state.settingsOverview) state.settingsOverview.owner = profile;
    applyOwnerProfileUI(profile);
    closeOwnerProfileModal();
    notifySuccess("个人信息已更新");
  } catch (error) {
    notifyError(`保存失败：${error.message}`);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = original;
    }
  }
}

function setOpsRailCollapsed(collapsed) {
  state.opsRailCollapsed = Boolean(collapsed);
  const mobile = window.matchMedia("(max-width: 900px)").matches;
  try {
    localStorage.setItem("mk_ops_rail_collapsed", state.opsRailCollapsed ? "1" : "0");
  } catch (_) {
    /* ignore */
  }
  if (mobile) {
    // 窄屏：中栏独占；Logo 控制左栏抽屉
    document.body.classList.add("ops-rail-collapsed");
    document.body.classList.toggle("show-work-rail", !state.opsRailCollapsed);
  } else {
    document.body.classList.remove("show-work-rail");
    document.body.classList.toggle("ops-rail-collapsed", state.opsRailCollapsed);
  }
  const toggle = qs("#mkWorkRailToggleBtn");
  if (toggle) {
    toggle.setAttribute("aria-expanded", state.opsRailCollapsed ? "false" : "true");
    toggle.title = state.opsRailCollapsed ? "展开左侧工作线程" : "收起左侧工作线程";
  }
  const reopen = qs("#mkWorkRailReopenBtn");
  if (reopen) reopen.hidden = true;
}

function initOpsRailCollapsed() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem("mk_ops_rail_collapsed") === "1";
  } catch (_) {
    collapsed = false;
  }
  setOpsRailCollapsed(collapsed);
}

function enterWorkFromDialog(prompt = "") {
  openHomeChatMode();
  const text = String(prompt || "").trim();
  if (text) {
    askStoreManager(text, { stayOnHome: true }).catch((error) => notifyError(error.message));
    return;
  }
  qs("#homeChatInput")?.focus();
}

function enterWorkFromRail(item) {
  if (!item) return;
  const kind = item.dataset.railWork || "";
  const prompt = item.dataset.railPrompt || "";
  openHomeChatMode();
  if (kind === "need") {
    qs("#mkDecisionHost")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (prompt) {
    askStoreManager(prompt, { stayOnHome: true }).catch((error) => notifyError(error.message));
    return;
  }
  qs("#homeChatInput")?.focus();
}


// AI 任务专属视图：老板要什么就只给什么
function showTaskView(title, bodyHtml) {
  const tv = qs("#mkTaskView");
  if (!tv) return;
  const titleEl = qs("#mkTaskTitle");
  const bodyEl = qs("#mkTaskBody");
  const thread = qs("#homeChatThread");
  const guide = qs("#mkGuideArea");
  if (titleEl) titleEl.textContent = title || "任务";
  if (bodyEl) bodyEl.innerHTML = bodyHtml;
  if (thread) thread.hidden = true;
  if (guide) guide.hidden = true;
  tv.hidden = false;
  tv.scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideTaskView() {
  const tv = qs("#mkTaskView");
  const thread = qs("#homeChatThread");
  const guide = qs("#mkGuideArea");
  if (tv) tv.hidden = true;
  if (thread) thread.hidden = false;
  if (guide) guide.hidden = false;
}

function renderAssistGuideBody(guide) {
  if (!guide) return "<p>暂无引导内容。</p>";
  const parts = [];
  if (guide.summary) parts.push("<p>" + escapeHtml(guide.summary) + "</p>");
  const stepRows = guide.steps || guide.modes || [];
  if (stepRows.length) {
    parts.push('<div class="task-steps">');
    stepRows.forEach(function(step) {
      var heading = step.title || step.label || "";
      var detail = step.detail || step.hint || "";
      var command = step.command ? "<code>" + escapeHtml(step.command) + "</code>" : "";
      parts.push("<article><strong>" + escapeHtml(heading) + "</strong><p>" + escapeHtml(detail) + "</p>" + command + "</article>");
    });
    parts.push("</div>");
  }
  if (guide.recommended_action) parts.push("<p><strong>建议：</strong>" + escapeHtml(guide.recommended_action) + "</p>");
  return parts.join("\n") || "<p>" + escapeHtml(guide.conclusion || "请按引导操作。") + "</p>";
}

function taskRoutePrompt(targetId) {
  return (
    {
      "section-settings": "帮我沿着这条路径把平台接入和能力设置继续推进，不要展开整个后台。",
      "section-diagnosis": "沿着当前诊断路径继续推进，只给我这件事相关的判断和下一步。",
      "section-growth": "沿着当前增长主线继续推进，只保留这一条经营路径。",
      "section-product": "沿着当前商品优化路径继续推进，只看这一个商品问题。",
      "section-ads": "沿着当前投流决策路径继续推进，只处理这一条投放动作。",
      "section-record": "只打开这条经营线程的记录和结果，不要打开整页后台。",
    }[targetId] || "沿着这条任务路径继续推进，只保留当前这件事相关内容。"
  );
}

function renderTaskRouteBody(targetId, title = "") {
  const view = workspaceView(targetId);
  const runtime = runtimeWorkspacePanels();
  const plan = state.dailyPlan || {};
  const bits = [
    runtime?.store?.runtime_state ? `当前状态：${runtime.store.runtime_state}` : "",
    plan?.current_meal_period ? `当前餐段：${plan.current_meal_period}` : "",
    plan?.core_goal ? `当前目标：${plan.core_goal}` : "",
  ].filter(Boolean);
  const guide = currentRuntimeGuide();
  return `
    <div class="task-route-view">
      <p class="task-route-kicker">单一路径任务</p>
      <h3>${escapeHtml(title || view.title || "继续推进当前任务")}</h3>
      <p>${escapeHtml(view.summary || "我只保留这件事相关的信息和步骤。")}</p>
      ${bits.length ? `<div class="task-route-meta">${bits.map((b) => `<span>${escapeHtml(b)}</span>`).join("")}</div>` : ""}
      ${
        guide
          ? `<div class="task-route-guide">
              <strong>${escapeHtml(guide.title || guide.prompt || "当前需要你")}</strong>
              <p>${escapeHtml(guide.explanation || guide.summary || "确认后我继续推进。")}</p>
            </div>`
          : ""
      }
      <div class="task-route-actions">
        <button class="action-button primary" type="button" data-task-ask="${escapeHtml(taskRoutePrompt(targetId))}">继续这条路径</button>
        <button class="action-button ghost" type="button" data-task-back>返回首页</button>
      </div>
    </div>`;
}

function showTaskRoute(targetId, title = "") {
  showTaskView(title || workspaceView(targetId).label || "任务路径", renderTaskRouteBody(targetId, title));
}

function openHomeChatMode() {
  if (!document.body.classList.contains("view-home")) return;
  document.body.classList.add("home-chat-open");
  setHomeChatReply("");
  renderHomeChatThread();
  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) analyzing.hidden = !(state.chatMessages || []).some((m) => m.pending);
}

function closeHomeChatMode() {
  document.body.classList.remove("home-chat-open");
  renderHomeChatThread();
}

function renderChatMessages() {
  const container = qs("#aiChatMessages");
  if (container) {
    if (!state.chatMessages.length) {
      container.innerHTML = `<div class="ai-chat-empty">向 AI 店长提问，回答会显示在这里。</div>`;
    } else {
      container.innerHTML = state.chatMessages.map((message) => renderChatBubble(message)).join("");
      container.scrollTop = container.scrollHeight;
    }
  }
  if (document.body.classList.contains("home-chat-open")) {
    renderHomeChatThread();
  }
}

function renderChatAttachments(message) {
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  if (!attachments.length) return "";
  return `
    <div class="chat-attachment-list">
      ${attachments
        .map(
          (item) => `
            <div class="chat-attachment-chip ${message.role === "assistant" ? "parsed" : ""}">
              <strong>${escapeHtml(item.name || "附件")}</strong>
              <span>${escapeHtml(item.kind || item.type || "file")}${item.size_kb ? ` · ${escapeHtml(String(item.size_kb))}KB` : ""}</span>
              ${message.role === "assistant" && item.summary ? `<em>${escapeHtml(item.summary)}</em>` : ""}
            </div>
          `,
        )
        .join("")}
    </div>`;
}

function structuredAssistantSections(text) {
  const raw = String(text || "").trim();
  if (!raw) return { lead: "", sections: [] };
  const blocks = raw.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);
  const sections = [];
  let lead = "";
  const mappings = [
    ["已执行：", "已执行"],
    ["依据：", "判断依据"],
    ["接下来：", "下一步"],
    ["预计：", "预期结果"],
    ["观察窗：", "观察窗"],
    ["风险：", "风险提醒"],
  ];
  blocks.forEach((block, index) => {
    const found = mappings.find(([prefix]) => block.startsWith(prefix));
    if (found) {
      const [prefix, title] = found;
      sections.push({
        title,
        body: block.slice(prefix.length).trim(),
      });
      return;
    }
    if (!lead && index === 0) {
      lead = block;
      return;
    }
    sections.push({
      title: sections.length ? `补充${sections.length}` : "补充说明",
      body: block,
    });
  });
  return { lead: lead || blocks[0] || "", sections };
}

function renderChatBubble(message, { home = false } = {}) {
  const klass = home ? "mk-chat-bubble" : "ai-chat-bubble";
  const speaker = message.role === "user" ? "我" : home ? "MealKey" : "AI 店长";
  if (home && message.role === "assistant") {
    const structured = structuredAssistantSections(message.text);
    const leadHtml = structured.lead ? `<p class="mk-output-lead">${escapeHtml(structured.lead)}</p>` : "";
    const sectionHtml = structured.sections.length
      ? `<div class="mk-output-sections">
          ${structured.sections
            .map(
              (section) => `
                <section class="mk-output-section">
                  <strong>${escapeHtml(section.title)}</strong>
                  <p>${escapeHtml(section.body)}</p>
                </section>`,
            )
            .join("")}
        </div>`
      : "";
    return `
      <div class="${klass} ${message.role}${message.pending ? " pending" : ""}">
        <strong>${speaker}</strong>
        ${leadHtml}
        ${sectionHtml}
        ${renderChatAttachments(message)}
      </div>
    `;
  }
  return `
    <div class="${klass} ${message.role}${message.pending ? " pending" : ""}">
      <strong>${speaker}</strong>
      <p>${escapeHtml(message.text)}</p>
      ${renderChatAttachments(message)}
    </div>
  `;
}

function appendChatMessage(role, text, options = {}) {
  state.chatMessages.push({
    role,
    text,
    pending: Boolean(options.pending),
    attachments: Array.isArray(options.attachments) ? options.attachments : [],
  });
  renderChatMessages();
}

function setHomeChatReply(text, { pending = false } = {}) {
  const reply = qs("#homeChatReply");
  if (!reply) return;
  if (!text || document.body.classList.contains("home-chat-open")) {
    reply.hidden = true;
    reply.textContent = "";
    return;
  }
  reply.hidden = false;
  reply.classList.toggle("pending", pending);
  reply.textContent = text;
}

function formatWorkReply(question, response) {
  if (response?.guide?.prompt || response?.guide?.title) {
    const guide = response.guide;
    const lines = [
      guide.title || "我先把这件事推进一格。",
      guide.prompt || "",
      guide.explanation || guide.summary || "",
    ].filter(Boolean);
    return lines.join("\n\n");
  }
  const conclusion = response?.conclusion || response?.answer || "";
  const actions = (response?.actions || []).filter(Boolean);
  const expected = response?.expected || "";
  const reasons = (response?.reasons || []).filter(Boolean);
  const agentsCalled = (response?.agents_called || []).filter(Boolean);
  const mode = response?.mode || "";
  const confidence = response?.confidence || "";
  const observationWindow = response?.observation_window || response?.next_check || response?.next_check_at || "";

  // chief_agent ReAct 模式：展示调度了哪些 agent + 依据
  const agentNote = agentsCalled.length
    ? agentsCalled.some(a => a.startsWith("write:"))
      ? `已执行：${agentsCalled.filter(a => a.startsWith("write:")).map(a => a.replace("write:", "")).join("、")}`
      : `我帮你查了：${agentsCalled.join("、")}`
    : "";

  // 降级提示：如果 ReAct 失败走了规则，标注一下
  const modeNote = mode === "rule_fallback" && response?.error
    ? `（注：AI 实时分析暂时不可用，以上基于规则引擎。原因：${response.error.slice(0, 60)}）`
    : "";

  const lines = [
    conclusion || "明白。我来处理。",
    agentNote,
    reasons.length ? `依据：\n${reasons.map(r => `· ${r}`).join("\n")}` : "",
    actions.length ? `接下来：\n${actions.map((item, i) => `${i + 1}. ${item}`).join("\n")}` : "需要你参与时我再找你。",
    expected ? `预计：${expected}` : "",
    observationWindow ? `观察窗：${String(observationWindow)}` : "",
    modeNote,
  ].filter(Boolean);
  return lines.join("\n\n");
}

// Goal：优先 POST /goals；失败则交给 /ask（后端 handle_user_intent）

// TTS：朗读 AI 回答
async function speakReply(text) {
  if (!text || text.length < 2) return;
  try {
    const result = await fetchJson('/speech/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 500) }),
    });
    if (result.ok && result.audio) {
      const audio = new Audio('data:audio/' + (result.format || 'mp3') + ';base64,' + result.audio);
      audio.play().catch(() => null);
    }
  } catch (e) { /* TTS 失败静默 */ }
}

// 追溯"为什么 AI 做了这个动作"
async function explainAction(traceId) {
  if (!state.currentStoreId || !traceId) return;
  try {
    const result = await fetchJson(`/stores/${state.currentStoreId}/action-traces/${traceId}/explain`);
    if (result.explanation) {
      appendChatMessage('assistant', result.explanation);
    }
  } catch (e) {
    notifyError('追踪查询失败：' + e.message);
  }
}


// 文件路径读取：给路径→蒸馏→接入对话
async function readFileAndAsk(filePath, question) {
  if (!state.currentStoreId || !filePath) return;
  try {
    const q = question || '帮我分析这个文件';
    const params = new URLSearchParams({ file_path: filePath, question: q });
    const result = await fetchJson(`/workspace/stores/${state.currentStoreId}/read-file?${params}`);
    if (result.ok !== false && result.extracted_text) {
      appendChatMessage('assistant', result.answer?.conclusion || result.extracted_text.slice(0, 500));
    }
  } catch (e) {
    notifyError('文件读取失败：' + e.message);
  }
}

function tryParseGoal(text) {
  const t = (text || "").trim();
  let m = t.match(/(?:这个月|本月|月内)?.{0,6}(?:做到|冲到|完成|达到)\s*(\d+(?:\.\d+)?)\s*万/);
  if (m) return { raw_text: t, metric: "gmv", target_value: parseFloat(m[1]) * 10000, deadline: monthEnd() };
  m = t.match(/利润(?:率)?(?:拉回|拉到|做到|提到|提高到)?\s*(\d+(?:\.\d+)?)\s*%?/);
  if (m && t.includes("利润") && !/利润优先|先赚钱/.test(t)) {
    let val = parseFloat(m[1]);
    if (val > 1) val = val / 100;
    return { raw_text: t, metric: "take_home_rate", target_value: val, deadline: monthEnd() };
  }
  if (/前\s*三|top\s*3/i.test(t) && (t.includes("饭") || t.includes("菜") || t.includes("做到") || t.includes("帮我"))) {
    return { raw_text: t, metric: "rank", target_value: 3, deadline: monthEnd() };
  }
  m = t.match(/(?:多|增加|做到)\s*(\d+)\s*单/);
  if (m && (t.includes("午餐") || t.includes("今天") || t.includes("一天")) && !t.includes("一小时") && !t.includes("每小时")) {
    return { raw_text: t, metric: "orders", target_value: parseFloat(m[1]), deadline: todayStr() };
  }
  return null;
}

function monthEnd() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

async function createGoalFromInput(text) {
  if (!state.currentStoreId) return false;
  const goalReq = tryParseGoal(text);
  if (!goalReq) return false;
  await fetchJson(`/stores/${state.currentStoreId}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(goalReq),
  });
  await loadDashboard(state.currentStoreId).catch(() => null);
  fetch(`/stores/${state.currentStoreId}/goals/sync`, { method: "POST" }).catch(() => null);
  renderWorkRail();
  renderContextRail();
  renderDecisionHost(currentNeedCard());
  return goalReq;
}

async function askStoreManager(question, options = {}) {
  if (!state.currentStoreId) return;
  const stayOnHome =
    (Boolean(options.stayOnHome) || document.body.classList.contains("view-home")) &&
    document.body.classList.contains("view-home");
  const trimmed = question.trim();
  const attachments = Array.isArray(options.attachments) ? options.attachments : [];
  if (!trimmed && !attachments.length) return;

  const input = qs("#aiChatInput");
  const sendBtn = qs("#aiChatSendBtn");
  const homeInput = qs("#homeChatInput");
  const homeSend = qs("#homeChatSendBtn");
  const displayQuestion = trimmed || `请先看我上传的 ${attachments.length} 个文件`;
  const parsedGoal = !attachments.length ? tryParseGoal(trimmed) : null;

  if (stayOnHome) openHomeChatMode();
  appendChatMessage("user", displayQuestion, {
    attachments: attachments.map((file) => ({
      name: file.name,
      type: file.type || "file",
      size_kb: Math.max(1, Math.round(file.size / 1024)),
    })),
  });
  if (input) {
    input.value = "";
    input.disabled = true;
  }
  if (homeInput) {
    homeInput.value = "";
    homeInput.disabled = true;
  }
  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.dataset.originalLabel = sendBtn.textContent || "";
    sendBtn.textContent = "处理中…";
  }
  if (homeSend) {
    homeSend.disabled = true;
    if (!homeSend.dataset.readyHtml) homeSend.dataset.readyHtml = homeSend.innerHTML;
    homeSend.textContent = "…";
  }
  appendChatMessage("assistant", "明白。我来处理…", { pending: true });

  try {
    if (parsedGoal) {
      try {
        const goalReq = await createGoalFromInput(trimmed);
        if (state.chatMessages.length && state.chatMessages[state.chatMessages.length - 1].pending) {
          state.chatMessages.pop();
        }
        appendChatMessage(
          "assistant",
          `明白。目标已记录：${goalReq.raw_text}\n我会持续跟踪进度，偏离计划或需要你拍板时出现在「现在需要你」。`,
        );
        notifySuccess("目标已建立");
        if (stayOnHome) renderHomeChatThread();
        return;
      } catch (_error) {
        // CRUD 失败则继续走 /ask（后端 intent 同样会建目标）
      }
    }

    let response = null;
    if (attachments.length) {
      response = await (async () => {
        const form = new FormData();
        form.set("question", trimmed);
        form.set("days", "7");
        attachments.forEach((file) => form.append("files", file, file.name));
        const res = await fetch(`/workspace/stores/${state.currentStoreId}/ask-rich`, {
          method: "POST",
          headers: apiAuthHeaders(),
          body: form,
        });
        if (!res.ok) {
          const payload = await res.json().catch(() => ({}));
          throw new Error(payload.detail || `请求失败：${res.status}`);
        }
        return res.json();
      })();
    } else {
      try {
        response = await fetchJson(`/v1/stores/${state.currentStoreId}/intent`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: trimmed }),
        });
      } catch (_intentError) {
        response = await fetchJson(`/workspace/stores/${state.currentStoreId}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: trimmed, days: 7 }),
        });
      }
    }
    if (state.chatMessages.length && state.chatMessages[state.chatMessages.length - 1].pending) {
      state.chatMessages.pop();
    }
    const answer = stayOnHome
      ? formatWorkReply(displayQuestion, response)
      : formatWorkReply(displayQuestion, response) ||
        "暂时没有可用结论。";
    appendChatMessage("assistant", answer, {
      attachments: response.attachments || [],
    });
    if (response.understanding) {
      state.understanding = response.understanding;
    }
    if (response.workspace) {
      state.runtimeWorkspace = response.workspace;
    }
    if (response.daily_plan) {
      state.dailyPlan = response.daily_plan.plan || response.daily_plan;
    }
    if (response.intent === "goal") {
      notifySuccess("目标已建立，已进入经营线程");
    } else if (response.intent === "understanding_update") {
      notifySuccess("已记住你的偏好");
    }
    if (stayOnHome) {
      // 优先吃 /intent 返回的最新 runtime；拿不到时再整页刷新兜底
      if (!response.workspace) {
        await loadDashboard(state.currentStoreId).catch(() => null);
      }
      renderWorkRail();
      renderContextRail();
      renderDecisionHost(currentNeedCard());
      renderHomeChatThread();
    }
    // AI 对话专属视图：老板要什么就只给什么，不跳全量看板
    var _guide = response.guide || response;
    if (response.intent === "deploy" || response.intent === "platform" || response.intent === "settings") {
      var _title = _guide.title || (response.intent === "platform" ? "AI 协助对接" : "AI 协助上手");
      var _body = renderAssistGuideBody(_guide);
      showTaskView(_title, _body);
    } else if (response.intent === "storefront" && !stayOnHome) {
      showTaskView("线上装修", "<p>已准备装修方案，请在首页确认。</p>");
    } else if (response.intent === "goal" || response.intent === "understanding_update") {
      // 留在对话流，不跳转
    } else if (!stayOnHome) {
      // 留在对话流
    }
  } catch (error) {
    if (state.chatMessages.length && state.chatMessages[state.chatMessages.length - 1].pending) {
      state.chatMessages.pop();
    }
    appendChatMessage("assistant", `提问失败：${error.message}`);
    if (stayOnHome && !document.body.classList.contains("home-chat-open")) {
      setHomeChatReply(`提问失败：${error.message}`);
    }
    notifyError(error.message);
  } finally {
    if (attachments.length) clearHomeAttachments();
    if (input) input.disabled = false;
    if (homeInput) homeInput.disabled = false;
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.textContent = sendBtn.dataset.originalLabel || "发送";
    }
    if (homeSend) {
      homeSend.disabled = false;
      homeSend.innerHTML = homeSend.dataset.readyHtml || "↑";
    }
  }
}

async function evaluateExperiment(experimentId, button) {
  if (!experimentId) return;
  const originalLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "评估中…";
  }
  try {
    const result = await fetchJson(`/workspace/experiments/${experimentId}/evaluate`, { method: "POST" });
    await loadDashboard(state.currentStoreId);
    const lift =
      result.lift_pct === null || result.lift_pct === undefined ? "" : `，提升 ${formatDelta(result.lift_pct)}`;
    notifySuccess(
      result.result
        ? `评估完成：${formatStatus(result.result)}${lift}`
        : `评估完成${lift || ""}`,
    );
  } catch (error) {
    notifyError(`实验评估失败：${error.message}`);
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

async function decideOperatingEvent(fingerprint, decision, button) {
  if (!state.currentStoreId || !fingerprint || !decision) return;
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
  }
  try {
    const result = await fetchJson(`/stores/${state.currentStoreId}/events/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fingerprint, decision }),
    });
    state.operatingEvents = result.events || state.operatingEvents;
    state.managerBrief = await fetchJson(
      `/stores/${state.currentStoreId}/manager_brief`,
    ).catch(() => state.managerBrief);
    renderEventDigest();
    renderManagerBrief();
    notifySuccess(result.message || "决策已保存");
  } catch (error) {
    notifyError(`事件决策失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function scanCompetitionNow() {
  if (!state.currentStoreId) return;
  const buttons = [qs("#scanCompetitionBtn"), qs("#scanCompetitionWorkbenchBtn")].filter(Boolean);
  const originals = buttons.map((button) => button.textContent);
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "扫描中…";
  });
  try {
    const provider = state.publicConfig?.competition_collection?.default_provider || "amap";
    const result = await fetchJson(
      `/stores/${state.currentStoreId}/competition/collect?provider=${encodeURIComponent(provider)}`,
      { method: "POST" },
    );
    if (result.status !== "completed") {
      throw new Error(result.error || "竞品扫描失败");
    }
    await loadDashboard(state.currentStoreId);
    const status = qs("#competitionCollectionStatus");
    if (status) {
      status.textContent = `本次发现 ${result.discovered_count} 家，写入 ${result.snapshot_count} 份快照。`;
    }
  } catch (error) {
    notifyError(error.message);
  } finally {
    buttons.forEach((button, index) => {
      button.disabled = false;
      button.textContent = originals[index];
    });
    renderCompetitionMap();
  }
}

function setConnectPollStatus(text, status = "idle") {
  const el = qs("#connectPollStatus");
  if (!el) return;
  el.textContent = text;
  el.dataset.state = status;
}

function stopConnectCodePolling() {
  if (state.connectPollTimer) {
    window.clearInterval(state.connectPollTimer);
    state.connectPollTimer = null;
  }
  state.connectPollInFlight = false;
}

async function refreshPlatformLinks() {
  if (!state.currentStoreId) return [];
  const payload = await fetchJson(`/workspace/stores/${state.currentStoreId}/platform-links`).catch(() => ({
    links: state.platformLinks || [],
  }));
  state.platformLinks = payload.links || [];
  renderCollectionCenter();
  renderAgentTeamRoster();
  return state.platformLinks;
}

async function handleConnectCodeConnected(code) {
  stopConnectCodePolling();
  state.activeConnectCode = code || state.activeConnectCode;
  setConnectPollStatus("手机端已确认，平台连接成功。", "connected");
  await refreshPlatformLinks();
  if (state.currentStoreId) {
    await loadDashboard(state.currentStoreId).catch(() => null);
  }
  notifySuccess(`${state.pendingPlatform || "平台"}已连接`);
  window.setTimeout(() => {
    const modal = qs("#collectionModal");
    if (modal?.classList.contains("open")) closeCollectionModal();
  }, 900);
}

async function pollConnectCodeOnce() {
  if (!state.currentStoreId || !state.activeConnectCode || state.connectPollInFlight) return;
  state.connectPollInFlight = true;
  try {
    const payload = await fetchJson(
      `/workspace/stores/${state.currentStoreId}/connect-codes/${encodeURIComponent(state.activeConnectCode)}`,
    );
    if (payload.status === "connected") {
      await handleConnectCodeConnected(payload.code);
      return;
    }
    if (payload.status === "expired") {
      stopConnectCodePolling();
      setConnectPollStatus("连接码已过期，请重新生成。", "expired");
      return;
    }
    const seconds = Number(payload.expires_in_seconds || 0);
    const mins = Math.max(1, Math.ceil(seconds / 60));
    setConnectPollStatus(`等待手机端输入连接码确认…约剩 ${mins} 分钟`, "waiting");

    const links = await refreshPlatformLinks();
    const key = String(state.pendingPlatformKey || "").toLowerCase();
    const label = String(state.pendingPlatform || "");
    const linked = links.some((link) => {
      if (!(link.status === "connected" || link.connected_at)) return false;
      const value = String(link.platform || "").toLowerCase();
      return value === key || (key && value.includes(key)) || String(link.platform || "") === label;
    });
    if (linked) {
      await handleConnectCodeConnected(state.activeConnectCode);
    }
  } catch (error) {
    setConnectPollStatus(`轮询连接状态失败：${error.message}`, "error");
  } finally {
    state.connectPollInFlight = false;
  }
}

function startConnectCodePolling() {
  stopConnectCodePolling();
  if (!state.activeConnectCode) return;
  setConnectPollStatus("等待手机端输入连接码确认…", "waiting");
  pollConnectCodeOnce();
  state.connectPollTimer = window.setInterval(pollConnectCodeOnce, 2500);
}

async function generateMobileConnectCode() {
  if (!state.currentStoreId) {
    qs("#mobileConnectCode").textContent = "------";
    setConnectPollStatus("请先选择门店，再生成连接码。", "error");
    return null;
  }
  const platform = state.pendingPlatformKey || state.pendingPlatform || "外卖平台";
  const button = qs("#generateConnectCodeBtn");
  const originalLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "生成中…";
  }
  stopConnectCodePolling();
  try {
    const payload = await fetchJson(
      `/workspace/stores/${state.currentStoreId}/connect-codes?platform=${encodeURIComponent(platform)}`,
      { method: "POST" },
    );
    const code = payload.code || "------";
    state.activeConnectCode = code === "------" ? null : code;
    qs("#mobileConnectCode").textContent = code;
    if (state.activeConnectCode) {
      startConnectCodePolling();
    } else {
      setConnectPollStatus("连接码生成异常，请重试。", "error");
    }
    return state.activeConnectCode;
  } catch (error) {
    state.activeConnectCode = null;
    qs("#mobileConnectCode").textContent = "------";
    setConnectPollStatus(`连接码生成失败：${error.message}`, "error");
    notifyError(`连接码生成失败：${error.message}`);
    return null;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

async function confirmActiveConnectCode() {
  if (!state.currentStoreId) return;
  let code = state.activeConnectCode || qs("#mobileConnectCode")?.textContent;
  if (!code || code === "------") {
    code = await generateMobileConnectCode();
  }
  if (!code) return;
  const button = qs("#demoConfirmConnectBtn");
  const originalLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "确认中…";
  }
  try {
    const result = await fetchJson(
      `/workspace/stores/${state.currentStoreId}/platform-links/${encodeURIComponent(code)}/confirm`,
      { method: "POST" },
    );
    state.platformLinks = result.links || state.platformLinks;
    await handleConnectCodeConnected(code);
  } catch (error) {
    setConnectPollStatus(`确认失败：${error.message}`, "error");
    notifyError(`连接确认失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel || "模拟手机确认";
    }
  }
}

function openCollectionModal(platformLabel = "外卖平台", platformKey = null) {
  state.pendingPlatform = platformLabel;
  state.pendingPlatformKey = platformKey || platformLabel;
  qs("#collectionModalTitle").textContent = `连接${platformLabel}`;
  setConnectPollStatus("正在生成连接码…", "waiting");
  const modal = qs("#collectionModal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  generateMobileConnectCode();
}

function closeCollectionModal() {
  stopConnectCodePolling();
  const modal = qs("#collectionModal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  setConnectPollStatus("打开弹窗后会自动生成连接码，并等待手机端确认。", "idle");
}

async function copyMobileConnectionGuide() {
  const code = qs("#mobileConnectCode").textContent;
  const platform = state.pendingPlatform || "外卖平台";
  const guide = `MealKey 餐启手机连接说明\n平台：${platform}\n连接码：${code}\n请在商家手机餐启 App 内输入连接码，并在本机 WebView 中完成登录。密码和登录态不会上传云端。`;
  try {
    await navigator.clipboard.writeText(guide);
    qs("#copyMobileGuideBtn").textContent = "已复制";
    setTimeout(() => {
      qs("#copyMobileGuideBtn").textContent = "复制连接说明";
    }, 1600);
  } catch (_error) {
    notifyInfo("复制失败，请手动记下上方连接码");
  }
}

function setSidebarOpen(open) {
  const sidebar = qs("#sidebar");
  const toggle = qs("#sidebarToggle");
  const backdrop = qs("#sidebarBackdrop");
  if (!sidebar) return;
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  if (!isMobile) {
    sidebar.classList.remove("collapsed");
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    if (backdrop) {
      backdrop.hidden = true;
      backdrop.classList.remove("show");
    }
    document.body.classList.remove("sidebar-open");
    return;
  }
  sidebar.classList.toggle("collapsed", !open);
  if (toggle) toggle.setAttribute("aria-expanded", String(open));
  if (backdrop) {
    backdrop.hidden = !open;
    backdrop.classList.toggle("show", open);
  }
  document.body.classList.toggle("sidebar-open", open);
}

function syncSidebarForViewport() {
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  setSidebarOpen(!isMobile);
}

function toggleSidebar() {
  const sidebar = qs("#sidebar");
  if (!sidebar) return;
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  if (!isMobile) return;
  setSidebarOpen(sidebar.classList.contains("collapsed"));
}

function bindSidebarNav() {
  qsa(".nav-item[data-scroll-target], .nav-sub-item[data-scroll-target]").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const groupKey = item.dataset.navToggle;
      if (groupKey) {
        const group = item.closest(".nav-group");
        const isOpen = group?.classList.contains("open");
        // 已展开时再点分组标题：只收起，避免 scroll/sync 又把它打开
        if (isOpen) {
          setNavGroupOpen(groupKey, false);
          return;
        }
        setNavGroupOpen(groupKey, true);
      }
      scrollToSection(item.dataset.scrollTarget);
    });
  });
}

function showAssistGuide(guide) {
  if (!guide) return;
  const title = qs("#settingsAssistTitle");
  const summary = qs("#settingsAssistSummary");
  const steps = qs("#settingsAssistSteps");
  if (title) title.textContent = guide.title || (guide.topic === "platform" ? "AI 协助对接" : "AI 协助上手");
  if (summary) summary.textContent = guide.summary || guide.recommended_action || guide.conclusion || "";
  const stepRows = guide.steps || guide.modes || [];
  if (steps) {
    steps.innerHTML = stepRows.length
      ? stepRows
          .map((step) => {
            const heading = step.title || step.label || "";
            const detail = step.detail || step.hint || "";
            const command = step.command ? `<code>${escapeHtml(step.command)}</code>` : "";
            return `<article><strong>${escapeHtml(heading)}</strong><p>${escapeHtml(detail)}</p>${command}</article>`;
          })
          .join("")
      : "";
  }
}

function renderSettingsOverview() {
  const overview = state.settingsOverview;
  if (!overview) return;

  const checklist = overview.checklist || {};
  qs("#settingsChecklist").innerHTML = (checklist.steps || [])
    .map(
      (step) => `
        <article class="settings-check-item ${step.done ? "done" : ""}">
          <strong>${step.done ? "✓" : "○"} ${escapeHtml(step.title)}</strong>
          <p>${escapeHtml(step.hint)}</p>
        </article>
      `,
    )
    .join("");

  const llm = overview.llm || {};
  const guide = overview.ai?.platform || overview.ai?.deploy || {};
  if (llm.configured) {
    guide.summary = `内置大模型引擎已就绪（独立部署，不依赖主仓）。${guide.summary || ""}`.trim();
  } else if (guide.summary) {
    guide.summary = `大模型未配置，问答将走规则引擎。可在下方系统密钥中填写。${guide.summary}`.trim();
  }
  showAssistGuide(guide);

  const llmHint = qs("#settingsLlmHint");
  const llmGrid = qs("#settingsLlmGrid");
  if (llmHint) {
    llmHint.textContent = llm.configured
      ? "引擎已配置，AI 店长对话将直连厂商（DeepSeek / 千问 / Kimi），失败自动 Failover。"
      : "尚未检测到 Key。独立部署时请用 .env 或下方「系统与平台密钥」中的 LLM 分组填写。";
  }
  if (llmGrid) {
    const purposeEntries = Object.entries(llm.purposes || {});
    llmGrid.innerHTML = purposeEntries.length
      ? purposeEntries
          .map(([purpose, info]) => {
            const ready = (info.candidates || []).filter((c) => c.has_key).length;
            const total = (info.candidates || []).length;
            return `<article class="settings-llm-card ${info.configured ? "ready" : ""}">
              <strong>${escapeHtml(purpose)}</strong>
              <span>${info.configured ? "可调用" : "未就绪"} · ${ready}/${total} 节点有 Key</span>
              <small>${(info.candidates || [])
                .map((c) => `${c.provider}/${c.model}${c.has_key ? "" : "(无Key)"}`)
                .join(" → ")}</small>
            </article>`;
          })
          .join("")
      : `<div class="empty-state">正在读取引擎状态…</div>`;
  }

  const store = overview.store || {};
  const form = qs("#storeSettingsForm");
  if (form) {
    Array.from(form.elements).forEach((el) => {
      if (!(el instanceof HTMLInputElement) || !el.name) return;
      const value = store[el.name];
      el.value = value === null || value === undefined ? "" : value;
    });
  }

  const menuText = qs("#menuSettingsText");
  if (menuText) {
    menuText.value = (overview.menu?.items || [])
      .map((item) => [item.name, item.category || "", item.price ?? ""].join("|"))
      .join("\n");
  }

  const systemList = qs("#systemSettingsList");
  if (systemList) {
    systemList.innerHTML = (overview.system || [])
      .map(
        (row) => `
          <label>
            <span>${escapeHtml(row.label)} <small>${row.configured ? "已配置" : "未配置"} · ${escapeHtml(row.source)}</small></span>
            <input
              data-setting-key="${escapeHtml(row.key)}"
              type="${row.is_secret ? "password" : "text"}"
              value="${escapeHtml(row.value || "")}"
              placeholder="${escapeHtml(row.description || "")}"
              autocomplete="off"
            />
          </label>
        `,
      )
      .join("");
  }

  const platformList = qs("#settingsPlatformList");
  if (platformList) {
    const links = overview.platforms || [];
    platformList.innerHTML = links.length
      ? links
          .map(
            (link) => `
              <div class="settings-platform-row">
                <strong>${escapeHtml(link.platform)}</strong>
                <span>${escapeHtml(link.status)} · ${escapeHtml(link.connector_mode || "--")}</span>
                <small>${link.last_sync_at ? `同步于 ${escapeHtml(link.last_sync_at)}` : "尚未同步"}</small>
              </div>
            `,
          )
          .join("")
      : `<div class="empty-state">尚未连接平台。可先用演示同步，或填写 HTTP 对接地址。</div>`;
  }
}

async function reloadSettingsOverview() {
  if (!state.currentStoreId) return;
  state.settingsOverview = await fetchJson(
    `/settings/overview?store_id=${encodeURIComponent(state.currentStoreId)}`,
  );
  renderSettingsOverview();
  renderGuide();
}

async function saveStoreSettings(event) {
  event.preventDefault();
  if (!state.currentStoreId) return;
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  ["latitude", "longitude", "delivery_radius_m"].forEach((key) => {
    if (data[key] === "" || data[key] === undefined) delete data[key];
    else data[key] = Number(data[key]);
  });
  await fetchJson(`/settings/stores/${state.currentStoreId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  await loadDashboard(state.currentStoreId);
  notifySuccess("门店资料已保存");
}

async function saveMenuSettings(event) {
  event.preventDefault();
  if (!state.currentStoreId) return;
  const text = qs("#menuSettingsText")?.value || "";
  const items = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, category, price] = line.split("|").map((part) => part.trim());
      return {
        name,
        category: category || null,
        price: price ? Number(price) : null,
        is_active: true,
      };
    })
    .filter((item) => item.name);
  if (!items.length) {
    notifyInfo("请至少填写 1 个菜单商品");
    return;
  }
  await fetchJson(`/settings/stores/${state.currentStoreId}/menu`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  await loadDashboard(state.currentStoreId);
  notifySuccess("菜单已保存");
}

async function saveSystemSettings(event) {
  event.preventDefault();
  const inputs = qsa("#systemSettingsList [data-setting-key]");
  const settingsPayload = inputs.map((input) => ({
    key: input.dataset.settingKey,
    value: input.value,
  }));
  await fetchJson("/settings/system", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: settingsPayload }),
  });
  state.publicConfig = await fetchJson("/public/config").catch(() => state.publicConfig);
  await reloadSettingsOverview();
  notifySuccess("系统设置已保存");
}

async function connectSelectedPlatform({ platform, mode } = {}) {
  if (!state.currentStoreId) return;
  const selectedPlatform = platform || qs("#settingsPlatformSelect")?.value || "meituan";
  const selectedMode = mode || qs("#settingsPlatformMode")?.value || "mock";
  if (selectedMode === "mobile") {
    openCollectionModal(
      selectedPlatform === "meituan"
        ? "美团外卖"
        : selectedPlatform === "eleme"
          ? "饿了么"
          : selectedPlatform,
      selectedPlatform,
    );
    await fetchJson(`/settings/stores/${state.currentStoreId}/platforms/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform: selectedPlatform, mode: "mobile", run_daily_job: false }),
    });
    return;
  }
  const result = await fetchJson(`/settings/stores/${state.currentStoreId}/platforms/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      platform: selectedPlatform,
      mode: selectedMode,
      run_daily_job: true,
    }),
  });
  await loadDashboard(state.currentStoreId);
  notifySuccess(result.message || "平台已同步");
}

async function demoConnectAndSync() {
  try {
    await connectSelectedPlatform({ platform: "meituan", mode: "mock" });
  } catch (error) {
    notifyError(error.message);
  }
}

async function loadAssist(topic) {
  if (!state.currentStoreId) return;
  const path =
    topic === "deploy"
      ? "/settings/assist/deploy"
      : `/settings/assist/platform?store_id=${encodeURIComponent(state.currentStoreId)}`;
  const guide = await fetchJson(path);
  showAssistGuide(guide);
  scrollToSection("section-settings");
}

function bindEvents() {
  qs("#storeSelect").addEventListener("change", async (event) => {
    await loadDashboard(event.target.value);
  });

  qs("#bootstrapBtn").addEventListener("click", bootstrapWorkspace);
  qs("#refreshBtn").addEventListener("click", refreshDashboard);
  qs("#runDiagnosisBtn").addEventListener("click", runDiagnosisNow);
  qs("#runMenuDiagnosisBtn")?.addEventListener("click", runMenuDeepDiagnosis);
  qs("#rebuildGrowthBtn").addEventListener("click", rebuildGrowthPlan);
  qs("#scanCompetitionBtn").addEventListener("click", scanCompetitionNow);
  qs("#scanCompetitionWorkbenchBtn").addEventListener("click", scanCompetitionNow);
  qs("#runCollectionNowBtn").addEventListener("click", scanCompetitionNow);
  qs("#openCollectionConnectBtn").addEventListener("click", () => openCollectionModal());
  qs("#openMobileGuideBtn").addEventListener("click", () => openCollectionModal());
  qs("#generateConnectCodeBtn").addEventListener("click", generateMobileConnectCode);
  qs("#copyMobileGuideBtn").addEventListener("click", copyMobileConnectionGuide);
  qs("#chatQuickBtn")?.addEventListener("click", () => {
    if (document.body.classList.contains("view-home")) {
      openHomeChatMode();
      qs("#homeChatInput")?.focus();
      return;
    }
    scrollToSection("section-ai");
  });
  qs("#mkWorkRailToggleBtn")?.addEventListener("click", () => {
    setOpsRailCollapsed(!state.opsRailCollapsed);
  });
  qs("#mkOwnerAvatar")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openOwnerProfileModal();
  });
  qs("#ownerProfileForm")?.addEventListener("submit", saveOwnerProfile);
  qs("#ownerAvatarPickBtn")?.addEventListener("click", () => qs("#ownerAvatarFileInput")?.click());
  qs("#ownerAvatarPreview")?.addEventListener("click", () => qs("#ownerAvatarFileInput")?.click());
  qs("#ownerAvatarClearBtn")?.addEventListener("click", () => {
    state.pendingAvatarDataUrl = null;
    const preview = qs("#ownerAvatarPreview");
    const name = (qs("#ownerDisplayNameInput")?.value || "老板").trim() || "老板";
    if (preview) {
      preview.classList.remove("has-photo");
      preview.style.backgroundImage = "";
      preview.textContent = name.slice(0, 1);
    }
  });
  qs("#ownerAvatarFileInput")?.addEventListener("change", async (event) => {
    const file = event.target?.files?.[0];
    if (!file) return;
    try {
      const dataUrl = await readAvatarFileAsDataUrl(file);
      state.pendingAvatarDataUrl = dataUrl;
      const preview = qs("#ownerAvatarPreview");
      if (preview) {
        preview.classList.add("has-photo");
        preview.style.backgroundImage = `url("${dataUrl}")`;
        preview.textContent = "";
      }
    } catch (error) {
      notifyError(error.message);
    } finally {
      event.target.value = "";
    }
  });
  qs("#ownerDisplayNameInput")?.addEventListener("input", () => {
    if (state.pendingAvatarDataUrl) return;
    const preview = qs("#ownerAvatarPreview");
    const name = (qs("#ownerDisplayNameInput")?.value || "老板").trim() || "老板";
    if (preview) preview.textContent = name.slice(0, 1);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && qs("#ownerProfileModal")?.classList.contains("open")) {
      closeOwnerProfileModal();
    }
  });
  qs("#mkWorkRailReopenBtn")?.addEventListener("click", () => setOpsRailCollapsed(false));
  qs("#mkWorkRail")?.addEventListener("click", (event) => {
    const railItem = event.target.closest("[data-rail-work]");
    if (railItem) enterWorkFromRail(railItem);
  });
  qs("#mkContextRail")?.addEventListener("click", (event) => {
    const feedItem = event.target.closest("[data-rail-work]");
    if (feedItem) {
      enterWorkFromRail(feedItem);
      qs("#mkGuideArea")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  qs("#mkDecisionHost")?.addEventListener("click", (event) => {
    const opt = event.target.closest("[data-intent-fill]");
    if (!opt) return;
    qsa(".mk-decision-option, .mk-choice-card").forEach((el) => el.classList.remove("selected"));
    opt.classList.add("selected");
  });
  qs("#mkDailyBriefBtn")?.addEventListener("click", () => {
    const details = qs("#mkEvidenceDetails");
    if (details) {
      details.style.display = "block";
      details.open = true;
      details.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  qs("#mkNotifyBtn")?.addEventListener("click", () => {
    qs("#mkDecisionHost")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  qs("#commandBarMoreBtn")?.addEventListener("click", () => {
    const more = qs("#commandBarMoreChips");
    const btn = qs("#commandBarMoreBtn");
    if (!more || !btn) return;
    const open = more.hidden;
    more.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.textContent = open ? "收起 ▴" : "更多 ▾";
  });
  qs("#commandBarExamplesBtn")?.addEventListener("click", () => {
    const more = qs("#commandBarMoreChips");
    const btn = qs("#commandBarMoreBtn");
    if (more) more.hidden = false;
    if (btn) {
      btn.setAttribute("aria-expanded", "true");
      btn.textContent = "收起 ▴";
    }
    qs("#homeChatInput")?.focus();
    notifySuccess("点上方标签，或直接输入你的目标");
  });
  qs("#commandBarAttachBtn")?.addEventListener("click", () => {
    qs("#commandBarFileInput")?.click();
  });
  qs("#commandBarLiveVoiceBtn")?.addEventListener("click", toggleVoiceInput);
  qs("#commandBarAudioToolBtn")?.addEventListener("click", () => {
    qs("#commandBarAudioInput")?.click();
  });
  qs("#commandBarChips")?.addEventListener("click", (event) => {
    const upload = event.target.closest("[data-command-action='upload']");
    if (upload) {
      qs("#commandBarFileInput")?.click();
    }
  });
  qs("#commandBarFileInput")?.addEventListener("change", (event) => {
    const files = Array.from(event.target?.files || []);
    if (!files.length) return;
    ingestHomeAttachments(files, { source: "upload" });
  });
  qs("#commandBarAudioInput")?.addEventListener("change", (event) => {
    const files = Array.from(event.target?.files || []);
    if (!files.length) return;
    transcribeAudioFiles(files).catch((error) => notifyError(error.message));
  });
  qs("#commandBarMicBtn")?.addEventListener("click", toggleVoiceInput);
  qs("#toggleRightRailBtn")?.addEventListener("click", () => {
    if (!document.body.classList.contains("view-home")) {
      scrollToSection("section-overview");
    }
    setRightRailOpen(!state.rightRailOpen);
  });
  qs("#closeRightRailBtn")?.addEventListener("click", () => setRightRailOpen(false));
  qs("#sidebarToggle")?.addEventListener("click", toggleSidebar);
  qs("#sidebarBackdrop")?.addEventListener("click", () => setSidebarOpen(false));
  qs("#openHelpBtn")?.addEventListener("click", async () => {
    scrollToSection("section-ai");
    const prompt = "我是新用户，请用三步带我上手：先确认门店资料，再对接平台，最后看今天该做什么。";
    await askStoreManager(prompt);
  });
  qs("#askExamplesBtn").addEventListener("click", async () => {
    const examples = state.dashboard?.question_examples || [];
    if (examples[0]) await askStoreManager(examples[0]);
  });
  const sendHomeChat = async () => {
    const input = qs("#homeChatInput");
    const question = input?.value || "";
    if (!question.trim() && !hasPendingHomeAttachments()) return;
    await askStoreManager(question, { stayOnHome: true, attachments: state.pendingHomeAttachments });
  };
  qs("#homeChatSendBtn")?.addEventListener("click", () => {
    sendHomeChat().catch((error) => notifyError(error.message));
  });
  qs("#homeChatInput")?.addEventListener("focus", () => {
    if (document.body.classList.contains("view-home")) openHomeChatMode();
  });
  qs("#homeChatInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendHomeChat().catch((error) => notifyError(error.message));
    }
  });
  qs("#commandBarAttachments")?.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-remove-home-file]");
    if (!removeBtn) return;
    removeHomeAttachment(Number(removeBtn.dataset.removeHomeFile));
  });
  const homeDock = qs("#homeChatDock");
  if (homeDock) {
    ["dragenter", "dragover"].forEach((type) => {
      homeDock.addEventListener(type, (event) => {
        const files = Array.from(event.dataTransfer?.items || []).filter((item) => item.kind === "file");
        if (!files.length) return;
        event.preventDefault();
        setHomeChatDropState(true);
      });
    });
    homeDock.addEventListener("dragleave", (event) => {
      if (event.relatedTarget && homeDock.contains(event.relatedTarget)) return;
      setHomeChatDropState(false);
    });
    homeDock.addEventListener("drop", (event) => {
      const files = Array.from(event.dataTransfer?.files || []);
      if (!files.length) return;
      event.preventDefault();
      setHomeChatDropState(false);
      ingestHomeAttachments(files, { source: "drop" });
    });
  }
  document.addEventListener("dragover", (event) => {
    const files = Array.from(event.dataTransfer?.items || []).filter((item) => item.kind === "file");
    if (!files.length) return;
    event.preventDefault();
  });
  document.addEventListener("drop", (event) => {
    const files = Array.from(event.dataTransfer?.files || []);
    if (!files.length) return;
    if (homeDock?.contains(event.target)) return;
    event.preventDefault();
    setHomeChatDropState(false);
  });
  qs("#aiChatSendBtn")?.addEventListener("click", async () => {
    const question = qs("#aiChatInput")?.value || "";
    await askStoreManager(question);
  });
  qs("#aiChatInput")?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await askStoreManager(event.target.value || "");
    }
  });
  qs("#storeSettingsForm")?.addEventListener("submit", (event) => {
    saveStoreSettings(event).catch((error) => notifyError(error.message));
  });
  qs("#menuSettingsForm")?.addEventListener("submit", (event) => {
    saveMenuSettings(event).catch((error) => notifyError(error.message));
  });
  qs("#systemSettingsForm")?.addEventListener("submit", (event) => {
    saveSystemSettings(event).catch((error) => notifyError(error.message));
  });
  qs("#refreshSettingsBtn")?.addEventListener("click", () => {
    reloadSettingsOverview().catch((error) => notifyError(error.message));
  });
  qs("#demoConnectBtn")?.addEventListener("click", demoConnectAndSync);
  qs("#settingsConnectPlatformBtn")?.addEventListener("click", () => {
    connectSelectedPlatform().catch((error) => notifyError(error.message));
  });
  qs("#assistDeployBtn")?.addEventListener("click", () => {
    loadAssist("deploy").catch((error) => notifyError(error.message));
  });
  qs("#assistPlatformBtn")?.addEventListener("click", () => {
    loadAssist("platform").catch((error) => notifyError(error.message));
  });
  qs("#aiStorefrontDecorateBtn")?.addEventListener("click", () => {
    runStorefrontAiDecorate().catch((error) => notifyError(error.message));
  });
  qs("#aiStorefrontImageBtn")?.addEventListener("click", () => {
    runStorefrontAiImage().catch((error) => notifyError(error.message));
  });
  qs("#closeStorefrontAiBtn")?.addEventListener("click", () => {
    const panel = qs("#storefrontAiPanel");
    if (panel) panel.hidden = true;
  });
  qs("#copyStorefrontAiBtn")?.addEventListener("click", async () => {
    const plan = state.storefrontAiPlan;
    if (!plan) return;
    const text = JSON.stringify(plan, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      notifySuccess("方案已复制");
    } catch (error) {
      notifyError(`复制失败：${error.message}`);
    }
  });
  qs("#demoConfirmConnectBtn")?.addEventListener("click", () => {
    confirmActiveConnectCode().catch((error) => notifyError(error.message));
  });
  window.addEventListener("resize", () => {
    syncSidebarForViewport();
    setOpsRailCollapsed(state.opsRailCollapsed);
  });

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const assistChip = target.closest("[data-assist-prompt]");
    if (assistChip) {
      await askStoreManager(assistChip.dataset.assistPrompt || "", {
        stayOnHome: document.body.classList.contains("view-home"),
      });
      return;
    }

    const profileClose = target.closest("[data-profile-modal-close]");
    if (profileClose) {
      closeOwnerProfileModal();
      return;
    }

    const modalClose = target.closest("[data-collection-modal-close]");
    if (modalClose) {
      closeCollectionModal();
      return;
    }

    const platformConnect = target.closest("[data-platform-connect]");
    if (platformConnect) {
      openCollectionModal(
        platformConnect.dataset.platformLabel || "外卖平台",
        platformConnect.dataset.platformConnect || null,
      );
      return;
    }

    const experimentEvaluate = target.closest("[data-experiment-evaluate]");
    if (experimentEvaluate) {
      await evaluateExperiment(experimentEvaluate.dataset.experimentEvaluate, experimentEvaluate);
      return;
    }

    const eventDecision = target.closest("[data-event-decision]");
    if (eventDecision) {
      await decideOperatingEvent(
        eventDecision.dataset.eventFingerprint,
        eventDecision.dataset.eventDecision,
        eventDecision,
      );
      return;
    }

    const competitionFilter = target.closest("[data-competition-filter]");
    if (competitionFilter) {
      state.competitionFilter = competitionFilter.dataset.competitionFilter || "intensity";
      qsa("[data-competition-filter]").forEach((button) => {
        const isActive = button.dataset.competitionFilter === state.competitionFilter;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
      });
      renderCompetition();
      return;
    }

    const productApply = target.closest("[data-product-apply-index]");
    if (productApply) {
      await applyProductAction(
        Number(productApply.dataset.productApplyIndex),
        productApply.dataset.productItemId,
        productApply,
      );
      return;
    }

    const goalAction = target.closest("[data-goal-action]");
    if (goalAction) {
      const action = goalAction.dataset.goalAction;
      const goalId = goalAction.dataset.goalId;
      if (goalId) {
        try {
          const q = new URLSearchParams({ status: action });
          await fetch(`/stores/${state.currentStoreId}/goals/${goalId}?${q}`, { method: "PATCH" });
          await loadDashboard(state.currentStoreId);
          notifySuccess(action === "achieved" ? "目标已标记达成" : "目标已放弃");
        } catch (e) { notifyError(e.message); }
      }
      return;
    }

    const productSuggestion = target.closest("[data-product-suggestion-index]");
    if (productSuggestion) {
      await createProductAction(
        Number(productSuggestion.dataset.productSuggestionIndex),
        productSuggestion.dataset.productItemId,
        productSuggestion,
      );
      return;
    }

    const storefrontAction = target.closest("[data-storefront-action-index]");
    if (storefrontAction) {
      await createStorefrontAction(Number(storefrontAction.dataset.storefrontActionIndex), storefrontAction);
      return;
    }

    const matrixAction = target.closest("[data-matrix-action-index]");
    if (matrixAction) {
      await createMatrixAgentAction(
        matrixAction.dataset.matrixAgent,
        Number(matrixAction.dataset.matrixActionIndex),
        matrixAction,
        { enable: matrixAction.dataset.matrixEnable === "1" },
      );
      return;
    }

    const menuAction = target.closest("[data-menu-action]");
    if (menuAction) {
      await applyMenuAction(
        menuAction.dataset.menuAction,
        Number(menuAction.dataset.menuIndex),
        menuAction,
      );
      return;
    }

    const intentFill = target.closest("[data-intent-fill]");
    if (intentFill) {
      const text = intentFill.dataset.intentFill || intentFill.textContent || "";
      if (document.body.classList.contains("view-home")) openHomeChatMode();
      await askStoreManager(text.trim(), {
        stayOnHome: document.body.classList.contains("view-home"),
      });
      return;
    }

    // 返回首页（任务视图的返回按钮）
    const taskBack = target.closest("[data-task-back]");
    if (taskBack) {
      hideTaskView();
      return;
    }

    const explainTrace = target.closest("[data-explain-trace]");
    if (explainTrace) {
      await explainAction(explainTrace.dataset.explainTrace);
      return;
    }

    const taskAsk = target.closest("[data-task-ask]");
    if (taskAsk) {
      hideTaskView();
      await askStoreManager(taskAsk.dataset.taskAsk || "", { stayOnHome: true });
      return;
    }

    const taskRoute = target.closest("[data-task-route]");
    if (taskRoute) {
      showTaskRoute(taskRoute.dataset.taskRoute, taskRoute.dataset.taskTitle || "");
      return;
    }

    const focusIntent = target.closest("[data-focus-intent]");
    if (focusIntent) {
      if (document.body.classList.contains("view-home")) openHomeChatMode();
      const input = qs("#homeChatInput");
      if (input) {
        input.focus();
        input.placeholder = "一句话告诉我即可，例如：利润优先 / 午餐一小时100单 / 广告每天200以内你定";
      }
      return;
    }

    const nav = target.closest("[data-scroll-target]");
    if (nav) {
      scrollToSection(nav.dataset.scrollTarget);
      return;
    }

    const actionButton = target.closest("[data-recommendation-action]");
    if (actionButton) {
      await mutateRecommendation(actionButton.dataset.recommendationAction, actionButton.dataset.recommendationId);
      return;
    }

    const askButton = target.closest("[data-ask-question]");
    if (askButton) {
      await askStoreManager(askButton.dataset.askQuestion);
    }
  });
}

async function init() {
  ensureMatrixWorkspace();
  bindSidebarNav();
  bindEvents();
  initOpsRailCollapsed();
  syncSidebarForViewport();
  scrollToSection(state.activeWorkspace);
  renderChatMessages();
  state.publicConfig = await fetchJson("/public/config").catch(() => null);
  await loadStores();
  if (!state.stores.length) {
    await bootstrapWorkspace();
    return;
  }
  await loadDashboard(state.currentStoreId);
}

init().catch((error) => {
  const title = qs("#greetingTitle") || qs("#topbarTitle");
  const summary = qs("#greetingStore") || qs("#topbarSummary");
  if (title) title.textContent = "经营队列加载失败";
  if (summary) summary.textContent = error.message;
});
