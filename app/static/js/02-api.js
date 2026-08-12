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

async function ensureAccessToken() {
  if (window.localStorage.getItem("mealky_access_token")) return true;
  const apiToken = window.localStorage.getItem("mealky_api_token");
  if (!apiToken) return false;
  try {
    const response = await fetch("/auth/token", {
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
    if (!response.ok) return false;
    const payload = await response.json();
    if (payload.access_token) {
      window.localStorage.setItem("mealky_access_token", payload.access_token);
      return true;
    }
  } catch (_) {
    /* ignore */
  }
  return false;
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
    refresh ? { method: "POST" } : undefined,
  );
}

async function fetchRuntimeWorkspace(storeId) {
  return fetchJson(`/v1/stores/${storeId}/workspace`).catch(() => null);
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
  if (rw.left.need_you?.length) oq.need_you = rw.left.need_you;
  if (rw.left.active?.length) oq.working = rw.left.active;
  if (rw.left.completed?.length) oq.results = rw.left.completed;
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
  const [runtimeWorkspace, settingsOverview, understanding, platformLinks] = await Promise.all([
    fetchRuntimeWorkspace(storeId),
    fetchJson(`/settings/overview?store_id=${encodeURIComponent(storeId)}`).catch(
      () => null,
    ),
    fetchJson(`/stores/${storeId}/understanding`).catch(() => null),
    fetchJson(`/workspace/stores/${storeId}/platform-links`).catch(() => ({ links: [] })),
  ]);
  state.runtimeWorkspace = runtimeWorkspace;
  state.settingsOverview = settingsOverview;
  state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
  state.understanding = understanding;
  state.platformLinks = platformLinks?.links || [];
  if (!state.dashboard) {
    state.dashboard = {
      store: settingsOverview?.store || { id: storeId, name: "门店" },
      experiments: [],
      question_examples: [],
    };
  }
  await pollStoreNotifications(storeId);
  renderHomeShell();
  applyOwnerProfileUI(state.ownerProfile || settingsOverview?.owner);
  loadOwnerProfile(storeId).catch(() => null);
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
      fetchJson(`/stores/${storeId}/manager_brief`).catch(() => null),
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

function openIntakeModal() {
  const modal = qs("#intakeModal");
  if (!modal) return;
  modal.setAttribute("aria-hidden", "false");
  modal.classList.add("open");
  qs("#intakeStoreName")?.focus();
}

function closeIntakeModal() {
  const modal = qs("#intakeModal");
  if (!modal) return;
  modal.setAttribute("aria-hidden", "true");
  modal.classList.remove("open");
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
    closeIntakeModal();
    await loadStores();
    if (result.store_id) {
      state.currentStoreId = result.store_id;
      state._fullDashboardLoaded = false;
      await loadDashboard(result.store_id);
    }
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
  const stayHome =
    !forceFull &&
    isHomeWorkspace(state.activeWorkspace || "section-overview");
  if (stayHome) {
    state._fullDashboardLoaded = false;
    await loadHomeWorkspace(storeId);
    return;
  }
  const [dashboard, competitionMap, collectionRuns, platformLinks, settingsOverview, runtimeWorkspace] =
    await Promise.all([
      fetchDashboardBundle(storeId),
      fetchJson(`/stores/${storeId}/competition/map`).catch(() => null),
      fetchJson(`/stores/${storeId}/competition/collection-runs`).catch(() => ({
        runs: [],
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
  state.platformLinks = platformLinks.links || [];
  state.settingsOverview = settingsOverview;
  state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
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
    const [dashboard, competitionMap, collectionRuns, platformLinks, settingsOverview, runtimeWorkspace] =
      await Promise.all([
        fetchDashboardBundle(state.currentStoreId, { refresh: true }),
        fetchJson(`/stores/${state.currentStoreId}/competition/map`).catch(() => null),
        fetchJson(`/stores/${state.currentStoreId}/competition/collection-runs`).catch(
          () => ({ runs: [] }),
        ),
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
    state.platformLinks = platformLinks.links || [];
    state.settingsOverview = settingsOverview;
    state.ownerProfile = settingsOverview?.owner || state.ownerProfile;
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
