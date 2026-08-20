/* MealKey UI — bootstrap / init */

function applyPhonePreviewMode() {
  const params = new URLSearchParams(window.location.search);
  const inPreview =
    params.get("mobile_preview") === "1" ||
    window.self !== window.top;
  document.body.classList.toggle("is-phone-preview", inPreview);
  const ref = params.get("ref");
  if (ref) window.localStorage.setItem("mealky_ref_artifact", ref);
}

function captureLaunchToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("api_token") || params.get("access_token");
  if (!token) return;
  window.localStorage.setItem("mealky_api_token", token);
  window.localStorage.removeItem("mealky_access_token");
  params.delete("api_token");
  params.delete("access_token");
  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState({}, "", next);
}

function showAuthGate(message) {
  const gate = qs("#mkAuthGate");
  const hint = qs("#mkAuthGateHint");
  const input = qs("#mkAuthTokenInput");
  if (hint && message) hint.textContent = message;
  if (gate) gate.hidden = false;
  input?.focus();
  return new Promise((resolve) => {
    const form = qs("#mkAuthGateForm");
    if (!form) {
      resolve("");
      return;
    }
    const onSubmit = (event) => {
      event.preventDefault();
      const value = String(input?.value || "").trim();
      if (!value) return;
      window.localStorage.setItem("mealky_api_token", value);
      window.localStorage.removeItem("mealky_access_token");
      if (gate) gate.hidden = true;
      form.removeEventListener("submit", onSubmit);
      resolve(value);
    };
    form.addEventListener("submit", onSubmit);
  });
}

async function ensureWorkspaceAuth() {
  const authRequired = Boolean(state.publicConfig?.auth?.required);
  if (authRequired && !window.localStorage.getItem("mealky_api_token")) {
    await showAuthGate("请输入访问口令后进入店长工作台。");
  }
  let authed = await ensureAccessToken();
  if (!authed && authRequired) {
    await showAuthGate(state.lastAuthError?.message || "口令无效，请重试。");
    authed = await ensureAccessToken();
  }
  if (!authed && state.lastAuthError) {
    if (state.lastAuthError.type === "network") {
      notifyError("网络异常，无法连接服务器。请检查网络后刷新页面。");
    } else if (state.lastAuthError.type === "token_expired") {
      notifyError("登录已过期，请重新输入访问口令。");
    }
  }
  return authed;
}

async function init() {
  applyPhonePreviewMode();
  captureLaunchToken();
  ensureMatrixWorkspace();
  bindSidebarNav();
  bindEvents();
  initOpsRailCollapsed();
  syncSidebarForViewport();
  scrollToSection(state.activeWorkspace);
  renderChatMessages();
  if (typeof applyOwnerProfileUI === "function") applyOwnerProfileUI({});
  state.publicConfig = await fetchJson("/public/config").catch(() => null);
  if (typeof renderDeploymentTierBanner === "function") renderDeploymentTierBanner();
  await ensureWorkspaceAuth();
  try {
    await loadStores();
  } catch (error) {
    if (error?.status === 401) {
      await showAuthGate("需要访问口令才能进入。");
      await ensureAccessToken();
      await loadStores();
    } else {
      throw error;
    }
  }
  if (!state.stores.length) {
    await bootstrapWorkspace();
    return;
  }
  await loadDashboard(state.currentStoreId);
  if (typeof loadOwnerProfile === "function") {
    loadOwnerProfile(state.currentStoreId).catch(() => null);
  }
  if (typeof loadEnterpriseSettings === "function") {
    loadEnterpriseSettings(state.currentStoreId).catch(() => null);
  }
  if (typeof renderDataCoveragePanel === "function") renderDataCoveragePanel();
  if (typeof bindDecisionCoreButtons === "function") bindDecisionCoreButtons();
  if (typeof renderCostItemsPanel === "function") renderCostItemsPanel();
}

init().catch((error) => {
  const title = qs("#greetingTitle") || qs("#topbarTitle");
  const summary = qs("#greetingStore") || qs("#topbarSummary");
  if (title) title.textContent = "经营队列加载失败";
  if (summary) summary.textContent = error.message;
});
