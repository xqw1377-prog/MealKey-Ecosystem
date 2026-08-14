/* MealKey UI — home shell, decision host, interview, rails, command bar, chat */

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

const RAIL_CARD_DRAG_MIME = "application/x-mealkey-rail-card";

function isRailCardTransfer(dataTransfer) {
  const types = Array.from(dataTransfer?.types || []);
  return types.includes(RAIL_CARD_DRAG_MIME);
}

function buildRailCardPayload(item) {
  if (!item) return null;
  const kind = String(item.dataset.railWork || "ask").trim() || "ask";
  const workThreadId = String(item.dataset.workThreadId || "").trim();
  const title =
    item.querySelector("strong")?.textContent?.trim() ||
    item.getAttribute("aria-label") ||
    item.textContent?.trim() ||
    "经营事项";
  const prompt = String(item.dataset.railPrompt || "").trim();
  return {
    kind,
    title,
    work_thread_id: workThreadId || "",
    prompt: prompt || `关于「${title}」，现在我该怎么处理？`,
  };
}

function startRailCardDrag(item, dataTransfer) {
  const payload = buildRailCardPayload(item);
  if (!payload || !dataTransfer) return;
  dataTransfer.effectAllowed = "copy";
  dataTransfer.setData(RAIL_CARD_DRAG_MIME, JSON.stringify(payload));
  dataTransfer.setData("text/plain", payload.prompt || payload.title);
}

function readRailCardTransfer(dataTransfer) {
  if (!isRailCardTransfer(dataTransfer)) return null;
  try {
    const raw = dataTransfer.getData(RAIL_CARD_DRAG_MIME);
    return raw ? JSON.parse(raw) : null;
  } catch (_error) {
    return null;
  }
}

function ingestRailCardToChat(payload, { replace = false, source = "drag" } = {}) {
  const text = String(payload?.prompt || "").trim();
  if (!text) return;
  state.pendingWorkThreadId = String(payload?.work_thread_id || "").trim() || state.pendingWorkThreadId || null;
  if (typeof closeMobileSheets === "function") closeMobileSheets();
  document.body.classList.add("view-home");
  document.body.classList.remove("view-module", "workspace-focus");
  openHomeChatMode();
  appendHomeInputText(text, { replace: replace || !qs("#homeChatInput")?.value.trim() });
  notifySuccess(
    source === "drag" ? "已把卡片内容带到对话栏，补一句需求后可直接发送" : "我已把这条经营事项带到对话栏",
  );
}

function currentWorkThreadId() {
  const pending = String(state.pendingWorkThreadId || "").trim();
  if (pending) return pending;
  const focus = currentNeedCard?.() || null;
  const focusThread = String(focus?.work_thread_id || focus?.loop_id || "").trim();
  if (focusThread) return focusThread;
  const loopThread = String(currentLoop?.()?.work_thread_id || "").trim();
  if (loopThread) return loopThread;
  const active = String(state.runtimeWorkspace?.center?.active_thread_id || "").trim();
  return active || "";
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

function renderHomeShell() {
  mergeRuntimeIntoBrief();
  applyWorkspaceMode(state.activeWorkspace || "section-overview");
  renderStoreSelector();
  renderTopbar();
  renderOpsQueue();
  if (typeof renderStoreProfileCard === "function") renderStoreProfileCard();
  applyOwnerProfileUI(state.ownerProfile || state.settingsOverview?.owner);
  if (typeof renderWalletBanner === "function") renderWalletBanner();
  if (typeof renderAdsSummaryPanel === "function") renderAdsSummaryPanel();
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
  if (!select) return;
  select.innerHTML = state.stores
    .map((store) => {
      const meta = [store.city, store.category].filter(Boolean).join(" · ");
      const label = meta ? `${store.name} · ${meta}` : store.name;
      return `<option value="${store.id}" ${store.id === state.currentStoreId ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("");
  const bootstrapBtn = qs("#bootstrapBtn");
  if (bootstrapBtn) bootstrapBtn.style.display = state.stores.length ? "none" : "";
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
      if (action.kind === "upload_cost") {
        return `<button class="action-button ${escapeHtml(className || "primary")}" type="button" data-cost-upload="1">${escapeHtml(
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
      ${card.recommendation_id && (card.queue_bucket === "working" || card.arbiter_state === "auto_do") ? `<div class="ops-queue-actions" style="margin-top:4px;"><button class="rec-preview-btn" data-rec-preview="${escapeHtml(card.recommendation_id)}">预览变更</button></div>` : ""}
      ${card.recommendation_id && card.queue_bucket === "result" ? `<div class="ops-queue-actions" style="margin-top:4px;"><button class="rec-rollback-btn" data-rec-rollback="${escapeHtml(card.recommendation_id)}">回滚</button></div>` : ""}
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
  if (!card) return false;
  const id = String(card.id || "");
  if (id.startsWith("understanding:")) return true;
  if (card.trigger === "understanding") return true;
  if (card.interrupt_reason === "understanding" && String(card.meta || "").includes("understanding")) {
    return true;
  }
  return card.arbiter_state === "need_input" && String(card.meta || "").includes("understanding");
}

function interviewKind(card) {
  return interviewKeyFromCard(card);
}

function interviewGapKeys() {
  const u = state.understanding || {};
  const gaps = Array.isArray(u.open_gaps) ? u.open_gaps.filter(Boolean) : [];
  if (gaps.length) return gaps;
  const mapped = Array.isArray(u.mos_gap_keys) ? u.mos_gap_keys.filter(Boolean) : [];
  if (mapped.length) return mapped;
  return [];
}

function interviewKeyFromCard(card) {
  const id = String(card?.id || "");
  const matched = id.match(/^(?:understanding:|mue:)(.+)$/);
  const fromId = matched ? String(matched[1] || "").trim() : "";
  if (fromId && fromId !== "mue_gap" && fromId !== "mue_nl_setting" && fromId !== "mue_ready") {
    return fromId;
  }
  const fromGaps = interviewGapKeys()[0];
  if (fromGaps) return fromGaps;
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
    { label: "帮我平衡", fill: "你帮我平衡" },
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
        `<button class="mk-interview-chip" type="button" data-interview-key="${escapeHtml(
          interviewKind(card) || "",
        )}" data-intent-fill="${escapeHtml(c.fill)}">${escapeHtml(c.label)}</button>`,
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

function runtimeWorkspacePanels() {
  return state.runtimeWorkspace || null;
}

function runtimeBridgeMeta() {
  return runtimeWorkspacePanels()?.meta?.runtime_bridge || {};
}

function currentRuntimeGuide() {
  return runtimeWorkspacePanels()?.center?.guide || null;
}

function currentDecisionFlow() {
  const center = runtimeWorkspacePanels()?.center || {};
  return center.decision_flow || currentRuntimeGuide()?.decision_flow || null;
}

function runtimeGuideChoices(guide) {
  return Array.isArray(guide?.choices) ? guide.choices : [];
}

function runtimeGuideToCard(guide) {
  if (!guide) return null;
  const flow = guide.decision_flow || currentDecisionFlow() || null;
  const now = flow?.now || {};
  const humanGuide = ["QUESTION", "APPROVAL", "FILE_REQUEST"].includes(guide.type);
  const choices = runtimeGuideChoices(guide).map((choice) => ({
    label: choice.label || choice.title || choice.id || "选项",
    fill: choice.prompt || choice.value || choice.label || choice.id || "",
  }));
  const actions = Array.isArray(guide.actions) && guide.actions.length
    ? guide.actions
    : Array.isArray(now.actions)
      ? now.actions
      : [];
  const titleSource = humanGuide ? (guide.title || now.title) : (now.title || guide.title);
  const promptSource = humanGuide ? (guide.prompt || now.why_now) : (now.why_now || guide.prompt);
  return {
    id: guide.id || now.id || guide.guide_id || "runtime_guide",
    guide_type: guide.type || "INFO",
    title: titleSource || "",
    guide_title: guide.title || now.title || "",
    guide_prompt: promptSource || "",
    guide_explanation: guide.explanation || guide.clock_why || flow?.clock_why || "",
    guide_choices: choices,
    guide_allow_free_text: Boolean(guide.allow_free_text),
    guide_allow_file: Boolean(guide.allow_file),
    guide_request_label: guide.request_label || guide.phase_label || "",
    guide_status: guide.status || guide.phase_label || "",
    guide_cta_label: guide.cta_label || "",
    interrupt_reason: guide.trigger_reason?.toLowerCase?.() || "time",
    arbiter_state:
      guide.type === "QUESTION"
        ? "need_input"
        : guide.type === "APPROVAL"
          ? "confirm"
          : "report_result",
    meta: guide.type || "",
    why_now: guide.clock_why || now.why_now || guide.explanation || "",
    if_skip: guide.if_skip || now.if_skip || "",
    clock_why: guide.clock_why || flow?.clock_why || "",
    phase_label: guide.phase_label || flow?.phase_label || "",
    decision_flow: flow,
    ai_judgment: guide.summary || now.ai_already_did || "",
    actions,
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

function workItemKey(item) {
  if (!item) return "";
  return String(item.id || item.source_card_id || item.source_odo_id || `${item.slot || ""}:${item.title || ""}`).trim();
}

function findQueueCard(id) {
  const needle = String(id || "").trim();
  if (!needle) return null;
  const left = runtimeWorkspacePanels()?.left || {};
  const queue = state.managerBrief?.ops_queue || {};
  const buckets = [
    left.need_you,
    left.active,
    left.waiting,
    left.completed,
    left.opportunities,
    queue.need_you,
    queue.working,
    queue.results,
    queue.opportunities,
    queue.threads,
  ];
  for (const bucket of buckets) {
    if (!Array.isArray(bucket)) continue;
    const found = bucket.find(
      (card) =>
        card &&
        (card.id === needle ||
          card.source_card_id === needle ||
          card.source_odo_id === needle),
    );
    if (found) return found;
  }
  return null;
}

function allWorkSources() {
  const flow = currentDecisionFlow() || {};
  const left = runtimeWorkspacePanels()?.left || {};
  const queue = state.managerBrief?.ops_queue || {};
  const feed = runtimeFeedItems().length ? runtimeFeedItems() : state.managerBrief?.proactive_feed || [];
  const events = state.operatingEvents?.events || [];
  const list = [];
  const push = (slot, kind, source) => {
    if (!source) return;
    const title = source.title || source.summary || source.name || "";
    if (!title && !source.id) return;
    list.push({
      slot,
      kind,
      source,
      id: workItemKey({ id: source.id || source.source_card_id || source.source_odo_id, slot, title }),
      title,
    });
  };
  const loop = currentLoop();
  if (loop?.id) {
    push(loop.left?.slot || (loop.waiting ? "waiting" : "need"), "loop", {
      id: loop.id,
      title: loop.title,
      summary: loop.finding,
      finding: loop.finding,
      decision: loop.judgment,
      meta: loop.left?.meta || "",
    });
  }
  if (flow.now?.title) push("flow-now", "flow", flow.now);
  if (flow.next?.title) push("flow-next", "flow", flow.next);
  if (flow.later?.title) push("flow-later", "flow", flow.later);
  (left.need_you || queue.need_you || []).forEach((item) =>
    push("need", item.kind === "event" ? "event" : "need", item),
  );
  (left.active || queue.working || []).forEach((item) => push("active", "thread", item));
  (left.waiting || []).forEach((item) => push("waiting", "waiting", item));
  (left.completed || queue.results || []).forEach((item) => push("done", "done", item));
  (queue.threads || []).forEach((item) => push("active", "thread", item));
  (Array.isArray(feed) ? feed : []).forEach((item) => push("feed", "event", item));
  (Array.isArray(events) ? events : []).forEach((item) => push("event", "event", item));
  return list;
}

function titlesMatch(a, b) {
  const left = humanizeDecisionTitle(a || "");
  const right = humanizeDecisionTitle(b || "");
  return Boolean(left) && left === right;
}

function cardFromWorkSource(entry, fallback = {}) {
  if (!entry?.source && !fallback.title) return null;
  const src = entry?.source || {};
  const slot = entry?.slot || fallback.slot || "active";
  const kind = entry?.kind || fallback.kind || "thread";
  const queued = findQueueCard(src.id || src.source_card_id || fallback.id) || {};
  const merged = { ...queued, ...src };
  const title = merged.title || merged.summary || fallback.title || "经营事项";
  const key = workItemKey({
    id: merged.id || src.source_odo_id || fallback.id,
    slot,
    title,
  });
  const base = {
    ...merged,
    id: merged.id || key,
    title,
    why_now: merged.why_now || merged.summary || merged.finding || merged.detail || fallback.why || "",
    ai_judgment:
      merged.ai_judgment ||
      merged.decision ||
      merged.estimated_impact ||
      merged.finding ||
      merged.detail ||
      "",
    business_impact: merged.business_impact || merged.estimated_impact || "",
    meta: humanizeDecisionTitle(merged.meta || merged.domain_label || merged.label || fallback.meta || ""),
    actions: Array.isArray(merged.actions) ? merged.actions : [],
    focus_kind: kind,
    focus_slot: slot,
    focus_key: key,
  };
  if (kind === "flow") {
    base.decision_flow = currentDecisionFlow();
    base.guide_prompt = merged.why_now || merged.why || base.why_now;
  }
  return base;
}

function resolveFocusedWorkCard() {
  const key = String(state.focusedWorkKey || "").trim();
  if (!key) return null;
  const slot = String(state.focusedWorkSlot || "").trim();
  const sources = allWorkSources();
  const idMatch = (item) => item.id === key || item.source?.id === key || item.source?.source_card_id === key;
  const byIdAndSlot = slot ? sources.find((item) => idMatch(item) && item.slot === slot) : null;
  if (byIdAndSlot) return cardFromWorkSource(byIdAndSlot);
  const byId = sources.find(idMatch);
  if (byId) return cardFromWorkSource(byId);
  const bySlotTitle = sources.find(
    (item) => item.slot === slot && (item.title === key || titlesMatch(item.title, key)),
  );
  if (bySlotTitle) return cardFromWorkSource(bySlotTitle);
  const [keySlot, ...rest] = key.split(":");
  const title = rest.join(":");
  const byComposite = sources.find(
    (item) => item.slot === keySlot && (item.title === title || titlesMatch(item.title, title)),
  );
  if (byComposite) return cardFromWorkSource(byComposite);
  const byTitle = sources.find((item) => item.title === key || titlesMatch(item.title, key));
  if (byTitle) return cardFromWorkSource(byTitle);
  return null;
}

function currentNeedCard() {
  const understanding = state.understanding || {};
  const needYou = state.managerBrief?.ops_queue?.need_you || [];
  const needUnderstanding = needYou.find((item) => isUnderstandingCard(item)) || null;
  const forceUnderstanding =
    document.body.classList.contains("interviewing") ||
    document.body.classList.contains("path-exclusive") ||
    understanding.system_mode === "safe" ||
    understanding.mos_satisfied === false ||
    (Array.isArray(understanding.mos_blocking_fields) && understanding.mos_blocking_fields.length > 0);
  /* Safe Mode / 未满足 MOS：确认题优先于 runtime INFO，避免点了选项却不进访谈 */
  if (forceUnderstanding) {
    return needUnderstanding || localUnderstandingCard();
  }
  const focused = resolveFocusedWorkCard();
  if (focused) return focused;
  if (state.focusOverrideCard) return state.focusOverrideCard;
  const runtimeGuide = currentRuntimeGuide();
  if (runtimeGuide) return runtimeGuideToCard(runtimeGuide);
  return (
    [...needYou].sort((a, b) => {
      const aw = isUnderstandingCard(a) ? 0 : 1;
      const bw = isUnderstandingCard(b) ? 0 : 1;
      return aw - bw;
    })[0] || null
  );
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
  const interviewing =
    isUnderstandingCard(card) ||
    card?.guide_type === "QUESTION" ||
    card?.guide_type === "FILE_REQUEST";
  if (input) {
    input.placeholder = interviewing
      ? "也可以直接告诉我，例如：利润优先"
      : "直接告诉 MealKey 你的目标或把资料发给我";
  }
  // 访谈态选项已在中栏 2×2 展示，底部不再重复 chip
  if (interviewing && (card?.guide_choices?.length || isUnderstandingCard(card))) {
    host.hidden = true;
    host.innerHTML = "";
    return;
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
  if (!key) return "待确认";
  if (GAP_LABELS[key]) return GAP_LABELS[key];
  // 避免把 key_constraint 这类原始字段名直接甩给老板
  if (/^[a-z0-9_]+$/i.test(key)) return "关键经营信息未确认";
  return key;
}

function humanizeBlockerKeys(blockers) {
  return Array.from(new Set((blockers || []).map((b) => guideBlockerLabel(b)).filter(Boolean)));
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
    const gaps = interviewGapKeys();
    const blockers = gaps.length ? gaps : Array.from(new Set(understanding.mos_blocking_fields || []));
    const mapping = {
      priority_style: "经营原则",
      lunch_capacity: "经营边界",
      profit_floor: "经营边界",
      hero_item_floor_price: "经营边界",
      ads_daily_budget: "经营边界",
      weekend_strategy: "经营原则",
      competitor_focus: "经营原则",
      low_risk_auto: "自动权限",
      risk_boundary: "自动权限",
      key_constraint: "经营边界",
    };
    const currentKind = interviewKeyFromCard(card);
    const currentLabel = mapping[currentKind] || guideBlockerLabel(blockers[0]);
    const donePrinciple =
      !blockers.includes("priority_style") &&
      !blockers.includes("weekend_strategy") &&
      !blockers.includes("competitor_focus");
    const doneBoundary =
      !blockers.includes("profit_floor") &&
      !blockers.includes("hero_item_floor_price") &&
      !blockers.includes("ads_daily_budget") &&
      !blockers.includes("lunch_capacity") &&
      !blockers.includes("key_constraint");
    const doneAutomation = !blockers.includes("low_risk_auto") && !blockers.includes("risk_boundary");
    const platformDone =
      platformConnected() || !(understanding.mos_blocking_fields || []).includes("platform_connected");
    return {
      title: "接管这家店",
      steps: [
        guideStepState("平台数据", platformDone ? "done" : "now"),
        guideStepState("经营原则", currentLabel === "经营原则" ? "now" : donePrinciple ? "done" : "next"),
        guideStepState("经营边界", currentLabel === "经营边界" ? "now" : doneBoundary ? "done" : "next"),
        guideStepState("自动权限", currentLabel === "自动权限" ? "now" : doneAutomation ? "done" : "next"),
      ],
      foot: blockers.length ? `还有 ${blockers.length} 项待确认，完成这些我就开始经营。` : "完成这些，我就开始经营。",
    };
  }

  const flow = card?.decision_flow || currentDecisionFlow();
  if (flow?.now?.title) {
    const short = (text) => {
      const value = String(text || "").trim();
      return value.length > 10 ? `${value.slice(0, 10)}…` : value;
    };
    return {
      title: flow.phase_label || "今日决策流",
      steps: [
        guideStepState(short(flow.now.title) || "现在", "now"),
        flow.next?.title ? guideStepState(short(flow.next.title), "next") : null,
        flow.later?.title ? guideStepState(short(flow.later.title), "next") : null,
      ].filter(Boolean),
      foot: flow.clock_why || "",
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

  // Safe Mode：路径入口（点进去继续确认，不是静态提示）
  const safeBanner = qs("#mkSafeModeBanner");
  if (safeBanner) {
    if (isUnderstandingCard(card)) {
      safeBanner.hidden = true;
      safeBanner.style.display = "none";
    } else if (understanding.system_mode === "safe" || understanding.mos_satisfied === false) {
      const blockers = understanding.mos_blocking_fields || [];
      const blockerLabels = humanizeBlockerKeys(blockers);
      const count = Math.max(blockers.length || 0, blockerLabels.length || 0, 1);
      safeBanner.hidden = false;
      safeBanner.style.display = "";
      safeBanner.classList.add("is-path");
      safeBanner.setAttribute("aria-label", `进入确认，还差 ${count} 项`);
      safeBanner.innerHTML = `
        <span class="mk-safe-mode-copy">
          <strong>Safe Mode · 还差 ${count} 项确认</strong>
          <span>${escapeHtml(blockerLabels.slice(0, 2).join(" / ") || "关键经营信息未确认")}</span>
          <em>利润相关动作暂不自动执行</em>
        </span>
        <span class="mk-safe-mode-cta">去确认 <i aria-hidden="true">›</i></span>`;
    } else {
      safeBanner.hidden = true;
      safeBanner.style.display = "none";
      safeBanner.classList.remove("is-path");
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

function currentExecutionPack(card) {
  return card?.execution_pack || card?.decision_flow?.now?.execution_pack || null;
}

function renderExecutionPackHtml(pack, options = {}) {
  if (!pack || !pack.copy_text) return "";
  const writeable = Boolean(options.writeable);
  const writeback = pack.writeback || {};
  const pasteOnly = writeback.mode === "human_paste" || options.pasteOnly;
  const steps = Array.isArray(pack.steps)
    ? pack.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")
    : "";
  const failLine =
    writeback.ok === false && writeback.error
      ? `<p class="mk-guide-watch">上次没写上：${escapeHtml(String(writeback.error))}。可以再试一次，或自己改完点「已修改」。</p>`
      : writeback.mode === "human_paste"
        ? `<p class="mk-guide-watch">${escapeHtml(writeback.summary || "请先复制到美团。改完点「已修改」。现在还没写到平台。")}</p>`
        : "";
  return `
    <div class="mk-exec-pack">
      <p class="mk-exec-kicker">${escapeHtml(pack.title || "执行包")}</p>
      <pre class="mk-exec-copy">${escapeHtml(pack.copy_text)}</pre>
      ${steps ? `<ol class="mk-exec-steps">${steps}</ol>` : ""}
      ${pack.watch ? `<p class="mk-guide-watch">${escapeHtml(pack.watch)}</p>` : ""}
      ${pack.how_to_use ? `<p class="mk-support">${escapeHtml(pack.how_to_use)}</p>` : ""}
      ${failLine}
      ${
        writeable && !pasteOnly
          ? ""
          : `<div class="mk-cta-row">
        <button type="button" class="action-button ${pasteOnly ? "primary" : "ghost"}" data-copy-text="${encodeURIComponent(
          pack.copy_text,
        )}">复制去平台改</button>
      </div>`
      }
    </div>`;
}

function threadStatusLabel(status, fallback = "") {
  const key = String(status || "").trim().toUpperCase();
  return (
    {
      DISCOVERED: "新发现",
      ANALYZING: "分析中",
      NEED_INFORMATION: "等你补信息",
      NEED_APPROVAL: "需要你确认",
      READY_TO_EXECUTE: "待执行",
      APPROVED: "已确认",
      EXECUTING: "正在执行",
      OBSERVING: "观察中",
      WAITING_RESULT: "结果出来了",
      COMPLETED: "已完成",
      NO_EFFECT: "已归档",
      CANCELLED: "这次未执行",
      FAILED: "执行失败",
    }[key] || fallback
  );
}

function threadStatusPriority(status, slot = "") {
  const key = String(status || "").trim().toUpperCase();
  const group = String(slot || "").trim();
  const table =
    group === "active"
      ? { EXECUTING: 0, APPROVED: 1, ANALYZING: 2, OBSERVING: 3 }
      : group === "waiting"
        ? { OBSERVING: 0, WAITING_RESULT: 1 }
        : group === "done"
          ? { COMPLETED: 0, NO_EFFECT: 1, CANCELLED: 2, FAILED: 3 }
          : { NEED_APPROVAL: 0, NEED_INFORMATION: 1, READY_TO_EXECUTE: 2, DISCOVERED: 3 };
  return Number.isInteger(table[key]) ? table[key] : 99;
}

function sortWorkItems(items, slot = "") {
  return [...(items || [])].sort((a, b) => {
    const diff = threadStatusPriority(a?.thread_status, slot) - threadStatusPriority(b?.thread_status, slot);
    if (diff !== 0) return diff;
    const at = String(a?.thread_status_updated_at || a?.updated_at || a?.occurred_at || "");
    const bt = String(b?.thread_status_updated_at || b?.updated_at || b?.occurred_at || "");
    if (at && bt && at !== bt) return bt.localeCompare(at);
    return String(a?.title || a?.name || "").localeCompare(String(b?.title || b?.name || ""), "zh-CN");
  });
}

function currentLoop() {
  return state.runtimeWorkspace?.center?.loop || null;
}

function loopFocusIds(loop) {
  if (!loop) return [];
  return [loop.id, loop.source_card_id, loop.source_event_id].filter(Boolean).map(String);
}

function isCurrentLoopFocus(loop) {
  if (!loop) return false;
  const slot = String(state.focusedWorkSlot || "").trim();
  if (slot === "flow-next" || slot === "flow-later") return false;
  const key = String(state.focusedWorkKey || "").trim();
  if (!key) return true;
  if (loopFocusIds(loop).includes(key)) return true;
  if (slot === "flow-now") return true;
  return false;
}

function renderLoopHost(loop) {
  if (!loop) return "";
  const threadStatus = String(loop.thread_status || "").trim().toUpperCase();
  const waiting = Boolean(loop.waiting) || threadStatus === "OBSERVING";
  const resultReady =
    Boolean(loop.result_ready) ||
    loop.status === "result_ready" ||
    threadStatus === "WAITING_RESULT" ||
    threadStatus === "COMPLETED" ||
    threadStatus === "NO_EFFECT";
  const pack = loop.execution_pack || {};
  const title = humanizeDecisionTitle(loop.title || "当前经营事项");
  const finding = humanizeDecisionTitle(loop.finding || "");
  const judgment = humanizeDecisionTitle(loop.judgment || pack.current_problem || "");
  const metric = humanizeDecisionTitle(loop.success_metric || pack.success_metric || "点击率");
  const target = loop.success_target || pack.success_target || "";
  const guard = humanizeDecisionTitle(loop.guardrail || pack.guardrail || "");
  const resultLine = humanizeDecisionTitle(loop.result_summary || "");
  if (resultReady) {
    return `
      <div class="mk-guide need">
        <div class="mk-ai-intro">
          <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
          <p><strong>我回来了。</strong><span>这件事的观察窗到了，结果会改变我下次怎么排动作。</span></p>
        </div>
        <div class="mk-ai-status"><span>结果出来了</span></div>
        <h2 class="mk-question">${escapeHtml(title)}</h2>
        <p class="mk-support">${escapeHtml(resultLine || `成功标准：${metric}${target ? ` ${target}` : ""}。护栏：${guard || "不要叠改其他变量"}。`)}</p>
        <div class="mk-cta-row">
          <button type="button" class="action-button primary" data-loop-ack="${escapeHtml(loop.id)}">
            <strong>知道了</strong><span>这条闭环先记下</span>
          </button>
          <button type="button" class="action-button ghost" data-loop-share="${escapeHtml(loop.id)}">
            <strong>分享给同行</strong><span>结果卡 · 测一下我的店</span>
          </button>
        </div>
      </div>`;
  }
  if (waiting) {
    const until = loop.observe_until
      ? new Date(loop.observe_until).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : `${loop.observe_hours || 48} 小时后`;
    const writeback = (loop.execution_pack || {}).writeback || {};
    const viaPlatform =
      String(loop.executor || "") === "PLATFORM" &&
      String(writeback.mode || "") !== "human_paste" &&
      writeback.platform_changed !== false;
    const waitingLead = viaPlatform
      ? writeback.summary || "我已经改到平台并读回确认。正在观察窗口里等结果，到期会回来告诉你有没有效。"
      : "我在观察窗口里等结果，到期会回来告诉你有没有效。";
    return `
      <div class="mk-guide clear">
        <div class="mk-ai-intro">
          <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
          <p><strong>这件事已经记下执行。</strong><span>${escapeHtml(waitingLead)}</span></p>
        </div>
        <div class="mk-ai-status quiet"><i></i><span>等待结果 · ${escapeHtml(String(loop.observe_hours || 48))} 小时</span></div>
        <h2 class="mk-question">${escapeHtml(title)}</h2>
        <p class="mk-support">成功标准：${escapeHtml(metric)}${target ? ` ${escapeHtml(target)}` : ""}。护栏：${escapeHtml(guard || "不要叠改其他变量")}。</p>
        <p class="mk-guide-watch">预计 ${escapeHtml(until)} 回来看结果。在此之前不要对同一商品再改第二下。</p>
      </div>`;
  }
  const pasteOnly =
    String(loop.writeback_mode || pack.writeback?.mode || "") === "human_paste";
  const writeable = Boolean(loop.platform_writeable) && !pasteOnly;
  const humanTask = Boolean(loop.human_task);
  const actionType = String(loop.action_type || pack.action_type || "");
  const appealTask = actionType === "appeal_pack";
  const writeCta =
    actionType === "reply_ordinary_reviews"
      ? { strong: "帮我回好评", span: "写回并读回确认" }
      : appealTask
        ? { strong: "帮我提交申诉", span: "提交并读回工单号" }
      : { strong: "帮我改到平台", span: "写回并读回确认" };
  if (humanTask) {
    const who = loop.assignee_name || "店长";
    const needed = loop.evidence_needed || pack.evidence_needed || "现场照片或处理说明";
    const hasEvidence = Boolean(loop.has_evidence);
    const taskUrl = loop.task_url ? `${location.origin}${loop.task_url}` : "";
    const evidenceRows = (loop.evidence || [])
      .map((row) => `<li>${escapeHtml(row.note || "现场照片")} · ${escapeHtml((row.at || "").slice(0, 16))}</li>`)
      .join("");
    return `
    <div class="mk-guide need">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p><strong>这件事要门店做完。</strong><span>已派给${escapeHtml(who)}。没有证据不能算做完。</span></p>
      </div>
      <div class="mk-ai-status"><span>${hasEvidence ? "证据已交，可以确认做完" : "等待门店交证据"}</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${finding ? `<p class="mk-support">${escapeHtml(finding)}</p>` : ""}
      <p class="mk-support">必须提交：${escapeHtml(needed)}${loop.due_at ? ` · 截止 ${escapeHtml(String(loop.due_at).slice(0, 16))}` : ""}</p>
      ${evidenceRows ? `<ul class="mk-evidence-list">${evidenceRows}</ul>` : ""}
      ${taskUrl ? `<p class="mk-guide-watch">门店任务页：${escapeHtml(taskUrl)}</p>` : `<p class="mk-guide-watch">还没设置店长时，你也可以在这里代交证据。</p>`}
      <label class="mk-evidence-note">处理说明<textarea id="mkLoopEvidenceNote" rows="2" placeholder="例如：午班已补牛肉、打包改用防漏袋"></textarea></label>
      <div class="mk-cta-row">
        <button type="button" class="action-button ghost" data-loop-evidence="${escapeHtml(loop.id)}">
          <strong>先交证据</strong><span>照片或说明</span>
        </button>
        <button type="button" class="action-button ${hasEvidence ? "primary" : "ghost"}" data-loop-executed="${escapeHtml(loop.id)}" ${hasEvidence ? "" : ""}>
          <strong>门店已做完</strong><span>${hasEvidence ? "进入观察窗" : "没有证据点了也会拦住"}</span>
        </button>
        <button type="button" class="action-button ghost" data-loop-skip="${escapeHtml(loop.id)}">
          <strong>还没做</strong><span>这一次先不改</span>
        </button>
      </div>
    </div>`;
  }
  if (appealTask) {
    const needed = loop.evidence_needed || pack.evidence_needed || "订单记录、聊天截图、现场说明";
    const hasEvidence = Boolean(loop.has_evidence);
    const evidenceRows = (loop.evidence || [])
      .map((row) => `<li>${escapeHtml(row.note || "申诉证据")} · ${escapeHtml((row.at || "").slice(0, 16))}</li>`)
      .join("");
    return `
    <div class="mk-guide need">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p><strong>这件事先补齐申诉证据。</strong><span>${escapeHtml(
          judgment || "证据齐了我就能帮你提交申诉，并读回工单号。",
        )}</span></p>
      </div>
      <div class="mk-ai-status"><span>${hasEvidence ? "证据已就位，可以提交申诉" : "还差申诉证据"}</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${finding ? `<p class="mk-support">${escapeHtml(finding)}</p>` : ""}
      ${renderExecutionPackHtml(pack, { writeable, pasteOnly })}
      <p class="mk-support">必须提交：${escapeHtml(needed)}。没有证据不要硬申。</p>
      ${evidenceRows ? `<ul class="mk-evidence-list">${evidenceRows}</ul>` : ""}
      <label class="mk-evidence-note">申诉说明<textarea id="mkLoopEvidenceNote" rows="2" placeholder="例如：已核对订单与聊天记录，客诉内容与实际不符"></textarea></label>
      <div class="mk-cta-row">
        <button type="button" class="action-button ghost" data-loop-evidence="${escapeHtml(loop.id)}">
          <strong>先记证据</strong><span>订单/聊天/现场说明</span>
        </button>
        <button type="button" class="action-button ${hasEvidence ? "primary" : "ghost"}" data-loop-execute-platform="${escapeHtml(loop.id)}">
          <strong>${escapeHtml(writeCta.strong)}</strong><span>${escapeHtml(hasEvidence ? writeCta.span : "先补证据再提交")}</span>
        </button>
        <button type="button" class="action-button ghost" data-loop-skip="${escapeHtml(loop.id)}">
          <strong>还没做</strong><span>这一次先不提</span>
        </button>
      </div>
    </div>`;
  }
  return `
    <div class="mk-guide need">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p><strong>现在只做这一件事。</strong><span>${escapeHtml(
          pasteOnly
            ? judgment || "方案已经准备好。请复制到美团商家端改完，再点「已修改」。现在还没写到平台。"
            : writeable
            ? judgment || "方案已经准备好。确认后我会改到平台，读回成功再进入观察。"
            : judgment || "方案已经准备好，你在平台改完后回来告诉我。",
        )}</span></p>
      </div>
      <div class="mk-ai-status"><span>需要你确认执行</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${finding ? `<p class="mk-support">${escapeHtml(finding)}</p>` : ""}
      ${renderExecutionPackHtml(pack, { writeable, pasteOnly })}
      <div class="mk-cta-row">
        ${
          writeable
            ? `<button type="button" class="action-button primary" data-loop-execute-platform="${escapeHtml(loop.id)}">
          <strong>${escapeHtml(writeCta.strong)}</strong><span>${escapeHtml(writeCta.span)}</span>
        </button>`
            : ""
        }
        <button type="button" class="action-button ${writeable ? "ghost" : "primary"}" data-loop-executed="${escapeHtml(loop.id)}">
          <strong>已修改</strong><span>${writeable ? "我自己已经改完了" : "我已经在平台做完了"}</span>
        </button>
        <button type="button" class="action-button ghost" data-loop-skip="${escapeHtml(loop.id)}">
          <strong>还没做</strong><span>这一次先不改</span>
        </button>
      </div>
    </div>`;
}

function renderDecisionFlowHost(card) {
  const loop = currentLoop();
  const slot = card?.focus_slot || "flow-now";
  const isNow = slot !== "flow-next" && slot !== "flow-later";
  if (loop && isNow) {
    return renderLoopHost(loop);
  }
  const flow = card?.decision_flow || currentDecisionFlow() || {};
  const now = flow.now || {};
  const next = flow.next || {};
  const later = flow.later || {};
  const step = slot === "flow-next" ? next : slot === "flow-later" ? later : now;
  const protect = Boolean(flow.protect_mode);
  const quiet = Boolean(flow.quiet);
  const owner = isNow
    ? now.owner || (card?.guide_type === "APPROVAL" || card?.guide_type === "QUESTION" ? "boss" : "ai")
    : step.owner || "ai";
  const introLead = !isNow
    ? slot === "flow-next"
      ? "这是下一窗要做的事。"
      : "这是再之后的安排。"
    : quiet
      ? "休息时段，我不打扰你。"
      : protect
        ? "高峰保护中，我只盯异常。"
        : owner === "boss"
          ? "现在有一件事需要你拍板。"
          : "这件事我先自己做。";
  const introBody = !isNow
    ? step.when
      ? `计划在${step.when}处理。现在点进来，先把这件事看清楚。`
      : "还没到窗口，先让你看内容，不会和现在这张卡混在一起。"
    : flow.clock_why || card?.clock_why || "到点了我再叫你。";
  const title = humanizeDecisionTitle(card?.title || step.title || now.title || "我继续盯着。");
  const whyNow = isNow
    ? card?.guide_prompt || step.why_now || now.why_now || ""
    : step.why || step.why_now || `到「${step.when || "下一窗"}」再处理「${step.title || title}」。`;
  const ifSkip = isNow ? now.if_skip || card?.if_skip || "" : "";
  const showSkip = ifSkip && !/不用做|不需要你做战略|不用拍板/.test(ifSkip);
  const autoDoing = Array.isArray(flow.auto_doing) ? flow.auto_doing.slice(0, 3) : [];
  const actions = isNow
    ? Array.isArray(now.actions) && now.actions.length
      ? now.actions
      : card?.actions || []
    : Array.isArray(step.actions)
      ? step.actions
      : [];
  const primaryAction = pickPrimaryAction(actions);
  const secondaryAction = pickSecondaryAction(actions, primaryAction);
  const choices = isNow && Array.isArray(card?.guide_choices) ? card.guide_choices : [];
  const choiceHtml =
    !primaryAction && choices.length
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
  const askLater = `关于「${title}」，${step.when || "到点了"}该怎么做？`;
  const ctaHtml = primaryAction
    ? `<div class="mk-cta-row">
        ${ctaButtonHtml(primaryAction, "primary", primaryAction?.label || "按这个做", "确认后我继续推进")}
        ${ctaButtonHtml(secondaryAction, "secondary", secondaryAction?.label || "先放一放", "窗口过了再议")}
      </div>`
    : choiceHtml ||
      (!isNow
        ? `<div class="mk-cta-row">
        <button type="button" class="action-button primary" data-intent-fill="${escapeHtml(askLater)}">先问店长这件</button>
      </div>`
        : "");
  const railHtml = [now, next, later]
    .filter((item) => item && item.title && item.title !== step.title)
    .map((item) => {
      const label = item === now ? "现在" : item === next ? "下一窗" : "再之后";
      return `
        <div class="mk-flow-step">
          <span>${label}${item.when ? ` · ${escapeHtml(item.when)}` : ""}</span>
          <strong>${escapeHtml(item.title)}</strong>
        </div>`;
    })
    .join("");
  const autoHtml = isNow && autoDoing.length
    ? `<p class="mk-flow-auto">我同时在做：${escapeHtml(autoDoing.map((item) => item.title).join("、"))}</p>`
    : "";
  const status = !isNow
    ? step.when || (slot === "flow-next" ? "下一窗" : "再之后")
    : flow.phase_label || card?.guide_status || card?.phase_label || "经营节奏";
  return `
    <div class="mk-guide flow ${protect ? "protect" : ""} ${quiet ? "quiet" : ""} ${owner === "boss" && isNow ? "need" : "clear"}">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p><strong>${escapeHtml(introLead)}</strong><span>${escapeHtml(introBody)}</span></p>
      </div>
      <div class="mk-ai-status ${owner === "ai" || !isNow ? "quiet" : ""}"><i></i><span>${escapeHtml(status)}</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${whyNow ? `<p class="mk-support">${escapeHtml(whyNow)}</p>` : ""}
      ${showSkip ? `<p class="mk-guide-note">如果现在不做：${escapeHtml(ifSkip)}</p>` : ""}
      ${isNow ? renderExecutionPackHtml(currentExecutionPack(card) || step.execution_pack) : ""}
      ${ctaHtml}
      ${autoHtml}
      ${railHtml ? `<div class="mk-flow-rail">${railHtml}</div>` : ""}
    </div>`;
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
  const title = humanizeDecisionTitle(card?.guide_prompt || card?.title || "还差一步");
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

function renderWorkFocusHost(card) {
  const loop = currentLoop();
  if (loop && loopFocusIds(loop).includes(String(card?.id || ""))) {
    return renderLoopHost(loop);
  }
  const kind = card?.focus_kind || "thread";
  const title = humanizeDecisionTitle(card?.title || "经营事项");
  const why = humanizeDecisionTitle(card?.why_now || card?.guide_prompt || card?.summary || "");
  const judgment = humanizeDecisionTitle(card?.ai_judgment || card?.finding || card?.detail || "");
  const impact = humanizeDecisionTitle(card?.business_impact || "");
  const status =
    kind === "event"
      ? "经营发现"
      : kind === "waiting"
        ? "等待结果"
        : kind === "done"
          ? "最近完成"
          : "我正在跟进";
  const introLead =
    kind === "event"
      ? "这是我盯到的变化。"
      : kind === "waiting"
        ? "这件事还在观察窗口里。"
        : kind === "done"
          ? "这件事已经有结果了。"
          : "这条经营线程我还在推进。";
  const introBody =
    kind === "event"
      ? "发现和建议动作分开看：这里是发生了什么，另一张卡才是现在要不要改。"
      : "点进来只看这一条，不会再回到第一张建议卡。";
  const primaryAction = pickPrimaryAction(card?.actions || []);
  const secondaryAction = pickSecondaryAction(card?.actions || [], primaryAction);
  const ask = `关于「${title}」，${why || "现在这件事"}怎样了？请按这条线程回答，不要重复另一张卡。`;
  const ctaHtml = primaryAction
    ? `<div class="mk-cta-row">
        ${ctaButtonHtml(primaryAction, "primary", primaryAction?.label || "按这个做", "确认后我继续推进")}
        ${ctaButtonHtml(secondaryAction, "secondary", secondaryAction?.label || "先放一放", "窗口过了再议")}
      </div>`
    : `<div class="mk-cta-row">
        <button type="button" class="action-button primary" data-intent-fill="${escapeHtml(ask)}">问店长这件事</button>
      </div>`;
  const note = [judgment, impact].filter((line) => line && line !== why && line !== title);
  return `
    <div class="mk-guide ${kind === "event" || kind === "need" ? "need" : "clear"}">
      <div class="mk-ai-intro">
        <img class="mk-ai-mark" src="/static/brand/mealkey-mark.svg" width="28" height="28" alt="" />
        <p><strong>${escapeHtml(introLead)}</strong><span>${escapeHtml(introBody)}</span></p>
      </div>
      <div class="mk-ai-status quiet"><i></i><span>${escapeHtml(status)}</span></div>
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${why ? `<p class="mk-support">${escapeHtml(why)}</p>` : ""}
      ${note[0] ? `<p class="mk-guide-note">${escapeHtml(note[0])}</p>` : ""}
      ${note[1] ? `<p class="mk-guide-watch">${escapeHtml(note[1])}</p>` : ""}
      ${ctaHtml}
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
                `<button type="button" class="mk-choice-card" data-interview-key="${escapeHtml(
                  interviewKind(card) || "",
                )}" data-intent-fill="${escapeHtml(c.fill)}">${escapeHtml(c.label)}</button>`,
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

  const loop = currentLoop();
  if (loop && isCurrentLoopFocus(loop)) {
    host.innerHTML = renderLoopHost(loop);
    return;
  }

  const focusKind = card?.focus_kind || "";
  if (loop && loopFocusIds(loop).includes(String(card?.id || ""))) {
    host.innerHTML = renderLoopHost(loop);
    return;
  }
  if (["thread", "event", "waiting", "done"].includes(focusKind)) {
    host.innerHTML = renderWorkFocusHost(card);
    return;
  }
  if (focusKind === "need" && !(Array.isArray(card.actions) && card.actions.length)) {
    host.innerHTML = renderWorkFocusHost(card);
    return;
  }

  if (focusKind === "flow" || (!focusKind && card?.decision_flow?.now?.title)) {
    host.innerHTML = renderDecisionFlowHost(card);
    return;
  }

  if (!focusKind && card?.guide_type) {
    host.innerHTML = renderRuntimeGuideHost(card);
    return;
  }

  const primaryAction = pickPrimaryAction(card.actions || []);
  const secondaryAction = pickSecondaryAction(card.actions || [], primaryAction);
  const didLine = card.ai_already_did || card.ai_judgment || "";
  const noteLine = [card.why_now, card.business_impact, card.success_metric].filter(Boolean)[0] || "";
  const title = humanizeDecisionTitle(card.title || "");
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
      <h2 class="mk-question">${escapeHtml(title)}</h2>
      ${didLine ? `<p class="mk-support">${escapeHtml(didLine)}</p>` : ""}
      ${noteLine ? `<p class="mk-guide-note">${escapeHtml(noteLine)}</p>` : ""}
      ${watchLine ? `<p class="mk-guide-watch">${escapeHtml(watchLine)}</p>` : ""}
      ${renderExecutionPackHtml(currentExecutionPack(card))}
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

  const flow = currentDecisionFlow();
  const loop = currentLoop();
  const loopId = loop?.id || "";
  const loopSlot = String(loop?.left?.slot || "").trim();
  const flowNowItems =
    flow?.now?.title && (!loop || loopSlot === "need")
      ? [
          {
            id: loopId || workItemKey({ id: flow.now.id || flow.now.source_card_id, slot: "flow-now", title: flow.now.title }),
            work_thread_id: loop?.work_thread_id || flow.now.work_thread_id || loopId || "",
            slot: "flow-now",
            title: loop?.title || flow.now.title,
            meta: loop?.left?.meta || flow.now.success_metric || flow.now.business_impact || flow.phase_label || "现在",
            work: !loop || loopSlot === "need" ? "need" : flow.now.owner === "boss" ? "need" : "ask",
            prompt: loop?.finding || flow.now.why_now
              ? `关于「${loop?.title || flow.now.title}」，${loop?.finding || flow.now.why_now}`
              : `关于「${loop?.title || flow.now.title}」，现在怎么做？`,
            active: true,
          },
        ]
      : [];
  const flowNextItems = [flow?.next, flow?.later]
    .filter((step) => step && step.title && step.title !== flow?.now?.title)
    .map((step, idx) => ({
      id: workItemKey({ id: step.id || step.source_card_id, slot: idx === 0 ? "flow-next" : "flow-later", title: step.title }),
      work_thread_id: step.work_thread_id || "",
      slot: idx === 0 ? "flow-next" : "flow-later",
      title: step.title,
      meta: `${idx === 0 ? "下一窗" : "再之后"} · ${step.when || ""}`.trim(),
      work: "ask",
      prompt: step.why || step.why_now || `到「${step.when || "下一窗"}」再处理「${step.title}」`,
    }));

  const runtimeNeedItems = sortWorkItems(runtimeLeftItems("need_you"), "need").slice(0, 4).map((item) => ({
    id: workItemKey({ id: item.id || item.source_odo_id, slot: item.kind === "event" ? "feed" : "need", title: item.title || item.name }),
    work_thread_id: item.work_thread_id || item.id || "",
    thread_status: item.thread_status || "",
    slot: item.kind === "event" ? "feed" : "need",
    title: item.title || item.name || "需要你确认",
    meta:
      item.meta ||
      threadStatusLabel(item.thread_status, "") ||
      item.summary ||
      item.why_now ||
      item.status ||
      item.next_step ||
      "待你拍板",
    work: "need",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，现在需要我做什么？` : ""),
  }));
  const runtimeActiveItems = sortWorkItems(runtimeLeftItems("active"), "active").slice(0, 4).map((item, idx) => ({
    id: workItemKey({ id: item.id || item.source_odo_id, slot: "active", title: item.title || item.name }),
    work_thread_id: item.work_thread_id || item.id || "",
    thread_status: item.thread_status || "",
    slot: "active",
    title: item.title || item.name || "经营线程",
    meta:
      item.meta ||
      threadStatusLabel(item.thread_status, "") ||
      item.summary ||
      item.why_now ||
      item.phase ||
      item.status ||
      (idx === 0 ? "AI 处理中" : "进行中"),
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，现在进展怎样？` : ""),
  }));
  const runtimeWaitingItems = sortWorkItems(runtimeLeftItems("waiting"), "waiting").slice(0, 3).map((item) => ({
    id: workItemKey({ id: item.id || item.source_odo_id, slot: "waiting", title: item.title || item.name }),
    work_thread_id: item.work_thread_id || item.id || "",
    thread_status: item.thread_status || "",
    slot: "waiting",
    title: item.title || item.name || "等待结果",
    meta: item.meta || threadStatusLabel(item.thread_status, "") || item.summary || item.status || "观察中",
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，结果出来了吗？` : ""),
  }));
  const runtimeDoneItems = sortWorkItems(runtimeLeftItems("completed"), "done").slice(0, 3).map((item) => ({
    id: workItemKey({ id: item.id || item.source_odo_id, slot: "done", title: item.title || item.name }),
    work_thread_id: item.work_thread_id || item.id || "",
    thread_status: item.thread_status || "",
    slot: "done",
    title: item.title || item.name || "最近完成",
    meta: item.meta || threadStatusLabel(item.thread_status, "") || item.summary || item.status || "已完成",
    work: "ask",
    prompt: item.prompt || (item.title ? `关于「${item.title}」，帮我复盘下一步` : ""),
  }));

  const needItems = runtimeNeedItems.length
    ? runtimeNeedItems
    : card
    ? [
        {
          id: workItemKey({ id: card.id, slot: isUnderstandingCard(card) ? "need" : "need", title: card.title }),
          work_thread_id: card.work_thread_id || card.id || "",
          slot: "need",
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
              : card.meta || card.why_now || "待你拍板",
          work: isUnderstandingCard(card) ? "talk" : "need",
        },
      ]
    : [];

  const workingSource = runtimeActiveItems.length ? runtimeActiveItems : working.length ? working : threads;
  const workingItems = workingSource.slice(0, 4).map((item, idx) => ({
    id: item.id || workItemKey({ id: item.id, slot: "active", title: item.title }),
    work_thread_id: item.work_thread_id || item.id || "",
    slot: item.slot || "active",
    title: item.title || "经营线程",
    meta: humanizeDecisionTitle(item.meta || item.summary || item.next_step || (idx === 0 ? "AI 处理中" : "进行中")),
    work: item.work || "ask",
    prompt: item.prompt || `关于「${item.title || ""}」，现在进展怎样？`,
  }));

  const seenKeys = new Set(
    [...flowNowItems, ...flowNextItems, ...needItems]
      .map((item) => item.id)
      .filter(Boolean),
  );
  const seenTitles = new Set(
    [...flowNowItems, ...needItems].map((item) => humanizeDecisionTitle(item.title || "")).filter(Boolean),
  );
  const uniqueWorkingItems = workingItems.filter((item) => {
    const key = item.id;
    const title = humanizeDecisionTitle(item.title || "");
    if (key && seenKeys.has(key)) return false;
    if (title && seenTitles.has(title)) return false;
    if (key) seenKeys.add(key);
    if (title) seenTitles.add(title);
    return true;
  });
  const uniqueNeedItems = needItems.filter((item) => {
    const title = humanizeDecisionTitle(item.title || "");
    const nowTitle = humanizeDecisionTitle(flow?.now?.title || "");
    if (item.id && flowNowItems.some((now) => now.id === item.id)) return false;
    if (title && nowTitle && title === nowTitle) return false;
    return true;
  });

  const waitingItems = runtimeWaitingItems.length
    ? runtimeWaitingItems
    : experiments.slice(0, 2).map((exp) => ({
    id: workItemKey({ id: exp.id || exp.recommendation_id, slot: "waiting", title: exp.action_title }),
    work_thread_id: exp.work_thread_id || exp.recommendation_id || exp.id || "",
    slot: "waiting",
    title: exp.action_title || "实验观察中",
    meta: exp.notes || "等待结果",
    work: "ask",
    prompt: `实验「${exp.action_title || ""}」现在怎样了？`,
  }));

  const doneItems = runtimeDoneItems.length
    ? runtimeDoneItems
    : results.slice(0, 2).map((item) => ({
    id: workItemKey({ id: item.id, slot: "done", title: item.title }),
    work_thread_id: item.work_thread_id || item.id || "",
    slot: "done",
    title: item.title || "已完成",
    meta: item.summary || "已完成",
    work: "ask",
    prompt: `关于结果「${item.title || ""}」，帮我复盘下一步`,
  }));

  const selectedKey = String(state.focusedWorkKey || flowNowItems[0]?.id || "").trim();
  const section = (title, items, { empty = "暂无" } = {}) => `
      <div class="mk-work-group">
        <p class="mk-work-group-title">${escapeHtml(title)}</p>
        ${
          items.length
            ? items
                .map(
                  (item) => {
                    const displayTitle = humanizeDecisionTitle(item.title || "经营事项");
                    const rawMeta = humanizeDecisionTitle(item.meta || "");
                    const displayMeta = rawMeta && rawMeta !== displayTitle ? rawMeta : "";
                    const key = item.id || `${item.slot || ""}:${item.title || ""}`;
                    const isActive = selectedKey
                      ? key === selectedKey || item.id === selectedKey
                      : Boolean(item.active);
                    return `
          <button type="button" class="mk-work-item${isActive ? " active" : ""}"
            data-rail-work="${escapeHtml(item.work || "talk")}"
            data-rail-id="${escapeHtml(item.id || "")}"
            data-rail-slot="${escapeHtml(item.slot || "")}"
            data-rail-prompt="${escapeHtml(item.prompt || "")}"
            data-work-thread-id="${escapeHtml(item.work_thread_id || item.id || "")}"
            draggable="true">
            <span class="mk-work-copy">
              <strong>${escapeHtml(displayTitle)}</strong>
              ${displayMeta ? `<span>${escapeHtml(displayMeta)}</span>` : ""}
            </span>
            <span class="mk-work-arrow" aria-hidden="true">›</span>
          </button>`;
                  },
                )
                .join("")
            : `<p class="mk-work-empty">${escapeHtml(empty)}</p>`
        }
      </div>`;

  rail.innerHTML = `
    <div class="mk-work-head">工作线程</div>
    <div class="mk-work-body">
      ${section("今日决策流", [...flowNowItems, ...flowNextItems], { empty: "按节律推进中" })}
      ${section(`需要你 ${uniqueNeedItems.length || ""}`.trim(), uniqueNeedItems, { empty: "今天没有要你拍板的事" })}
      ${section(`正在进行 ${uniqueWorkingItems.length || ""}`.trim(), uniqueWorkingItems, { empty: "暂无" })}
      ${section(`等待结果 ${waitingItems.length || ""}`.trim(), waitingItems, { empty: "暂无" })}
      ${section(`最近完成 ${doneItems.length || ""}`.trim(), doneItems, { empty: "暂无" })}
    </div>
  `;
}

function renderContextRail() {
  const rail = qs("#mkContextRail");
  if (!rail) return;
  const brief = state.managerBrief || {};
  // 只吃真实 proactive_feed，禁止把左栏 ops_queue 整队列投影成日记噪音
  let feed = runtimeFeedItems();
  if (!feed.length) feed = brief.proactive_feed || [];
  const loop = currentLoop();
  const focus = currentNeedCard();
  const focusId = focus?.id;

  // 同一闭环对象必须同时出现在右栏；其它焦点才去重
  feed = feed.filter((ev) => {
    if (loop && ev.id === loop.id) return true;
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
            data-rail-id="${escapeHtml(ev.id || "")}"
            data-rail-slot="feed"
            data-rail-prompt="${escapeHtml(ev.summary ? `关于「${ev.summary}」，现在怎样了？` : "")}"
            data-work-thread-id="${escapeHtml(ev.work_thread_id || ev.id || "")}"
            data-feed-id="${escapeHtml(ev.id || "")}"
            draggable="true"
            tabindex="0"
            role="button"
            aria-label="${escapeHtml(`打开经营事件：${humanizeDecisionTitle(ev.summary || "经营动态")}`)}">
            <div class="mk-feed-top">
              <time>${escapeHtml(`${time} · ${kicker}`)}</time>
              <span class="mk-feed-status">${escapeHtml(proactiveStatusLabel(status))}</span>
            </div>
            <strong>${escapeHtml(humanizeDecisionTitle(ev.summary || "经营动态"))}</strong>
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
  const skillLabels = {
    product: "商品",
    traffic: "投流",
    profit: "利润",
    competition: "竞争",
    review: "评价",
    customer: "用户",
    store_growth: "增长",
  };
  if (skills.length) {
    const labels = skills.slice(0, 3).map((item) => skillLabels[String(item).toLowerCase()] || item);
    return `主动经营流 · ${labels.join(" / ")} 正在推进`;
  }
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
  // 访谈/确认路径：独占中栏，聊天线程与其他模块退出
  if (interviewing) {
    enterExclusivePathMode();
  } else {
    if (document.body.classList.contains("path-exclusive") || document.body.classList.contains("interviewing")) {
      exitExclusivePathMode();
    }
    document.body.classList.toggle(
      "home-chat-open",
      document.body.classList.contains("home-chat-open") || Boolean((state.chatMessages || []).length),
    );
  }

  const badge = qs("#mkNeedBadge");
  if (badge) {
    badge.hidden = !card;
    badge.textContent = card ? "1" : "0";
  }

  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) {
    /* 聊天态用线程内联状态，避免外层状态行错位 */
    analyzing.hidden =
      document.body.classList.contains("home-chat-open") ||
      !(state.chatMessages || []).some((m) => m.pending);
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

function renderHomeChatThread() {
  const container = qs("#homeChatThread");
  if (!container) return;
  const main = qs("#section-overview") || qs(".mk-home-main");
  const exclusive =
    document.body.classList.contains("interviewing") || document.body.classList.contains("path-exclusive");
  /* 路径独占时隐藏聊天层；用 class 控制命令条间距，避免 :empty 撑出空白 */
  if (exclusive) {
    container.hidden = true;
    container.setAttribute("aria-hidden", "true");
    container.innerHTML = `<div class="mk-chat-path-placeholder" hidden aria-hidden="true"></div>`;
    if (main) main.classList.remove("chat-thread-empty");
    return;
  }
  const runtimeMeta = runtimeOutputMetaHtml();
  if (!state.chatMessages.length) {
    if (main) main.classList.toggle("chat-thread-empty", !document.body.classList.contains("home-chat-open"));
    if (document.body.classList.contains("home-chat-open")) {
      container.innerHTML = `
        <section class="mk-chat-output-shell mk-chat-stream">
          <div class="mk-chat-output-head">
            <span class="mk-chat-output-kicker">任务输出</span>
            <strong class="mk-chat-output-title">MealKey 会在这里持续更新</strong>
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
  if (main) main.classList.remove("chat-thread-empty");
  const pending = state.chatMessages.some((m) => m.pending);
  container.innerHTML = `
    <section class="mk-chat-output-shell mk-chat-stream">
      <div class="mk-chat-output-head">
        <span class="mk-chat-output-kicker">任务输出</span>
        <strong class="mk-chat-output-title">当前路径的判断、进展和结果</strong>
        ${runtimeMeta}
      </div>
      <div class="mk-chat-output-body">
        ${state.chatMessages.map((message) => renderChatBubble(message, { home: true })).join("")}
        ${
          pending
            ? `<p class="mk-analyzing mk-analyzing-inline">MealKey 正在分析中… 预计 1–2 分钟</p>`
            : ""
        }
      </div>
    </section>`;
  container.scrollTop = container.scrollHeight;
  /* 首页聊天态改为线程内联状态行，避免与内容列错位 */
  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) analyzing.hidden = true;
}

function runtimeOutputMetaHtml() {
  const runtime = runtimeWorkspacePanels();
  const meta = runtimeBridgeMeta();
  const dailyPlan = state.dailyPlan || {};
  const guide = currentRuntimeGuide();
  const items = [
    runtime?.store?.phase_label || (runtime?.store?.runtime_state ? `当前 ${runtime.store.runtime_state}` : ""),
    dailyPlan?.current_meal_period ? `聚焦 ${dailyPlan.current_meal_period}` : "",
    guide?.phase_label || guide?.status || "",
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
  if (typeof closeMobileSheets === "function") {
    closeMobileSheets();
  }
  if (kind === "talk") {
    enterSafeModePath().catch((error) => notifyError(error.message || "进入确认失败"));
    return;
  }
  document.body.classList.add("view-home");
  document.body.classList.remove("view-module", "workspace-focus", "home-chat-open");
  if (typeof hideTaskView === "function") hideTaskView();
  const card = focusWorkFromRailElement(item);
  if (card) {
    renderDecisionHost(card);
    syncCommandBarForFocus(card);
    renderWorkRail();
    renderContextRail();
    const main = qs("#section-overview") || qs(".mk-home-main");
    if (main) main.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const payload = buildRailCardPayload(item);
  if (payload?.prompt) {
    ingestRailCardToChat(payload, { replace: true, source: "click" });
    return;
  }
  openHomeChatMode();
  qs("#homeChatInput")?.focus();
}

function focusWorkFromRailElement(el) {
  const title =
    el.querySelector("strong")?.textContent?.trim() ||
    el.getAttribute("aria-label") ||
    "";
  const id = String(el.dataset.railId || "").trim();
  const slot = String(el.dataset.railSlot || "").trim();
  const workThreadId = String(el.dataset.workThreadId || "").trim();
  const meta = el.querySelector(".mk-work-copy span")?.textContent?.trim() || "";
  const prompt = String(el.dataset.railPrompt || "").trim();
  const key = id || (slot && title ? `${slot}:${title}` : title);
  state.focusedWorkKey = key;
  state.focusedWorkSlot = slot;
  state.pendingWorkThreadId = workThreadId || null;
  const resolved = resolveFocusedWorkCard();
  if (resolved) {
    state.focusOverrideCard = resolved;
    return resolved;
  }
  const kind =
    slot === "feed" || slot === "event"
      ? "event"
      : slot === "waiting"
        ? "waiting"
        : slot === "done"
          ? "done"
          : slot === "need"
            ? "need"
            : slot.startsWith("flow")
              ? "flow"
              : "thread";
  const fallback = cardFromWorkSource(null, {
    id,
    slot,
    kind,
    title: title || "经营事项",
    why: prompt || meta,
    meta,
  });
  if (fallback) {
    state.focusOverrideCard = fallback;
    return fallback;
  }
  state.focusedWorkKey = null;
  state.focusedWorkSlot = null;
  return null;
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

function railTaskTitle(item, fallback = "") {
  const title =
    item?.querySelector("strong")?.textContent?.trim() ||
    item?.dataset?.taskTitle ||
    fallback ||
    "继续推进当前任务";
  return humanizeDecisionTitle(title);
}

function railTaskMeta(item, fallback = "") {
  const copy = item?.querySelector(".mk-work-copy span");
  return String(copy?.textContent || fallback || "").trim();
}

function renderNeedTaskBody(item) {
  const card = currentNeedCard();
  const title = railTaskTitle(item, card?.title || "需要你确认");
  const summary =
    railTaskMeta(item, card?.guide_explanation || card?.why_now || card?.meta || "") ||
    "这件事确认后，我会继续推进。";
  const request =
    card?.need_from_owner ||
    card?.guide_request_label ||
    card?.guide_title ||
    "现在需要你确认";
  const nextPrompt =
    item?.dataset?.railPrompt ||
    (title ? `关于「${title}」，现在需要我做什么？` : "继续当前这件事");
  return `
    <div class="task-route-view">
      <p class="task-route-kicker">当前需要你</p>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(summary)}</p>
      <div class="task-route-guide">
        <strong>${escapeHtml(request)}</strong>
        <p>${escapeHtml(card?.why_now || card?.guide_explanation || "你确认后，我继续往下做。")}</p>
      </div>
      <div class="task-route-actions">
        <button class="action-button primary" type="button" data-task-ask="${escapeHtml(nextPrompt)}">继续这件事</button>
        <button class="action-button ghost" type="button" data-task-back>返回首页</button>
      </div>
    </div>`;
}

function showTaskRoute(targetId, title = "") {
  showTaskView(title || workspaceView(targetId).label || "任务路径", renderTaskRouteBody(targetId, title));
}

function openHomeChatMode() {
  /* 确认路径独占时不叠聊天层 */
  if (document.body.classList.contains("interviewing") || document.body.classList.contains("path-exclusive")) {
    return;
  }
  const thread = qs("#homeChatThread");
  const dock = qs("#homeChatDock");
  if (!thread || !dock) return;
  document.body.classList.add("view-home");
  document.body.classList.remove("view-module", "workspace-focus");
  document.body.classList.add("home-chat-open");
  setHomeChatReply("");
  renderHomeChatThread();
  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) analyzing.hidden = true;
}

function closeHomeChatMode() {
  document.body.classList.remove("home-chat-open");
  renderHomeChatThread();
}

function interviewTurnQuestion(turn) {
  if (!turn || typeof turn !== "object") {
    return {
      prompt: "还需要你确认一项经营信息",
      key: interviewGapKeys()[0] || "priority_style",
    };
  }
  const raw = turn.question ?? turn.next_question;
  let prompt = "";
  let key = "";
  if (typeof raw === "string") {
    prompt = raw.trim();
  } else if (raw && typeof raw === "object") {
    prompt = String(raw.prompt || raw.title || raw.text || "").trim();
    key = String(raw.key || "").trim();
  }
  const rawKey = String(turn.gap_key || key || "").trim();
  key = rawKey === "mue_gap" || rawKey === "mue_nl_setting" || rawKey === "mue_ready" ? "" : rawKey;
  key = key || interviewGapKeys()[0] || "priority_style";
  if (!prompt && typeof turn.answer === "string") {
    const starred = turn.answer.match(/\*\*([^*？?]+[？?])\*\*/);
    const plain = turn.answer.match(/经营这家店[^\n]*[？?]/);
    prompt = String((starred && starred[1]) || (plain && plain[0]) || "").trim();
  }
  if (!prompt) prompt = "还需要你确认一项经营信息";
  return { prompt, key };
}

function interviewStillBlocking(result) {
  const u = result?.understanding || state.understanding || {};
  if (result?.intent === "understanding_ready") return false;
  if (u.mos_satisfied === true) return false;
  if (u.mos_satisfied === false) return true;
  if (result?.gap_key) return true;
  return interviewGapKeys().length > 0 || (Array.isArray(u.mos_blocking_fields) && u.mos_blocking_fields.length > 0);
}

function understandingCardFromInterview(turn) {
  const { prompt, key } = interviewTurnQuestion(turn);
  return {
    id: `understanding:${key}`,
    interrupt_reason: "understanding",
    trigger: "understanding",
    arbiter_state: "need_input",
    meta: "understanding",
    title: prompt,
    why_now: "确认后我才能放开利润相关自动动作。",
    need_from_owner: guideBlockerLabel(key),
  };
}

async function confirmInterviewChoice(opt) {
  if (!opt || state._interviewBusy) return true;
  const text = (opt.dataset.intentFill || opt.textContent || "").trim();
  if (!text) return true;

  const inInterview =
    document.body.classList.contains("interviewing") ||
    document.body.classList.contains("path-exclusive") ||
    isUnderstandingCard(currentNeedCard()) ||
    state.understanding?.system_mode === "safe" ||
    state.understanding?.mos_satisfied === false ||
    (Array.isArray(state.understanding?.mos_blocking_fields) &&
      state.understanding.mos_blocking_fields.length > 0);
  if (!inInterview) return false;

  state._interviewBusy = true;
  qsa(".mk-choice-card, .mk-decision-option").forEach((el) => {
    el.disabled = true;
    el.classList.toggle("selected", el === opt);
    el.classList.toggle("is-busy", el === opt);
  });
  const status = qs("#mkDecisionHost .mk-ai-status span");
  const prevStatus = status?.textContent || "";
  if (status) status.textContent = "正在记下你的选择…";

  try {
    if (!state.currentStoreId) throw new Error("门店还在加载，请稍后再点");
    const card = currentNeedCard();
    const key =
      (opt.dataset.interviewKey || "").trim() ||
      (isUnderstandingCard(card) ? interviewKeyFromCard(card) : "") ||
      interviewGapKeys()[0];
    const result = await submitInterviewAnswer(text, { key });
    if (!result) throw new Error("确认没有成功，请再点一次");

    if (interviewStillBlocking(result)) {
      showUnderstandingCard(understandingCardFromInterview(result));
      notifySuccess("已记下，继续下一项");
    } else {
      exitExclusivePathMode();
      state.focusOverrideCard = null;
      renderDecisionHost(currentNeedCard());
      syncCommandBarForFocus(currentNeedCard());
      renderWorkRail();
      notifySuccess("确认完成，我可以继续自动经营了");
      loadHomeWorkspace(state.currentStoreId).catch(() => null);
    }
  } catch (error) {
    const payload = error?.payload;
    if (payload?.understanding) state.understanding = payload.understanding;
    if (payload?.gap_key || payload?.question) {
      showUnderstandingCard(understandingCardFromInterview(payload));
    }
    if (status) status.textContent = prevStatus || "还差一些问题";
    notifyError(error?.message || payload?.detail || "确认失败，请再点一次");
  } finally {
    state._interviewBusy = false;
    qsa(".mk-choice-card, .mk-decision-option").forEach((el) => {
      el.disabled = false;
      el.classList.remove("is-busy");
    });
  }
  return true;
}

function localUnderstandingCard(key = "") {
  const field =
    String(key || "").trim() ||
    interviewGapKeys()[0] ||
    "priority_style";
  return {
    id: `understanding:${field}`,
    interrupt_reason: "understanding",
    trigger: "understanding",
    arbiter_state: "need_input",
    meta: "understanding",
    title: guideBlockerLabel(field),
    why_now: "点选项告诉我，确认后我继续经营。",
    need_from_owner: guideBlockerLabel(field),
  };
}

function enterExclusivePathMode() {
  document.body.classList.add("view-home", "interviewing", "path-exclusive");
  document.body.classList.remove("home-chat-open", "view-module", "workspace-focus");
  if (typeof closeMobileSheets === "function") closeMobileSheets();
  const tv = qs("#mkTaskView");
  if (tv) tv.hidden = true;
  const guide = qs("#mkGuideArea");
  if (guide) guide.hidden = false;
  const thread = qs("#homeChatThread");
  if (thread) {
    thread.hidden = true;
    thread.setAttribute("aria-hidden", "true");
  }
  const analyzing = qs("#mkAnalyzingLine");
  if (analyzing) analyzing.hidden = true;
  const banner = qs("#mkSafeModeBanner");
  if (banner) {
    banner.hidden = true;
    banner.style.display = "none";
  }
}

function exitExclusivePathMode() {
  document.body.classList.remove("interviewing", "path-exclusive");
  const thread = qs("#homeChatThread");
  if (thread) {
    thread.hidden = false;
    thread.removeAttribute("aria-hidden");
  }
}

function showUnderstandingCard(card) {
  if (!card) return;
  state.focusOverrideCard = card;
  enterExclusivePathMode();
  renderDecisionHost(card);
  syncCommandBarForFocus(card);
  renderWorkRail();
  /* 只滚中栏，避免把钉住的顶栏卷出视野 */
  const main = qs("#section-overview") || qs(".mk-home-main");
  if (main) main.scrollTo({ top: 0, behavior: "smooth" });
}

async function enterSafeModePath() {
  if (typeof closeMobileSheets === "function") closeMobileSheets();
  document.body.classList.add("view-home");
  document.body.classList.remove("view-module", "workspace-focus", "home-chat-open");
  closeHomeChatMode();

  const needYou = state.managerBrief?.ops_queue?.need_you || [];
  let card =
    needYou.find((item) => isUnderstandingCard(item)) ||
    (isUnderstandingCard(state.focusOverrideCard) ? state.focusOverrideCard : null) ||
    localUnderstandingCard();

  // 先立刻进入确认页，避免卡在 interview 接口上「点了没反应」
  showUnderstandingCard(card);
  notifySuccess("先确认这几项，我才能放开自动动作");

  if (!state.currentStoreId) return;
  try {
    const turn = await fetchJson(`/stores/${state.currentStoreId}/understanding/interview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!document.body.classList.contains("interviewing")) return;
    if (turn?.understanding) state.understanding = turn.understanding;
    const next = understandingCardFromInterview(turn);
    showUnderstandingCard(next);
  } catch (_error) {
    /* 本地确认卡已展示，接口失败不挡进入 */
  }
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
  const speakerHtml = home
    ? `<strong class="mk-chat-speaker">${speaker}</strong>`
    : `<strong>${speaker}</strong>`;
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
      <div class="${klass} ${message.role}${message.pending ? " pending" : ""}" data-role="${message.role}">
        ${speakerHtml}
        ${leadHtml}
        ${sectionHtml}
        ${renderChatAttachments(message)}
      </div>
    `;
  }
  return `
    <div class="${klass} ${message.role}${message.pending ? " pending" : ""}" data-role="${message.role || ""}">
      ${speakerHtml}
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
