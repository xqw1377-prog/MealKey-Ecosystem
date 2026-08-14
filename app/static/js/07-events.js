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
  qs("#collectPlatformIntelBtn")?.addEventListener("click", () => {
    collectPlatformIntelNow().catch((error) => notifyError(error.message));
  });
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
  qs("#sidebarOwnerBtn")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openOwnerProfileModal();
  });
  qs("#ownerBillCycles")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-bill-cycle]");
    if (!card) return;
    subscribeOwnerBillCycle(card.dataset.billCycle).catch((error) => notifyError(error.message));
  });
  qs("#ownerWalletTopups")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-wallet-topup]");
    if (!btn) return;
    topupOwnerWallet(btn.dataset.walletTopup).catch((error) => notifyError(error.message));
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
    const platformBtn = event.target.closest("[data-loop-execute-platform]");
    if (platformBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = platformBtn.dataset.loopExecutePlatform;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      platformBtn.disabled = true;
      try {
        await executeLoopPlatform(storeId, loopId);
        notifySuccess("已经改到平台并读回确认。这件事进入观察，到期我会回来看结果。");
        await loadHomeWorkspace(storeId);
      } catch (error) {
        platformBtn.disabled = false;
        notifyError(error.message || "没能写回平台，这件事还停在现在");
      }
      return;
    }
    const evidenceBtn = event.target.closest("[data-loop-evidence]");
    if (evidenceBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = evidenceBtn.dataset.loopEvidence;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      const note = qs("#mkLoopEvidenceNote")?.value || "";
      evidenceBtn.disabled = true;
      try {
        await attachLoopEvidence(storeId, loopId, { kind: "note", note, by: "OWNER" });
        notifySuccess("证据已记下。有证据后才能点门店已做完。");
        await loadHomeWorkspace(storeId);
      } catch (error) {
        evidenceBtn.disabled = false;
        notifyError(error.message || "没能记下证据");
      }
      return;
    }
    const executedBtn = event.target.closest("[data-loop-executed]");
    if (executedBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = executedBtn.dataset.loopExecuted;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      executedBtn.disabled = true;
      try {
        await markLoopExecuted(storeId, loopId);
        notifySuccess("已记下。这件事进入观察，到期我会回来看结果。");
        await loadHomeWorkspace(storeId);
      } catch (error) {
        executedBtn.disabled = false;
        notifyError(error.message || "没能记下执行状态");
      }
      return;
    }
    const skipBtn = event.target.closest("[data-loop-skip]");
    if (skipBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = skipBtn.dataset.loopSkip;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      skipBtn.disabled = true;
      try {
        await markLoopNotExecuted(storeId, loopId);
        notifySuccess("好，这一次先不改。");
        await loadHomeWorkspace(storeId);
      } catch (error) {
        skipBtn.disabled = false;
        notifyError(error.message || "没能记下");
      }
      return;
    }
    const ackBtn = event.target.closest("[data-loop-ack]");
    if (ackBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = ackBtn.dataset.loopAck;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      ackBtn.disabled = true;
      try {
        await markLoopAcked(storeId, loopId);
        notifySuccess("记下了。下次同类问题我会按这次结果排序。");
        await loadHomeWorkspace(storeId);
      } catch (error) {
        ackBtn.disabled = false;
        notifyError(error.message || "没能记下");
      }
      return;
    }
    const shareBtn = event.target.closest("[data-loop-share]");
    if (shareBtn) {
      event.preventDefault();
      event.stopPropagation();
      const loopId = shareBtn.dataset.loopShare;
      const storeId = state.currentStoreId;
      if (!loopId || !storeId) return;
      shareBtn.disabled = true;
      try {
        const result = await shareLoopResultCard(storeId, loopId);
        const card = result.share_card || {};
        const url = `${window.location.origin}${card.share_url || `/r/${card.id}`}`;
        const text = `${card.wechat_copy || "一家外卖店刚做出结果。点开就能免费测自己的店。"}\n${url}`;
        try {
          await navigator.clipboard.writeText(text);
          notifySuccess("结果卡已复制，发给同行就能测店");
        } catch (_copyError) {
          notifySuccess(url);
        }
      } catch (error) {
        notifyError(error.message || "还不能分享这次结果");
      } finally {
        shareBtn.disabled = false;
      }
      return;
    }
    const copyBtn = event.target.closest("[data-copy-text]");
    if (copyBtn) {
      event.preventDefault();
      event.stopPropagation();
      try {
        const text = decodeURIComponent(copyBtn.dataset.copyText || "");
        await navigator.clipboard.writeText(text);
        notifySuccess("执行包已复制，去美团后台按步骤用");
      } catch (_error) {
        notifyError("复制失败，请手动选中文案");
      }
      return;
    }
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
  qs("#commandBarCostBtn")?.addEventListener("click", () => {
    qs("#commandBarCostInput")?.click();
  });
  qs("#commandBarPosterBtn")?.addEventListener("click", () => {
    openPromoPosterPlugin().catch((error) => notifyError(error.message));
  });
  qs("#mkWalletBanner")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openOwnerProfileModal({ focus: "wallet" });
  });
  qs("#commandBarCostInput")?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    if (!file) return;
    uploadCostSheet(file).catch((error) => notifyError(error.message || "成本表上传失败"));
    event.target.value = ""; // reset for re-upload
  });
  qs("#mkDataCoveragePanel")?.addEventListener("click", (event) => {
    const importBtn = event.target.closest("[data-seed-import]");
    if (importBtn) {
      event.preventDefault();
      if (typeof startSeedImport === "function") startSeedImport(importBtn.dataset.seedImport);
      return;
    }
    const slaBtn = event.target.closest("[data-sla-loop]");
    if (slaBtn) {
      event.preventDefault();
      const fake = document.createElement("button");
      fake.dataset.railId = slaBtn.dataset.slaLoop || "";
      fake.dataset.railSlot = slaBtn.dataset.slaSlot || "need";
      fake.dataset.workThreadId = slaBtn.dataset.slaLoop || "";
      const strong = document.createElement("strong");
      strong.textContent = slaBtn.dataset.slaTitle || "经营事项";
      fake.appendChild(strong);
      if (typeof enterWorkFromRail === "function") enterWorkFromRail(fake);
      return;
    }
  });
  qs("#commandBarImportBtn")?.addEventListener("click", () => {
    const next = state.seedLaunch?.onboarding?.next;
    if (next?.key && typeof startSeedImport === "function") {
      startSeedImport(next.key);
      return;
    }
    const choice = prompt(
      "选择要导入的数据类型：\n1. 经营数据(曝光/订单/GMV)\n2. 推广投流(花费/点击/CPC)\n3. 评价数据(评分/内容)\n4. 活动数据(活动规则/补贴)\n5. 订单明细(真实销量)\n6. 运营指标(IM回复率/准时率)\n\n输入数字(1-6):",
      "1",
    );
    const typeMap = { "1": "funnel", "2": "ads", "3": "reviews", "4": "campaigns", "5": "orders", "6": "ops" };
    const importType = typeMap[(choice || "").trim()];
    if (!importType) return;
    state.pendingImportType = importType;
    qs("#commandBarImportInput")?.click();
  });
  qs("#commandBarImportInput")?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    if (!file) return;
    const importType = state.pendingImportType || "funnel";
    state.pendingImportType = null;
    uploadBusinessData(file, importType).catch((error) => notifyError(error.message || "数据导入失败"));
    event.target.value = "";
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
  qs("#storeOpsForm")?.addEventListener("submit", (event) => {
    saveStoreOpsRoster(event).catch((error) => notifyError(error.message));
  });
  qs("#copyStoreTaskLinkBtn")?.addEventListener("click", async () => {
    const url = qs("#storeOpsForm")?.elements?.task_url?.value || "";
    if (!url) {
      notifyError("请先保存店长姓名，生成任务页");
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      notifySuccess("已复制门店任务页，发给店长");
    } catch {
      notifyInfo(url);
    }
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
  qs("#settingsCollectIntelBtn")?.addEventListener("click", () => {
    collectPlatformIntelNow().catch((error) => notifyError(error.message));
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

    const copyPack = target.closest("[data-copy-text]");
    if (copyPack) {
      try {
        const text = decodeURIComponent(copyPack.dataset.copyText || "");
        await navigator.clipboard.writeText(text);
        notifySuccess("执行包已复制，去美团后台按步骤用");
      } catch (_error) {
        notifyError("复制失败，请手动选中文案");
      }
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

    const openWallet = target.closest("[data-open-wallet]");
    if (openWallet) {
      openOwnerProfileModal({ focus: "wallet" });
      return;
    }

    const posterTheme = target.closest("[data-poster-theme]");
    if (posterTheme) {
      openPromoPosterPlugin({
        prompt: state.promoPoster?.poster?.dish || "",
        occasion: posterTheme.dataset.posterTheme,
      }).catch((error) => notifyError(error.message));
      return;
    }

    const posterDownload = target.closest("[data-poster-download]");
    if (posterDownload) {
      downloadPromoPosterPng();
      return;
    }

    const posterCopy = target.closest("[data-poster-copy]");
    if (posterCopy) {
      copyPromoPosterText().catch((error) => notifyError(error.message));
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

    const costButton = target.closest("[data-cost-upload]");
    if (costButton) {
      qs("#commandBarCostInput")?.click();
      return;
    }

    const askButton = target.closest("[data-ask-question]");
    if (askButton) {
      await askStoreManager(askButton.dataset.askQuestion);
    }
  });
}
