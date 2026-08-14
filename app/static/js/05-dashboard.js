/* MealKey UI — renderDashboard and agent/dashboard section renderers */

function renderFallbackCompetitionMap(payload, message) {
  const container = qs("#competitionMap");
  if (!payload) {
    container.innerHTML = `<div class="map-empty">${escapeHtml(message || "缺少门店经纬度，暂时无法生成竞争地图。")}</div>`;
    return;
  }
  const latRange = Math.max(payload.radius_m / 111000, 0.005);
  const longitudeScale = Math.cos((payload.center_latitude * Math.PI) / 180) || 0.7;
  const lngRange = Math.max(payload.radius_m / (111000 * longitudeScale), 0.005);
  const points = [
    {
      name: payload.store_name,
      latitude: payload.center_latitude,
      longitude: payload.center_longitude,
      store: true,
    },
    ...(payload.competitors || []),
  ];
  container.innerHTML = `
    <div class="map-radius-ring"></div>
    ${points
      .map((point) => {
        const left = Math.max(8, Math.min(92, 50 + ((point.longitude - payload.center_longitude) / lngRange) * 40));
        const topPosition = Math.max(8, Math.min(92, 50 - ((point.latitude - payload.center_latitude) / latRange) * 40));
        return `
          <div class="fallback-map-point ${point.store ? "store" : ""}" style="left:${left}%;top:${topPosition}%;" title="${escapeHtml(point.name)}"></div>
          <div class="fallback-map-label" style="left:${left}%;top:${topPosition}%;">${escapeHtml(point.store ? "本店" : point.name)}</div>
        `;
      })
      .join("")}
  `;
  if (message) qs("#competitionCollectionStatus").textContent = message;
}

async function renderCompetitionMap() {
  const payload = state.competitionMap;
  const amapConfig = state.publicConfig?.amap;
  const collectionConfig = state.publicConfig?.competition_collection;
  const pointCount = payload?.competitors?.length || 0;
  const schedule = collectionConfig?.schedule || "07:30";
  const scanButton = qs("#scanCompetitionBtn");
  scanButton.disabled = !collectionConfig?.enabled;
  scanButton.title = collectionConfig?.enabled ? "立即执行一次竞品扫描" : "请先配置高德或授权数据源";

  if (!payload) {
    renderFallbackCompetitionMap(null);
    qs("#competitionCollectionStatus").textContent = "门店缺少经纬度或地图数据不可用。";
    return;
  }
  if (!amapConfig?.enabled) {
    renderFallbackCompetitionMap(
      payload,
      `已展示坐标降级地图｜每日 ${schedule} 自动采集｜当前 ${pointCount} 个竞品`,
    );
    return;
  }

  try {
    const AMap = await loadAmapSdk(amapConfig);
    if (state.amapInstance) state.amapInstance.destroy();
    qs("#competitionMap").innerHTML = "";
    const map = new AMap.Map("competitionMap", {
      zoom: 14,
      center: [payload.center_longitude, payload.center_latitude],
      viewMode: "2D",
    });
    state.amapInstance = map;
    const markers = [
      new AMap.Marker({
        position: [payload.center_longitude, payload.center_latitude],
        title: payload.store_name,
        label: { content: "本店", direction: "top" },
      }),
      ...(payload.competitors || []).map(
        (point) =>
          new AMap.Marker({
            position: [point.longitude, point.latitude],
            title: point.name,
            label: { content: escapeHtml(point.name), direction: "top" },
          }),
      ),
    ];
    map.add(markers);
    map.add(
      new AMap.Circle({
        center: [payload.center_longitude, payload.center_latitude],
        radius: payload.radius_m,
        strokeColor: "#2f7c60",
        strokeOpacity: 0.45,
        fillColor: "#2f7c60",
        fillOpacity: 0.06,
      }),
    );
    map.setFitView(markers, false, [40, 40, 40, 40]);
    qs("#competitionCollectionStatus").textContent = `高德真实地图｜每日 ${schedule} 自动采集｜当前 ${pointCount} 个竞品`;
  } catch (error) {
    renderFallbackCompetitionMap(payload, `地图服务异常，已降级展示坐标：${error.message}`);
  }
}

function renderMenuAgent() {
  const menu = state.dashboard?.agents?.menu || {};
  const roles = menu.role_distribution || {};
  const current = menu.current_action;
  const queueBrief = actionQueueBrief(menu);
  qs("#menuHealthTag").textContent = menu.readiness
    ? `菜单健康度 ${menu.menu_health_score ?? "--"} 分 · ${formatReadiness(menu.readiness)}`
    : `菜单健康度 ${menu.menu_health_score ?? "--"} 分`;
  qs("#menuWorkflowSummary").textContent =
    queueBrief ||
    (current
      ? `${formatExecutionPhase(current.execution_phase)}｜${current.phase_reason || current.next_decision || menu.workflow_summary || "先继续看菜单反馈。"}`
      : menu.workflow_summary || "菜单证据还不够，先补齐商品和订单数据。");
  qs("#menuItemCount").textContent = `${(menu.items || []).length} 个商品`;
  qs("#menuRoleGrid").innerHTML = Object.entries(roles).length
    ? Object.entries(roles)
        .map(
          ([role, count]) => `
            <div>
              <strong>${count}</strong>
              <span>${escapeHtml(menuRoleLabel(role))}</span>
            </div>
          `,
        )
        .join("")
    : `<div><strong>--</strong><span>等待角色识别</span></div>`;

  const ladder = menu.pricing_ladder || {};
  qs("#menuPriceRange").textContent =
    ladder.anchor_min === null || ladder.anchor_min === undefined
      ? "价格锚点待建立"
      : `¥${ladder.anchor_min} — ¥${ladder.anchor_max}`;
  qs("#menuPriceBands").innerHTML = [
    ["低价带", ladder.low_band_count || 0],
    ["主价格带", ladder.mid_band_count || 0],
    ["高价带", ladder.high_band_count || 0],
  ]
    .map(([label, count]) => `<div><strong>${count}</strong><span>${label}</span></div>`)
    .join("");
  qs("#menuPriceGap").textContent = ladder.gap_note || "当前价格梯度没有明显缺口。";

  qs("#menuItemList").innerHTML = (menu.items || []).length
    ? takeTop(menu.items, 8)
        .map(
          (item) => `
            <article class="menu-item-row">
              <img src="${imageForFood(item.name)}" alt="${escapeHtml(item.name)}" />
              <div>
                <strong>${escapeHtml(item.name)}</strong>
                <p>${escapeHtml(item.rationale)}</p>
              </div>
              <span class="menu-role ${menuRoleClass(item.role)}">${escapeHtml(menuRoleLabel(item.role))}</span>
              <div class="menu-item-metrics">
                <strong>${item.price === null || item.price === undefined ? "--" : `¥${item.price}`}</strong>
                <small>${item.order_share_pct === null || item.order_share_pct === undefined ? "占比 --" : `订单占比 ${item.order_share_pct.toFixed(1)}%`}</small>
            </div>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无菜单商品，请先导入菜单。</div>`;

  const gaps = [
    ...(menu.structural_gaps || []),
    ...(menu.document_gaps || []),
    ...(menu.blockers || []),
    ...(menu.evidence || []),
    ...(menu.category_summary || []).map(
      (row) => `${row.category}：${row.health_note || `${row.item_count} 个商品`}`,
    ),
  ];
  qs("#menuGapList").innerHTML = gaps.length
    ? takeTop(gaps, 8).map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>当前没有明显菜单结构缺口。</span></div>`;

  renderMenuDeepDiagnosis();

  qs("#menuPatchList").innerHTML = (menu.suggested_patches || []).length
    ? takeTop(menu.suggested_patches, 3)
        .map(
          (patch, index) => `
            <article class="menu-action-card">
              <span>${escapeHtml(menuRoleLabel(patch.target_role) || patch.patch_type)}</span>
              <h3>${escapeHtml(patch.item_name)}${patch.suggested_price ? ` · ¥${patch.suggested_price}` : ""}</h3>
              <p>${escapeHtml(patch.reason)}</p>
              <small>${escapeHtml(patch.expected_outcome)}</small>
              <button data-menu-action="patches" data-menu-index="${index}">生成并加入菜单</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无需要补齐的菜单缺口。</div>`;
  qs("#menuBundleList").innerHTML = (menu.bundle_opportunities || []).length
    ? takeTop(menu.bundle_opportunities, 3)
        .map(
          (bundle, index) => `
            <article class="menu-action-card">
              <span>套餐组合</span>
              <h3>${escapeHtml(bundle.primary_item_name)} + ${escapeHtml(bundle.attach_item_name)}</h3>
              <p>${escapeHtml(bundle.reason)}</p>
              <small>${escapeHtml(bundle.expected_outcome)}</small>
              <button data-menu-action="bundles" data-menu-index="${index}">生成套餐动作</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂未发现高置信度套餐机会。</div>`;
  qs("#menuCleanupList").innerHTML = (menu.cleanup_candidates || []).length
    ? takeTop(menu.cleanup_candidates, 3)
        .map(
          (candidate, index) => `
            <article class="menu-action-card warning">
              <span>${escapeHtml(candidate.action || "低效商品")}</span>
              <h3>${escapeHtml(candidate.name)}</h3>
              <p>${escapeHtml(candidate.reason)}</p>
              <small>${escapeHtml(menuRoleLabel(candidate.role))} · 建议先创建清理实验再决定是否下架</small>
              <button data-menu-action="cleanup" data-menu-index="${index}">创建清理实验</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前没有需要清理的商品。</div>`;
}

function renderCompetitionAgent() {
  const competition = state.dashboard?.agents?.competition || state.dashboard?.competition || {};
  qs("#competitionAgentScore").textContent = competition.competition_score ?? "--";
  qs("#competitionReadiness").textContent = `准备度 ${formatReadiness(competition.readiness)}`;
  qs("#competitionBenchmark").textContent = `基准组 ${competition.benchmark_group || "--"}`;
  qs("#competitionAgentConclusion").textContent =
    competition.conclusion || "当前还没有足够竞品证据，先完成商圈采集。";
  qs("#competitionExpectedImpact").textContent =
    competition.expected_impact || "完成快照后会给出预期影响。";
  qs("#competitionFocusList").innerHTML = (competition.market_focus || []).length
    ? competition.market_focus.map((row) => `<span>${escapeHtml(row)}</span>`).join("")
    : `<span>等待商圈焦点</span>`;

  qs("#competitionAgentList").innerHTML = (competition.top_competitors || []).length
    ? takeTop(competition.top_competitors, 4)
        .map(
          (competitor) => `
            <article class="competition-agent-card">
              <div class="competition-agent-card-top">
                <strong>${escapeHtml(competitor.name)}</strong>
                <span>${competitor.score ?? "--"} 分</span>
              </div>
              <p>${escapeHtml(competitor.positioning || "同商圈竞品")} · ${
                competitor.distance_m ? `${Math.round(competitor.distance_m)}m` : "同商圈"
              }</p>
              <div class="competition-agent-tags">
                ${(competitor.strengths || []).slice(0, 2).map((row) => `<span>优 ${escapeHtml(row)}</span>`).join("")}
                ${(competitor.weaknesses || []).slice(0, 2).map((row) => `<span class="weak">弱 ${escapeHtml(row)}</span>`).join("")}
            </div>
              <small>${
                competitor.recent_move
                  ? `最近变化：${escapeHtml(competitor.recent_move)}`
                  : `主推：${escapeHtml((competitor.featured_products || []).slice(0, 2).join(" / ") || "暂无")}`
              }</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无重点竞品，请先更新商圈快照。</div>`;

  qs("#competitionChangeGrid").innerHTML = (competition.changes || []).length
    ? takeTop(competition.changes, 6)
        .map(
          (change) => `
            <div class="competition-change-card">
              <strong>${escapeHtml(change.type || "变化")}</strong>
              <p>${escapeHtml(change.summary)}</p>
              <small>${change.price === null || change.price === undefined ? "价格未变" : `¥${change.price}`}</small>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">近期没有可追踪的竞品变化。</div>`;

  const threats = [
    ...(competition.threat_signals || []),
    ...(competition.blockers || []),
    ...(competition.evidence || []),
    ...(competition.reasons || []),
  ];
  qs("#competitionThreatList").innerHTML = threats.length
    ? takeTop(threats, 6).map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>暂无威胁信号，继续保持日常监测。</span></div>`;
  const actionRows = competition.actions || [];
  qs("#competitionActionList").innerHTML = actionRows.length
    ? actionRows
        .map((row) => {
          const text = String(row || "");
          let scroll = "section-growth";
          let label = "交给增长策略排序";
          if (/主图|装修|店页|第一眼|图片/.test(text)) {
            scroll = "section-storefront";
            label = "去线上装修";
          } else if (/套餐|菜单|SKU|价格带/.test(text)) {
            scroll = "section-menu";
            label = "去菜单分析";
          } else if (/商品|CTR|CVR|主推/.test(text)) {
            scroll = "section-product";
            label = "去商品优化";
          } else if (/活动|补贴/.test(text)) {
            scroll = "section-promo";
            label = "去平台活动";
          } else if (/采集|快照|连接/.test(text)) {
            scroll = "section-collection";
            label = "去数据采集";
          }
          return `
            <div class="agent-action-row">
              <strong>→</strong>
              <span>${escapeHtml(text)}</span>
              <button class="link-button" type="button" data-scroll-target="${scroll}">${label}</button>
            </div>
          `;
        })
        .join("")
    : `<div class="agent-action-row"><strong>→</strong><span>先更新快照，再决定响应动作。</span><button class="link-button" type="button" data-scroll-target="section-collection">去数据采集</button></div>`;
}

function renderStorefrontAgent() {
  const storefront = state.dashboard?.agents?.storefront || {};
  const impact = storefront.sales_impact || {};
  qs("#storefrontScore").textContent = storefront.health_score ?? "--";
  qs("#storefrontHealthTag").textContent = `装修健康度 ${storefront.health_score ?? "--"} 分 · ${formatReadiness(storefront.readiness)}`;
  qs("#storefrontConclusion").textContent = storefront.conclusion || "暂无线上装修结论。";
  qs("#storefrontImpact").textContent = impact.narrative || storefront.expected_impact || "完成诊断后给出销售影响预估。";
  qs("#storefrontReadiness").textContent = `准备度 ${formatReadiness(storefront.readiness)}`;
  const queueBrief = actionQueueBrief(storefront);
  qs("#storefrontCurrentAction").textContent =
    queueBrief || "先创建一条装修动作，再进入采纳→执行→验证。";

  qs("#storefrontDimensionList").innerHTML = (storefront.dimensions || []).length
    ? storefront.dimensions
        .map(
          (dim) => `
            <article class="storefront-dimension-card status-${escapeHtml(dim.status || "watch")}">
              <div class="storefront-dimension-top">
                <strong>${escapeHtml(dim.label)}</strong>
                <span>${dim.score ?? "--"}</span>
              </div>
              <p>${escapeHtml(dim.summary || "")}</p>
              <small>销售杠杆：${escapeHtml((dim.sales_lever || "ctr").toUpperCase())}</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无装修维度结果。</div>`;

  qs("#storefrontIssueList").innerHTML = (storefront.issues || []).length
    ? storefront.issues
        .map(
          (issue) => `
            <article class="storefront-issue-card severity-${escapeHtml(issue.severity || "medium")}">
              <div class="storefront-issue-top">
                <strong>${escapeHtml(issue.title)}</strong>
                <span>${escapeHtml(issue.severity === "high" ? "高优" : issue.severity === "low" ? "观察" : "中优")}</span>
              </div>
              <p>${escapeHtml(issue.detail || "")}</p>
              <small>${escapeHtml(issue.sales_impact_est || "")}</small>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无高优先级装修漏洞，维持主图与套餐观察即可。</div>`;

  qs("#storefrontActionGrid").innerHTML = (storefront.priority_actions || []).length
    ? storefront.priority_actions
        .map(
          (action, index) => `
            <article class="storefront-action-card">
              <div class="storefront-action-top">
                <strong>${escapeHtml(action.title)}</strong>
                <span>${escapeHtml((action.expected_metric || "ctr").toUpperCase())} +${Number(action.expected_lift_pct_low || 0).toFixed(0)}~${Number(action.expected_lift_pct_high || 0).toFixed(0)}%</span>
              </div>
              <p>${escapeHtml(action.detail || "")}</p>
              <small>${escapeHtml((action.generated_content && (action.generated_content.visual_brief || action.generated_content.ia_brief || action.generated_content.bundle_brief || action.generated_content.trust_brief)) || "可回退的店页改造")}</small>
              <button class="topbar-button primary" data-storefront-action-index="${index}">AI 生成并落库动作</button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前没有可落库的装修动作。</div>`;
}

function renderStorefrontAiPanel(payload) {
  const panel = qs("#storefrontAiPanel");
  const title = qs("#storefrontAiTitle");
  const body = qs("#storefrontAiBody");
  if (!panel || !body) return;
  const plan = payload?.plan || payload || {};
  const assistType = payload?.assist_type || plan.assist_type || "decorate";
  state.storefrontAiPlan = plan;
  title.textContent =
    assistType === "image_optimize"
      ? plan.title || "AI 主图优化方案"
      : plan.title || "AI 装修协助方案";

  if (assistType === "image_optimize") {
    body.innerHTML = `
      <p class="storefront-ai-summary">${escapeHtml(plan.goal || "")}</p>
      <div class="storefront-ai-block"><strong>问题</strong><p>${escapeHtml(plan.problem || "")}</p></div>
      <div class="storefront-ai-block"><strong>拍摄清单</strong><ul>${(plan.shot_list || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-block"><strong>中文提示词</strong><code>${escapeHtml(plan.prompt_zh || "")}</code></div>
      <div class="storefront-ai-block"><strong>英文提示词</strong><code>${escapeHtml(plan.prompt_en || "")}</code></div>
      <div class="storefront-ai-block"><strong>验收清单</strong><ul>${(plan.checklist || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-meta">模式：${escapeHtml(plan.mode || "--")}${
        plan.llm ? ` · ${escapeHtml(plan.llm.provider)}/${escapeHtml(plan.llm.model)}` : ""
      }</div>
    `;
  } else {
    body.innerHTML = `
      <p class="storefront-ai-summary">${escapeHtml(plan.summary || "")}</p>
      <div class="storefront-ai-block"><strong>销售重点</strong><p>${escapeHtml(plan.sales_focus || "")}</p></div>
      <div class="storefront-ai-steps">${(plan.steps || [])
        .map(
          (step) => `
            <article>
              <strong>${step.order || ""}. ${escapeHtml(step.title || "")}</strong>
              <p>${escapeHtml(step.why || "")}</p>
              <p>怎么做：${escapeHtml(step.how || "")}</p>
              <small>验证：${escapeHtml(step.verify || "")}</small>
            </article>
          `,
        )
        .join("")}</div>
      <div class="storefront-ai-block"><strong>店页文案包</strong>
        <p>店招：${escapeHtml(plan.copy_pack?.store_tagline || "--")}</p>
        <p>招牌：${escapeHtml(plan.copy_pack?.signature_title || "--")}</p>
        <p>套餐：${escapeHtml(plan.copy_pack?.set_meal_title || "--")}</p>
      </div>
      <div class="storefront-ai-block"><strong>不要做</strong><ul>${(plan.do_not_do || [])
        .map((row) => `<li>${escapeHtml(row)}</li>`)
        .join("")}</ul></div>
      <div class="storefront-ai-meta">下一步：${escapeHtml(plan.next_action || "--")} · 模式 ${escapeHtml(plan.mode || "--")}</div>
    `;
  }
  panel.hidden = false;
  scrollToSection("section-storefront");
}

function renderProductAgent() {
  const product = state.dashboard?.agents?.product || {};
  const itemId = product.focus_item_id;
  const current = product.current_action;
  const queueBrief = actionQueueBrief(product);
  qs("#productHealthTag").textContent = product.readiness
    ? `健康度 ${product.health_score ?? "--"} 分 · ${formatReadiness(product.readiness)}`
    : `健康度 ${product.health_score ?? "--"} 分`;
  qs("#productCandidateMeta").textContent = `已扫描 ${(product.item_candidates || []).length} 个候选商品`;
  qs("#productGuardrail").textContent = product.experiment_guardrail || "一次只执行一个商品动作。";
  qs("#productCurrentAction").innerHTML = current
    ? `<span class="inline-phase"><span class="phase-pill ${executionPhaseClass(current.execution_phase)}">${escapeHtml(formatExecutionPhase(current.execution_phase))}</span><span>${escapeHtml(current.title)}</span></span><span class="inline-note">${escapeHtml(current.phase_reason || current.next_decision || `窗口 ${current.window_hours || "--"}h`)}${product.blockers?.[0] ? ` · 阻塞：${escapeHtml(product.blockers[0])}` : ""}</span>`
    : escapeHtml(queueBrief || product.blockers?.[0] || "现在还没有商品动作，先看今天该盯哪一个商品。");

  qs("#productFocusCard").innerHTML = itemId
    ? `
      <img src="${imageForFood(product.focus_item_name)}" alt="${escapeHtml(product.focus_item_name)}" />
      <div class="product-focus-overlay">
        <div>
          <div class="section-kicker">当前优先商品</div>
          <h3>${escapeHtml(product.focus_item_name)}</h3>
          <p>${escapeHtml(product.why_now || product.issue || "正在建立商品证据")}</p>
        </div>
        <strong>${product.health_score ?? "--"}<small>分</small></strong>
      </div>
    `
    : `<div class="empty-state">当前没有可分析的商品，请先接入菜单和商品经营数据。</div>`;

  qs("#productDimensionList").innerHTML = (product.health_dimensions || [])
        .map(
          (row) => `
        <div class="product-dimension-row">
          <div class="product-dimension-meta">
            <span>${escapeHtml(row.label)}</span>
            <strong>${row.score} 分</strong>
              </div>
          <div class="product-dimension-track"><i class="${escapeHtml(row.status)}" style="width:${Math.max(
            4,
            Math.min(100, row.score),
          )}%"></i></div>
          <div class="product-dimension-foot">${row.delta_pct === null || row.delta_pct === undefined ? "等待对比数据" : `较基线 ${formatDelta(row.delta_pct)}`}</div>
            </div>
      `,
    )
    .join("");

  const rootCause = (product.root_causes || [])[0];
  qs("#productDiagnosisPanel").innerHTML = `
    <div class="product-panel-title">AI 根因诊断</div>
    <div class="product-stage">${escapeHtml(product.diagnosis_stage || "unknown")}</div>
    <h3>${escapeHtml(product.issue || "等待诊断")}</h3>
    <p>${escapeHtml(product.diagnosis || "接入更多商品漏斗数据后生成根因。")}</p>
    ${
      rootCause
        ? `<div class="product-root-cause"><strong>${escapeHtml(rootCause.title)}</strong><span>${escapeHtml(
            rootCause.explanation,
          )}</span><small>置信度 ${Math.round((rootCause.confidence || 0) * 100)}%</small></div>`
        : ""
    }
    <div class="product-decision-path">${(product.decision_path || [])
      .map((step, index) => `<span>${index + 1}. ${escapeHtml(step)}</span>`)
      .join("")}</div>
  `;

  qs("#productCandidateGrid").innerHTML = (product.item_candidates || []).length
    ? takeTop(product.item_candidates, 4)
        .map(
          (candidate) => `
            <article class="product-candidate-card ${candidate.item_id === itemId ? "selected" : ""}">
              <div class="product-candidate-top">
                <strong>${escapeHtml(candidate.name)}</strong>
                <span>${candidate.opportunity_score ?? candidate.health_score ?? "--"}</span>
              </div>
              <p>${escapeHtml(candidate.issue || "等待诊断")}</p>
              <small>${escapeHtml(menuRoleLabel(candidate.role))} · ${escapeHtml(candidate.diagnosis_stage || "--")}</small>
              <button data-product-suggestion-index="0" data-product-item-id="${escapeHtml(candidate.item_id)}">
                ${escapeHtml(candidate.recommended_action || "生成动作")}
              </button>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无候选商品。</div>`;

  qs("#productRecommendationGrid").innerHTML = (product.recommendations || []).length
    ? product.recommendations
        .map(
          (suggestion, index) => `
            <article class="product-recommendation-card">
              <div class="product-recommendation-top">
                <span>优先级 ${suggestion.priority || index + 1}</span>
                <span>${escapeHtml(suggestion.risk_level || "low")} risk</span>
              </div>
              <h3>${escapeHtml(suggestion.title)}</h3>
              <p>${escapeHtml(suggestion.detail)}</p>
              ${productPreview(suggestion.generated_content)}
              <div class="product-recommendation-foot">
                <span>${escapeHtml(suggestion.expected_metric || "指标")} · ${
                  suggestion.expected_lift_pct_high
                    ? `预计 +${suggestion.expected_lift_pct_low || 0}~${suggestion.expected_lift_pct_high}%`
                    : `${suggestion.window_hours || 24}h`
                }</span>
                <button data-product-suggestion-index="${index}" data-product-item-id="${escapeHtml(itemId || "")}">生成动作</button>
                <button class="ghost" data-product-apply-index="${index}" data-product-item-id="${escapeHtml(itemId || "")}">直接执行</button>
            </div>
              ${suggestion.rollback_rule ? `<small class="product-rollback">回滚：${escapeHtml(suggestion.rollback_rule)}</small>` : ""}
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">当前证据不足，暂不生成商品动作。</div>`;
}

function renderDiagnosisAgent() {
  const diagnosis = state.dashboard?.agents?.diagnosis || {};
  qs("#diagnosisScore").textContent = diagnosis.diagnosis_score ?? "--";
  qs("#diagnosisSummary").textContent =
    diagnosis.executive_summary || diagnosis.root_cause || diagnosis.primary_problem || "当前没有明确诊断结论";
  qs("#diagnosisDailySummary").textContent = [
    diagnosis.daily_summary ||
      (diagnosis.primary_problem ? `主问题：${diagnosis.primary_problem}` : "等待多周期指标对比。"),
    diagnosis.readiness ? `准备度 ${formatReadiness(diagnosis.readiness)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  qs("#diagnosisComparisonGrid").innerHTML = (diagnosis.comparisons || []).length
    ? diagnosis.comparisons
        .map(
          (row) => `
        <article class="diagnosis-comparison-card ${escapeHtml(row.status)}">
          <div class="diagnosis-comparison-top">
            <strong>${escapeHtml(row.label)}</strong>
            <span>${escapeHtml(row.status)}</span>
              </div>
          <div class="diagnosis-comparison-values">
            <div><span>订单</span><strong>${row.orders_delta_pct === null ? "--" : formatDelta(row.orders_delta_pct)}</strong></div>
            <div><span>营业额</span><strong>${row.gmv_delta_pct === null ? "--" : formatDelta(row.gmv_delta_pct)}</strong></div>
            </div>
          <p>${escapeHtml(row.note)}</p>
        </article>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无周期对比结果，完成诊断后会显示同星期 / 7 日 / 30 日对比。</div>`;

  qs("#diagnosisSignalList").innerHTML = (diagnosis.metric_signals || []).length
    ? diagnosis.metric_signals
        .map(
          (signal) => `
        <div class="diagnosis-signal-row">
          <div>
            <strong>${escapeHtml(signal.label)}</strong>
            <span>${diagnosisMetricValue(signal.metric, signal.observed_value)}</span>
                </div>
          <span class="diagnosis-severity ${escapeHtml(signal.severity)}">${escapeHtml(signal.severity)}</span>
          <strong class="diagnosis-signal-delta">${
            signal.delta_pct === null || signal.delta_pct === undefined ? "--" : formatDelta(signal.delta_pct)
          }</strong>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">暂无指标信号，等待经营数据进入诊断窗口。</div>`;

  qs("#diagnosisRootList").innerHTML = (diagnosis.root_causes || []).length
    ? diagnosis.root_causes
        .map(
          (cause) => `
        <article class="diagnosis-root-card">
          <div class="diagnosis-root-rank">${cause.rank}</div>
          <div>
            <div class="diagnosis-root-head">
              <strong>${escapeHtml(cause.title)}</strong>
              <span>${Math.round((cause.confidence || 0) * 100)}%</span>
              </div>
            <p>${escapeHtml(cause.explanation)}</p>
            <small>${escapeHtml((cause.evidence || []).join(" · "))}</small>
            </div>
        </article>
      `,
        )
        .join("")
    : `<div class="empty-state">暂无根因结论，先补齐诊断证据再复盘。</div>`;

  const market = diagnosis.market_comparison || {};
  qs("#diagnosisMarketCard").innerHTML = `
    <div class="diagnosis-market-head">
      <div class="product-panel-title">本店 vs 商圈</div>
      <span>${escapeHtml(market.relative_status || market.data_type || "unavailable")}</span>
    </div>
    <div class="diagnosis-market-value">
      <span>本店订单变化</span>
      <strong>${market.own_orders_delta_pct === null || market.own_orders_delta_pct === undefined ? "--" : formatDelta(market.own_orders_delta_pct)}</strong>
    </div>
    <div class="diagnosis-market-value">
      <span>商圈订单变化</span>
      <strong>${market.market_orders_delta_pct === null || market.market_orders_delta_pct === undefined ? "--" : formatDelta(market.market_orders_delta_pct)}</strong>
    </div>
    <p>${escapeHtml(market.note || "尚未接入商圈趋势。")}</p>
  `;
  qs("#diagnosisGapList").innerHTML = (diagnosis.data_gaps || []).length
    ? diagnosis.data_gaps.map((gap) => `<div><i></i><span>${escapeHtml(gap)}</span></div>`).join("")
    : `<div><i></i><span>当前核心诊断数据已满足要求。</span></div>`;

  const observationList = qs("#diagnosisObservationList");
  if (observationList) {
    observationList.innerHTML = (diagnosis.observations || []).length
      ? diagnosis.observations
          .map(
            (obs) => `
          <article class="diagnosis-observation-row">
            <strong>${escapeHtml(obs.metric || "指标")}</strong>
            <p>${escapeHtml(obs.what_happened || "")}</p>
            <span>${
              obs.delta_pct === null || obs.delta_pct === undefined ? "--" : formatDelta(obs.delta_pct)
            } · 置信 ${
              obs.confidence == null ? "--" : `${Math.round(Number(obs.confidence) * 100)}%`
            }</span>
          </article>
        `,
          )
          .join("")
      : `<div class="empty-state soft">暂无 Observation，先跑一次诊断。</div>`;
  }

  const hypothesisCard = qs("#diagnosisHypothesisCard");
  if (hypothesisCard) {
    const reasons = diagnosis.reasons || [];
    hypothesisCard.innerHTML = `
      <div class="diagnosis-hypothesis-kicker">主假设</div>
      <h3>${escapeHtml(diagnosis.root_cause || diagnosis.primary_problem || "等待形成假设")}</h3>
      <p>${escapeHtml(diagnosis.executive_summary || diagnosis.daily_summary || "先看 Observation，再收敛 Hypothesis。")}</p>
      ${
        reasons.length
          ? `<ul class="diagnosis-hypothesis-reasons">${reasons
              .slice(0, 3)
              .map((row) => `<li>${escapeHtml(row)}</li>`)
              .join("")}</ul>`
          : ""
      }
      <button class="link-button" type="button" data-scroll-target="section-growth">用这个假设去排今日动作</button>
    `;
  }

  const nextActions = [
    ...(diagnosis.action_priorities || []),
    ...(diagnosis.next_actions || []),
    ...(diagnosis.blockers || []).map((row) => `先处理：${row}`),
  ];
  qs("#diagnosisNextActions").innerHTML = nextActions.length
    ? takeTop(nextActions, 5)
        .map((row) => {
          const text = String(row || "");
          let scroll = "section-growth";
          let label = "交给增长策略";
          if (/评价|差评|评分/.test(text)) {
            scroll = "section-review";
            label = "去评分评价";
          } else if (/客服|回复|IM/.test(text)) {
            scroll = "section-service";
            label = "去AI客服";
          } else if (/装修|主图|店页/.test(text)) {
            scroll = "section-storefront";
            label = "去线上装修";
          } else if (/商品|CTR|CVR/.test(text)) {
            scroll = "section-product";
            label = "去商品优化";
          } else if (/菜单|套餐/.test(text)) {
            scroll = "section-menu";
            label = "去菜单分析";
          } else if (/竞争|竞品/.test(text)) {
            scroll = "section-competition-agent";
            label = "去商圈竞争";
          } else if (/采集|连接|数据/.test(text)) {
            scroll = "section-collection";
            label = "去数据采集";
          }
          return `
            <div class="agent-action-row">
              <strong>→</strong>
              <span>${escapeHtml(text)}</span>
              <button class="link-button" type="button" data-scroll-target="${scroll}">${label}</button>
            </div>
          `;
        })
        .join("")
    : `<div class="agent-action-row"><strong>→</strong><span>先完成诊断复盘，再进入增长策略排序。</span><button class="link-button" type="button" data-scroll-target="section-growth">去增长策略</button></div>`;
}

function renderGrowthAgent() {
  const growth = state.dashboard?.agents?.growth || {};
  const selectedKey = growth.selected_opportunity?.key;
  const sourceLabels = Object.fromEntries(AGENT_TEAM.map((agent) => [agent.key, agent.label]));
  qs("#growthStrategyScore").textContent = growth.strategy_score ?? "--";
  qs("#growthTodayPriority").textContent = growth.today_priority || "当前没有可执行动作";
  qs("#growthReason").textContent = [
    growth.reason || "等待核心 Agent 与运营矩阵汇总。",
    growth.readiness ? `准备度 ${formatReadiness(growth.readiness)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  qs("#growthWeeklyGoal").textContent = `本周目标 · ${growth.weekly_goal || "--"}`;
  qs("#growthExecutionMode").textContent =
    growth.execution_mode === "alignment_first" ? "先对齐资料" : "单变量实验";
  qs("#growthPoolMeta").textContent = `${(growth.opportunity_pool || []).length} 个候选 · 只选 1 个执行`;
  qs("#growthProgressTag").textContent = `已复盘 ${growth.plan_progress_pct || 0}%`;
  const learningNote = qs("#growthLearningNote");
  if (learningNote) {
    learningNote.textContent =
      growth.learning_summary || "OHRE 的 Result 会沉淀成下次决策经验，避免重复买流水。";
  }

  const current = growth.current_action;
  const summary = growth.experiments_summary || {};
  const queueBrief = actionQueueBrief(growth);
  qs("#growthCurrentActionCard").innerHTML = current
    ? `
      <div class="product-panel-title">当前执行中</div>
      <div class="inline-phase" style="margin-top:8px;">
        <span class="phase-pill ${executionPhaseClass(current.execution_phase)}">${escapeHtml(formatExecutionPhase(current.execution_phase))}</span>
        <span>${escapeHtml(current.expected_metric)} · ${current.window_hours || "--"}h</span>
      </div>
      <h3>${escapeHtml(current.title)}</h3>
      <p>${escapeHtml(current.phase_reason || current.next_decision || "保持单变量观察。")}</p>
      <small>${escapeHtml(
        [current.next_decision || "等待下一步判断。", growth.blockers?.[0] ? `阻塞：${growth.blockers[0]}` : ""]
          .filter(Boolean)
          .join(" · "),
      )}</small>
    `
    : `
      <div class="product-panel-title">当前执行中</div>
      <h3>${escapeHtml(growth.today_priority || "等待主动作")}</h3>
      <p>${escapeHtml(queueBrief || growth.blockers?.[0] || "还没进入执行阶段，先把今天唯一主动作定下来。")}</p>
    `;
  qs("#growthExperimentSummary").innerHTML = `
    <div class="product-panel-title">实验反馈</div>
    <div class="growth-experiment-pills">
      <span>待验证 ${summary.pending || 0}</span>
      <span>有效 ${summary.positive || 0}</span>
      <span>中性 ${summary.neutral || 0}</span>
      <span>无效 ${summary.negative || 0}</span>
    </div>
    <p>${escapeHtml(growth.learning_summary || "做完的结果会回写，下次排序会更准。")}</p>
  `;

  const sourceScroll = { ...AGENT_SECTION_MAP };

  qs("#growthOpportunityGrid").innerHTML = (growth.opportunity_pool || []).length
    ? takeTop(growth.opportunity_pool, 6)
        .map((opportunity, index) => {
          const factors = opportunity.factors || {};
          const isSelected = opportunity.key === selectedKey;
          const nextAction =
            opportunity.status === "proposed"
              ? "adopt"
              : opportunity.status === "adopted"
                ? "execute"
                : null;
          return `
            <article class="growth-opportunity-card ${isSelected ? "selected" : ""}">
              <div class="growth-opportunity-top">
                <span>${escapeHtml(sourceLabels[opportunity.source_agent] || opportunity.source_agent)}</span>
                <strong>${Number(opportunity.score || 0).toFixed(1)}</strong>
              </div>
              <div class="growth-opportunity-rank">${isSelected ? "今日主动作" : `机会 ${index + 1}`}</div>
              <h3>${escapeHtml(opportunity.title)}</h3>
              <p>${escapeHtml(opportunity.problem)}</p>
              <div class="growth-factor-row">
                <span>影响 ${factors.expected_impact ?? "--"}</span>
                <span>置信 ${factors.confidence ?? "--"}</span>
                <span>易执行 ${factors.ease_of_execution ?? "--"}</span>
                <span>契合 ${factors.strategic_fit ?? "--"}</span>
                <span>风险 ${factors.risk ?? "--"}</span>
              </div>
              <div class="growth-opportunity-foot">
                <span>${escapeHtml(opportunity.expected_metric)} · ${
                  opportunity.expected_lift_pct_high
                    ? `预计 +${opportunity.expected_lift_pct_low || 0}~${opportunity.expected_lift_pct_high}%`
                    : "待验证"
                }</span>
                ${
                  nextAction && opportunity.recommendation_id
                    ? `<button data-recommendation-id="${opportunity.recommendation_id}" data-recommendation-action="${nextAction}">${
                        nextAction === "adopt" ? "采纳主动作" : "标记执行"
                      }</button>`
                    : sourceScroll[opportunity.source_agent]
                      ? `<button data-scroll-target="${sourceScroll[opportunity.source_agent]}">去对应 Agent</button>`
                      : `<em>${opportunity.executable ? escapeHtml(formatStatus(opportunity.status)) : "待生成动作"}</em>`
                }
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="empty-state">当前没有足够证据建立增长机会池。</div>`;

  qs("#growthPlanGrid").innerHTML = (growth.weekly_plan || []).length
    ? growth.weekly_plan
        .map(
          (step) => `
        <article class="growth-plan-step ${escapeHtml(step.status || "planned")}">
          <div class="growth-plan-day">D${step.day}</div>
          <div>
            <span>${escapeHtml(step.goal)}</span>
            <h3>${escapeHtml(step.title)}</h3>
            <p>${escapeHtml(step.instruction)}</p>
            <small>${escapeHtml(step.verify)}</small>
            ${step.stop_condition ? `<em>停止：${escapeHtml(step.stop_condition)}</em>` : ""}
              </div>
        </article>
          `,
        )
        .join("")
    : `<div class="empty-state">本周增长计划尚未生成，确认主动作后会排出 7 日节奏。</div>`;
  qs("#growthEvidenceList").innerHTML = (growth.evidence || []).length
    ? growth.evidence.map((row) => `<div><i></i><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><i></i><span>等待可展开的经营依据。</span></div>`;
  qs("#growthStopList").innerHTML = (growth.do_not_do || []).length
    ? growth.do_not_do.map((row) => `<div><strong>×</strong><span>${escapeHtml(row)}</span></div>`).join("")
    : `<div><strong>×</strong><span>不要同时改动多个经营变量。</span></div>`;
}

function renderInsightTiles() {
  const dashboard = state.dashboard;
  const alignment = dashboard.document_alignment || {};
  const growth = dashboard.agents?.growth || {};
  const diagnosis = dashboard.agents?.diagnosis || {};
  const examples = takeTop(dashboard.question_examples || [], 3);
  const tiles = [
    {
      tone: "green",
      icon: "T",
      title: "资料对齐优先",
      copy: alignment.recommendations?.[0] || alignment.summary || "把资料补齐后，5 个 Agent 才能共享同一事实源。",
      button: { label: alignment.status === "aligned" ? "查看资料状态" : "先修资料", question: "现在最需要补什么资料？" },
      metric: alignment.alignment_score ? `对齐分 ${alignment.alignment_score}` : "等待资料",
    },
    {
      tone: "orange",
      icon: "✦",
      title: "诊断结论",
      copy: diagnosis.workflow_summary || dashboard.daily_brief?.reason || "优先看昨日主问题，再决定动作。",
      button: { label: "问 AI 店长", question: examples[0] || "为什么最近订单下降？" },
      metric: dashboard.daily_brief?.yesterday_change || "诊断中",
    },
    {
      tone: "violet",
      icon: "◍",
      title: "增长节奏",
      copy: growth.reason || "先锁定主动作，再推进备选动作。",
      button: { label: "打开增长策略", scroll: "section-growth" },
      metric: growth.today_priority || `实验 ${(dashboard.experiments || []).length} 条`,
    },
  ];

  qs("#insightTiles").innerHTML = tiles
    .map(
      (tile) => `
        <article class="insight-tile ${tile.tone}">
          <div class="insight-icon">${escapeHtml(tile.icon)}</div>
          <div class="insight-metric">${escapeHtml(tile.metric)}</div>
          <div class="insight-title">${escapeHtml(tile.title)}</div>
          <div class="insight-copy">${escapeHtml(tile.copy)}</div>
          <button class="insight-button" ${
            tile.button.question ? `data-ask-question="${escapeHtml(tile.button.question)}"` : ""
          } ${tile.button.scroll ? `data-scroll-target="${tile.button.scroll}"` : ""}>${escapeHtml(tile.button.label)}</button>
        </article>
      `,
    )
    .join("");
}

function renderCompetition() {
  const dashboard = state.dashboard;
  const competition = dashboard.agents?.competition || dashboard.competition || {};
  const competitorPool = [...(competition.top_competitors || [])];
  if (state.competitionFilter === "change") {
    competitorPool.sort(
      (left, right) =>
        Number(Boolean(right.recent_move)) - Number(Boolean(left.recent_move)) ||
        (right.score || 0) - (left.score || 0),
    );
  } else {
    competitorPool.sort((left, right) => (right.score || 0) - (left.score || 0));
  }
  const competitors = takeTop(competitorPool, 3);
  renderCompetitionMap();
  qs("#competitionSummary").textContent =
    competition.conclusion || competition.strategy || "周边证据还不够，先按商圈和价格带做稳妥判断。";
  const nearbyTotal = competition.nearby_total ?? (competition.top_competitors || []).length;
  qs("#competitionFootnote").textContent = nearbyTotal
    ? `这会儿重点盯着周边 ${nearbyTotal} 家同类商家`
    : "周边竞品数据还在慢慢补齐";

  if (!competitors.length) {
    const evidence = takeTop([...(competition.evidence || []), ...(competition.reasons || [])], 3);
    qs("#competitorList").innerHTML = `
      <div class="competition-evidence-card">
        <div class="competition-evidence-head">
          <strong>竞品快照待补齐</strong>
          <span>${evidence.length || 0} 条基础依据</span>
      </div>
        <div class="competition-evidence-list">
          ${
            evidence.length
              ? evidence.map((item) => `<div><i></i><span>${escapeHtml(item)}</span></div>`).join("")
              : `<div><i></i><span>连接采集平台后，将自动建立竞品商品与价格变化快照。</span></div>`
          }
      </div>
    </div>
  `;
    return;
  }

  qs("#competitorList").innerHTML = competitors
    .map(
      (competitor, index) => `
        <div class="competitor-row">
          <div class="competitor-media">
            <img class="thumb small" src="${imageForFood((competitor.featured_products || [competitor.name])[0])}" alt="${escapeHtml(competitor.name)}" />
            <div class="competitor-rank">${index + 1}</div>
          </div>
          <div>
            <div class="competitor-title">${escapeHtml(competitor.name)}｜${escapeHtml(competitor.positioning || "同商圈竞品")}</div>
            <div class="competitor-meta">${
              competitor.price_band ? `¥${escapeHtml(competitor.price_band)}｜` : ""
            }${competitor.rating ? `评分 ${competitor.rating}｜` : ""}菜单 ${competitor.menu_item_count || 0} 个 / 套餐 ${competitor.set_meal_count || 0} 个</div>
            <div class="competitor-meta">优势：${escapeHtml((competitor.strengths || [competitor.advantage]).filter(Boolean).join("；") || "证据不足")}</div>
          </div>
          <div>
            <div class="competitor-distance">${competitor.distance_m ? `${Math.round(competitor.distance_m)}m` : "同商圈"}</div>
            <div class="competitor-score">${competitor.score || "--"} 分</div>
        </div>
      </div>
    `,
    )
    .join("");
}

function renderCollectionCenter() {
  const runs = state.collectionRuns || [];
  const latestRun = runs[0];
  const competition = state.dashboard?.agents?.competition || state.dashboard?.competition || {};
  const changes = competition.changes || [];
  const monitoredCount = state.competitionMap?.competitors?.length || 0;
  const configuredProviders = state.publicConfig?.competition_collection?.providers || [];
  const schedule = state.publicConfig?.competition_collection?.schedule || "07:30";
  const teamStatus = agentCapabilityStatus("collection");

  qs("#collectionLiveStatus").textContent = latestRun
    ? `${latestRun.status === "completed" ? "采集正常" : "需要处理"} · ${collectionTime(latestRun.completed_at || latestRun.started_at)}`
    : "等待首次手机授权";

  const connectedLinks = (state.platformLinks || []).filter(
    (link) => link.status === "connected" || link.connected_at,
  );
  const connectedCount = Math.min(4, connectedLinks.length);

  const collectionHero = qs("#collectionAgentHero");
  if (collectionHero) {
    collectionHero.innerHTML = `
      <div class="matrix-hero-score">
        <span>连接度</span>
        <strong>${connectedCount}/4</strong>
      </div>
      <div class="matrix-hero-copy">
        <div class="product-panel-title">数据采集 Agent · L1 感知</div>
        <h3>${
          connectedCount
            ? "公开页证据正在流入经营大脑"
            : "先连接手机端，店长才能看见市场变化"
        }</h3>
        <p>输入：外卖后台可见页、菜单、评价与竞品公开信息。输出：统一快照，供诊断 / 竞争 / 增长调度。</p>
        <small>${escapeHtml(teamStatus.meta)} · 每日 ${schedule} 补采</small>
      </div>
      <div class="matrix-hero-side">
        <div class="product-panel-title">下一步</div>
        <strong>${connectedCount ? "保持更新" : "连接平台"}</strong>
        <p>${
          connectedCount
            ? "有变化时会进入商圈竞争与今日异常。"
            : "密码留在手机本地；云端只收公开页证据。"
        }</p>
        <button class="topbar-button primary" type="button" id="collectionHeroConnectBtn">${
          connectedCount ? "连接更多平台" : "开始连接"
        }</button>
      </div>
    `;
    qs("#collectionHeroConnectBtn")?.addEventListener("click", () => openCollectionModal());
  }
  const summary = [
    {
      label: "手机平台连接",
      value: `${connectedCount} / 4`,
      meta: connectedCount ? "已有平台完成手机端连接" : "等待移动端 Connector 回传",
    },
    { label: "重点竞品", value: monitoredCount, meta: "已进入门店竞争观察集合" },
    { label: "最近写入快照", value: latestRun?.snapshot_count || 0, meta: `每日 ${schedule} 更新` },
    { label: "公开页面变化", value: changes.length, meta: "Observed / Derived 证据" },
  ];
  qs("#collectionSummaryGrid").innerHTML = summary
    .map(
      (item) => `
        <article class="collection-summary-card">
          <div class="collection-summary-label">${escapeHtml(item.label)}</div>
          <div class="collection-summary-value">${escapeHtml(item.value)}</div>
          <div class="collection-summary-meta">${escapeHtml(item.meta)}</div>
        </article>
      `,
    )
    .join("");

  const platforms = [
    { key: "meituan", mark: "美", name: "美团外卖", scope: "菜品 · 价格 · 月售", copy: "采集公开菜单、价格、页面月售、套餐和配送信息。" },
    { key: "dianping", mark: "点", name: "大众点评", scope: "评分 · 评价 · 榜单", copy: "采集推荐菜、评分、公开评价和榜单位置变化。" },
    { key: "eleme", mark: "饿", name: "饿了么", scope: "菜品 · 价格 · 销量", copy: "采集公开菜单、价格、销量、活动和配送信息。" },
    { key: "douyin", mark: "抖", name: "抖音生活服务", scope: "团购 · 价格 · 已售", copy: "采集团购套餐、价格、公开已售和评价内容。" },
  ];
  qs("#platformConnectionGrid").innerHTML = platforms
    .map((platform) => {
      const linked = (state.platformLinks || []).some((link) => {
        if (!(link.status === "connected" || link.connected_at)) return false;
        const value = String(link.platform || "").toLowerCase();
        return value === platform.key || value.includes(platform.key) || String(link.platform || "") === platform.name;
      });
      return `
        <article class="platform-card">
          <div class="platform-card-head">
            <div class="platform-mark ${platform.key}">${platform.mark}</div>
            <div>
              <div class="platform-title">${platform.name}</div>
              <div class="platform-status">${linked ? "已连接" : "待商家手机授权"}</div>
        </div>
      </div>
          <div class="platform-card-copy">${platform.copy}</div>
          <div class="platform-card-foot">
            <span class="platform-scope">${platform.scope}</span>
            <button class="platform-connect-button" data-platform-connect="${platform.key}" data-platform-label="${platform.name}">${linked ? "重新连接" : "连接"}</button>
          </div>
        </article>
      `;
    })
    .join("");

  qs("#collectionRunList").innerHTML = runs.length
    ? takeTop(runs, 4)
        .map(
          (run) => `
            <div class="collection-run-row">
              <span class="run-dot ${run.status === "failed" ? "failed" : ""}"></span>
              <div>
                <div class="collection-row-title">${escapeHtml(run.provider === "amap" ? "高德周边发现" : run.provider === "licensed_partner" ? "授权数据供应商" : run.provider)}</div>
                <div class="collection-row-meta">${run.status === "completed" ? `发现 ${run.discovered_count} 家，写入 ${run.snapshot_count} 份快照` : escapeHtml(run.error || "采集失败")}</div>
              </div>
              <div class="collection-row-time">${collectionTime(run.completed_at || run.started_at)}</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">尚无采集记录。配置高德或在手机端连接平台后开始更新。</div>`;

  qs("#collectionChangeCount").textContent = `${changes.length} 条`;
  qs("#collectionChangeList").innerHTML = changes.length
    ? takeTop(changes, 4)
        .map(
          (change) => `
            <div class="collection-change-row">
              <span class="change-dot"></span>
              <div>
                <div class="collection-row-title">${escapeHtml(collectionChangeLabel(change.type))}</div>
                <div class="collection-row-meta">${escapeHtml(change.summary)}</div>
              </div>
              <div class="collection-row-time">有证据</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">至少完成两次快照后，系统会在这里展示菜品变化。</div>`;

  renderPlatformIntelPanel();

  const providerText = configuredProviders.length
    ? `服务端已配置：${configuredProviders.join(" / ")}`
    : "服务端尚未配置自动采集源";
  qs("#collectionLiveStatus").title = providerText;
}

function renderPlatformIntelPanel() {
  const intel = state.platformIntel || {};
  const items = intel.items || [];
  const lastRun = intel.last_run;
  const schedule = intel.schedule || state.publicConfig?.platform_intel?.schedule || "07:45";
  const countEl = qs("#platformIntelCount");
  const statusEl = qs("#platformIntelRunStatus");
  const listEl = qs("#platformIntelList");
  if (!countEl || !statusEl || !listEl) return;
  countEl.textContent = `${items.length} 条`;
  const kindLabel = { promo: "促销", policy: "政策", news: "新闻" };
  if (lastRun) {
    const runOk = lastRun.status === "completed" || lastRun.status === "completed_with_errors";
    statusEl.innerHTML = `
      <div class="collection-run-row">
        <span class="run-dot ${runOk ? "" : "failed"}"></span>
        <div>
          <div class="collection-row-title">${runOk ? "官网公开页已采集" : "官网采集失败"}</div>
          <div class="collection-row-meta">${
            lastRun.error
              ? escapeHtml(lastRun.error)
              : `新 ${lastRun.new_count || 0} · 更新 ${lastRun.updated_count || 0} · 每日 ${schedule}`
          }</div>
        </div>
        <div class="collection-row-time">${collectionTime(lastRun.completed_at || lastRun.started_at)}</div>
      </div>
    `;
  } else {
    statusEl.innerHTML = `<div class="empty-state">还没采过官网。点「采集官网政策与活动」，或等每日 ${schedule} 自动跑。</div>`;
  }
  listEl.innerHTML = items.length
    ? takeTop(items, 8)
        .map((item) => {
          const kind = kindLabel[item.kind] || item.kind;
          return `
            <div class="collection-change-row">
              <span class="change-dot"></span>
              <div>
                <div class="collection-row-title"><span class="intel-kind ${escapeHtml(item.kind || "news")}">${escapeHtml(kind)}</span>${escapeHtml(item.title || "")}</div>
                <div class="collection-row-meta">${escapeHtml((item.platform || "") + " · " + (item.summary || item.source_name || item.url || ""))}</div>
              </div>
              <div class="collection-row-time">${item.fetched_at ? collectionTime(item.fetched_at) : ""}</div>
            </div>
          `;
        })
        .join("")
    : `<div class="empty-state">没有公开政策/活动证据。采集失败时不会假装有活动。</div>`;
}

function renderDailyBoard() {
  const dashboard = state.dashboard;
  const metrics = dashboard.metrics || [];
  const gmv = metrics.find((item) => item.key === "gmv");
  const orders = metrics.find((item) => item.key === "orders");
  const ctr = metrics.find((item) => item.key === "ctr");
  const cvr = metrics.find((item) => item.key === "cvr");
  const aov = gmv?.value && orders?.value ? gmv.value / orders.value : null;
  const aovBaseline = gmv?.baseline_value && orders?.baseline_value ? gmv.baseline_value / orders.baseline_value : null;
  const aovDelta = aov !== null && aovBaseline ? ((aov - aovBaseline) / aovBaseline) * 100 : null;
  const trend = dashboard.trend || [];
  const lastDay = trend[trend.length - 1];
  const prevDay = trend[trend.length - 2];
  qs("#yesterdayDate").textContent = lastDay && prevDay ? `${formatShortDate(lastDay.day)} vs ${formatShortDate(prevDay.day)}` : "昨日";

  const dailyCards = [
    { label: "订单量", key: "orders", value: orders?.value, delta: orders?.delta_pct },
    { label: "营业额", key: "gmv", value: gmv?.value, delta: gmv?.delta_pct },
    { label: "客单价", key: "gmv", value: aov, delta: aovDelta, formatter: (value) => (value === null ? "--" : `¥${value.toFixed(1)}`) },
    { label: "点击率", key: "ctr", value: ctr?.value, delta: ctr?.delta_pct },
    { label: "转化率", key: "cvr", value: cvr?.value, delta: cvr?.delta_pct },
    { label: "资料对齐", key: "score", value: dashboard.document_alignment?.alignment_score, delta: null, formatter: (value) => (value === null || value === undefined ? "--" : `${value} 分`) },
  ];

  qs("#yesterdayMetrics").innerHTML = dailyCards
        .map(
          (item) => `
        <div class="mini-metric">
          <div class="mini-metric-label">${escapeHtml(item.label)}</div>
          <div class="mini-metric-value">${escapeHtml(item.formatter ? item.formatter(item.value) : formatMetricValue(item.key, item.value))}</div>
          <div class="mini-metric-delta ${item.delta !== null && item.delta !== undefined && item.delta < 0 ? "delta-negative" : "delta-positive"}">${escapeHtml(item.delta === null || item.delta === undefined ? "观察中" : formatDelta(item.delta))}</div>
            </div>
          `,
        )
    .join("");

  const reasons = takeTop(dashboard.agents?.diagnosis?.reasons || dashboard.observations?.map((item) => item.what_happened) || [], 3);
  qs("#yesterdayReasons").innerHTML = reasons.length
    ? reasons
        .map(
          (reason, index) => `
            <div class="reason-item">
              <div class="reason-item-title"><span class="reason-rank">${index + 1}</span><span>原因 ${index + 1}</span></div>
              <div class="reason-item-copy">${escapeHtml(reason)}</div>
            </div>
          `,
        )
        .join("")
    : `<div class="empty-state">还没有昨日归因结果。</div>`;
}

function renderStrategyMemory() {
  const memory = state.strategyMemory;
  const grid = qs("#strategyMemoryGrid");
  const meta = qs("#strategyMemoryMeta");
  const side = qs("#strategyMemorySide");
  const items = memory?.items || [];
  if (meta) meta.textContent = `${items.length} 条经验`;

  if (grid) {
    if (!items.length) {
      grid.innerHTML = `<div class="empty-state">还没有沉淀经验。评估实验 Result 后，会自动写入 Strategy Memory。</div>`;
    } else {
      grid.innerHTML = takeTop(items, 4)
        .map(
          (item) => `
          <article class="strategy-memory-card ${escapeHtml(item.result || "unknown")}">
            <div class="strategy-memory-top">
              <span>${escapeHtml(item.action_type || "动作")}</span>
              <strong>${escapeHtml(formatStatus(item.result || "unknown"))}${
                item.lift_pct == null ? "" : ` · ${formatDelta(item.lift_pct)}`
              }</strong>
            </div>
            <h3>${escapeHtml(item.lesson || "暂无 lesson")}</h3>
            <p><strong>复用：</strong>${escapeHtml(item.reuse_when || "--")}</p>
            <p><strong>避免：</strong>${escapeHtml(item.avoid_when || "无")}</p>
          </article>
        `,
        )
        .join("");
    }
  }

  if (side) {
    const positives = memory?.positive_patterns || [];
    const negatives = memory?.negative_patterns || [];
    if (!positives.length && !negatives.length && !items.length) {
      side.innerHTML = `<div class="empty-state soft">评估实验后会出现可复用经验。</div>`;
    } else {
      side.innerHTML = `
        ${positives.slice(0, 2).map((row) => `<div class="memory-pattern positive">✓ ${escapeHtml(row)}</div>`).join("")}
        ${negatives.slice(0, 2).map((row) => `<div class="memory-pattern negative">× ${escapeHtml(row)}</div>`).join("")}
        ${
          !positives.length && !negatives.length
            ? takeTop(items, 2)
                .map((item) => `<div class="memory-pattern">${escapeHtml(item.lesson)}</div>`)
                .join("")
            : ""
        }
      `;
    }
  }
}

function renderExperiments() {
  const dashboard = state.dashboard;
  const summary = dashboard.execution_summary || {};
  const experiments = takeTop(dashboard.experiments || [], 3);
  const pills = [
    { label: `待执行 ${summary.proposed || 0}`, className: "proposed" },
    { label: `已执行 ${summary.executed || 0}`, className: "executed" },
    { label: `待验证 ${summary.pending_verification || 0}`, className: "pending" },
    { label: `总实验 ${(dashboard.experiments || []).length}`, className: "total" },
  ];

  qs("#executionSummary").innerHTML = pills
    .map((pill) => `<div class="summary-pill ${pill.className}">${escapeHtml(pill.label)}</div>`)
    .join("");
  qs("#experimentTag").textContent = (dashboard.experiments || []).length ? "还在观察" : "还没开始";

  qs("#experimentTracker").innerHTML = experiments.length
    ? experiments
        .map((experiment) => {
          const { from, to } = experimentWindowBounds(experiment);
          const isPending = !experiment.result || experiment.result === "pending";
          const canEvaluate = isPending && experiment.can_evaluate !== false;
          const liftText =
            experiment.lift_pct === null || experiment.lift_pct === undefined
              ? ""
              : `｜提升 ${formatDelta(experiment.lift_pct)}`;
          return `
            <div class="experiment-row">
              <div class="experiment-headline">
                <div class="experiment-title">${escapeHtml(experiment.action_title || "动作实验")}</div>
                <div class="row-status ${statusClass(experiment.result || "pending")}">${escapeHtml(formatStatus(experiment.result || "pending"))}</div>
              </div>
              <div class="experiment-copy">${escapeHtml(experiment.notes || experiment.result_summary || "等待观察窗完成。")}</div>
              <div class="experiment-copy">指标 ${escapeHtml(experiment.metric_name || "--")}｜基线 ${experiment.baseline_value ?? "--"}${experiment.observed_value !== null && experiment.observed_value !== undefined ? `｜当前 ${experiment.observed_value}` : ""}${liftText}${from && to ? `｜窗口 ${escapeHtml(formatShortDate(from))}-${escapeHtml(formatShortDate(to))}` : ""}</div>
              <div class="experiment-copy">归因质量 ${escapeHtml(experiment.attribution_quality || "medium")}${
                experiment.ads_budget != null ? `｜预算 ¥${Number(experiment.ads_budget).toFixed(0)}` : ""
              }${
                experiment.ads_roi != null ? `｜预估 ROI ${Number(experiment.ads_roi).toFixed(2)}` : ""
              }</div>
              <div class="progress-track"><div class="progress-bar" style="width:${experimentProgress(experiment)}%"></div></div>
              ${
                canEvaluate
                  ? `<button class="action-button" data-experiment-evaluate="${escapeHtml(experiment.id)}">评估结果</button>`
                  : isPending
                    ? `<div class="experiment-copy">观察窗未到，先不要评估。</div>`
                    : `<button class="link-button" type="button" data-scroll-target="section-growth">查看经验沉淀</button>`
              }
            </div>
          `;
        })
        .join("")
    : `<div class="empty-state">当前还没有实验记录，动作执行后会自动进入追踪。</div>`;
}

function buildMatrixWorkspaceHtml() {
  const hubCards = MATRIX_AGENT_DEFS.map(
    (item) => `
      <article class="matrix-hub-card" data-matrix-hub-key="${item.key}">
        <div class="matrix-hub-top">
          <span>${escapeHtml(item.kicker)}</span>
          <strong id="matrix-hub-score-${item.key}">--</strong>
        </div>
        <h3>${escapeHtml(item.label)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="matrix-hub-meta" id="matrix-hub-meta-${item.key}">等待读取</div>
        <button class="action-button" type="button" data-scroll-target="section-${item.key}">进入工作台</button>
      </article>
    `,
  ).join("");

  const panels = MATRIX_AGENT_DEFS.map(
    (item) => `
      <section class="dashboard-section matrix-agent-section workspace-panel" id="section-${item.key}" data-workspace-panel="section-${item.key}" data-matrix-key="${item.key}">
        <div class="section-head">
          <div>
            <div class="section-kicker">${escapeHtml(item.kicker)}</div>
            <h2>${escapeHtml(item.label)}工作台</h2>
            <p>${escapeHtml(item.copy)}</p>
          </div>
          <div class="matrix-head-actions">
            <button class="link-button" type="button" data-scroll-target="section-matrix">返回矩阵</button>
            <div class="product-health-tag" id="matrix-tag-${item.key}">健康度 --</div>
          </div>
        </div>
        <div class="matrix-hero" id="matrix-hero-${item.key}"></div>
        <div class="matrix-grid">
          <div class="matrix-panel">
            <div class="product-panel-title">关键信号</div>
            <div class="matrix-signal-list" id="matrix-signals-${item.key}"></div>
          </div>
          <div class="matrix-panel">
            <div class="product-panel-title">专属洞察</div>
            <div class="matrix-extra" id="matrix-extra-${item.key}"></div>
          </div>
        </div>
        <div class="matrix-section-head">
          <div>
            <div class="product-panel-title">优先动作</div>
            <p>生成后进入 OHRE，并通过 Profit Gate 约束活动/投流。</p>
          </div>
          <div class="section-meta" id="matrix-action-meta-${item.key}">0 条动作</div>
        </div>
        <div class="matrix-action-grid" id="matrix-actions-${item.key}"></div>
      </section>
    `,
  ).join("");

  return `
    <section class="dashboard-section matrix-hub-section workspace-panel" id="section-matrix" data-workspace-panel="section-matrix">
      <div class="section-head">
        <div>
          <div class="section-kicker">行动中心 · 由 AI 店长调度</div>
          <h2>增长执行与规模化 Agent</h2>
          <p>平台活动 / 投流 / AI客服 / 用户关系 / 评分评价 / 线上门店增长：有任务再进。</p>
        </div>
        <button class="topbar-button" type="button" data-scroll-target="section-growth">回增长策略</button>
      </div>
      <div class="matrix-hub-grid" id="matrixHubGrid">${hubCards}</div>
    </section>
    ${panels}
  `;
}

function ensureMatrixWorkspace() {
  if (qs("#section-matrix")) return;
  const stage = qs("#workspaceStage");
  if (!stage) return;
  const ai = qs("#section-ai");
  if (ai) ai.insertAdjacentHTML("beforebegin", buildMatrixWorkspaceHtml());
  else stage.insertAdjacentHTML("beforeend", buildMatrixWorkspaceHtml());
}

function renderMatrixExtras(key, agent) {
  if (key === "promo") {
    const unlock = agent.unlock_ready ? "可解锁活动动作" : "暂未达到解锁条件";
    const opportunities = (agent.opportunities || []).slice(0, 4);
    return `
      <div class="matrix-kv"><span>解锁状态</span><strong>${unlock}</strong></div>
      <div class="matrix-kv"><span>预期影响</span><strong>${escapeHtml(agent.expected_impact || "--")}</strong></div>
      ${
        opportunities.length
          ? `<ul class="matrix-bullet-list">${opportunities
              .map((row) => `<li>${escapeHtml(row)}</li>`)
              .join("")}</ul>`
          : `<div class="empty-state soft">暂无活动机会，先观察到手率与活动到期事件。</div>`
      }
    `;
  }
  if (key === "ads") {
    return `
      <div class="matrix-kv"><span>建议预算</span><strong>${
        agent.recommended_budget != null ? `¥${Number(agent.recommended_budget).toFixed(0)}` : "--"
      }</strong></div>
      <div class="matrix-kv"><span>目标商品</span><strong>${escapeHtml(agent.target_item_name || "--")}</strong></div>
      <div class="matrix-kv"><span>预估 ROI</span><strong>${
        agent.estimated_roi != null ? Number(agent.estimated_roi).toFixed(2) : "--"
      }</strong></div>
      <div class="matrix-kv"><span>解锁状态</span><strong>${agent.unlock_ready ? "可试验投流" : "先补转化证据"}</strong></div>
      <p class="matrix-extra-copy">${escapeHtml(agent.expected_impact || "投流动作必须过 Profit Gate。")}</p>
    `;
  }
  if (key === "crm") {
    const segments = agent.segments || [];
    return `
      <div class="matrix-kv"><span>复购率</span><strong>${
        agent.repurchase_rate != null ? `${(Number(agent.repurchase_rate) * 100).toFixed(1)}%` : "--"
      }</strong></div>
      <div class="matrix-kv"><span>复购变化</span><strong>${
        agent.repurchase_delta_pct == null ? "--" : formatDelta(agent.repurchase_delta_pct)
      }</strong></div>
      ${
        segments.length
          ? segments
              .map(
                (seg) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(seg.label)}</strong>
              <span>${seg.estimated_count ?? "--"} 人${
                  seg.share_pct != null ? ` · ${(Number(seg.share_pct) * 100).toFixed(0)}%` : ""
                }</span>
              <p>${escapeHtml(seg.note || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">客群分层证据不足。</div>`
      }
    `;
  }
  if (key === "service") {
    const themes = Object.entries(agent.theme_breakdown || {}).slice(0, 4);
    return `
      <div class="matrix-kv"><span>待处理回复</span><strong>${agent.pending_replies ?? 0}</strong></div>
      <div class="matrix-kv"><span>差评数</span><strong>${agent.negative_review_count ?? 0}</strong></div>
      ${
        themes.length
          ? `<ul class="matrix-bullet-list">${themes
              .map(([label, count]) => `<li>${escapeHtml(label)} · ${count}</li>`)
              .join("")}</ul>`
          : `<p class="matrix-extra-copy">${escapeHtml(agent.expected_impact || "客服积压会在首页后台并行区汇总。")}</p>`
      }
    `;
  }
  if (key === "review") {
    const themes = agent.themes || [];
    return `
      <div class="matrix-kv"><span>均分</span><strong>${
        agent.avg_rating != null ? Number(agent.avg_rating).toFixed(1) : "--"
      }</strong></div>
      <div class="matrix-kv"><span>评分变化</span><strong>${
        agent.rating_delta_pct == null ? "--" : formatDelta(agent.rating_delta_pct)
      }</strong></div>
      <div class="matrix-kv"><span>评价数</span><strong>${agent.review_count ?? 0}</strong></div>
      ${
        themes.length
          ? themes
              .slice(0, 4)
              .map(
                (theme) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(theme.label)}</strong>
              <span>${theme.count} · ${(Number(theme.share_pct || 0) * 100).toFixed(0)}%</span>
              <p>${escapeHtml(theme.sample || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">暂无评价主题。</div>`
      }
    `;
  }
  if (key === "store_matrix") {
    const concepts = agent.concepts || [];
    return `
      <div class="matrix-kv"><span>兄弟店</span><strong>${agent.sibling_store_count ?? 0}</strong></div>
      <div class="matrix-kv"><span>解锁状态</span><strong>${agent.unlock_ready ? "可规划新店概念" : "先稳住本店"}</strong></div>
      <p class="matrix-extra-copy">${escapeHtml((agent.sibling_stores || []).slice(0, 3).join("、") || "暂无兄弟店清单")}</p>
      ${
        concepts.length
          ? concepts
              .slice(0, 3)
              .map(
                (concept) => `
            <article class="matrix-mini-card">
              <strong>${escapeHtml(concept.name)}</strong>
              <span>${escapeHtml(concept.daypart)} · ${escapeHtml(concept.readiness)}</span>
              <p>${escapeHtml(concept.rationale || concept.positioning || "")}</p>
            </article>
          `,
              )
              .join("")
          : `<div class="empty-state soft">暂无多店概念候选。</div>`
      }
    `;
  }
  return `<div class="empty-state soft">暂无专属洞察。</div>`;
}

function renderMatrixAgent(key) {
  const def = MATRIX_AGENT_DEFS.find((item) => item.key === key);
  const agent = state.dashboard?.agents?.[key] || {};
  if (!def || !qs(`#section-${key}`)) return;

  const score = agent.health_score ?? "--";
  const tag = qs(`#matrix-tag-${key}`);
  if (tag) tag.textContent = `健康度 ${score}`;

  const hubScore = qs(`#matrix-hub-score-${key}`);
  if (hubScore) hubScore.textContent = score;
  const hubMeta = qs(`#matrix-hub-meta-${key}`);
  if (hubMeta) {
    hubMeta.textContent = [
      formatReadiness(agent.readiness),
      agent.unlock_ready === true ? "可解锁" : agent.unlock_ready === false ? "未解锁" : "",
      (agent.blockers || [])[0] || "",
      (agent.priority_actions || []).length ? `${agent.priority_actions.length} 个动作` : "暂无动作",
    ]
      .filter(Boolean)
      .join(" · ");
  }

  const hero = qs(`#matrix-hero-${key}`);
  if (hero) {
    const current = agent.current_action;
    const blockers = agent.blockers || [];
    hero.innerHTML = `
      <div class="matrix-hero-score">
        <span>健康度</span>
        <strong>${score}</strong>
      </div>
      <div class="matrix-hero-copy">
        <div class="product-panel-title">AI 判断</div>
        <h3>${escapeHtml(agent.conclusion || def.summary)}</h3>
        <p>${escapeHtml((agent.reasons || [])[0] || agent.expected_impact || def.copy)}</p>
        <small>${escapeHtml(actionQueueBrief(agent) || blockers[0] || "等待更多经营证据。")}</small>
        ${
          blockers.length
            ? `<ul class="matrix-blocker-list">${blockers
                .slice(0, 4)
                .map((row) => `<li>${escapeHtml(row)}</li>`)
                .join("")}</ul>`
            : ""
        }
      </div>
      <div class="matrix-hero-side">
        <div class="product-panel-title">当前动作</div>
        <strong>${escapeHtml(current?.title || "暂无进行中动作")}</strong>
        <p>${escapeHtml(current?.phase_reason || current?.next_decision || "优先动作确认后进入 OHRE。")}</p>
        <div class="matrix-unlock-tag ${agent.unlock_ready === false ? "locked" : "ready"}">${
          agent.unlock_ready === false ? "未解锁" : "可执行"
        }</div>
      </div>
    `;
  }

  const signals = qs(`#matrix-signals-${key}`);
  if (signals) {
    signals.innerHTML = (agent.signals || []).length
      ? agent.signals
          .slice(0, 5)
          .map(
            (signal) => `
          <article class="matrix-signal-row">
            <div>
              <strong>${escapeHtml(signal.title)}</strong>
              <p>${escapeHtml(signal.detail)}</p>
            </div>
            <span class="diagnosis-severity ${escapeHtml(signal.severity || "medium")}">${escapeHtml(
              eventSeverityLabel(signal.severity || "medium"),
            )}</span>
          </article>
        `,
          )
          .join("")
      : `<div class="empty-state soft">暂无新增信号。</div>`;
  }

  const extra = qs(`#matrix-extra-${key}`);
  if (extra) extra.innerHTML = renderMatrixExtras(key, agent);

  const actions = qs(`#matrix-actions-${key}`);
  const actionMeta = qs(`#matrix-action-meta-${key}`);
  const priorityActions = agent.priority_actions || [];
  if (actionMeta) actionMeta.textContent = `${priorityActions.length} 条动作`;
  if (actions) {
    actions.innerHTML = priorityActions.length
      ? priorityActions
          .map((action, index) => {
            const gated = action.create_enabled === false;
            const gateReason =
              action.create_block_reason ||
              action.profit_gate_reason ||
              (agent.unlock_ready === false ? (agent.blockers || [])[0] : "") ||
              "暂不可创建";
            return `
          <article class="matrix-action-card ${gated ? "gated" : ""}">
            <div class="matrix-action-top">
              <span>${escapeHtml(action.risk_level || "low")} risk</span>
              <span>${escapeHtml(action.expected_metric || "指标")} · ${action.window_hours || 24}h</span>
            </div>
            <h3>${escapeHtml(action.title)}</h3>
            <p>${escapeHtml(action.detail)}</p>
            ${
              action.profit_gate_reason
                ? `<div class="matrix-gate-note ${action.profit_gate_allowed === false ? "blocked" : ""}">${escapeHtml(
                    action.profit_gate_reason,
                  )}</div>`
                : ""
            }
            <div class="matrix-action-foot">
              <span>${
                action.expected_lift_pct_high
                  ? `预计 +${action.expected_lift_pct_low || 0}~${action.expected_lift_pct_high}%`
                  : escapeHtml(action.object_name || "门店")
              }</span>
              ${
                gated
                  ? `<button type="button" disabled title="${escapeHtml(gateReason)}">暂不可创建</button>`
                  : ["service", "review"].includes(key)
                    ? `<button type="button" class="primary" data-matrix-agent="${key}" data-matrix-action-index="${index}" data-matrix-enable="1">一键启用</button>`
                    : `<button type="button" data-matrix-agent="${key}" data-matrix-action-index="${index}">生成动作</button>`
              }
            </div>
            ${gated ? `<small class="matrix-gate-reason">${escapeHtml(gateReason)}</small>` : ""}
          </article>
        `;
          })
          .join("")
      : `<div class="empty-state">当前没有可执行优先动作。${
          (agent.blockers || [])[0] ? `阻塞：${escapeHtml(agent.blockers[0])}` : "先补证据或回增长策略排序。"
        }</div>`;
  }
}

function renderMatrixAgents() {
  ensureMatrixWorkspace();
  MATRIX_AGENT_DEFS.forEach((item) => renderMatrixAgent(item.key));
}

function renderDashboard() {
  mergeRuntimeIntoBrief();
  // 首页只渲染三栏主舞台，避免整舱 Agent/实验面板白烧
  if (document.body.classList.contains("view-home") || isHomeWorkspace(state.activeWorkspace || "section-overview")) {
    renderHomeShell();
    return;
  }
  ensureMatrixWorkspace();
  applyWorkspaceMode(state.activeWorkspace || "section-overview");
  renderStoreSelector();
  renderTopbar();
  renderGuide();
  renderManagerBrief();
  renderEventDigest();
  renderActionCenter();
  renderCompetitionAgent();
  renderMenuAgent();
  renderProductAgent();
  renderStorefrontAgent();
  renderDiagnosisAgent();
  renderGrowthAgent();
  renderMatrixAgents();
  renderStrategyMemory();
  renderInsightTiles();
  renderCompetition();
  renderCollectionCenter();
  renderAgentTeamRoster();
  renderDailyBoard();
  renderExperiments();
  renderSettingsOverview();
  renderHomeEventFeed();
  renderWorthDoing();
  renderAutoActivity();
  renderVerifiedWins();
  renderStoreProfileCard();
}

function renderMenuDeepDiagnosis() {
  const host = qs("#menuDeepDiagnosisResult");
  if (!host) return;
  const result = state.menuDeepDiagnosis;
  if (!result) {
    host.innerHTML = `<div class="empty-state">点「深度诊断」运行 12 引擎，查看结构与定价发现。</div>`;
    return;
  }
  const findings = result.findings || [];
  const counts = result.finding_count_by_severity || {};
  const countBits = Object.entries(counts)
    .map(([sev, n]) => `${sev} ${n}`)
    .join(" · ");
  host.innerHTML = `
    <p class="menu-dx-summary">${escapeHtml(
      result.summary || `共 ${findings.length} 条发现 · 数据成熟度 ${result.data_level || "--"}`,
    )}${countBits ? ` · ${escapeHtml(countBits)}` : ""}</p>
    <div class="menu-dx-findings">
      ${
        findings.length
          ? findings
              .slice(0, 12)
              .map(
                (finding) => `
                  <article class="menu-action-card">
                    <div class="product-recommendation-top">
                      <span>${escapeHtml(finding.severity || "info")}</span>
                      <span>${escapeHtml(finding.engine_id || "")}</span>
                    </div>
                    <h3>${escapeHtml(finding.title || "发现")}</h3>
                    <p>${escapeHtml(finding.description || finding.impact || "")}</p>
                    ${
                      (finding.suggested_actions || []).length
                        ? `<small>${(finding.suggested_actions || [])
                            .map((action) => escapeHtml(action))
                            .join(" · ")}</small>`
                        : ""
                    }
                  </article>
                `,
              )
              .join("")
          : `<div class="empty-state">本次诊断没有发现。</div>`
      }
    </div>
  `;
}

function renderSettingsOverview() {
  const overview = state.settingsOverview;
  if (!overview) return;

  const checklist = overview.checklist || {};
  qs("#settingsChecklist").innerHTML = (checklist.steps || [])
    .map(
      (step) => `
        <article class="settings-check-item ${step.done ? "done" : ""}">
          <strong>${step.done ? "✓" : "○"} ${escapeHtml(step.title)}</strong>
          <p>${escapeHtml(step.hint)}</p>
        </article>
      `,
    )
    .join("");

  const llm = overview.llm || {};
  const guide = overview.ai?.platform || overview.ai?.deploy || {};
  if (llm.configured) {
    guide.summary = `内置大模型引擎已就绪（独立部署，不依赖主仓）。${guide.summary || ""}`.trim();
  } else if (guide.summary) {
    guide.summary = `大模型未配置，问答将走规则引擎；如需启用请在部署环境的 .env 中配置。${guide.summary}`.trim();
  }
  showAssistGuide(guide);

  const llmHint = qs("#settingsLlmHint");
  const llmGrid = qs("#settingsLlmGrid");
  if (llmHint) {
    llmHint.textContent = llm.configured
      ? "引擎已配置，AI 店长对话将直连厂商（DeepSeek / 千问 / Kimi），失败自动 Failover。"
      : "尚未检测到大模型 Key。这里不再手动维护，需由平台默认配置或部署环境的 .env 提供。";
  }
  if (llmGrid) {
    const purposeEntries = Object.entries(llm.purposes || {});
    llmGrid.innerHTML = purposeEntries.length
      ? purposeEntries
          .map(([purpose, info]) => {
            const ready = (info.candidates || []).filter((c) => c.has_key).length;
            const total = (info.candidates || []).length;
            return `<article class="settings-llm-card ${info.configured ? "ready" : ""}">
              <strong>${escapeHtml(purpose)}</strong>
              <span>${info.configured ? "可调用" : "未就绪"} · ${ready}/${total} 节点有 Key</span>
              <small>${(info.candidates || [])
                .map((c) => `${c.provider}/${c.model}${c.has_key ? "" : "(无Key)"}`)
                .join(" → ")}</small>
            </article>`;
          })
          .join("")
      : `<div class="empty-state">正在读取引擎状态…</div>`;
  }

  const store = overview.store || {};
  const form = qs("#storeSettingsForm");
  const ops = overview.store_ops || {};
  const opsForm = qs("#storeOpsForm");
  if (opsForm) {
    Array.from(opsForm.elements).forEach((el) => {
      if (!el.name) return;
      if (el.name === "task_url") el.value = ops.task_url ? `${location.origin}${ops.task_url}` : "";
      else if (ops[el.name] !== undefined && ops[el.name] !== null) el.value = ops[el.name];
    });
  }
  if (form) {
    Array.from(form.elements).forEach((el) => {
      if (!(el instanceof HTMLInputElement) || !el.name) return;
      const value = store[el.name];
      el.value = value === null || value === undefined ? "" : value;
    });
  }

  const menuText = qs("#menuSettingsText");
  if (menuText) {
    menuText.value = (overview.menu?.items || [])
      .map((item) => [item.name, item.category || "", item.price ?? ""].join("|"))
      .join("\n");
  }

  const systemList = qs("#systemSettingsList");
  if (systemList) {
    systemList.innerHTML = (overview.system || [])
      .map(
        (row) => `
          <label>
            <span>${escapeHtml(row.label)} <small>${row.configured ? "已配置" : "未配置"} · ${escapeHtml(row.source)}</small></span>
            <input
              data-setting-key="${escapeHtml(row.key)}"
              type="${row.is_secret ? "password" : "text"}"
              value="${escapeHtml(row.value || "")}"
              placeholder="${escapeHtml(row.description || "")}"
              autocomplete="off"
            />
          </label>
        `,
      )
      .join("");
  }

  const platformList = qs("#settingsPlatformList");
  if (platformList) {
    const links = overview.platforms || [];
    platformList.innerHTML = links.length
      ? links
          .map(
            (link) => `
              <div class="settings-platform-row">
                <strong>${escapeHtml(link.platform)}</strong>
                <span>${escapeHtml(link.status)} · ${escapeHtml(link.connector_mode || "--")}</span>
                <small>${link.last_sync_at ? `同步于 ${escapeHtml(link.last_sync_at)}` : "尚未同步"}</small>
              </div>
            `,
          )
          .join("")
      : `<div class="empty-state">尚未连接平台。可先用演示同步，或填写 HTTP 对接地址。</div>`;
  }
}
