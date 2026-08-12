/* MealKey UI — mutate actions, chat asks, goals, experiments, platform, profile */

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

function defaultOwnerAvatarUrl() {
  return "/static/brand/owner-avatar-default.svg";
}

function setAvatarPhoto(el, photo, initial) {
  if (!el) return;
  let img = el.querySelector("img.mk-avatar-photo");
  if (!img) {
    img = document.createElement("img");
    img.className = "mk-avatar-photo";
    img.alt = "";
    img.decoding = "async";
    el.insertBefore(img, el.firstChild);
  }
  const clearText = () => {
    Array.from(el.childNodes).forEach((n) => {
      if (n.nodeType === Node.TEXT_NODE) n.textContent = "";
    });
  };
  const showInitial = () => {
    el.classList.remove("has-photo");
    el.style.backgroundImage = "";
    img.removeAttribute("src");
    img.hidden = true;
    clearText();
    el.appendChild(document.createTextNode(initial || "王"));
  };
  const showPhoto = (src) => {
    el.classList.add("has-photo");
    el.style.backgroundImage = "";
    img.hidden = false;
    clearText();
    img.onload = () => {
      el.classList.add("has-photo");
      clearText();
    };
    img.onerror = () => {
      if (src !== defaultOwnerAvatarUrl()) {
        showPhoto(defaultOwnerAvatarUrl());
        return;
      }
      showInitial();
    };
    if (img.src && img.getAttribute("src") === src && img.complete && img.naturalWidth) {
      el.classList.add("has-photo");
      clearText();
      return;
    }
    img.src = src;
  };
  if (photo) showPhoto(photo);
  else showInitial();
}

function applyOwnerProfileUI(profile) {
  const data = profile || state.ownerProfile || {};
  const name = String(data.display_name || "老板").trim() || "老板";
  const initial = String(data.avatar_initial || name.slice(0, 1) || "王").slice(0, 1);
  const photo = data.avatar_data_url || defaultOwnerAvatarUrl();

  const sidebarName = qs("#sidebarOwnerName");
  if (sidebarName) sidebarName.textContent = name;
  const topName = qs("#mkOwnerName");
  if (topName) topName.textContent = name;

  setAvatarPhoto(qs("#mkOwnerAvatarFace"), photo, initial);
  setAvatarPhoto(qs("#sidebarOwnerAvatar"), photo, initial);

  const preview = qs("#ownerAvatarPreview");
  if (preview && !qs("#ownerProfileModal")?.classList.contains("open")) {
    setAvatarPhoto(preview, photo, initial);
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
    setAvatarPhoto(preview, state.pendingAvatarDataUrl || defaultOwnerAvatarUrl(), initial);
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
    const result = await fetchJson(`/workspace/stores/${state.currentStoreId}/read-file?${params}`, {
      method: "POST",
    });
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
  fetchJson(`/stores/${state.currentStoreId}/goals/sync`, { method: "POST" }).catch(
    () => null,
  );
  renderWorkRail();
  renderContextRail();
  renderDecisionHost(currentNeedCard());
  return goalReq;
}

async function submitInterviewAnswer(answer, options = {}) {
  if (!state.currentStoreId || !answer?.trim()) return null;
  const card = currentNeedCard();
  const key =
    options.key ||
    (typeof interviewKeyFromCard === "function" ? interviewKeyFromCard(card) : null) ||
    interviewGapKeys()[0] ||
    null;
  const result = await fetchJson(
    `/stores/${state.currentStoreId}/understanding/interview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, answer: answer.trim() }),
    },
  );
  if (result?.understanding) state.understanding = result.understanding;
  if (result?.workspace) state.runtimeWorkspace = result.workspace;
  if (typeof interviewStillBlocking === "function" && interviewStillBlocking(result)) {
    state.focusOverrideCard = understandingCardFromInterview(result);
  } else {
    state.focusOverrideCard = null;
    if (typeof exitExclusivePathMode === "function") exitExclusivePathMode();
  }
  return result;
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
      // 访谈态优先走 MUE interview；其余统一 /v1/intent，失败再 ask
      const focusCard = currentNeedCard();
      if (isUnderstandingCard(focusCard)) {
        try {
          const key = interviewKind(focusCard);
          response = await fetchJson(
            `/stores/${state.currentStoreId}/understanding/interview`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ key, answer: trimmed }),
            },
          );
          if (response?.understanding) state.understanding = response.understanding;
          if (!response.answer && !response.reply) {
            response = {
              ...response,
              answer:
                response?.question?.prompt ||
                response?.next_question?.prompt ||
                "已记下。我会按这个继续经营。",
              intent: "understanding_update",
            };
          }
        } catch (_interviewError) {
          response = null;
        }
      }
      if (!response) {
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
    if (response.decision && typeof currentNeedCard === "function") {
      const d = response.decision;
      if (d.kind !== "setting" && d.kind !== "constraint") {
        state.focusOverrideCard = {
          id: `decision:${d.action_type || "nba"}`,
          title: d.action || response.conclusion || "今天这一件",
          why_now: response.expected || "确认后我继续推进。",
          need_from_owner: d.execution_tier === "confirm" ? "需要你确认后执行" : "方案已备好",
          interrupt_reason: d.execution_tier === "confirm" ? "confirm" : "report_result",
          arbiter_state: d.execution_tier === "confirm" ? "confirm" : "report_result",
          meta: d.execution_tier || "decision",
          guide_type: d.execution_tier === "confirm" ? "APPROVAL" : "INFO",
        };
      }
    }
    if (response.workspace) {
      state.runtimeWorkspace = response.workspace;
    }
    if (response.daily_plan) {
      state.dailyPlan = response.daily_plan.plan || response.daily_plan;
    }
    if (response.intent === "goal") {
      notifySuccess("目标已建立，已进入经营线程");
    } else if (response.intent === "action") {
      notifySuccess("已准备好这一件事");
    } else if (response.intent === "understanding_update") {
      const stillBlocking =
        response?.understanding?.mos_satisfied === false ||
        (Array.isArray(response?.understanding?.mos_blocking_fields) &&
          response.understanding.mos_blocking_fields.length) ||
        Boolean(response?.question || response?.next_question);
      if (stillBlocking) {
        showUnderstandingCard(understandingCardFromInterview(response));
      } else {
        state.focusOverrideCard = null;
        if (typeof exitExclusivePathMode === "function") exitExclusivePathMode();
      }
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
      if (!document.body.classList.contains("interviewing")) {
        renderHomeChatThread();
      }
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
