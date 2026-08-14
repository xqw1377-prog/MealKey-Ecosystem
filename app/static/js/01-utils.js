/* MealKey UI — formatters, toasts, and small pure helpers */

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

function humanizeDecisionTitle(raw) {
  const text = String(raw || "").trim();
  if (!text) return "经营任务";
  const replacements = [
    ["baseline_window", "基线期"],
    ["benchmark_window", "对照期"],
    ["delta_pct", "变化"],
    ["impressions", "曝光"],
    ["CTR", "点击率"],
    ["ctr", "点击率"],
    ["CVR", "转化率"],
    ["cvr", "转化率"],
    ["GMV", "营业额"],
    ["gmv", "营业额"],
    ["SKU", "商品"],
    ["sku", "商品"],
    ["benchmark", "对照"],
    ["orders", "订单"],
    ["visits", "进店"],
  ];
  let result = text;
  replacements.forEach(([source, target]) => {
    result = result.replaceAll(source, target);
  });
  result = result.replaceAll("_", " ");
  result = result.replace(/\s+/g, " ").trim();
  result = result.replaceAll("较 ", "较").replaceAll(" 下降", "下降").replaceAll(" 上升", "上升");
  return result;
}

function compactChipLabel(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  return normalized.length > 14 ? `${normalized.slice(0, 14).trim()}…` : normalized;
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

function diagnosisMetricValue(metric, value) {
  if (value === null || value === undefined) return "--";
  if (["ctr", "cvr", "repurchase_rate", "refund_rate"].includes(metric)) return `${(Number(value) * 100).toFixed(1)}%`;
  if (["gmv", "aov"].includes(metric)) return `¥${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
  if (metric === "rating") return Number(value).toFixed(1);
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
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

function monthEnd() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}
