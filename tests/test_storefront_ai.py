from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.schemas.agents import (
    AgentMeta,
    StorefrontAgentResult,
    StorefrontIssue,
    StorefrontPriorityAction,
    StorefrontSalesImpact,
)
from app.services.agents import (
    assist_storefront_image,
    assist_storefront_renovation,
    create_storefront_action,
)
from app.services.llm_engine.gateway import LlmResult
from app.services.storefront_ai import _heuristic_decorate, _heuristic_image_optimize


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_heuristic_storefront_ai_helpers() -> None:
    diagnosis = StorefrontAgentResult(
        meta=AgentMeta(
            key="storefront",
            label="线上装修诊断 Agent",
            generated_at=datetime.now(timezone.utc),
        ),
        health_score=42,
        conclusion="主图偏弱",
        sales_impact=StorefrontSalesImpact(
            primary_metric="ctr",
            lift_pct_low=8,
            lift_pct_high=16,
            narrative="优先修主图",
        ),
        issues=[
            StorefrontIssue(
                code="weak_hero_visual",
                severity="high",
                title="第一眼主图竞争力不足",
                detail="缺主图",
                sales_impact_est="CTR 8%-18%",
                suggested_action_type="refresh_hero_image",
                dimension_key="hero_image",
            )
        ],
        priority_actions=[
            StorefrontPriorityAction(
                action_type="refresh_hero_image",
                title="重做店页第一眼主图",
                detail="换近景主图",
                expected_metric="ctr",
                expected_lift_pct_low=8,
                expected_lift_pct_high=16,
                object_ref="store:demo",
                object_name="演示店",
                generated_content={"visual_brief": "近景主图"},
            )
        ],
    )
    decorate = _heuristic_decorate(diagnosis, "演示店", "快餐")
    assert decorate["steps"]
    image = _heuristic_image_optimize(
        item_name="招牌盖饭",
        category="快餐",
        storefront=diagnosis,
        problem=None,
    )
    assert "prompt_zh" in image
    assert image["title"].startswith("「招牌盖饭」")


def test_storefront_ai_services_with_mocked_llm(monkeypatch) -> None:
    def fake_call_llm(**kwargs):
        purpose = kwargs.get("purpose") or ""
        if "brand" in purpose:
            content = {
                "title": "主图优化",
                "goal": "提升CTR",
                "problem": "主图弱",
                "shot_list": ["近景45度"],
                "prompt_zh": "盖饭近景美食摄影",
                "prompt_en": "rice bowl food photo",
                "checklist": ["无贴纸"],
                "before_after_tips": ["去贴纸"],
                "risk": "避免过度美颜",
            }
        else:
            content = {
                "title": "装修方案",
                "summary": "先修主图",
                "sales_focus": "CTR",
                "steps": [
                    {
                        "order": 1,
                        "title": "换主图",
                        "why": "点击低",
                        "how": "近景拍摄",
                        "verify": "看CTR 24h",
                        "action_type": "refresh_hero_image",
                    }
                ],
                "do_not_do": ["不要一次改太多"],
                "next_action": "生成动作",
                "copy_pack": {
                    "store_tagline": "分量足",
                    "signature_title": "招牌必点",
                    "set_meal_title": "单人餐",
                },
            }
        import json

        return LlmResult(ok=True, content=json.dumps(content, ensure_ascii=False), provider="mock", model="test")

    monkeypatch.setattr("app.services.storefront_ai.call_llm", fake_call_llm)
    monkeypatch.setattr("app.services.storefront_ai.is_llm_configured", lambda purpose="general.consulting": True)

    db = _session()
    seeded = seed_demo(db)

    decorate = assist_storefront_renovation(db, seeded["store_id"])
    assert decorate is not None
    assert decorate["plan"]["mode"] == "llm"
    assert decorate["plan"]["steps"]

    image = assist_storefront_image(db, seeded["store_id"])
    assert image is not None
    assert image["plan"]["mode"] == "llm"
    assert image["plan"]["prompt_zh"]

    created = create_storefront_action(db, seeded["store_id"], action_index=0, with_ai=True)
    assert created is not None
    assert created.action.generated_content
