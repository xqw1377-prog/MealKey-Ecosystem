"""Closed Loop V1 — Business Truth + Memory Boost + work_thread_id 测试。

验证 Track B(成本导入→利润真相) 和 Gap4(记忆复用) 的核心行为。
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Menu, MenuItem, MenuItemVersion, Store
from app.services.cost_import import (
    get_item_costs,
    get_store_cost_coverage,
    import_cost_sheet,
    update_single_item_cost,
)
from app.services.execution_policy import (
    _has_positive_memory,
    arbitrate_execution_mode,
)
from app.services.sensing import build_profit_state


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store_with_menu(db: Session) -> tuple[str, list[str]]:
    """创建门店 + 菜单 + 3 个商品。"""
    m = Merchant(name="测试商户")
    db.add(m)
    db.flush()
    s = Store(merchant_id=m.id, name="测试店")
    db.add(s)
    db.flush()
    menu = Menu(store_id=s.id, name="默认菜单")
    db.add(menu)
    db.flush()

    item_ids = []
    for name, price in [("黑椒牛肉饭", 29.9), ("宫保鸡丁", 26.9), ("番茄炒蛋", 19.9)]:
        item = MenuItem(store_id=s.id, menu_id=menu.id, is_active=True)
        db.add(item)
        db.flush()
        version = MenuItemVersion(item_id=item.id, name=name, price=price)
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        item_ids.append(item.id)
    db.commit()
    return s.id, item_ids


# ═══════════════════════════════════════════════════════════
# Track B: Cost Import Tests
# ═══════════════════════════════════════════════════════════


def test_import_csv_cost_sheet() -> None:
    """CSV 成本表导入 + SKU 匹配。"""
    db = _session()
    store_id, item_ids = _seed_store_with_menu(db)

    csv_content = "商品名,食材成本,包装成本\n黑椒牛肉饭,14.6,2.0\n宫保鸡丁,12.0,1.8\n不存在商品,5.0,1.0\n"
    report = import_cost_sheet(
        db, store_id, csv_content.encode("utf-8"), "cost.csv"
    )

    assert report["total_rows"] == 3
    assert report["matched"] == 2  # 黑椒+宫保匹配,不存在的不匹配
    assert report["unmatched"] == 1
    assert report["updated_items"] == 2
    assert len(report["unmatched_items"]) == 1
    db.close()


def test_import_json_cost_sheet() -> None:
    """JSON 成本表导入。"""
    db = _session()
    store_id, item_ids = _seed_store_with_menu(db)

    import json
    data = json.dumps({
        "items": [
            {"item_name": "黑椒牛肉饭", "food_cost": 14.6, "packaging_cost": 2.0},
            {"item_name": "番茄炒蛋", "food_cost": 8.0, "packaging_cost": 1.5},
        ]
    })
    report = import_cost_sheet(db, store_id, data.encode("utf-8"), "cost.json")

    assert report["matched"] == 2
    assert report["updated_items"] == 2
    db.close()


def test_cost_coverage_after_import() -> None:
    """导入后覆盖度正确。"""
    db = _session()
    store_id, item_ids = _seed_store_with_menu(db)

    # 导入前
    cov = get_store_cost_coverage(db, store_id)
    assert cov["total_items"] == 3
    assert cov["has_both_cost"] == 0
    assert cov["coverage_pct"] == 0.0

    # 导入 2 个
    csv_content = "商品名,食材成本,包装成本\n黑椒牛肉饭,14.6,2.0\n宫保鸡丁,12.0,1.8\n"
    import_cost_sheet(db, store_id, csv_content.encode("utf-8"), "cost.csv")

    cov = get_store_cost_coverage(db, store_id)
    assert cov["has_both_cost"] == 2
    assert cov["coverage_pct"] == 66.7
    assert cov["missing_cost"] == 1
    db.close()


def test_update_single_item_cost() -> None:
    """手动更新单品成本。"""
    db = _session()
    store_id, item_ids = _seed_store_with_menu(db)

    result = update_single_item_cost(
        db, store_id, item_ids[0], food_cost=15.0, packaging_cost=2.5
    )
    assert result["updated"] is True

    item = db.get(MenuItem, item_ids[0])
    assert item.food_cost == 15.0
    assert item.packaging_cost == 2.5
    assert item.cost_source == "manual_input"
    db.close()


def test_get_item_costs_display() -> None:
    """商品成本列表展示。"""
    db = _session()
    store_id, item_ids = _seed_store_with_menu(db)

    update_single_item_cost(db, store_id, item_ids[0], food_cost=14.6, packaging_cost=2.0)

    items = get_item_costs(db, store_id)
    assert len(items) == 3
    beef = [i for i in items if "黑椒" in i["name"]][0]
    assert beef["food_cost"] == 14.6
    assert beef["has_cost"] is True
    others = [i for i in items if "黑椒" not in i["name"]]
    assert all(not i["has_cost"] for i in others)
    db.close()


# ═══════════════════════════════════════════════════════════
# Track B: Profit Truth Tests (calculate_profit 接通)
# ═══════════════════════════════════════════════════════════


def test_profit_with_real_cost_uses_observed() -> None:
    """有真实成本 → data_quality=observed。"""
    p = build_profit_state(
        gross_gmv=10000,
        orders=200,
        food_cost=3000,
        packaging_cost=500,
        cost_source="owner_cost_sheet",
        cost_confidence="high",
    )
    assert p.data_quality == "observed"
    # 10000 - 2200(comm 22%) - 800(sub 8%) - 3000(food) - 500(pack) = 3500
    assert abs(p.contribution_profit - 3500) < 1
    assert p.food_cost == 3000
    assert p.packaging_cost == 500
    assert "真实成本" in p.judgment


def test_profit_without_cost_uses_proxy() -> None:
    """无真实成本 → data_quality=proxy + missing_blocks。"""
    p = build_profit_state(gross_gmv=10000, orders=200)
    assert p.data_quality == "proxy"
    assert "food_cost" in p.missing_blocks
    assert "packaging_cost" in p.missing_blocks
    assert "代理估算" in p.judgment


def test_profit_observed_lower_than_proxy() -> None:
    """真实利润必然低于 proxy(因为扣了成本)。"""
    real = build_profit_state(
        gross_gmv=10000, orders=200, food_cost=3000, packaging_cost=500,
        cost_source="owner_cost_sheet",
    )
    proxy = build_profit_state(gross_gmv=10000, orders=200)
    assert real.contribution_profit < proxy.contribution_profit
    assert real.take_home_rate < proxy.take_home_rate


# ═══════════════════════════════════════════════════════════
# Gap4: Memory Boost Tests
# ═══════════════════════════════════════════════════════════


def test_positive_memory_boosts_execution_mode() -> None:
    """有正面记忆 → trust_level 门槛降低(BOOST)。"""
    db = _session()
    store_id, _ = _seed_store_with_menu(db)

    # 写一条 positive memory
    from app.models.strategy_memory import StrategyMemoryRecord

    mem = StrategyMemoryRecord(
        store_id=store_id,
        action_type="change_main_image",
        result="positive",
        lift_pct=12.0,
        lesson="换主图后 CTR +12%",
        reuse_when="优先复用 change_main_image",
        confidence=0.85,
        context_tags_json='["ctr", "change_main_image"]',
    )
    db.add(mem)
    db.commit()

    # trust_level=0 + 无正面记忆 → ASK_APPROVAL
    # trust_level=0 + 有正面记忆 → effective_trust=1 → 零风险动作 AUTO_AND_REPORT
    # 注意:正面记忆的 action_type 必须和查询的 action_type 一致
    mode = arbitrate_execution_mode(
        action_type="change_main_image",
        trust_level=0,
        is_in_system=True,
        db=db,
        store_id=store_id,
    )
    assert mode == "AUTO_AND_REPORT"  # BOOST 生效
    from app.models.strategy_memory import MemoryChangedDecision

    changed = db.query(MemoryChangedDecision).one()
    assert changed.cause == "positive_boost"
    assert changed.naive_mode == "ASK_APPROVAL"
    assert changed.learned_mode == "AUTO_AND_REPORT"


def test_positive_memory_query() -> None:
    """_has_positive_memory 正确查询。"""
    db = _session()
    store_id, _ = _seed_store_with_menu(db)

    from app.models.strategy_memory import StrategyMemoryRecord

    # 无记忆
    assert _has_positive_memory(db, store_id, "change_main_image") is None

    # 写一条
    mem = StrategyMemoryRecord(
        store_id=store_id,
        action_type="change_main_image",
        result="positive",
        lift_pct=15.0,
        lesson="成功",
        reuse_when="复用",
        confidence=0.85,
        context_tags_json='["ctr"]',
    )
    db.add(mem)
    db.commit()

    result = _has_positive_memory(db, store_id, "change_main_image")
    assert result is not None
    assert result["lift_pct"] == 15.0
    assert result["action_type"] == "change_main_image"


def test_negative_memory_still_drops() -> None:
    """负面记忆仍然 DROP(不因其他条件改变)。"""
    db = _session()
    store_id, _ = _seed_store_with_menu(db)

    from app.models.strategy_memory import StrategyMemoryRecord

    mem = StrategyMemoryRecord(
        store_id=store_id,
        action_type="adjust_price_value",
        result="negative",
        lift_pct=-8.0,
        lesson="降价没效果",
        reuse_when="谨慎重试",
        confidence=0.8,
        context_tags_json='["orders"]',
    )
    db.add(mem)
    db.commit()

    mode = arbitrate_execution_mode(
        action_type="adjust_price_value",
        trust_level=3,
        confidence=0.9,
        db=db,
        store_id=store_id,
    )
    assert mode == "DROP"
    from app.models.strategy_memory import MemoryChangedDecision

    changed = db.query(MemoryChangedDecision).one()
    assert changed.cause == "negative_drop"
    assert changed.learned_mode == "DROP"


# ═══════════════════════════════════════════════════════════
# Track A: work_thread_id Tests
# ═══════════════════════════════════════════════════════════


def test_recommendation_has_work_thread_id() -> None:
    """Recommendation 表有 work_thread_id 字段。"""
    from app.models.ohre import Recommendation

    col = Recommendation.__table__.columns.get("work_thread_id")
    assert col is not None


def test_experiment_has_work_thread_id() -> None:
    """Experiment 表有 work_thread_id 字段。"""
    from app.models.ohre import Experiment

    col = Experiment.__table__.columns.get("work_thread_id")
    assert col is not None


def test_action_trace_has_work_thread_id() -> None:
    """ActionTrace 表有 work_thread_id 字段。"""
    from app.models.action_trace import ActionTrace

    col = ActionTrace.__table__.columns.get("work_thread_id")
    assert col is not None


def test_menu_item_has_cost_columns() -> None:
    """MenuItem 表有 food_cost / packaging_cost 缓存列。"""
    cols = MenuItem.__table__.columns
    assert "food_cost" in cols
    assert "packaging_cost" in cols
    assert "cost_source" in cols
    assert "cost_confidence" in cols
    assert "cost_updated_at" in cols
