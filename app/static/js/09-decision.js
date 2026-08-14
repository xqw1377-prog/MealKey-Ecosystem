/* MealKey UI — Decision Core + Execution Plan 前端接入

活动测算 / 活动决策 / 利润诊断 / 推荐预览 / 推荐回滚
这些函数从 app.js 迁移到正式加载的模块。
*/

/* ── Decision Core: 活动测算 ── */

async function calculateCampaign(rule, skuData) {
  if (!state.currentStoreId) return null;
  try {
    return await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/campaign/calculate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule: rule, ...skuData }),
      },
    );
  } catch (e) {
    notifyError("活动测算失败：" + e.message);
    return null;
  }
}

/* ── Decision Core: 活动决策 + 执行 ── */

async function campaignDecideAndExecute(rule, skuData) {
  if (!state.currentStoreId) return;
  try {
    const result = await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/campaign/decide-and-execute`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule: rule, ...skuData }),
      },
    );
    const d = result.decision || {};
    const verdictLabel =
      {
        GREEN: "建议参加",
        YELLOW: "限量测试",
        RED: "不建议",
        BLACK: "无法判断",
      }[d.verdict] || d.verdict;
    if (result.recommendation_id) {
      const lines = [verdictLabel + "：" + (d.strategy || "")];
      if (d.calc && d.calc.profit_per_order_with_campaign != null) {
        lines.push("单均利润 ¥" + d.calc.profit_per_order_with_campaign.toFixed(1));
      }
      if (result.message) lines.push(result.message);
      appendChatMessage("assistant", lines.join("\n"));
      await loadDashboard(state.currentStoreId);
      notifySuccess("已创建活动测试任务");
    } else {
      appendChatMessage(
        "assistant",
        verdictLabel + "：" + (d.reasoning || d.strategy || ""),
      );
    }
  } catch (e) {
    notifyError("活动决策失败：" + e.message);
  }
}

/* ── Decision Core: 利润诊断 ── */

async function diagnoseProfit(current, baseline, ordersCurrent, ordersBaseline) {
  if (!state.currentStoreId) return null;
  try {
    const result = await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/profit/diagnose`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current: current,
          baseline: baseline,
          orders_current: ordersCurrent,
          orders_baseline: ordersBaseline,
        }),
      },
    );
    if (result.conclusion) appendChatMessage("assistant", result.conclusion);
    return result;
  } catch (e) {
    notifyError("利润诊断失败：" + e.message);
    return null;
  }
}

/* ── Execution Plan: 推荐预览 (diff) ── */

async function previewRecommendation(recId) {
  if (!recId) return null;
  try {
    const preview = await fetchJson(
      `/workspace/recommendations/${encodeURIComponent(recId)}/preview`,
    );
    // 渲染 diff 到聊天
    if (preview && preview.changes && preview.changes.length) {
      const lines = ["📋 执行预览："];
      for (const change of preview.changes) {
        const field = change.field || change.label || "";
        const oldVal = change.old_value ?? change.old ?? "—";
        const newVal = change.new_value ?? change.new ?? "—";
        lines.push(`  ${field}: ${oldVal} → ${newVal}`);
      }
      if (preview.expected) lines.push("预期：" + preview.expected);
      appendChatMessage("assistant", lines.join("\n"));
    } else if (preview && preview.mode === "awaiting_platform") {
      appendChatMessage(
        "assistant",
        "这个动作需要在外卖平台后台操作。系统已进入观察窗，到期自动回来检查结果。",
      );
    }
    return preview;
  } catch (e) {
    notifyError("预览失败：" + e.message);
    return null;
  }
}

/* ── Execution Plan: 推荐回滚 ── */

async function rollbackRecommendation(recId) {
  if (!recId) return;
  try {
    const result = await fetchJson(
      `/workspace/recommendations/${encodeURIComponent(recId)}/rollback`,
      { method: "POST" },
    );
    await loadDashboard(state.currentStoreId);
    notifySuccess(result.detail || "已回滚");
    appendChatMessage("assistant", "✅ 已回滚到之前的版本。");
  } catch (e) {
    notifyError("回滚失败：" + e.message);
  }
}

/* ── 数据覆盖度面板渲染 ── */

async function renderDataCoveragePanel() {
  const host = qs("#mkDataCoveragePanel");
  if (!host) return;
  const seed = typeof fetchSeedLaunch === "function" ? await fetchSeedLaunch() : null;
  const steps = seed?.onboarding?.steps || [];
  if (steps.length) {
    const chips = steps
      .map((step) => {
        const ready = Boolean(step.ready);
        const label = `${ready ? "✓" : "○"} ${escapeHtml(step.label || "")}`;
        if (ready) {
          return `<span class="coverage-chip ok">${label}</span>`;
        }
        return `<button type="button" class="coverage-chip missing is-action" data-seed-import="${escapeHtml(step.key)}">${label}</button>`;
      })
      .join("");
    const next = seed.onboarding?.next;
    const sla = seed.daily_sla || {};
    const pending = Array.isArray(sla.pending_confirm) ? sla.pending_confirm : [];
    const due = Array.isArray(sla.due_observe) ? sla.due_observe : [];
    const pendingBtns = pending
      .map(
        (item) =>
          `<button type="button" class="mk-seed-sla-item" data-sla-loop="${escapeHtml(item.id || "")}" data-sla-slot="need" data-sla-title="${escapeHtml(item.title || "")}">${escapeHtml(item.title || "待确认")}</button>`,
      )
      .join("");
    const dueBtns = due
      .map(
        (item) =>
          `<button type="button" class="mk-seed-sla-item" data-sla-loop="${escapeHtml(item.id || "")}" data-sla-slot="waiting" data-sla-title="${escapeHtml(item.title || "")}">${escapeHtml(item.title || "该回看")}</button>`,
      )
      .join("");
    const billing = seed.billing || state.commercialBoard?.billing || {};
    const billStatus = String(state.commercialBoard?.current?.status || "");
    const showTransfer = billing.mode === "bank_transfer" && billStatus !== "paid";
    host.innerHTML = `
      <p class="mk-seed-coach">${escapeHtml(seed.onboarding?.coach || "")}</p>
      <div class="mk-seed-chips">${chips}</div>
      ${
        next
          ? `<p class="mk-seed-how"><strong>下一步：${escapeHtml(next.label || "")}</strong> ${escapeHtml(next.how || "")}</p>`
          : ""
      }
      ${
        seed.profit && !seed.profit.precise_profit
          ? `<p class="mk-seed-how">${escapeHtml(seed.profit.boss_line || "没有成本，不能说今天亏多少")}</p>`
          : ""
      }
      <div class="mk-seed-sla">
        <p><strong>今天三件事</strong> ${escapeHtml(sla.morning_judgment || "今天没有必须你拍板的事")}</p>
        <p>待你确认 ${Number(sla.pending_count || 0)} 件${pendingBtns ? ` · ${pendingBtns}` : ""}</p>
        <p>该回看 ${Number(sla.due_count || 0)} 件${dueBtns ? ` · ${dueBtns}` : ""}</p>
      </div>
      ${
        showTransfer
          ? `<button type="button" class="mk-seed-bill" data-open-wallet>${escapeHtml(billing.instructions_text || "月费 ¥300。对公转账后由运营手工开通。")}</button>`
          : ""
      }
    `;
    renderAdsSummaryPanel();
    return;
  }
  const coverage = await fetchDataCoverage();
  const costCoverage = await fetchCostCoverage();
  if (!coverage && !costCoverage) {
    host.innerHTML = "";
    return;
  }
  const items = [];
  if (coverage) {
    if (coverage.funnel_days > 0)
      items.push(`<span class="coverage-chip ${coverage.funnel_days >= 7 ? "ok" : "warn"}">📊 ${coverage.funnel_days} 天经营数据</span>`);
    if (coverage.ads_days > 0)
      items.push(`<span class="coverage-chip ok">💰 ${coverage.ads_days} 天投流数据</span>`);
    if (coverage.reviews > 0)
      items.push(`<span class="coverage-chip ok">⭐ ${coverage.reviews} 条评价</span>`);
    if (coverage.campaigns > 0)
      items.push(`<span class="coverage-chip ok">🎯 ${coverage.campaigns} 个活动</span>`);
    if (coverage.menu_items > 0) {
      const costPct = coverage.cost_coverage_pct || 0;
      const costClass = costPct >= 80 ? "ok" : costPct > 0 ? "warn" : "missing";
      items.push(`<span class="coverage-chip ${costClass}">🍽️ ${coverage.items_with_cost}/${coverage.menu_items} 商品有成本 (${costPct.toFixed(0)}%)</span>`);
    }
  }
  if (!items.length) {
    host.innerHTML = `<span class="coverage-chip missing">⚠ 尚无真实数据，利润为代理估算。点「导入经营数据」上传平台导出。</span>`;
  } else {
    host.innerHTML = items.join("");
  }

  // 渲染投流摘要面板(CPC/ROAS/趋势)
  renderAdsSummaryPanel();
}

/* ── 投流摘要面板 — 显示 CPC/ROAS/花费/趋势/诊断发现 ── */

function renderAdsSummaryPanel() {
  const host = qs("#mkAdsSummaryPanel");
  if (!host) return;
  const storeState = state.dashboard?.store_state || state.runtimeWorkspace?.store_state;
  const ads = storeState?.ads_summary;
  if (!ads || !ads.days || ads.days < 1) {
    host.innerHTML = "";
    host.style.display = "none";
    return;
  }
  host.style.display = "block";

  const fmtMoney = (v) => (v != null ? "¥" + Number(v).toFixed(1) : "--");
  const fmtPct = (v) => (v != null ? Number(v).toFixed(1) + "%" : "--");
  const trendArrow = (v) => {
    if (v == null) return "";
    if (v > 10) return ` <span class="trend-bad">↑${Math.abs(v).toFixed(0)}%</span>`;
    if (v < -10) return ` <span class="trend-good">↓${Math.abs(v).toFixed(0)}%</span>`;
    return ` <span class="trend-neutral">→</span>`;
  };

  const metrics = [
    { label: "日均花费", value: fmtMoney(ads.avg_daily_cost) },
    { label: "CPC", value: fmtMoney(ads.avg_cpc) + trendArrow(ads.cpc_trend_pct) },
    { label: "ROAS", value: ads.avg_roas != null ? ads.avg_roas.toFixed(1) : "--" + trendArrow(ads.roas_trend_pct) },
    { label: "广告订单", value: ads.total_ads_orders || "--" },
  ];

  const findingsHtml = (ads.findings || [])
    .slice(0, 2)
    .map((f) => `<div class="ads-finding">${escapeHtml(f)}</div>`)
    .join("");

  host.innerHTML = `
    <div class="ads-summary-head">投流概览 · ${ads.days} 天</div>
    <div class="ads-metrics-grid">
      ${metrics.map((m) => `<div class="ads-metric"><strong>${m.value}</strong><span>${m.label}</span></div>`).join("")}
    </div>
    ${findingsHtml}
  `;
}

/* ── 成本列表渲染 — 调用 fetchCostItems 展示商品成本表 ── */

async function renderCostItemsPanel() {
  const host = qs("#mkCostItemsPanel");
  if (!host) return;
  const data = await fetchCostItems();
  if (!data || !data.items || !data.items.length) {
    host.innerHTML = "";
    host.style.display = "none";
    return;
  }
  host.style.display = "block";
  const rows = data.items.slice(0, 15).map((item) => {
    const foodClass = item.food_cost != null ? "has-cost" : "no-cost";
    const packClass = item.packaging_cost != null ? "has-cost" : "no-cost";
    return `<tr>
      <td>${escapeHtml(item.name)}</td>
      <td>${item.price != null ? "¥" + Number(item.price).toFixed(1) : "--"}</td>
      <td class="${foodClass}">${item.food_cost != null ? "¥" + Number(item.food_cost).toFixed(1) : "待填"}</td>
      <td class="${packClass}">${item.packaging_cost != null ? "¥" + Number(item.packaging_cost).toFixed(1) : "待填"}</td>
      <td><button class="rec-preview-btn" data-cost-edit="${escapeHtml(item.item_id)}">编辑</button></td>
    </tr>`;
  }).join("");
  host.innerHTML = `
    <div class="ads-summary-head">商品成本 · ${data.items.length} 个商品</div>
    <table class="mk-cost-table">
      <thead><tr><th>商品</th><th>售价</th><th>食材</th><th>包装</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

/* ── Decision Core 对话意图拦截 ──

当老板在对话里说:
  "这个活动要不要参加" / "帮我算算满30减5" / "满减划不划算"
→ 前端直接调 Decision Core,不走后端 chat

当老板说:
  "为什么利润变低了" / "利润怎么少了"
→ 前端直接调利润诊断
*/

function handleDecisionCoreIntent(text) {
  return _handleDecisionCoreIntentAsync(text);
}

async function _handleDecisionCoreIntentAsync(text) {
  const lower = text.toLowerCase();

  // 活动测算意图
  const campaignKeywords = ["活动", "满减", "满送", "折扣", "优惠", "划算", "要不要参加", "划不划", "帮我算"];
  const isCampaign = campaignKeywords.some((kw) => lower.includes(kw));

  // 利润诊断意图
  const profitKeywords = ["为什么利润", "利润怎么少", "利润下降", "利润变低", "利润跌", "毛利"];
  const isProfit = profitKeywords.some((kw) => lower.includes(kw));

  if (!isCampaign && !isProfit) return false;

  // 移除 pending 消息
  if (state.chatMessages.length && state.chatMessages[state.chatMessages.length - 1].pending) {
    state.chatMessages.pop();
  }

  if (isCampaign) {
    appendChatMessage("assistant", "我来帮你算算这个活动的经济账。需要你补充几个信息：");
    // 简化:从文本中提取数字,尝试构建 campaign rule
    const result = _parseCampaignFromText(text);
    if (result) {
      // 先测算(不执行),看结果再决定
      appendChatMessage("assistant", `测算中：${result.rule.campaign_name || "活动"}，售价 ¥${result.sku_price}…`);
      const calcResult = await calculateCampaign(result.rule, {
        sku_price: result.sku_price,
        food_cost: result.food_cost,
        packaging_cost: result.packaging_cost,
      });
      if (calcResult && calcResult.decision) {
        const d = calcResult.decision;
        const verdictLabel = { GREEN: "建议参加", YELLOW: "限量测试", RED: "不建议", BLACK: "无法判断" }[d.verdict] || d.verdict;
        appendChatMessage("assistant", `测算结果：${verdictLabel}。${d.reasoning || d.strategy || ""}\n如果要执行,再说一声「参加」。`);
      }
    } else {
      appendChatMessage(
        "assistant",
        "请告诉我：活动名称、商品售价、食材成本、包装成本。\n例如：「满30减5，牛肉饭售价29.9，食材14，包装2」",
      );
    }
    if (document.body.classList.contains("view-home")) renderHomeChatThread();
    return true;
  }

  if (isProfit) {
    // 尝试从当前 StoreState 自动提取利润诊断数据
    const storeState = state.dashboard?.store_state || state.runtimeWorkspace?.store_state;
    const profit = storeState?.profit;
    if (profit && profit.contribution_profit != null) {
      appendChatMessage("assistant", "我用当前利润数据做归因分析…");
      const result = await diagnoseProfit(
        {
          gmv: profit.gross_gmv,
          commission: profit.platform_commission,
          merchant_subsidy: profit.merchant_subsidy,
          ads: profit.ads_spend,
          food_cost: profit.food_cost,
          packaging_cost: profit.packaging_cost,
        },
        {
          gmv: profit.gross_gmv ? profit.gross_gmv * 1.1 : null,  // 近似基线
        },
        undefined,
        undefined,
      );
      if (result && result.conclusion) {
        appendChatMessage("assistant", result.conclusion);
      }
    } else {
      appendChatMessage("assistant", "利润诊断需要两期对比数据。导入经营数据后,我能自动做归因分析。");
    }
    if (document.body.classList.contains("view-home")) renderHomeChatThread();
    return true;
  }

  return false;
}

/** 从自然语言中尝试解析活动规则 */
function _parseCampaignFromText(text) {
  // 提取满减: "满30减5" / "满30减5元"
  const fullCutMatch = text.match(/满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)/);
  // 提取售价: "售价29.9" / "29.9元"
  const priceMatch = text.match(/(?:售价|价格|单价)\s*[:：]?\s*(\d+(?:\.\d+)?)/);
  // 提取食材成本
  const foodMatch = text.match(/(?:食材|成本|物料)\s*[:：]?\s*(\d+(?:\.\d+)?)/);
  // 提取包装成本
  const packMatch = text.match(/(?:包装|打包)\s*[:：]?\s*(\d+(?:\.\d+)?)/);

  const price = priceMatch ? parseFloat(priceMatch[1]) : 0;
  if (!price && !fullCutMatch) return null;

  const rule = {
    campaign_name: fullCutMatch ? `满${fullCutMatch[1]}减${fullCutMatch[2]}` : "活动测算",
    campaign_type: "fullcut",
    merchant_bear_amount: fullCutMatch ? parseFloat(fullCutMatch[2]) : 0,
    platform_subsidy_amount: 0,
    applicable_days: 7,
    discount_depth_pct: fullCutMatch ? parseFloat(fullCutMatch[2]) / parseFloat(fullCutMatch[1]) * 100 : 10,
  };

  return {
    rule: rule,
    sku_price: price,
    food_cost: foodMatch ? parseFloat(foodMatch[1]) : null,
    packaging_cost: packMatch ? parseFloat(packMatch[1]) : null,
  };
}

/* ── 推荐操作: 预览/回滚按钮处理 ── */

function bindDecisionCoreButtons() {
  document.addEventListener("click", (event) => {
    const previewBtn = event.target.closest("[data-rec-preview]");
    if (previewBtn) {
      const recId = previewBtn.dataset.recPreview;
      previewRecommendation(recId);
      event.stopPropagation();
      return;
    }
    const rollbackBtn = event.target.closest("[data-rec-rollback]");
    if (rollbackBtn) {
      const recId = rollbackBtn.dataset.recRollback;
      if (confirm("确定回滚这个操作吗？")) {
        rollbackRecommendation(recId);
      }
      event.stopPropagation();
      return;
    }
    // 成本编辑
    const costEditBtn = event.target.closest("[data-cost-edit]");
    if (costEditBtn) {
      const itemId = costEditBtn.dataset.costEdit;
      const foodCost = prompt("食材成本(元):");
      if (foodCost === null) return;
      const packCost = prompt("包装成本(元):");
      if (packCost === null) return;
      _updateItemCost(itemId, parseFloat(foodCost) || null, parseFloat(packCost) || null);
      event.stopPropagation();
      return;
    }
  });
}

async function _updateItemCost(itemId, foodCost, packCost) {
  if (!state.currentStoreId) return;
  try {
    await fetchJson(
      `/stores/${encodeURIComponent(state.currentStoreId)}/cost/items/${encodeURIComponent(itemId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ food_cost: foodCost, packaging_cost: packCost }),
      },
    );
    notifySuccess("成本已更新");
    renderCostItemsPanel();
    renderDataCoveragePanel();
  } catch (e) {
    notifyError("更新失败：" + e.message);
  }
}
