"""菜单经营诊断 12 引擎测试（从主仓迁移验证）。"""

from app.schemas.menu_diagnosis import DiagnosisContext, MenuItemInput
from app.services.menu_diagnosis_engine import (
    run_diagnosis_engines,
    diagnose_menu_structure,
    diagnose_cost_profit,
    diagnose_flavor_spice,
    diagnose_visual_appearance,
    diagnose_dish_role_joint,
)


def _make_items(count: int = 10, **kwargs) -> list[MenuItemInput]:
    """生成测试用菜品列表。"""
    items = []
    for i in range(count):
        item = MenuItemInput(
            id=f"item-{i}",
            name=f"测试菜{i}",
            category="主食",
            price=20 + i * 3,
            description=f"这是测试菜{i}的描述" if kwargs.get("with_desc") else None,
            image_url=f"http://example.com/{i}.jpg" if kwargs.get("with_image") else None,
            is_signature=(i == 0) if kwargs.get("with_signature") else False,
            spice_level=(i % 3) if kwargs.get("with_spice") else None,
            flavor_primary="咸鲜" if kwargs.get("with_flavor") else None,
            order_count=10 + i * 5,
            order_share_pct=float(10 + i),
            ctr=0.04 + i * 0.001,
            cvr=0.15 + i * 0.005,
        )
        items.append(item)
    return items


def test_menu_structure_detects_too_many_items() -> None:
    """菜品超过 80 道应报警。"""
    items = _make_items(85)
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_menu_structure(ctx)
    assert any("过多" in f.title for f in findings)


def test_menu_structure_detects_missing_signature() -> None:
    """无招牌菜标记应报警。"""
    items = _make_items(10)  # with_signature=False
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_menu_structure(ctx)
    assert any("招牌" in f.title for f in findings)


def test_menu_structure_detects_price_gap() -> None:
    """价格断档应报告。"""
    items = [
        MenuItemInput(id="1", name="A", price=25),
        MenuItemInput(id="2", name="B", price=30),
        MenuItemInput(id="3", name="C", price=35),
        MenuItemInput(id="4", name="D", price=40),
        MenuItemInput(id="5", name="E", price=120),  # 断档
    ]
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_menu_structure(ctx)
    assert any("断档" in f.title for f in findings)


def test_cost_profit_detects_loss_items() -> None:
    """亏损菜（成本>售价）应 critical。"""
    items = [
        MenuItemInput(id="1", name="亏本菜", price=20, standard_cost=25),
        MenuItemInput(id="2", name="正常菜", price=30, standard_cost=15),
    ]
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_cost_profit(ctx)
    assert any(f.severity == "critical" and "亏损" in f.title for f in findings)


def test_cost_profit_detects_low_margin() -> None:
    """低毛利菜（<40%）应 warning。"""
    items = [
        MenuItemInput(id="1", name="低毛利A", price=30, standard_cost=22),  # 26.7%
        MenuItemInput(id="2", name="低毛利B", price=30, standard_cost=20),  # 33%
        MenuItemInput(id="3", name="低毛利C", price=30, standard_cost=21),
        MenuItemInput(id="4", name="低毛利D", price=30, standard_cost=19),
        MenuItemInput(id="5", name="正常", price=30, standard_cost=10),
    ]
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_cost_profit(ctx)
    assert any("毛利率低于" in f.title for f in findings)


def test_cost_profit_no_data_degrades_gracefully() -> None:
    """无成本数据应降级提示。"""
    items = _make_items(5)
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_cost_profit(ctx)
    assert any("缺少成本" in f.title for f in findings)


def test_flavor_spice_detects_low_not_spicy() -> None:
    """不辣菜品占比低应警告。"""
    items = [
        MenuItemInput(id=str(i), name=f"辣菜{i}", spice_level=2, flavor_primary="麻辣")
        for i in range(10)
    ]
    items.append(MenuItemInput(id="11", name="不辣", spice_level=0, flavor_primary="咸鲜"))
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_flavor_spice(ctx)
    assert any("不辣" in f.title for f in findings)


def test_visual_appearance_detects_low_coverage() -> None:
    """图片覆盖率低应报告。"""
    items = _make_items(10)  # with_image=False
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_visual_appearance(ctx)
    assert any("图片覆盖率" in f.title for f in findings)


def test_dish_role_joint_detects_high_traffic_low_cvr() -> None:
    """高曝光低转化应警告。"""
    items = [
        MenuItemInput(id="1", name="高流量低转化", order_count=100, order_share_pct=10, cvr=0.05),
        MenuItemInput(id="2", name="正常A", order_count=80, order_share_pct=8, cvr=0.15),
        MenuItemInput(id="3", name="正常B", order_count=70, order_share_pct=7, cvr=0.14),
        MenuItemInput(id="4", name="正常C", order_count=60, order_share_pct=6, cvr=0.16),
        MenuItemInput(id="5", name="正常D", order_count=50, order_share_pct=5, cvr=0.13),
    ]
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    findings = diagnose_dish_role_joint(ctx)
    assert any("高曝光但低转化" in f.title for f in findings)


def test_run_all_engines_returns_summary() -> None:
    """run_diagnosis_engines 返回完整结果含统计和摘要。"""
    items = _make_items(15, with_desc=True, with_image=True, with_signature=True)
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    result = run_diagnosis_engines(ctx)
    assert result.store_id == "s1"
    assert isinstance(result.findings, list)
    assert result.summary  # 有摘要
    assert isinstance(result.finding_count_by_severity, dict)


def test_run_all_engines_empty_menu() -> None:
    """空菜单不崩溃，可能输出数据缺口提示。"""
    ctx = DiagnosisContext(store_id="s1", menu_items=[])
    result = run_diagnosis_engines(ctx)
    # 空菜单时只应有 info 级的缺数据提示，不应有 critical/warning
    for f in result.findings:
        assert f.severity == "info"


def test_12_engines_all_callable() -> None:
    """12 个引擎都能被调用不崩溃。"""
    from app.services.menu_diagnosis_engine import ENGINE_MAP

    assert len(ENGINE_MAP) == 12
    items = _make_items(10, with_desc=True, with_image=True, with_spice=True, with_flavor=True)
    ctx = DiagnosisContext(store_id="s1", menu_items=items)
    for engine_id, engine_fn in ENGINE_MAP.items():
        findings = engine_fn(ctx)  # 不崩溃即可
        assert isinstance(findings, list)
