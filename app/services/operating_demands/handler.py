"""老板问经营问题 → 命中契约 → 判断 → 进入 Closed Loop。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.operating_demands.playbooks import run_playbook
from app.services.operating_demands.router import match_demand
from app.services.operating_demands.runner import facts_from_store_state, open_demand_loop


def handle_demand_intent(db: Session, store_id: str, question: str) -> Optional[dict[str, Any]]:
    demand = match_demand(question)
    if demand is None:
        return None

    facts: dict[str, Any] = {}
    try:
        from app.services.store_state import build_store_state
        from app.services.store_ops import list_open_human_tasks, load_roster, project_task
        from app.services.platform_intel import project_for_demand, project_promos_to_store

        state = build_store_state(db, store_id)
        facts = facts_from_store_state(state)
        facts["open_human_tasks"] = [project_task(item) for item in list_open_human_tasks(db, store_id)]
        roster = load_roster(db, store_id)
        facts["store_ops_ready"] = roster.get("ready")
        facts.update(project_for_demand(db))
        if facts.get("official_promos"):
            project_promos_to_store(db, store_id)
            db.commit()
        from app.services.oci.case_retrieval import prior_facts_for_demand
        from app.services.ops_diagnosis import project_ops_findings

        facts.update(prior_facts_for_demand(demand.code, demand.family, question))
        facts.update(project_ops_findings(db, store_id, demand.id))
        from app.services.seed_launch import profit_honesty

        honesty = profit_honesty(db, store_id)
        facts["cost_ready"] = honesty["cost_ready"]
        facts["precise_profit"] = honesty["precise_profit"]
        facts["cost_coverage_pct"] = honesty["cost_coverage_pct"]
        if not honesty["precise_profit"]:
            facts["profit_gate_passed"] = False
    except Exception:  # noqa: BLE001
        facts = facts or {}

    verdict = run_playbook(demand, facts)
    loop_item = None
    try:
        loop_item = open_demand_loop(db, store_id, verdict)
    except Exception:  # noqa: BLE001
        loop_item = None

    answer_lines = [
        f"这是经营问题 #{demand.id}：{demand.question}",
        f"判断：{verdict.diagnosis}",
        f"现在只做：{verdict.action}",
    ]
    reasons: list[str] = []
    if verdict.why_not:
        reasons.append("不会做：" + "；".join(verdict.why_not[:2]))
    if verdict.blocked:
        reasons.append("最后一公里还没通：" + "、".join(verdict.missing_truth or list(demand.blockers)))
    if demand.loop == "C":
        reasons.append("这件事要门店完成实体动作。没有证据不能算做完，到期我会催办并回看指标。")
        if not facts.get("store_ops_ready"):
            reasons.append("还没设置店长：去设置里写下门店执行人，才能把任务发给具体的人。")
    elif demand.loop == "B":
        reasons.append("方案已经有了，价格/预算/活动/赔付仍要你确认。")
    if demand.code == "JOIN_CAMPAIGN":
        promos = facts.get("official_promos") or []
        policies = facts.get("official_policies") or []
        if promos:
            names = "、".join(str(item.get("title") or "") for item in promos[:3] if item.get("title"))
            reasons.append(f"官网刚采到的活动：{names}。这是公开页证据，不是后台报名结果。")
        elif policies:
            names = "、".join(str(item.get("title") or "") for item in policies[:3] if item.get("title"))
            reasons.append(f"官网刚采到的政策：{names}。没有活动细则时，先不报名。")
        elif facts.get("intel_status") == "failed":
            reasons.append("官网采集失败，不能假装有可参加的活动。")
        else:
            reasons.append("官网政策/活动还没采到。去采集中心点「采集官网政策与活动」，有证据后再判断参不参加。")
    if facts.get("case_priors"):
        reasons.append("外部案例只作弱先验，不能改下次决策权重。真正能改权重的，还是咱们自己做完的结果。")

    answer_lines.extend(reasons)

    return {
        "mode": "operating_demand",
        "intent": "operating_demand",
        "question": question,
        "question_type": "operating_demand",
        "demand": verdict.as_dict(),
        "loop_id": getattr(loop_item, "id", None),
        "conclusion": verdict.diagnosis,
        "actions": [verdict.action],
        "reasons": reasons,
        "expected": f"{demand.window_hours} 小时内回看 {demand.metric}",
        "confidence": "low" if verdict.blocked else "high",
        "answer": "\n".join(answer_lines),
    }
