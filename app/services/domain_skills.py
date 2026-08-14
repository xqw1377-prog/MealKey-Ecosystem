"""Domain Skills — 四个核心经营域的专业分析能力（Runtime V1 Domain Playbook）。

每个 Domain 只产出 findings/diagnosis/candidate_actions/evidence/dependencies。
不直接给老板建议——交给 ODO → Profit/Risk → POIE。

Product：商品为什么能卖/卖不动 + 线上货架承接力
Traffic：把有效商品放大、无效商品拦住
Profit：Gatekeeper，贡献利润守门
Competition：谁在抢生意 + 做了什么改变
"""

from __future__ import annotations

from typing import Any

from app.schemas.domain_playbook import (
    CandidateAction,
    DomainDiagnosis,
    DomainFinding,
    DomainKey,
    DomainSkillResult,
    ProductReadiness,
    TrafficReadiness,
)


def compute_product_readiness(
    *,
    sku_id: str = "",
    sku_name: str = "",
    role: str = "",
    ctr: float | None = None,
    ctr_baseline: float | None = None,
    cvr: float | None = None,
    cvr_baseline: float | None = None,
    rating: float | None = None,
    availability: float | None = None,
    price: float | None = None,
    avg_market_price: float | None = None,
    impressions: int | None = None,
    avg_impressions: int | None = None,
) -> ProductReadiness:
    """计算商品准备度（6 维评分）。

    每维 0-1，overall = 加权平均，ready = overall >= 0.65。
    """
    # 可见度：曝光 vs 均值
    visibility = 0.5
    if impressions is not None and avg_impressions and avg_impressions > 0:
        visibility = min(1.0, impressions / avg_impressions)

    # 点击力：CTR vs 基线
    clickability = 0.5
    if ctr is not None and ctr_baseline and ctr_baseline > 0:
        clickability = min(1.0, ctr / ctr_baseline)

    # 转化力：CVR vs 基线
    conversion = 0.5
    if cvr is not None and cvr_baseline and cvr_baseline > 0:
        conversion = min(1.0, cvr / cvr_baseline)

    # 评分
    rating_score = 0.5
    if rating is not None:
        rating_score = min(1.0, rating / 5.0)

    # 在售稳定性
    avail_score = availability if availability is not None else 0.95

    # 价格竞争力
    price_comp = 0.5
    if price is not None and avg_market_price and avg_market_price > 0:
        ratio = price / avg_market_price
        if ratio <= 0.9:
            price_comp = 0.9
        elif ratio <= 1.0:
            price_comp = 0.7
        elif ratio <= 1.1:
            price_comp = 0.5
        else:
            price_comp = 0.3

    # 加权
    overall = (
        visibility * 0.15
        + clickability * 0.25
        + conversion * 0.25
        + rating_score * 0.10
        + avail_score * 0.15
        + price_comp * 0.10
    )

    return ProductReadiness(
        sku_id=sku_id,
        sku_name=sku_name,
        role=role,
        visibility=round(visibility, 2),
        clickability=round(clickability, 2),
        conversion=round(conversion, 2),
        rating=round(rating_score, 2),
        availability=round(avail_score, 2),
        price_competitiveness=round(price_comp, 2),
        overall=round(overall, 2),
        ready=overall >= 0.65,
    )


def compute_traffic_readiness(
    product_readiness: ProductReadiness | None,
    *,
    cvr: float | None = None,
    cvr_baseline: float | None = None,
    take_home_rate: float | None = None,
    profit_floor: float | None = None,
    goal_relevant: bool = True,
) -> TrafficReadiness:
    """计算流量准备度（材料 §六）。

    聚合 Product Readiness × Conversion Health × Profit Safety × Capacity × Goal。
    """
    tr = TrafficReadiness()

    if product_readiness:
        tr.product_readiness_score = product_readiness.overall
        tr.product_ready = product_readiness.ready

    # Conversion Health
    if cvr is not None and cvr_baseline and cvr_baseline > 0:
        tr.conversion_score = min(1.0, cvr / cvr_baseline)
        tr.conversion_healthy = tr.conversion_score >= 0.85

    # Profit Safety
    if take_home_rate is not None:
        floor = profit_floor or 0.58
        tr.profit_score = min(1.0, take_home_rate / max(floor, 0.01))
        tr.profit_safe = take_home_rate >= floor

    tr.goal_relevant = goal_relevant
    tr.goal_score = 0.9 if goal_relevant else 0.3

    # 综合
    tr.overall = (
        tr.product_readiness_score * 0.30
        + tr.conversion_score * 0.25
        + tr.profit_score * 0.20
        + tr.capacity_score * 0.10
        + tr.goal_score * 0.15
    )
    tr.ready = tr.overall >= 0.60 and tr.product_ready and tr.profit_safe
    return tr


# ═══════════════════════════════════════════════════════════
# 四个 Domain 的 analyze 函数
# ═══════════════════════════════════════════════════════════


def analyze_product(
    *,
    item_snapshots: list[Any],
    ctr_delta: float | None = None,
    cvr_delta: float | None = None,
    store_rating: float | None = None,
) -> DomainSkillResult:
    """Product Domain 分析（材料 §三诊断路径）。"""
    findings: list[DomainFinding] = []
    candidate_actions: list[CandidateAction] = []
    dependencies: list[DomainKey] = []

    # 找核心商品
    hero = None
    for snap in item_snapshots:
        if getattr(snap, "role", "") == "Hero Product" or getattr(snap, "order_share_pct", 0) and (getattr(snap, "order_share_pct", 0) or 0) >= 35:
            hero = snap
            break
    if hero is None and item_snapshots:
        hero = max(item_snapshots, key=lambda s: getattr(s, "observe_orders", 0) or 0)

    product_readiness = None
    if hero:
        product_readiness = compute_product_readiness(
            sku_id=getattr(hero, "item_id", ""),
            sku_name=getattr(hero, "name", ""),
            role=getattr(hero, "role", ""),
            ctr=getattr(hero, "observe_ctr", None),
            ctr_baseline=getattr(hero, "baseline_ctr", None),
            cvr=getattr(hero, "observe_cvr", None),
            cvr_baseline=getattr(hero, "baseline_cvr", None),
            rating=store_rating,
            availability=0.95,
            price=getattr(hero, "price", None),
        )

        # 诊断路径（材料 §三决策树）— LLM 推理 + 规则降级
        from app.services.diagnosis_reasoner import llm_diagnose_product_issue

        hero_ctr_delta = getattr(hero, "ctr_delta_pct", None)
        hero_cvr_delta = getattr(hero, "cvr_delta_pct", None)

        # LLM 推理单品根因（上下文感知：竞品/评价/价格对比）
        llm_result = llm_diagnose_product_issue(
            item_name=getattr(hero, "name", ""),
            item_role=getattr(hero, "role", ""),
            ctr=getattr(hero, "observe_ctr", None),
            ctr_delta=hero_ctr_delta,
            cvr=getattr(hero, "observe_cvr", None),
            cvr_delta=hero_cvr_delta,
            orders=int(getattr(hero, "observe_orders", 0) or 0),
            order_share=getattr(hero, "order_share_pct", None),
            price=getattr(hero, "price", None),
            rating=store_rating,
        )

        if llm_result.get("source") == "llm":
            # LLM 推理成功——用 LLM 的根因替代 if-else
            diagnosis_text = llm_result.get("diagnosis", "")
            root_cause = llm_result.get("root_cause", "")
            confidence = llm_result.get("confidence", 0.7)
            if root_cause or hero_ctr_delta is not None and hero_ctr_delta <= -5:
                findings.append(DomainFinding(
                    code="HERO_SKU_CTR_DROP" if (hero_ctr_delta or 0) <= -5 else "SKU_ANALYSIS",
                    severity="high" if (hero_ctr_delta or 0) <= -10 else "medium" if (hero_ctr_delta or 0) <= -5 else "info",
                    title=diagnosis_text or f"{hero.name} 需要关注",
                    description=root_cause or "核心商品点击竞争力下降。",
                    evidence=llm_result.get("evidence", [])[:3],
                    confidence=confidence,
                ))
                for ca in llm_result.get("candidate_actions", [])[:2]:
                    candidate_actions.append(CandidateAction(
                        action_type=ca.get("action", "CHANGE_PRODUCT_IMAGE").upper().replace(" ", "_"),
                        title=ca.get("action", "商品优化"),
                        detail=root_cause,
                        observation_window_hours=ca.get("expected_window_hours", 48),
                        risk_level=ca.get("risk", "low"),
                        primary_variable=ca.get("primary_variable", ""),
                    ))
                dependencies.extend(llm_result.get("dependencies", []))
        elif hero_ctr_delta is not None and hero_ctr_delta <= -5:
            findings.append(DomainFinding(
                code="HERO_SKU_CTR_DROP",
                severity="high" if hero_ctr_delta <= -10 else "medium",
                title=f"{hero.name} CTR 下降 {hero_ctr_delta:.1f}%",
                description="核心商品点击竞争力下降，可能是主图/标题/价格感知/竞品视觉变化。",
                evidence=[f"CTR delta = {hero_ctr_delta:.1f}%"],
                confidence=0.82,
            ))
            candidate_actions.append(CandidateAction(
                action_type="CHANGE_PRODUCT_IMAGE",
                title=f"测试 {hero.name} 新主图",
                detail="只换主图，不改标题/价格/投流（单变量实验）。",
                observation_window_hours=48,
                risk_level="low",
                primary_variable="image",
            ))
            dependencies.append("competition")  # 需要竞争域验证

        if hero_cvr_delta is not None and hero_cvr_delta <= -5:
            findings.append(DomainFinding(
                code="SKU_CVR_DROP",
                severity="high" if hero_cvr_delta <= -10 else "medium",
                title=f"{hero.name} CVR 下降 {hero_cvr_delta:.1f}%",
                description="点击正常但购买下降，可能是价格/套餐/评价/竞争。",
                evidence=[f"CVR delta = {hero_cvr_delta:.1f}%"],
                confidence=0.80,
            ))
            candidate_actions.append(CandidateAction(
                action_type="CREATE_BUNDLE",
                title=f"为 {hero.name} 补充套餐",
                detail="用套餐提升价值感知，不改单价。",
                observation_window_hours=72,
                risk_level="medium",
                primary_variable="bundle",
            ))
            dependencies.extend(["profit", "competition"])

    diagnosis = DomainDiagnosis(
        primary=findings[0].title if findings else "商品状态正常",
        alternatives=[f.title for f in findings[1:3]],
        confidence=findings[0].confidence if findings else 0.7,
    )

    return DomainSkillResult(
        domain="product",
        findings=findings,
        diagnosis=diagnosis,
        evidence=[e for f in findings for e in f.evidence][:5],
        candidate_actions=candidate_actions,
        dependencies=list(set(dependencies)),
        recommended_next_step="换主图测试" if any(f.code == "HERO_SKU_CTR_DROP" for f in findings) else "继续观察",
        product_readiness=product_readiness,
    )


def analyze_traffic(
    *,
    product_result: DomainSkillResult | None = None,
    ads_spend: float | None = None,
    estimated_roi: float | None = None,
    cvr: float | None = None,
    cvr_baseline: float | None = None,
    take_home_rate: float | None = None,
    profit_floor: float | None = None,
    goal_relevant: bool = True,
) -> DomainSkillResult:
    """Traffic Domain 分析（材料 §九决策路径）。"""
    findings: list[DomainFinding] = []
    candidate_actions: list[CandidateAction] = []

    # 计算 Traffic Readiness
    tr = compute_traffic_readiness(
        product_result.product_readiness if product_result else None,
        cvr=cvr,
        cvr_baseline=cvr_baseline,
        take_home_rate=take_home_rate,
        profit_floor=profit_floor,
        goal_relevant=goal_relevant,
    )

    # 商品未 Ready → 禁止放量
    if not tr.product_ready:
        findings.append(DomainFinding(
            code="PRODUCT_NOT_READY",
            severity="high",
            title="商品准备度不足，禁止放大流量",
            description=f"Product Readiness = {tr.product_readiness_score:.0%}，低于 65% 阈值。先修商品再谈投流。",
            confidence=0.9,
        ))
        return DomainSkillResult(
            domain="traffic",
            findings=findings,
            diagnosis=DomainDiagnosis(primary="商品未 Ready，禁止投流", confidence=0.9),
            evidence=["Product Readiness 不足"],
            candidate_actions=[],  # 不产动作——必须先解决 Product
            dependencies=["product"],
            recommended_next_step="先调用 Product Domain 解决商品问题",
            traffic_readiness=tr,
        )

    # ROI 好 + 预算不足 → 建议加投
    if estimated_roi is not None and estimated_roi >= 3.0 and tr.ready:
        findings.append(DomainFinding(
            code="HIGH_ROI_UNDERSPEND",
            severity="positive",
            title="ROI 表现好，有放量空间",
            description=f"当前 ROI {estimated_roi:.1f}，商品 Ready，利润安全，可以考虑加投。",
            confidence=0.78,
        ))
        candidate_actions.append(CandidateAction(
            action_type="ADJUST_DAILY_BUDGET",
            title="午餐时段加投",
            detail="在 Product Ready + Profit Safe 条件下，加投 11:00-12:30 时段。",
            expected_incremental_orders=8,
            expected_incremental_profit=120,
            max_loss=60,
            observation_window_hours=24,
            risk_level="medium",
            primary_variable="budget",
        ))

    # ROI 差 → 拦截
    if estimated_roi is not None and estimated_roi < 1.5:
        findings.append(DomainFinding(
            code="LOW_ROI_OVERSPEND",
            severity="high",
            title=f"ROI {estimated_roi:.1f} 偏低，投流可能在亏钱",
            description="继续投钱的边际收益已经很低，建议暂停或减少。",
            confidence=0.82,
        ))

    return DomainSkillResult(
        domain="traffic",
        findings=findings,
        diagnosis=DomainDiagnosis(
            primary="可以放量" if tr.ready else "暂不具备放量条件",
            confidence=0.8,
        ),
        evidence=[f"Traffic Readiness = {tr.overall:.0%}"],
        candidate_actions=candidate_actions,
        dependencies=["product", "profit"],
        recommended_next_step="加投" if tr.ready else "暂不加投",
        traffic_readiness=tr,
    )


def analyze_ads(
    *,
    ads_daily: list[dict] | None = None,
    profit_floor: float | None = None,
    product_ready: bool = True,
) -> DomainSkillResult:
    """投流实战诊断 — 基于真实 AdSpendDaily 数据。

    判断维度:
    1. CPC 趋势(上升=竞争加剧/素材衰退)
    2. ROAS 变化(下降=投流效率恶化)
    3. 花费占比(占GMV比例过高=买流水)
    4. 广告订单占比(判断对自然流量的依赖)

    ads_daily: [{day, cost, clicks, impressions, orders_from_ads, gmv_from_ads, cpc, roas, ctr}]
    """
    findings: list[DomainFinding] = []
    candidate_actions: list[CandidateAction] = []

    if not ads_daily or len(ads_daily) < 2:
        return DomainSkillResult(
            domain="traffic",
            findings=[DomainFinding(
                code="ADS_DATA_INSUFFICIENT",
                severity="low",
                title="投流数据不足",
                description="需要至少 2 天投流数据才能做趋势判断。导入投流报表后会自动分析。",
                confidence=0.7,
            )],
            diagnosis=DomainDiagnosis(primary="投流数据不足,暂不诊断", confidence=0.6),
            evidence=["投流数据 < 2 天"],
            candidate_actions=[],
            dependencies=[],
            recommended_next_step="导入投流报表",
        )

    # 按日期排序,取最近 7 天
    rows = sorted(ads_daily, key=lambda r: r.get("day", ""))[-7:]
    latest = rows[-1]
    earliest = rows[0]

    # ── CPC 趋势 ──
    cpc_now = latest.get("cpc")
    cpc_before = earliest.get("cpc")
    cpc_trend = None
    if cpc_now is not None and cpc_before is not None and cpc_before > 0:
        cpc_trend = (cpc_now - cpc_before) / cpc_before * 100

    if cpc_trend is not None and cpc_trend > 20:
        findings.append(DomainFinding(
            code="CPC_RISING",
            severity="high",
            title=f"CPC 上涨 {cpc_trend:.0f}%,投流成本在恶化",
            description=f"CPC 从 ¥{cpc_before:.1f} 涨到 ¥{cpc_now:.1f}。可能原因:竞争加剧、素材衰退、出价策略不当。",
            confidence=0.82,
        ))
        candidate_actions.append(CandidateAction(
            action_type="OPTIMIZE_AD_CREATIVE",
            title="优化广告素材/出价",
            detail=f"CPC 上涨 {cpc_trend:.0f}%。建议:1)检查素材是否需要更新;2)调整出价策略;3)暂停高CPC低转化时段。",
            observation_window_hours=48,
            risk_level="low",
            primary_variable="budget",
        ))

    # ── ROAS 变化 ──
    roas_now = latest.get("roas")
    roas_before = earliest.get("roas")
    if roas_now is not None and roas_before is not None and roas_before > 0:
        roas_trend = (roas_now - roas_before) / roas_before * 100
        if roas_trend < -20:
            findings.append(DomainFinding(
                code="ROAS_DECLINING",
                severity="high",
                title=f"ROAS 下降 {-roas_trend:.0f}%,投流效率在恶化",
                description=f"ROAS 从 {roas_before:.1f} 降到 {roas_now:.1f}。每花 ¥1 带来的 GMV 在减少。",
                confidence=0.8,
            ))

    # ── ROAS 绝对值判断 ──
    if roas_now is not None:
        # ROAS = gmv_from_ads / cost。但需要考虑利润率
        # 如果到手率 60%,ROAS 至少要 > 1/0.6 = 1.67 才不亏
        threshold = 1.0 / (profit_floor or 0.17) if profit_floor else 2.0
        # profit_floor 是利润率底线(如0.17),那临界ROAS = 1/0.17 ≈ 5.9
        # 但这个口径偏保守,实际用到手率
        if roas_now < 2.0:
            findings.append(DomainFinding(
                code="LOW_ROAS",
                severity="high",
                title=f"ROAS 仅 {roas_now:.1f},投流可能亏钱",
                description=f"ROAS {roas_now:.1f} 意味着每花 ¥1 广告费只带来 ¥{roas_now:.1f} GMV。考虑利润率后大概率亏损。",
                confidence=0.85,
            ))
            if product_ready:
                candidate_actions.append(CandidateAction(
                    action_type="REDUCE_AD_BUDGET",
                    title="减少投流预算",
                    detail=f"ROAS {roas_now:.1f} 过低,建议减少预算或暂停,等商品优化后再恢复。",
                    observation_window_hours=24,
                    risk_level="medium",
                    primary_variable="budget",
                ))

    # ── 花费趋势(烧钱速度) ──
    total_cost = sum(r.get("cost") or 0 for r in rows)
    total_ads_orders = sum(r.get("orders_from_ads") or 0 for r in rows)
    avg_daily_cost = total_cost / len(rows) if rows else 0

    # ── 综合诊断 ──
    has_warning = any(f.severity == "high" for f in findings)
    primary = "投流效率健康" if not has_warning else "投流效率需要优化"
    if not findings:
        findings.append(DomainFinding(
            code="ADS_HEALTHY",
            severity="positive",
            title="投流数据正常",
            description=f"近 {len(rows)} 天平均日花费 ¥{avg_daily_cost:.0f},CPC ¥{cpc_now or 0:.1f},ROAS {roas_now or 0:.1f}。",
            confidence=0.7,
        ))
        primary = "投流效率健康,维持当前策略"

    evidence = [
        f"近 {len(rows)} 天总花费 ¥{total_cost:.0f}",
        f"CPC {('¥' + str(round(cpc_now, 1))) if cpc_now else '未知'}",
        f"ROAS {round(roas_now, 1) if roas_now else '未知'}",
    ]

    return DomainSkillResult(
        domain="traffic",
        findings=findings,
        diagnosis=DomainDiagnosis(primary=primary, confidence=0.8),
        evidence=evidence,
        candidate_actions=candidate_actions,
        dependencies=["product", "profit"],
        recommended_next_step="优化素材/出价" if has_warning else "维持当前策略",
    )


def analyze_profit(
    *,
    take_home_rate: float | None = None,
    take_home_rate_delta: float | None = None,
    contribution_margin: float | None = None,
    profit_floor: float | None = None,
    gmv_delta: float | None = None,
    ads_spend_delta: float | None = None,
    subsidy_delta: float | None = None,
) -> DomainSkillResult:
    """Profit Domain 分析（材料 §十四 Gatekeeper）。"""
    findings: list[DomainFinding] = []
    candidate_actions: list[CandidateAction] = []

    # 到手率跌破底线 → critical veto
    floor = profit_floor or 0.58
    if take_home_rate is not None and take_home_rate < floor:
        findings.append(DomainFinding(
            code="TAKE_HOME_RATE_DROP",
            severity="critical",
            title=f"到手率 {take_home_rate:.0%} 低于底线 {floor:.0%}",
            description="利润门禁拦截：所有补贴/投流类动作暂停。",
            confidence=0.95,
        ))

    # GMV 涨但利润跌
    if gmv_delta is not None and gmv_delta > 5:
        profit_dropping = (contribution_margin is not None and contribution_margin < 0.15)
        if profit_dropping or (ads_spend_delta is not None and ads_spend_delta > gmv_delta * 1.5):
            findings.append(DomainFinding(
                code="GMV_UP_PROFIT_DOWN",
                severity="high",
                title="GMV 增长但贡献利润下降——买流水",
                description=f"GMV +{gmv_delta:.1f}%，但利润结构在恶化。不是增长，是在花利润买 GMV。",
                confidence=0.85,
            ))

    # 发现涨价空间
    if take_home_rate is not None and take_home_rate > 0.70 and contribution_margin is not None and contribution_margin > 0.20:
        findings.append(DomainFinding(
            code="PRICE_INCREASE_OPPORTUNITY",
            severity="positive",
            title="存在涨价空间",
            description="到手率和贡献利润都偏高，有 ¥1-2 涨价空间。可以跑价格实验。",
            confidence=0.7,
        ))
        candidate_actions.append(CandidateAction(
            action_type="CHANGE_PRICE",
            title="价格实验 +¥1",
            detail="提价 ¥1 测试 CVR 影响。Guardrail：CVR 降幅不超过 5%。",
            expected_incremental_profit=200,
            max_loss=50,
            observation_window_hours=72,
            risk_level="medium",
            primary_variable="price",
        ))

    return DomainSkillResult(
        domain="profit",
        findings=findings,
        diagnosis=DomainDiagnosis(
            primary=findings[0].title if findings else "利润结构正常",
            confidence=findings[0].confidence if findings else 0.8,
        ),
        evidence=[f"到手率={take_home_rate}"] if take_home_rate else [],
        candidate_actions=candidate_actions,
        dependencies=[],  # Profit 不依赖其他域，它是 Gatekeeper
        recommended_next_step="拦截高风险动作" if any(f.severity == "critical" for f in findings) else "利润安全",
    )


def analyze_competition(
    *,
    competition_changes: list[Any] | None = None,
    competition_score: int | None = None,
) -> DomainSkillResult:
    """Competition Domain 分析（材料 §十九不直接跟）。"""
    findings: list[DomainFinding] = []

    for change in (competition_changes or [])[:5]:
        change_type = getattr(change, "type", "") or ""
        summary = getattr(change, "summary", "") or ""

        if change_type in ("price_down",):
            findings.append(DomainFinding(
                code="COMPETITOR_PRICE_DROP",
                severity="medium",
                title=f"竞品降价：{summary}",
                description="需要判断是否真竞品 + 是否影响我们 + 利润有没有跟价空间。不直接跟。",
                evidence=[summary],
                confidence=0.7,
            ))
        elif change_type in ("menu_added",):
            if any(kw in summary for kw in ("新品", "新上", "新增")):
                findings.append(DomainFinding(
                    code="COMPETITOR_NEW_PRODUCT",
                    severity="low",
                    title=f"竞品上新：{summary}",
                    description="需要判断是否分流我们的用户。",
                    evidence=[summary],
                    confidence=0.6,
                ))
            elif any(kw in summary for kw in ("套餐", "活动", "满减")):
                findings.append(DomainFinding(
                    code="COMPETITOR_NEW_BUNDLE",
                    severity="medium",
                    title=f"竞品新套餐/活动：{summary}",
                    description="需要判断对我们 CTR/CVR 的影响。",
                    evidence=[summary],
                    confidence=0.65,
                ))

    return DomainSkillResult(
        domain="competition",
        findings=findings,
        diagnosis=DomainDiagnosis(
            primary=findings[0].title if findings else "竞争环境稳定",
            alternatives=[],
            confidence=findings[0].confidence if findings else 0.7,
        ),
        evidence=[f.title for f in findings[:3]],
        candidate_actions=[],  # Competition 不直接产动作（材料 §十九）
        dependencies=["product", "profit"],  # 发现变化后需要 Product + Profit 验证
        recommended_next_step="交 Product + Profit 判断是否需要响应" if findings else "继续监控",
    )
