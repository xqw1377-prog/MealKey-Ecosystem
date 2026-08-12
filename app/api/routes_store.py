from __future__ import annotations

from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import (
    AgentActionCreateResponse,
    AgentKey,
    DiagnosisAgentResult,
    GrowthAgentResult,
    MenuBundleApplyResponse,
    MenuCleanupApplyResponse,
    MenuPatchApplyResponse,
    ProductActionCreateResponse,
    StoreAgentsResponse,
    StorefrontActionCreateRequest,
    StorefrontActionCreateResponse,
    StorefrontAgentResult,
    StorefrontImageAssistRequest,
)
from app.schemas.events import EventDecisionRequest, EventDecisionResponse, EventEngineResult
from app.schemas.runtime_api import DailyPlanResponse
from app.schemas.store_state import DailyJobResult, ManagerHomeBrief, StoreState
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.services.agents import (
    apply_menu_bundle,
    apply_menu_cleanup,
    apply_menu_patch,
    assist_storefront_image,
    assist_storefront_renovation,
    build_single_agent,
    build_store_agents,
    create_matrix_agent_action,
    create_product_action,
    apply_product_action,
    create_storefront_action,
)
from app.services.event_decisions import apply_decision_overrides, load_decision_map, upsert_event_decision
from app.services.event_engine import build_operating_events
from app.services.manager_brief import build_manager_home_brief, enrich_primary_experiment_from_dashboard
from app.services.strategy_memory import load_strategy_memory
from app.services.store_state import build_store_state
from app.services.daily_job import run_daily_job

router = APIRouter()

_ACTION_TITLE_MAP = {
    "change_main_image": "先换主图，抢回第一眼点击",
    "change_title": "重写标题，把卖点和价格感知说清",
    "add_set_meal": "补一组套餐，承接犹豫用户",
    "store_discount": "只在必要时做门店折扣测试",
}


def _brief_action_packages(db: Session, store_id: str) -> list[dict]:
    rows = list(
        db.execute(
            select(Recommendation)
            .where(Recommendation.store_id == store_id)
            .where(Recommendation.status.in_(("proposed", "adopted", "executed")))
            .order_by(Recommendation.created_at.desc())
            .limit(8)
        ).scalars()
    )
    packages: list[dict] = []
    for rec in rows:
        packages.append(
            {
                "id": rec.id,
                "title": _ACTION_TITLE_MAP.get(rec.action_type, rec.action_type),
                "status": rec.status,
                "expected_metric": rec.expected_metric,
                "expected_lift_pct_low": rec.expected_lift_pct_low,
                "expected_lift_pct_high": rec.expected_lift_pct_high,
                "window_hours": rec.window_hours,
                "action_type": rec.action_type,
            }
        )
    return packages


def _brief_experiments(db: Session, store_id: str) -> list[dict]:
    rows = list(
        db.execute(
            select(Experiment)
            .where(Experiment.store_id == store_id)
            .order_by(Experiment.created_at.desc())
            .limit(8)
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    payload: list[dict] = []
    for exp in rows:
        window_hours = None
        if exp.observe_from and exp.observe_to:
            window_hours = max(1, int((exp.observe_to - exp.observe_from).total_seconds() // 3600))
        can_evaluate = False
        if exp.result == "pending":
            if exp.observe_to is None:
                can_evaluate = True
            else:
                # observe_to 在模型里是 date
                can_evaluate = now.date() >= exp.observe_to
        payload.append(
            {
                "id": exp.id,
                "recommendation_id": exp.recommendation_id,
                "result": exp.result,
                "window_hours": window_hours,
                "can_evaluate": can_evaluate,
            }
        )
    return payload


@router.get("/{store_id}/store_state", response_model=StoreState)
def get_store_state(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    state = build_store_state(db=db, store_id=store_id, days=days)
    if state is None:
        raise HTTPException(status_code=404, detail="store not found")
    return state


def _events_with_overrides(db: Session, store_id: str, days: int = 7) -> EventEngineResult | None:
    state = build_store_state(db=db, store_id=store_id, days=days)
    if state is None:
        return None
    raw = build_operating_events(state)
    return apply_decision_overrides(raw, load_decision_map(db, store_id))


@router.get("/{store_id}/events", response_model=EventEngineResult)
def get_store_events(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    result = _events_with_overrides(db, store_id, days=days)
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    return result


@router.post("/{store_id}/events/decision", response_model=EventDecisionResponse)
def post_store_event_decision(
    store_id: str,
    payload: EventDecisionRequest,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    state = build_store_state(db=db, store_id=store_id, days=days)
    if state is None:
        raise HTTPException(status_code=404, detail="store not found")
    row = upsert_event_decision(
        db,
        store_id=store_id,
        fingerprint=payload.fingerprint,
        decision=str(payload.decision),
        note=payload.note,
    )
    events = apply_decision_overrides(build_operating_events(state), load_decision_map(db, store_id))
    labels = {
        "ignore": "已忽略该异常",
        "record": "已记录，稍后复盘",
        "handle_today": "已排进今天处理",
        "alert_owner": "已标记为提醒老板",
        "resolved": "已标记解决",
    }
    return EventDecisionResponse(
        store_id=store_id,
        fingerprint=row.fingerprint,
        decision=row.decision,  # type: ignore[arg-type]
        status=row.status,
        message=labels.get(row.decision, "决策已保存"),
        events=events,
    )


@router.get("/{store_id}/strategy_memory", response_model=StrategyMemorySnapshot)
def get_strategy_memory(store_id: str, db: Session = Depends(get_db)):
    state = build_store_state(db=db, store_id=store_id, days=7)
    if state is None:
        raise HTTPException(status_code=404, detail="store not found")
    return load_strategy_memory(db, store_id)


@router.get("/{store_id}/manager_brief", response_model=ManagerHomeBrief)
def get_manager_brief(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    agents = build_store_agents(db=db, store_id=store_id, days=days)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")
    events = apply_decision_overrides(
        build_operating_events(agents.store_state),
        load_decision_map(db, store_id),
    )
    parallel = []
    if agents.service.pending_replies:
        title = agents.service.priority_actions[0].title if agents.service.priority_actions else "客服积压待处理"
        parallel.append(f"[service] {title}（约 {agents.service.pending_replies} 条）")
    if agents.review.themes:
        theme = agents.review.themes[0].label
        parallel.append(f"[review] 评价主因：{theme}")
    if any(e.event_type == "ACTIVITY_EXPIRING" for e in events.events):
        parallel.append("[promo] 有活动即将到期/失效")
    if agents.ads.priority_actions and agents.ads.unlock_ready:
        parallel.append(f"[ads] {agents.ads.priority_actions[0].title}")
    strategy_memory = load_strategy_memory(db, store_id)
    brief = build_manager_home_brief(
        agents.store_state,
        events=events,
        growth=agents.growth,
        storefront=agents.storefront,
        parallel_service_notes=parallel,
        agents=agents,
        strategy_memory=strategy_memory,
        db=db,
        store_id=store_id,
    )
    brief = enrich_primary_experiment_from_dashboard(
        brief,
        action_packages=_brief_action_packages(db, store_id),
        experiments=_brief_experiments(db, store_id),
    )
    # POIE：Trigger 汇流 → 仲裁 → 投影到首页经营队列
    from app.services.poie import run_poie

    poie = run_poie(
        brief,
        store_id=store_id,
        events=events,
        agents=agents,
        strategy_memory=strategy_memory,
        db=db,
    )
    brief.ops_queue = poie.ops_queue
    from app.services.poie.proactive_feed import build_proactive_feed

    brief.proactive_feed = build_proactive_feed(poie.ops_queue)
    return brief


@router.post("/{store_id}/daily_job", response_model=DailyJobResult)
def daily_job(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    result = run_daily_job(db=db, store_id=store_id, days=days)
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    return result


@router.get("/{store_id}/agents", response_model=StoreAgentsResponse)
def get_store_agents(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    payload = build_store_agents(db=db, store_id=store_id, days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/menu/patches/{patch_index}/apply", response_model=MenuPatchApplyResponse)
def apply_store_menu_patch(
    store_id: str,
    patch_index: int,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    try:
        payload = apply_menu_patch(db=db, store_id=store_id, patch_index=patch_index, days=days)
    except IndexError:
        raise HTTPException(status_code=404, detail="menu patch suggestion not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/menu/cleanup/{candidate_index}/apply", response_model=MenuCleanupApplyResponse)
def apply_store_menu_cleanup(
    store_id: str,
    candidate_index: int,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    try:
        payload = apply_menu_cleanup(db=db, store_id=store_id, candidate_index=candidate_index, days=days)
    except IndexError:
        raise HTTPException(status_code=404, detail="menu cleanup candidate not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/menu/bundles/{opportunity_index}/apply", response_model=MenuBundleApplyResponse)
def apply_store_menu_bundle(
    store_id: str,
    opportunity_index: int,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    try:
        payload = apply_menu_bundle(db=db, store_id=store_id, opportunity_index=opportunity_index, days=days)
    except IndexError:
        raise HTTPException(status_code=404, detail="menu bundle opportunity not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post(
    "/{store_id}/agents/product/suggestions/{suggestion_index}/create",
    response_model=ProductActionCreateResponse,
)
def create_store_product_action(
    store_id: str,
    suggestion_index: int,
    item_id: str | None = Query(default=None),
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    try:
        payload = create_product_action(
            db=db,
            store_id=store_id,
            suggestion_index=suggestion_index,
            days=days,
            item_id=item_id,
        )
    except IndexError:
        raise HTTPException(status_code=404, detail="product suggestion not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post(
    "/{store_id}/agents/product/suggestions/{suggestion_index}/apply",
    response_model=ProductActionCreateResponse,
)
def apply_store_product_action(
    store_id: str,
    suggestion_index: int,
    item_id: str | None = Query(default=None),
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    """执行商品优化动作——在系统内真正修改 MenuItemVersion（标题/套餐/价格）。

    和 /create 不同，这个端点直接执行并建实验观察窗。
    """
    try:
        payload = apply_product_action(
            db=db,
            store_id=store_id,
            suggestion_index=suggestion_index,
            days=days,
            item_id=item_id,
        )
    except IndexError:
        raise HTTPException(status_code=404, detail="product suggestion not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.get("/{store_id}/agents/storefront", response_model=StorefrontAgentResult)
def get_storefront_agent(store_id: str, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    payload = build_single_agent(db=db, store_id=store_id, agent_key="storefront", days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/storefront/ai/decorate")
def ai_assist_storefront_decorate(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    payload = assist_storefront_renovation(db=db, store_id=store_id, days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/storefront/ai/optimize-image")
def ai_assist_storefront_image(
    store_id: str,
    payload: StorefrontImageAssistRequest | None = None,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    body = payload or StorefrontImageAssistRequest()
    result = assist_storefront_image(
        db=db,
        store_id=store_id,
        item_id=body.item_id,
        item_name=body.item_name,
        problem=body.problem,
        days=days,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    return result


@router.post(
    "/{store_id}/agents/storefront/actions/{action_index}/create",
    response_model=StorefrontActionCreateResponse,
)
def create_store_storefront_action(
    store_id: str,
    action_index: int,
    payload: StorefrontActionCreateRequest | None = None,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    body = payload or StorefrontActionCreateRequest()
    try:
        result = create_storefront_action(
            db=db,
            store_id=store_id,
            action_index=action_index,
            days=days,
            with_ai=body.with_ai,
        )
    except IndexError:
        raise HTTPException(status_code=404, detail="storefront action not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    return result


@router.post("/{store_id}/agents/diagnosis/run", response_model=DiagnosisAgentResult)
def run_store_diagnosis(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    job = run_daily_job(db=db, store_id=store_id, days=days)
    if job is None:
        raise HTTPException(status_code=404, detail="store not found")
    payload = build_single_agent(db=db, store_id=store_id, agent_key="diagnosis", days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.post("/{store_id}/agents/growth/rebuild", response_model=GrowthAgentResult)
def rebuild_store_growth_plan(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    payload = build_single_agent(db=db, store_id=store_id, agent_key="growth", days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload



@router.get("/{store_id}/item-image")
def food_image_proxy_store(store_id: str, name: str = "中式快餐"):
    """菜品占位图代理（按门店）。"""
    from urllib.parse import quote
    from fastapi.responses import RedirectResponse
    subject = quote(f"{name}，中式外卖美食摄影，热气腾腾，真实菜品特写，木质桌面，自然光，高质感餐饮品牌图片")
    return RedirectResponse(f"https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt={subject}&image_size=square_hd", status_code=302)

@router.get("/{store_id}/agents/{agent_key}")
def get_single_agent(store_id: str, agent_key: AgentKey, days: int = Query(default=7, ge=1), db: Session = Depends(get_db)):
    payload = build_single_agent(db=db, store_id=store_id, agent_key=agent_key, days=days)
    if payload is None:
        raise HTTPException(status_code=404, detail="store not found")
    return payload


@router.get("/{store_id}/daily-plan", response_model=DailyPlanResponse)
def get_daily_plan(store_id: str, db: Session = Depends(get_db)):
    """获取 AI 店长今日工作计划（Runtime V1 §12 DailyOperatingPlan）。"""
    from app.services.runtime_engine import build_daily_operating_plan, determine_runtime_state

    plan = build_daily_operating_plan(db, store_id)
    state = determine_runtime_state()
    return {
        "plan": plan.model_dump(mode="json"),
        "runtime_state": state,
    }


@router.get("/{store_id}/action-traces")
def get_action_traces(store_id: str, limit: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    """获取门店最近的动作追踪链——回答"AI 做了什么，为什么"。"""
    from app.services.tracing_service import get_trace_chain

    return {"traces": get_trace_chain(db, store_id, limit)}


@router.get("/{store_id}/action-traces/{trace_id}/explain")
def explain_action_trace(store_id: str, trace_id: str, db: Session = Depends(get_db)):
    """用自然语言解释"为什么 AI 做了这个动作"。"""
    from app.services.tracing_service import explain_action

    return {"explanation": explain_action(db, trace_id)}


@router.get("/{store_id}/item-image")
def proxy_item_image(store_id: str, name: str = Query(default="中式快餐", max_length=80)):
    """代理 Trae 菜品示意生图，避免前端硬编码第三方域名。"""
    _ = store_id
    subject = (
        f"{(name or '中式快餐').strip()}，中式外卖美食摄影，热气腾腾，真实菜品特写，"
        "木质桌面，自然光，高质感餐饮品牌图片"
    )
    upstream = (
        "https://coresg-normal.trae.ai/api/ide/v1/text_to_image"
        f"?prompt={quote(subject)}&image_size=square_hd"
    )
    request = Request(upstream, headers={"User-Agent": "MealKey/1.0"})
    try:
        with urlopen(request, timeout=30) as resp:  # noqa: S310 — fixed vendor host
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            data = resp.read()
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"image upstream HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"image proxy failed: {exc}") from exc
    return Response(
        content=data,
        media_type=content_type.split(";")[0] if content_type else "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{store_id}/menu-diagnosis")
def run_menu_diagnosis(store_id: str, db: Session = Depends(get_db)):
    """菜单经营诊断 12 引擎（从主仓迁移）。

    自动从门店菜单+经营数据构建诊断上下文，运行 12 个确定性引擎，
    返回结构化 findings + 置信度卡片 + 建议动作。
    """
    from app.schemas.menu_diagnosis import DiagnosisContext, MenuItemInput
    from app.services.menu_diagnosis_engine import run_diagnosis_engines
    from app.services.agents import build_agent_context

    ctx = build_agent_context(db=db, store_id=store_id, days=7)
    if ctx is None:
        raise HTTPException(status_code=404, detail="store not found")

    # 从 agent context 构建诊断输入
    menu_items: list[MenuItemInput] = []
    for snap in ctx.item_snapshots:
        menu_items.append(MenuItemInput(
            id=snap.item_id,
            name=snap.name,
            category=snap.category or "",
            price=snap.price or 0,
            description=snap.description,
            image_url=snap.image_url,
            role=snap.role,
            order_count=int(snap.observe_orders),
            order_share_pct=snap.order_share_pct,
            ctr=snap.observe_ctr,
            cvr=snap.observe_cvr,
        ))

    # 判断数据成熟度
    has_cost = any(mi.standard_cost for mi in menu_items)
    has_orders = any(mi.order_count > 0 for mi in menu_items)
    data_level = "D4" if has_cost and has_orders else "D2" if has_orders else "D1"

    # 从评价数据构建 feedbacks
    feedbacks: list[dict] = []
    try:
        from app.services.matrix_agents.common import load_reviews

        reviews = load_reviews(db, store_id, limit=30)
        for review, nlp in reviews:
            feedbacks.append({
                "rating": review.rating,
                "menu_item_name": None,
                "text": review.content,
                "tags": [],
            })
    except Exception:  # noqa: BLE001
        pass

    diag_ctx = DiagnosisContext(
        store_id=store_id,
        store_name=ctx.store.name,
        menu_items=menu_items,
        data_level=data_level,
        feedbacks=feedbacks,
    )
    result = run_diagnosis_engines(diag_ctx)
    return result.model_dump(mode="json")


@router.post(
    "/{store_id}/agents/{agent_key}/actions/{action_index}/create",
    response_model=AgentActionCreateResponse,
)
def create_store_matrix_agent_action(
    store_id: str,
    agent_key: AgentKey,
    action_index: int,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    try:
        result = create_matrix_agent_action(
            db=db,
            store_id=store_id,
            agent_key=agent_key,
            action_index=action_index,
            days=days,
        )
    except IndexError:
        raise HTTPException(status_code=404, detail=f"{agent_key} action not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    return result
