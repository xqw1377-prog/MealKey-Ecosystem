/* MealKey UI — bindEvents and DOM listeners */

function bindEvents() {
  qs("#storeSelect").addEventListener("change", async (event) => {
    await loadDashboard(event.target.value);
  });

  qs("#bootstrapBtn").addEventListener("click", bootstrapWorkspace);
  qs("#refreshBtn").addEventListener("click", refreshDashboard);
  qs("#mkIntakeBtn")?.addEventListener("click", openIntakeModal);
  qs("#intakePreviewBtn")?.addEventListener("click", previewIntakeForm);
  qs("#intakeForm")?.addEventListener("submit", submitIntakeForm);
  qsa("[data-intake-modal-close]").forEach((el) => {
    el.addEventListener("click", closeIntakeModal);
  });
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
    if (qs("#homeChatInput") && qs("#homeChatDock")) {
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
    if (preview) setAvatarPhoto(preview, defaultOwnerAvatarUrl(), "王");
  });
  qs("#ownerAvatarFileInput")?.addEventListener("change", async (event) => {
    const file = event.target?.files?.[0];
    if (!file) return;
    try {
      const dataUrl = await readAvatarFileAsDataUrl(file);
      state.pendingAvatarDataUrl = dataUrl;
      const preview = qs("#ownerAvatarPreview");
      if (preview) setAvatarPhoto(preview, dataUrl, "王");
    } catch (error) {
      notifyError(error.message);
    } finally {
      event.target.value = "";
    }
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
  qs("#mkWorkRail")?.addEventListener("dragstart", (event) => {
    const railItem = event.target.closest("[data-rail-work]");
    if (railItem) startRailCardDrag(railItem, event.dataTransfer);
  });
  qs("#mkContextRail")?.addEventListener("click", (event) => {
    const feedItem = event.target.closest("[data-rail-work]");
    if (feedItem) {
      enterWorkFromRail(feedItem);
      const main = qs("#section-overview");
      if (main) main.scrollTo({ top: 0, behavior: "smooth" });
    }
  });
  qs("#mkContextRail")?.addEventListener("keydown", (event) => {
    const feedItem = event.target.closest("[data-rail-work]");
    if (!feedItem || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    enterWorkFromRail(feedItem);
  });
  qs("#mkContextRail")?.addEventListener("dragstart", (event) => {
    const feedItem = event.target.closest("[data-rail-work]");
    if (feedItem) startRailCardDrag(feedItem, event.dataTransfer);
  });
  qs("#mkDecisionHost")?.addEventListener("click", async (event) => {
    const opt = event.target.closest("[data-intent-fill]");
    if (!opt) return;
    if (typeof confirmInterviewChoice === "function") {
      const handled = await confirmInterviewChoice(opt);
      if (handled) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
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
    const main = qs("#section-overview");
    if (main) main.scrollTo({ top: 0, behavior: "smooth" });
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
    if (isMobileHomeViewport()) {
      if (state.rightRailOpen) closeMobileSheets();
      else openMobilePanel("diary");
      return;
    }
    setRightRailOpen(!state.rightRailOpen);
  });
  qs("#closeRightRailBtn")?.addEventListener("click", () => setRightRailOpen(false));
  qs("#sidebarToggle")?.addEventListener("click", toggleSidebar);
  qs("#sidebarBackdrop")?.addEventListener("click", () => setSidebarOpen(false));
  qs("#mkSheetBackdrop")?.addEventListener("click", () => closeMobileSheets());
  qs("#mkSafeModeBanner")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    enterSafeModePath().catch((error) => notifyError(error.message || "进入确认失败"));
  });
  qsa("[data-mobile-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.mobileTab || "today";
      if (tab === "threads") {
        if (document.body.classList.contains("show-work-rail")) closeMobileSheets();
        else openMobilePanel("threads");
        return;
      }
      if (tab === "diary") {
        if (document.body.classList.contains("right-rail-open")) closeMobileSheets();
        else openMobilePanel("diary");
        return;
      }
      closeMobileSheets();
      const main = qs("#section-overview");
      if (main) main.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMobileSheets();
  });
  qs("#openHelpBtn")?.addEventListener("click", async () => {
    if (qs("#homeChatInput") && qs("#homeChatDock")) openHomeChatMode();
    else scrollToSection("section-ai");
    const prompt = "我是新用户，请用三步带我上手：先确认门店资料，再对接平台，最后看今天该做什么。";
    await askStoreManager(prompt, { stayOnHome: Boolean(qs("#homeChatInput") && qs("#homeChatDock")) });
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
        const hasRailCard = isRailCardTransfer(event.dataTransfer);
        if (!files.length && !hasRailCard) return;
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
      const railCard = readRailCardTransfer(event.dataTransfer);
      if (!files.length && !railCard) return;
      event.preventDefault();
      setHomeChatDropState(false);
      if (files.length) {
        ingestHomeAttachments(files, { source: "drop" });
        return;
      }
      ingestRailCardToChat(railCard, { replace: true, source: "drag" });
    });
  }
  document.addEventListener("dragover", (event) => {
    const files = Array.from(event.dataTransfer?.items || []).filter((item) => item.kind === "file");
    const hasRailCard = isRailCardTransfer(event.dataTransfer);
    if (!files.length && !hasRailCard) return;
    event.preventDefault();
  });
  document.addEventListener("drop", (event) => {
    const files = Array.from(event.dataTransfer?.files || []);
    const railCard = readRailCardTransfer(event.dataTransfer);
    if (!files.length && !railCard) return;
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
    if (isMobileHomeViewport()) {
      // 切到手机宽度时收敛为「今天」主舞台
      if (!state._wasMobileHome) {
        state._wasMobileHome = true;
        closeMobileSheets();
      } else {
        setOpsRailCollapsed(state.opsRailCollapsed);
      }
    } else {
      state._wasMobileHome = false;
      document.body.classList.remove("show-work-rail");
      syncMobileSheetBackdrop();
      setOpsRailCollapsed(state.opsRailCollapsed);
    }
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
          await fetchJson(`/stores/${state.currentStoreId}/goals/${goalId}?${q}`, {
            method: "PATCH",
          });
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
      const text = (intentFill.dataset.intentFill || intentFill.textContent || "").trim();
      if (!text) return;
      if (typeof confirmInterviewChoice === "function" && (await confirmInterviewChoice(intentFill))) {
        return;
      }
      if (document.body.classList.contains("view-home")) openHomeChatMode();
      await askStoreManager(text, {
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
