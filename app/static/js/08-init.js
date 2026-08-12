/* MealKey UI — bootstrap / init */

function applyPhonePreviewMode() {
  const params = new URLSearchParams(window.location.search);
  const inPreview =
    params.get("mobile_preview") === "1" ||
    window.self !== window.top;
  document.body.classList.toggle("is-phone-preview", inPreview);
}

async function init() {
  applyPhonePreviewMode();
  ensureMatrixWorkspace();
  bindSidebarNav();
  bindEvents();
  initOpsRailCollapsed();
  syncSidebarForViewport();
  scrollToSection(state.activeWorkspace);
  renderChatMessages();
  /* 首屏先挂上默认头像，避免只剩「王」字 */
  if (typeof applyOwnerProfileUI === "function") applyOwnerProfileUI({});
  state.publicConfig = await fetchJson("/public/config").catch(() => null);
  await ensureAccessToken();
  await loadStores();
  if (!state.stores.length) {
    await bootstrapWorkspace();
    return;
  }
  await loadDashboard(state.currentStoreId);
  if (typeof loadOwnerProfile === "function") {
    loadOwnerProfile(state.currentStoreId).catch(() => null);
  }
}

init().catch((error) => {
  const title = qs("#greetingTitle") || qs("#topbarTitle");
  const summary = qs("#greetingStore") || qs("#topbarSummary");
  if (title) title.textContent = "经营队列加载失败";
  if (summary) summary.textContent = error.message;
});
