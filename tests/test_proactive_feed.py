from app.schemas.arbiter import DecisionCard, OpsQueueBrief, ActiveGoalBrief
from app.services.poie.proactive_feed import build_proactive_feed


def test_proactive_feed_maps_reasons_and_prioritizes_need_you():
    queue = OpsQueueBrief(
        need_you=[
            DecisionCard(
                id="n1",
                title="牛肉饭提前售罄",
                arbiter_state="need_input",
                interrupt_reason="anomaly",
                queue_bucket="need_you",
                why_now="比四周均值提前 37 分钟",
                need_from_owner="确认是否少备货",
            )
        ],
        working=[
            DecisionCard(
                id="w1",
                title="午餐预算已调整",
                arbiter_state="auto_do",
                interrupt_reason="time",
                queue_bucket="working",
                ai_already_did="预算 ¥180 → ¥240",
            )
        ],
        results=[
            DecisionCard(
                id="r1",
                title="主图实验有效",
                arbiter_state="report_result",
                interrupt_reason="result",
                queue_bucket="result",
                ai_judgment="CTR +14.6%",
            )
        ],
        opportunities=[
            DecisionCard(
                id="o1",
                title="竞品优惠结束",
                arbiter_state="noop",
                interrupt_reason="opportunity",
                queue_bucket="opportunity",
                why_now="48 小时窗口",
            )
        ],
        active_goal=ActiveGoalBrief(
            title="本月利润",
            blocked_by="预测缺口约 ¥3,400",
            next_step="重算补救路径",
        ),
    )
    feed = build_proactive_feed(queue)
    assert feed
    assert feed[0].status == "need_you"
    reasons = {e.reason for e in feed}
    assert "ANOMALY" in reasons
    assert "TIME" in reasons
    assert "RESULT" in reasons
    assert "OPPORTUNITY" in reasons
    assert "GOAL_DEVIATION" in reasons
    assert any(e.status == "auto_done" for e in feed)
    assert feed[0].human_required is True
    assert feed[0].domain in {"PRODUCT", "PLATFORM", "PROFIT", "COMPETITION", "TRAFFIC"}
    assert any(e.domain_label for e in feed)
    assert any(e.next_check for e in feed)
