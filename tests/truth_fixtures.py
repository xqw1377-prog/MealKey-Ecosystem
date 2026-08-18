"""Truth Contract 测试 fixture。

PRE-PROD-GATE-01 / P0-7（Synthetic 永远不是 Truth）：

`seed_demo` 的 funnel 数据显式标 `data_source="synthetic"` —— 永不进入 production_funnel_clause，
永不伪装成真实平台导出。需要测试生产归因的用例必须自行构造满足 Truth Contract 的 observed 数据，
即经授权会话拉取、已对账的真实来源 `data_source="authorized_session"`。

当前 funnel 表只承载 `data_source` 一个 provenance 字段（Truth Resolution 真正检查的列）；
`acquisition_mode` / `reconciliation_status` / `confidence` 等字段若未来加入 provenance 表，
应在此 fixture 一并设置。重点不是「让测试通过」，而是：
> 测试必须证明：只有满足生产 Truth 条件的数据，才能被 attribution 看见。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.entities import ItemFunnelDaily, ShopFunnelDaily

#: 经授权会话拉取、已对账的真实平台数据来源 —— 通过 production_funnel_clause。
AUTHORIZED_SESSION_SOURCE = "authorized_session"


def seed_reconciled_authorized_session_funnel(
    db: Session,
    store_id: str,
    item_id: str,
    *,
    days: int = 14,
    observe_days: int = 7,
    observe_ctr: float = 0.040,
    baseline_ctr: float = 0.048,
    observe_impressions: int = 1200,
    baseline_impressions: int = 1100,
    observe_cvr: float = 0.18,
    baseline_cvr: float = 0.19,
    aov: float = 32.0,
    data_source: str = AUTHORIZED_SESSION_SOURCE,
) -> dict:
    """构造满足 Truth Contract 的 observed funnel 数据。

    语义：`data_source="authorized_session"` 表示经授权会话拉取并已对账的真实平台数据，
    通过 `production_funnel_clause`，被 `evaluate_experiment` / `build_store_state` 看见。

    先删除该 item / store 已有的 synthetic 行，避免双重求和；
    `_item_metric_value` 现已走 `production_funnel_clause`，synthetic 本就不可见，
    这里仍只留 authorized_session 行，保证口径干净。

    数值口径与 `seed_demo` 完全一致（仅 provenance 从 synthetic 改为 authorized_session）：
    observe 窗（最近 `observe_days` 天）impressions=1200 / ctr=0.040 / cvr=0.18（ctr 下滑），
    baseline 窗 impressions=1100 / ctr=0.048 / cvr=0.19。保证依赖 demo 数值的诊断/增长断言不变。
    """
    today = date.today()

    db.execute(delete(ItemFunnelDaily).where(ItemFunnelDaily.item_id == item_id))
    db.execute(delete(ShopFunnelDaily).where(ShopFunnelDaily.store_id == store_id))
    db.flush()

    for i in range(days):
        d = today - timedelta(days=i + 1)
        in_observe = i < observe_days
        ctr = observe_ctr if in_observe else baseline_ctr
        imp = observe_impressions if in_observe else baseline_impressions
        cvr = observe_cvr if in_observe else baseline_cvr
        visits = int(imp * ctr)
        orders = int(visits * cvr)
        gmv = float(orders * aov)
        db.add(
            ShopFunnelDaily(
                store_id=store_id,
                day=d,
                impressions=imp,
                visits=visits,
                payments=orders,
                orders=orders,
                gmv=gmv,
                aov=aov,
                data_source=data_source,
            )
        )
        db.add(
            ItemFunnelDaily(
                item_id=item_id,
                day=d,
                impressions=imp,
                visits=visits,
                orders=orders,
                payments=orders,
                gmv=gmv,
                ctr=ctr,
                cvr=(orders / visits) if visits else None,
                data_source=data_source,
            )
        )
    db.commit()
    return {"store_id": store_id, "item_id": item_id, "data_source": data_source}
