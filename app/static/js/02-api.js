/* MealKey UI — fetch helpers, dashboard/workspace loaders, intake API */

function apiAuthHeaders(extra = {}) {
  const headers = { ...extra };
  const jwt = window.localStorage.getItem("mealky_access_token");
  if (jwt) {
    headers.Authorization = `Bearer ${jwt}`;
  }
  const token = window.localStorage.getItem("mealky_api_token");
  if (token) headers["x-api-token"] = token;
  return headers;
}

/**
 * 刷新 access token。区分三种失败:
 * - "no_api_token": 没有 api_token,需要登录
 * - "network": 网络异常(fetch 抛错)
 * - "server": 服务器拒绝(非 200)
 * 返回 true 表示成功。
 */
async function ensureAccessToken() {
  if (window.localStorage.getItem("mealky_access_token")) return true;
  const apiToken = window.localStorage.getItem("mealky_api_token");
  if (!apiToken) return false;
  let response;
  try {
    response = await fetch("/auth/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-token": apiToken,
      },
      body: JSON.stringify({
        api_token: apiToken,
        store_id: state.currentStoreId || undefined,
      }),
    });
  } catch (networkError) {
    // 网络异常 — 不静默吞掉,记录到 state 供 UI 提示
    state.lastAuthError = { type: "network", message: "网络异常，无法连接服务器", error: networkError };
    return false;
  }
  if (!response.ok) {
    // 服务器拒绝 — token 可能已失效
    state.lastAuthError = { type: "token_expired", message: "登录已过期，请重新获取访问令牌", status: response.status };
    // 清掉可能过期的 token
    if (response.status === 401 || response.status === 403) {
      window.localStorage.removeItem("mealky_access_token");
    }
    return false;
  }
  const payload = await response.json().catch(() => ({}));
  if (payload.access_token) {
    window.localStorage.setItem("mealky_access_token", payload.access_token);
    state.lastAuthError = null;
    return true;
  }
  state.lastAuthError = { type: "server", message: "服务器返回异常，未能获取访问令牌" };
  return false;
}

async function fetchJson(url, options = {}) {
  const { timeoutMs, headers, ...rest } = options || {};
  const buildHeaders = (extra) =>
    apiAuthHeaders(
      extra instanceof Headers
        ? Object.fromEntries(extra.entries())
        : extra || {},
    );

  const controller = timeoutMs ? new AbortController() : null;
  const timer = timeoutMs ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  const send = () =>
    fetch(url, {
      ...rest,
      headers: buildHeaders(headers),
      signal: controller ? controller.signal : rest.signal,
    });

  let response;
  try {
    response = await send();
    if (response.status === 401) {
      const refreshed = await ensureAccessToken();
      if (refreshed) {
        response = await send();
      }
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error("加载超时，店长工作台已改走规则引擎，请刷新重试");
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail[0]?.msg || detail[0]?.detail || "请求失败"
          : payload.message || `请求失败：${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return response.json();
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
    refresh ? { method: "POST", timeoutMs: 12000 } : { timeoutMs: 12000 },
  );
}

async function fetchRuntimeWorkspace(storeId) {
  try {
    return await fetchJson(`/v1/stores/${storeId}/workspace`, { timeoutMs: 12000 });
  } catch (error) {
    if (typeof notifyError === "function") {
      notifyError(error.message || "经营工作台加载失败");
    }
    return null;
  }
}

async function markLoopExecuted(storeId, loopId) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/executed`, {
    method: "POST",
  });
}

async function attachLoopEvidence(storeId, loopId, payload) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/evidence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

async function executeLoopPlatform(storeId, loopId) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/execute-platform`, {
    method: "POST",
  });
}

async function markLoopNotExecuted(storeId, loopId) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/not-executed`, {
    method: "POST",
  });
}

async function markLoopAcked(storeId, loopId) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/ack`, {
    method: "POST",
  });
}

async function shareLoopResultCard(storeId, loopId) {
  return fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/loop/${encodeURIComponent(loopId)}/share-card`, {
    method: "POST",
  });
}

async function fetchRuntimeDailyPlan(storeId) {
  return fetchJson(`/stores/${storeId}/daily-plan`).catch(() => null);
}

function mergeRuntimeIntoBrief() {
  if (!state.runtimeWorkspace) return;
  const rw = state.runtimeWorkspace;
  if (!rw.left) return;
  if (!state.managerBrief) state.managerBrief = {};
  const mb = state.managerBrief;
  if (!mb.ops_queue) mb.ops_queue = {};
  const oq = mb.ops_queue;
  if (Array.isArray(rw.left.need_you)) oq.need_you = rw.left.need_you;
  if (Array.isArray(rw.left.active)) oq.working = rw.left.active;
  if (Array.isArray(rw.left.completed)) oq.results = rw.left.completed;
  if (Array.isArray(rw.left.waiting)) oq.waiting = rw.left.waiting;
  if (rw.left.opportunities?.length) oq.opportunities = rw.left.opportunities;
  if (rw.left.active_goal) oq.active_goal = rw.left.active_goal;
  if (rw.left.threads?.length) oq.threads = rw.left.threads;
  if (rw.center?.guide) {
    mb.ops_queue.principle = rw.center.principle || oq.principle;
  }
  if (rw.right?.proactive_feed?.length) {
    mb.proactive_feed = rw.right.proactive_feed;
  }
  if (rw.meta?.runtime_bridge) {
    mb.runtime_bridge = rw.meta.runtime_bridge;
  }
}

async function pollStoreNotifications(storeId) {
  if (!storeId) return;
  try {
    const notifications = await fetchJson(
      `/workspace/stores/${storeId}/notifications`,
    ).catch(() => null);
    const unread = (notifications?.notifications || []).filter((n) => !n.read);
    if (!unread.length) return;
    const latest = unread[0];
    if (!state._lastNotifId || state._lastNotifId !== latest.id) {
      state._lastNotifId = latest.id;
      notifySuccess(
        `${latest.title}${latest.body ? "：" + latest.body.slice(0, 60) : ""}`,
      );
      fetchJson(`/workspace/notifications/${latest.id}/read`, {
        method: "POST",
      }).catch(() => null);
    }
  } catch (_) {
    /* ignore */
  }
}

async function loadHomeWorkspace(storeId) {
  state.currentStoreId = storeId;
  persistStoreId(storeId);
  const [runtimeWorkspace, settingsOverview, understanding, platformLinks, commercialBoard] = await Promise.all([
    fetchRuntimeWorkspace(storeId),
    fetchJson(`/settings/overview?store_id=${encodeURIComponent(storeId)}`).catch(
      () => null,
    ),
    fetchJson(`/stores/${storeId}/understanding`).catch(() => null),
    fetchJson(`/workspace/stores/${storeId}/platform-links`).catch(() => ({ links: [] })),
    fetchJson(`/v1/stores/${encodeURIComponent(storeId)}/commercial/board`).catch(() => null),
  ]);
  state.runtimeWorkspace = runtimeWorkspace;
  state.settingsOverview = settingsOverview;
  state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
  state.enterpriseSettings = settingsOverview?.enterprise || state.enterpriseSettings;
  state.understanding = understanding;
  state.platformLinks = platformLinks?.links || [];
  if (commercialBoard) state.commercialBoard = commercialBoard;
  // canonical source：brief 直接取自 workspace（同一个 POIE run），
  // 不再单独 fetch manager_brief —— 消灭两次 POIE 执行互相漂移。
  if (runtimeWorkspace?.brief) {
    state.managerBrief = runtimeWorkspace.brief;
  }
  state.dashboard = {
    ...(state.dashboard || {}),
    store:
      settingsOverview?.store ||
      state.dashboard?.store ||
      { id: storeId, name: "门店" },
    experiments: state.dashboard?.experiments || [],
    question_examples: state.dashboard?.question_examples || [],
    // brief 已就位时同步 store_state 关键字段，避免 stub 回退显示 "--"
    store_state: state.managerBrief
      ? state.dashboard?.store_state || { kpis: {}, profit: state.managerBrief.profit_summary }
      : state.dashboard?.store_state,
  };
  await pollStoreNotifications(storeId);
  renderHomeShell();
  applyOwnerProfileUI(state.ownerProfile || settingsOverview?.owner);
  loadOwnerProfile(storeId).catch(() => null);
  loadEnterpriseSettings(storeId).catch(() => null);
  if (typeof renderDataCoveragePanel === "function") renderDataCoveragePanel();
}

async function ensureFullDashboard() {
  if (state._fullDashboardLoaded || !state.currentStoreId) return;
  await loadDashboard(state.currentStoreId, { forceFull: true });
}

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

async function fetchSensingBundle(storeId) {
  const [managerBrief, operatingEvents, strategyMemory, understanding, dailyPlan, actionTraces] =
    await Promise.all([
      fetchJson(`/stores/${storeId}/manager_brief`, { timeoutMs: 12000 }).catch(() => null),
      fetchJson(`/stores/${storeId}/events`).catch(() => null),
      fetchJson(`/stores/${storeId}/strategy_memory`).catch(() => null),
      fetchJson(`/stores/${storeId}/understanding`).catch(() => null),
      fetchRuntimeDailyPlan(storeId),
      fetchJson(`/stores/${storeId}/action-traces?limit=10`).catch(() => null),
    ]);
  state.managerBrief = managerBrief;
  state.operatingEvents = operatingEvents;
  state.strategyMemory = strategyMemory;
  state.understanding = understanding;
  state.actionTraces = actionTraces?.traces || [];
  state.dailyPlan = dailyPlan?.plan || dailyPlan || state.dailyPlan;
  await pollStoreNotifications(storeId);
}

async function loadStores() {
  const payload = await fetchJson("/workspace/stores");
  const preferredId = state.currentStoreId || persistedStoreId();
  state.stores = dedupeStores(payload.stores || [], preferredId);
  const hasCurrent = state.stores.some((store) => store.id === state.currentStoreId);
  if ((!state.currentStoreId || !hasCurrent) && state.stores.length) {
    const preferred = state.stores.find((store) => store.id === preferredId);
    state.currentStoreId = preferred?.id || state.stores[0].id;
  }
  if (state.currentStoreId) {
    persistStoreId(state.currentStoreId);
  }
  renderStoreSelector();
}

async function bootstrapWorkspace() {
  const payload = await fetchJson("/workspace/bootstrap", { method: "POST" });
  await loadStores();
  if (payload.default_store_id) {
    state.currentStoreId = payload.default_store_id;
    persistStoreId(payload.default_store_id);
  }
  if (state.currentStoreId) {
    await loadDashboard(state.currentStoreId);
  }
}

function openIntakeModal() {
  const modal = qs("#intakeModal");
  if (!modal) return;
  resetIntakeForm();
  modal.hidden = false;
  modal.inert = false;
  modal.setAttribute("aria-hidden", "false");
  modal.classList.add("open");
  qs("#intakeStoreName")?.focus();
}

function resetIntakeForm() {
  const form = qs("#intakeForm");
  if (form) form.reset();
  const hint = qs("#intakePreviewHint");
  if (hint) {
    if (!hint.dataset.defaultText) {
      hint.dataset.defaultText = hint.textContent || "填完后可先预览完备度，再提交建店。";
    }
    hint.textContent = hint.dataset.defaultText;
  }
  const submitBtn = qs("#intakeSubmitBtn");
  if (submitBtn) {
    if (!submitBtn.dataset.defaultLabel) {
      submitBtn.dataset.defaultLabel = submitBtn.textContent || "提交建店";
    }
    submitBtn.disabled = false;
    submitBtn.textContent = submitBtn.dataset.defaultLabel;
  }
}

function closeIntakeModal({ reset = false } = {}) {
  const modal = qs("#intakeModal");
  if (!modal) return;
  modal.setAttribute("aria-hidden", "true");
  modal.classList.remove("open");
  modal.inert = true;
  modal.hidden = true;
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
  if (reset) resetIntakeForm();
}

function intakeFormPayload() {
  return {
    store_name: (qs("#intakeStoreName")?.value || "").trim(),
    city: (qs("#intakeCity")?.value || "").trim() || null,
    category: (qs("#intakeCategory")?.value || "").trim() || null,
    audience: (qs("#intakeAudience")?.value || "").trim() || null,
    pain: (qs("#intakePain")?.value || "").trim() || null,
    menu_items: [],
    daily_metrics: [],
    raw_assets: [],
  };
}

async function previewIntakeForm() {
  const payload = intakeFormPayload();
  if (!payload.store_name) {
    notifyError("请先填写门店名称");
    return;
  }
  const hint = qs("#intakePreviewHint");
  try {
    const result = await fetchJson("/workspace/intake/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (hint) {
      hint.textContent = `${result.message || "已预览"} · 完备度 ${result.readiness_score ?? "—"}`;
    }
    notifySuccess(result.message || "预览完成");
  } catch (error) {
    notifyError(error.message || "预览失败");
  }
}

async function submitIntakeForm(event) {
  event?.preventDefault?.();
  const payload = intakeFormPayload();
  if (!payload.store_name) {
    notifyError("请先填写门店名称");
    return;
  }
  const ref = window.localStorage.getItem("mealky_ref_artifact");
  if (ref) payload.referral_artifact_id = ref;
  const btn = qs("#intakeSubmitBtn");
  const original = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "提交中…";
  }
  try {
    const result = await fetchJson("/workspace/intake/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const nextStoreId = String(result.store_id || "").trim();
    closeIntakeModal({ reset: true });
    await loadStores();
    if (nextStoreId) {
      state.currentStoreId = nextStoreId;
      persistStoreId(nextStoreId);
      state.activeWorkspace = "section-overview";
      state.focusOverrideCard = null;
      state.pendingWorkThreadId = null;
      state._fullDashboardLoaded = false;
      renderStoreSelector();
      await loadDashboard(nextStoreId);
      closeIntakeModal({ reset: true });
    }
    if (ref) window.localStorage.removeItem("mealky_ref_artifact");
    notifySuccess("门店已接入，MealKey 开始接手");
  } catch (error) {
    notifyError(error.message || "建店失败");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = original || "提交建店";
    }
  }
}

async function loadDashboard(storeId, { forceFull = false } = {}) {
  state.currentStoreId = storeId;
  persistStoreId(storeId);
  const stayHome =
    !forceFull &&
    isHomeWorkspace(state.activeWorkspace || "section-overview");
  if (stayHome) {
    state._fullDashboardLoaded = false;
    await loadHomeWorkspace(storeId);
    return;
  }
  const [dashboard, competitionMap, collectionRuns, platformIntel, platformLinks, settingsOverview, runtimeWorkspace] =
    await Promise.all([
      fetchDashboardBundle(storeId),
      fetchJson(`/stores/${storeId}/competition/map`).catch(() => null),
      fetchJson(`/stores/${storeId}/competition/collection-runs`).catch(() => ({
        runs: [],
      })),
      fetchJson("/v1/platform-intel?limit=20").catch(() => ({
        items: [],
        last_run: null,
        sources: [],
      })),
      fetchJson(`/workspace/stores/${storeId}/platform-links`).catch(() => ({
        links: [],
      })),
      fetchJson(
        `/settings/overview?store_id=${encodeURIComponent(storeId)}`,
      ).catch(() => null),
      fetchRuntimeWorkspace(storeId),
    ]);
  state.dashboard = dashboard;
  state.runtimeWorkspace = runtimeWorkspace;
  state.competitionMap = competitionMap;
  state.collectionRuns = collectionRuns.runs || [];
  state.platformIntel = platformIntel || { items: [], last_run: null, sources: [] };
  state.platformLinks = platformLinks.links || [];
  state.settingsOverview = settingsOverview;
  state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
  state.enterpriseSettings = settingsOverview?.enterprise || state.enterpriseSettings;
  await fetchSensingBundle(storeId);
  state._fullDashboardLoaded = true;
  renderDashboard();
}

async function refreshDashboard() {
  if (!state.currentStoreId) return;
  const button = qs("#refreshBtn");
  const originalLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "刷新中…";
  }
  try {
    const stayHome = isHomeWorkspace(state.activeWorkspace || "section-overview");
    if (stayHome) {
      state._fullDashboardLoaded = false;
      await loadHomeWorkspace(state.currentStoreId);
      return;
    }
    const [dashboard, competitionMap, collectionRuns, platformIntel, platformLinks, settingsOverview, runtimeWorkspace] =
      await Promise.all([
        fetchDashboardBundle(state.currentStoreId, { refresh: true }),
        fetchJson(`/stores/${state.currentStoreId}/competition/map`).catch(() => null),
        fetchJson(`/stores/${state.currentStoreId}/competition/collection-runs`).catch(
          () => ({ runs: [] }),
        ),
        fetchJson("/v1/platform-intel?limit=20").catch(() => ({
          items: [],
          last_run: null,
          sources: [],
        })),
        fetchJson(`/workspace/stores/${state.currentStoreId}/platform-links`).catch(
          () => ({ links: [] }),
        ),
        fetchJson(
          `/settings/overview?store_id=${encodeURIComponent(state.currentStoreId)}`,
        ).catch(() => null),
        fetchRuntimeWorkspace(state.currentStoreId),
      ]);
    state.dashboard = dashboard;
    state.runtimeWorkspace = runtimeWorkspace;
    state.competitionMap = competitionMap;
    state.collectionRuns = collectionRuns.runs || [];
    state.platformIntel = platformIntel || { items: [], last_run: null, sources: [] };
    state.platformLinks = platformLinks.links || [];
    state.settingsOverview = settingsOverview;
    state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
  state.enterpriseSettings = settingsOverview?.enterprise || state.enterpriseSettings;
    await fetchSensingBundle(state.currentStoreId);
    state._fullDashboardLoaded = true;
    renderDashboard();
  } catch (error) {
    notifyError(`看板刷新失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
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

async function loadEnterpriseSettings(storeId = state.currentStoreId) {
  if (!storeId) return null;
  try {
    const enterprise = await fetchJson(`/settings/stores/${storeId}/enterprise`);
    state.enterpriseSettings = enterprise;
    if (state.settingsOverview) state.settingsOverview.enterprise = enterprise;
    if (qs("#ownerProfileModal")?.classList.contains("open")) {
      fillEnterpriseSettingsForm(enterprise);
    }
    return enterprise;
  } catch (_) {
    return null;
  }
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

async function reloadSettingsOverview() {
  if (!state.currentStoreId) return;
  state.settingsOverview = await fetchJson(
    `/settings/overview?store_id=${encodeURIComponent(state.currentStoreId)}`,
  );
  renderSettingsOverview();
  renderGuide();
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

/* ── 成本管理 (Track B: Business Truth) ── */

async function uploadCostSheet(file) {
  if (!state.currentStoreId) {
    notifyError("请先选择门店");
    return null;
  }
  const form = new FormData();
  form.set("file", file, file.name);
  try {
    const response = await fetch(
      `/stores/${encodeURIComponent(state.currentStoreId)}/cost/import`,
      {
        method: "POST",
        headers: apiAuthHeaders(),
        body: form,
      },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `上传失败：${response.status}`);
    }
    const report = await response.json();
    const matched = report.matched || 0;
    const total = report.total_rows || 0;
    const unmatched = report.unmatched || 0;
    if (report.error) {
      notifyError(report.error);
    } else if (unmatched > 0) {
      notifyInfo(
        `成本表已导入：${matched}/${total} 个商品匹配成功，${unmatched} 个未匹配（需人工确认）。利润计算已切换为真实模式。`,
      );
    } else {
      notifySuccess(`成本表导入成功：${matched} 个商品成本已更新，利润计算更准了。`);
    }
    // 刷新首页,让利润数据从 proxy 切换到 observed
    if (state.currentStoreId) {
      loadHomeWorkspace(state.currentStoreId).catch(() => null);
    }
    return report;
  } catch (error) {
    notifyError(error.message || "成本表导入失败");
    return null;
  }
}

async function fetchCostCoverage() {
  if (!state.currentStoreId) return null;
  try {
    return await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/cost/coverage`,
    );
  } catch (_) {
    return null;
  }
}

async function fetchCostItems() {
  if (!state.currentStoreId) return null;
  try {
    return await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/cost/items`,
    );
  } catch (_) {
    return null;
  }
}

/* ── 经营数据导入 (补足平台真实数据短板) ── */

const IMPORT_TYPES = {
  funnel: { label: "经营数据", endpoint: "/import/funnel" },
  ads: { label: "推广投流", endpoint: "/import/ads" },
  reviews: { label: "评价数据", endpoint: "/import/reviews" },
  campaigns: { label: "活动数据", endpoint: "/import/campaigns" },
  orders: { label: "订单明细", endpoint: "/import/orders" },
  ops: { label: "运营指标", endpoint: "/import/ops" },
};

async function uploadBusinessData(file, importType) {
  if (!state.currentStoreId) { notifyError("请先选择门店"); return null; }
  const config = IMPORT_TYPES[importType];
  if (!config) { notifyError("未知的导入类型"); return null; }
  const form = new FormData();
  form.set("file", file, file.name);
  try {
    const response = await fetch(
      `/stores/${encodeURIComponent(state.currentStoreId)}${config.endpoint}`,
      { method: "POST", headers: apiAuthHeaders(), body: form },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `上传失败：${response.status}`);
    }
    const report = await response.json();
    if (report.error) { notifyError(report.error); }
    else { notifySuccess(report.message || `${config.label}导入成功`); }
    if (state.currentStoreId) { loadHomeWorkspace(state.currentStoreId).catch(() => null); }
    return report;
  } catch (error) {
    notifyError(error.message || "数据导入失败");
    return null;
  }
}

async function fetchDataCoverage() {
  if (!state.currentStoreId) return null;
  try {
    return await fetchJson(`/stores/${encodeURIComponent(state.currentStoreId)}/import/coverage`);
  } catch (_) { return null; }
}

async function fetchSeedLaunch() {
  if (!state.currentStoreId) return null;
  try {
    const seed = await fetchJson(`/stores/${encodeURIComponent(state.currentStoreId)}/seed-launch`);
    state.seedLaunch = seed;
    return seed;
  } catch (_) {
    state.seedLaunch = null;
    return null;
  }
}

function startSeedImport(key) {
  const step = (state.seedLaunch?.onboarding?.steps || []).find((item) => item.key === key);
  if (step?.how) notifyInfo(step.how);
  if (key === "cost") {
    qs("#commandBarCostInput")?.click();
    return;
  }
  const typeMap = { orders: "orders", funnel: "funnel", reviews: "reviews", ads: "ads" };
  const importType = typeMap[key];
  if (!importType) {
    notifyInfo("这份请点「导入经营数据」按提示上传。");
    return;
  }
  state.pendingImportType = importType;
  qs("#commandBarImportInput")?.click();
}
