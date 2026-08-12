"""Chief Agent (AI 店长) — ReAct 模式调度 13 个专业 agent。

这是目标架构的核心：老板只跟店长对话，店长用 function calling
按需调用专业 agent，再把结果汇总成「先结论→理由→动作→预期影响」的回答。

V2 升级（自然语言驱动）：
- 除了 13 个只读 query_* 工具，新增 3 个写入工具：
  create_goal / prepare_action / start_thread
- 老板说"这个月做到20万"→ create_goal
- 老板说"500块广告费帮我花掉"→ prepare_action
- 老板说"帮我提升午餐"→ start_thread
- 让"所想即所得"真正成立。

降级链（保证可用性）：
1. LLM 配置且支持 tools → ReAct 多轮调度（原生 function calling）
2. LLM 配置但不支持 tools → 单轮 LLM + 规则意图分类挑选 agent
3. LLM 未配置/失败 → 纯规则：意图分类 + 调对应 agent + 模板汇总
4. 规则也失败 → 返回 growth agent 的 today_priority 兜底
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.chief_agent import ChiefAgentResponse
from app.services.llm_engine.gateway import call_llm, is_llm_configured

logger = logging.getLogger(__name__)

# ReAct 循环上限（防止 LLM 反复调工具不收敛）
_MAX_REACT_ROUNDS = 5
# 单条 tool 结果的最大长度（防止 context 爆炸）
_TOOL_RESULT_MAX_CHARS = 3000

# 13 个专业 agent 的工具注册表（name → 描述）
# 这些就是店长可以调度的"部门"
AGENT_TOOLS: dict[str, dict[str, str]] = {
    "query_diagnosis": {
        "agent_key": "diagnosis",
        "description": "经营诊断：订单/曝光/点击率/转化率为什么变化，根因是什么。适合「订单下降」「为什么没人买」「流量问题」类问题。",
    },
    "query_competition": {
        "agent_key": "competition",
        "description": "商圈竞争：谁在抢用户、竞品靠什么赢、最近有什么变化。适合「竞争」「附近」「谁抢生意」「商圈」类问题。",
    },
    "query_menu": {
        "agent_key": "menu",
        "description": "菜单结构：角色分布是否平衡、价格梯度、套餐缺口、低效SKU。适合「菜单」「加什么菜」「SKU」「结构」类问题。",
    },
    "query_product": {
        "agent_key": "product",
        "description": "商品优化：单品根因分析、主图/标题/套餐/价格建议。适合「主图」「标题」「牛肉饭」「单品」类问题。",
    },
    "query_storefront": {
        "agent_key": "storefront",
        "description": "线上装修：店页首页、主图、分类、招牌位、评分区展示。适合「装修」「店页」「展示」「首图」类问题。",
    },
    "query_review": {
        "agent_key": "review",
        "description": "评分评价：差评主题、评分下滑原因、评价治理建议。适合「评价」「差评」「评分」「口碑」类问题。",
    },
    "query_growth": {
        "agent_key": "growth",
        "description": "增长策略：机会排序、今日主动作、7天计划、不要做什么。适合「增长」「提升」「计划」「先做什么」类问题。",
    },
    "query_promo": {
        "agent_key": "promo",
        "description": "平台活动：套餐活动、平台补贴、竞品活动对冲。适合「活动」「满减」「补贴」「促销」类问题。",
    },
    "query_ads": {
        "agent_key": "ads",
        "description": "投流：广告预算、主推品投放、投流解锁条件。适合「投流」「广告」「推广」「流量」类问题。",
    },
    "query_crm": {
        "agent_key": "crm",
        "description": "用户关系：复购、新客、流失召回、VIP经营。适合「复购」「回头客」「流失」「老客」类问题。",
    },
    "query_service": {
        "agent_key": "service",
        "description": "AI客服：差评回复、话术、份量投诉处理。适合「客服」「回复」「差评回复」「话术」类问题。",
    },
    "query_store_matrix": {
        "agent_key": "store_matrix",
        "description": "线上门店矩阵：一店多开、工作餐/夜宵/高性价比店。适合「开新店」「矩阵」「一店多开」类问题。",
    },
    "query_events": {
        "agent_key": "events",
        "description": "今日经营异常事件：售罄/闭店/活动失效/评分下降/竞品动作/投流ROI下滑等实时监控。适合「今天发生什么」「有什么异常」「售罄」「闭店」类问题。",
    },
}


# ---------------------------------------------------------------------------
# V2：自然语言驱动写入工具（让"所想即所得"成立）
# ---------------------------------------------------------------------------

WRITE_TOOLS: dict[str, dict[str, Any]] = {
    "create_goal": {
        "description": (
            "把老板的经营目标创建为长期 Goal，AI 会持续跟踪推进。"
            "适合「这个月做到20万」「牛肉饭做到前三」「利润率拉到18%」类请求。"
            "调用后 AI 会记住目标并每天检查进度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "raw_text": {"type": "string", "description": "老板原话，如'本月GMV做到20万'"},
                "metric": {
                    "type": "string",
                    "enum": ["gmv", "orders", "ctr", "cvr", "rating", "rank", "take_home_rate", "custom"],
                    "description": "目标指标",
                },
                "target_value": {"type": "number", "description": "目标值，如 200000 或 3（前三名）"},
                "deadline": {"type": "string", "description": "截止日期 YYYY-MM-DD，可选"},
            },
            "required": ["raw_text", "metric"],
        },
    },
    "prepare_action": {
        "description": (
            "把老板的指令准备成一条待确认动作（不直接执行，等老板点'同意'）。"
            "适合「500块广告费帮我花掉」「帮我上29元套餐」「换牛肉饭主图」类请求。"
            "动作进入'现在需要你'队列。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "动作类型：boost_hero_item_ads/join_lunch_campaign/add_set_meal/change_main_image/launch_value_bundle_promo 等",
                },
                "object_name": {"type": "string", "description": "动作对象，如'午餐投流'或'29元套餐'"},
                "detail": {"type": "string", "description": "具体方案说明，如'午餐11:10-12:40投放，预算¥500，主投牛肉饭'"},
                "expected_metric": {"type": "string", "description": "验证指标：orders/ctr/cvr/gmv"},
            },
            "required": ["action_type", "object_name"],
        },
    },
    "start_thread": {
        "description": (
            "把老板的长期经营需求创建为经营线程（跨日持续推进）。"
            "适合「帮我提升午餐」「把牛肉饭做到前三」「本月冲一波」类需要多步推进的请求。"
            "AI 会持续跟踪进度，老板回来不用重新解释上下文。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "线程标题，如'午餐增长计划'"},
                "goal_text": {"type": "string", "description": "线程目标，如'午餐订单提升20%'"},
            },
            "required": ["title", "goal_text"],
        },
    },
    "connect_platform": {
        "description": (
            "帮老板连接外卖平台。适合「帮我连接美团」「对接饿了么」「授权外卖平台」类请求。"
            "生成手机连接码或返回 OAuth 授权链接。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["meituan", "eleme", "dianping", "douyin"],
                    "description": "要连接的平台",
                },
            },
            "required": ["platform"],
        },
    },
}


def _build_tools_schema() -> list[dict[str, Any]]:
    """构建 OpenAI function calling 格式的 tools 定义（query 只读 + write 写入）。"""
    tools = []
    # 只读 query 工具（无参数）
    for name, info in AGENT_TOOLS.items():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "description": "无需参数，直接调用即可获取该专业 agent 的完整诊断结果。",
                    },
                },
            }
        )
    # 写入工具（有参数）
    for name, info in WRITE_TOOLS.items():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": info["parameters"],
                },
            }
        )
    return tools


def _truncate(text: str, limit: int = _TOOL_RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(结果已截断)"


def _compact_agent_result(result: dict[str, Any]) -> str:
    """把单个 agent 的完整结果压缩成 LLM 能快速消化的摘要 JSON。

    保留关键字段：meta/conclusion/reasons/evidence/priority_actions/根因等，
    丢弃超长的 list 详情（LLM 不需要看全部 SKU 候选）。
    """
    compact: dict[str, Any] = {}
    # meta（含 ai_narrative）
    if "meta" in result:
        meta = result["meta"]
        compact["agent"] = meta.get("key")
        compact["health_score"] = result.get("health_score") or result.get("diagnosis_score") or result.get("competition_score") or result.get("menu_health_score") or result.get("strategy_score")
        if meta.get("ai_narrative"):
            compact["summary"] = meta["ai_narrative"]
    # conclusion / reason / evidence（几乎所有 agent 都有）
    for key in ("conclusion", "daily_summary", "executive_summary", "reason", "expected_impact"):
        if result.get(key):
            compact.setdefault("summary", result[key])
            break
    if result.get("reasons"):
        compact["reasons"] = result["reasons"][:3]
    if result.get("evidence"):
        compact["evidence"] = result["evidence"][:3]
    # 优先动作（如果有）
    if result.get("priority_actions"):
        compact["top_actions"] = [
            {"title": a.get("title"), "detail": a.get("detail", "")[:100]}
            for a in result["priority_actions"][:2]
        ]
    # diagnosis 特有
    if result.get("root_causes"):
        compact["root_causes"] = [
            {"title": r.get("title"), "explanation": r.get("explanation", "")[:100]}
            for r in result["root_causes"][:2]
        ]
    # growth 特有
    if result.get("selected_opportunity"):
        opp = result["selected_opportunity"]
        compact["selected_opportunity"] = {
            "title": opp.get("title"),
            "expected_metric": opp.get("expected_metric"),
            "score": opp.get("score"),
        }
    # review 特有
    if result.get("themes"):
        compact["top_themes"] = [
            {"label": t.get("label"), "share_pct": t.get("share_pct")}
            for t in result["themes"][:2]
        ]
    # events 特有（事件引擎结果）
    if "events" in result and isinstance(result["events"], list):
        compact["agent"] = "events"
        compact["summary"] = result.get("summary", "")
        compact["events"] = [
            {
                "type": e.get("event_type"),
                "title": e.get("title"),
                "severity": e.get("severity"),
                "impact": e.get("estimated_impact"),
                "loss": e.get("estimated_impact_amount"),
            }
            for e in result["events"][:5]
        ]
    return _truncate(json.dumps(compact, ensure_ascii=False))


def _call_specialist_agent(
    db: Session, ctx: Any, tool_name: str, arguments: dict[str, Any] | None = None
) -> Optional[dict[str, Any]]:
    """根据 tool_name 调用对应工具。

    query_* 工具：调用专业 agent（只读）。
    write 工具（create_goal/prepare_action/start_thread）：执行写入操作。
    """
    # 写入工具优先处理
    if tool_name in WRITE_TOOLS:
        return _execute_write_tool(db, ctx, tool_name, arguments or {})

    tool_info = AGENT_TOOLS.get(tool_name)
    if tool_info is None:
        return None
    agent_key = tool_info["agent_key"]

    # events 不是 agent，是事件引擎——单独处理
    if agent_key == "events":
        try:
            from app.services.event_engine import build_operating_events

            result = build_operating_events(ctx.store_state)
            return result.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            logger.warning("events query failed: %s", exc)
            return {"error": f"events query failed: {type(exc).__name__}"}

    from app.services.agents import build_single_agent_cached

    try:
        result = build_single_agent_cached(
            db, ctx.store.id, agent_key, ctx=ctx, use_cache=False
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("specialist agent %s failed: %s", agent_key, exc)
        return {"error": f"agent {agent_key} failed: {type(exc).__name__}"}


def _execute_write_tool(
    db: Session, ctx: Any, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """执行写入工具（create_goal / prepare_action / start_thread）。

    安全护栏：每次最多创建 1 个实体，返回确认信息给 LLM。
    """
    store_id = ctx.store.id

    try:
        if tool_name == "create_goal":
            from app.schemas.goal import GoalCreateRequest
            from app.services.goal_engine import create_goal

            request = GoalCreateRequest(
                raw_text=arguments.get("raw_text", ""),
                metric=arguments.get("metric", "custom"),
                target_value=arguments.get("target_value"),
                deadline=arguments.get("deadline"),
            )
            goal = create_goal(db, store_id, request)
            return {
                "ok": True,
                "tool": "create_goal",
                "message": f"已创建目标：{goal.raw_text}（指标={goal.metric}，目标值={goal.target_value}）。AI 会持续跟踪推进。",
                "goal_id": goal.id,
            }

        if tool_name == "prepare_action":
            from app.models.ohre import Recommendation
            from datetime import datetime, timezone

            action_type = arguments.get("action_type", "custom")
            object_name = arguments.get("object_name", "")
            detail = arguments.get("detail", "")
            expected_metric = arguments.get("expected_metric", "orders")

            rec = Recommendation(
                store_id=store_id,
                scope="store",
                object_ref=f"store:{store_id}",
                action_type=action_type,
                expected_metric=expected_metric,
                window_hours=48,
                confidence=0.7,
                status="proposed",
                content_json=__import__("json").dumps(
                    {
                        "source": "chief_agent_nl",
                        "title": object_name,
                        "detail": detail,
                        "object_name": object_name,
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            return {
                "ok": True,
                "tool": "prepare_action",
                "message": f"已准备好动作「{object_name}」，进入'现在需要你'队列，等老板确认后执行。",
                "recommendation_id": rec.id,
            }

        if tool_name == "start_thread":
            from app.services.thread_engine import create_thread

            title = arguments.get("title", "经营线程")
            goal_text = arguments.get("goal_text", "")
            thread = create_thread(db, store_id, title=title, goal_text=goal_text)
            return {
                "ok": True,
                "tool": "start_thread",
                "message": f"已创建经营线程「{title}」，目标：{goal_text}。AI 会持续推进，老板回来不用重新解释上下文。",
                "thread_id": thread.id,
            }

        if tool_name == "connect_platform":
            platform = arguments.get("platform", "meituan")
            # 尝试 OAuth（如果配置了）
            from app.services.platform_oauth import get_oauth_url, is_oauth_configured

            if is_oauth_configured(platform):
                url = get_oauth_url(platform, state=store_id)
                return {
                    "ok": True,
                    "tool": "connect_platform",
                    "message": f"已生成{platform}授权链接。请让老板点击授权，授权后我会自动读取菜单、订单、评价和经营数据。",
                    "oauth_url": url,
                    "platform": platform,
                }
            else:
                # OAuth 未配置，引导用手机连接码
                return {
                    "ok": True,
                    "tool": "connect_platform",
                    "message": f"目前{platform}的自动对接还在准备中。老板可以在设置页面用「手机连接码」先手动采集数据，我一样能分析。点设置→平台连接→{platform}→获取连接码。",
                    "platform": platform,
                    "fallback": "manual_connect_code",
                }

        return {"ok": False, "error": f"unknown write tool: {tool_name}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("write tool %s failed: %s", tool_name, exc)
        return {"ok": False, "error": f"{tool_name} failed: {type(exc).__name__}: {str(exc)[:100]}"}


def _parse_final_answer(content: str) -> dict[str, Any]:
    """从 LLM 最终文本回答里提取 conclusion/reasons/actions。

    店长 system prompt 要求输出结构化 JSON，但也兼容纯文本。
    """
    text = (content or "").strip()
    if not text:
        return {}
    # 尝试解析 JSON（优先）
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {
                "conclusion": str(data.get("conclusion") or data.get("summary") or ""),
                "reasons": list(data.get("reasons") or data.get("because") or [])[:3],
                "actions": list(data.get("actions") or data.get("todo") or [])[:3],
                "expected": str(data.get("expected") or data.get("impact") or ""),
            }
    except json.JSONDecodeError:
        pass
    # 纯文本兜底：第一段当 conclusion，全文当 answer
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    conclusion = lines[0] if lines else text[:120]
    actions = [line.lstrip("-•*123456789. ").strip() for line in lines[1:] if any(w in line for w in ("先", "建议", "做", "执行", "优化", "换", "改", "上"))][:3]
    return {"conclusion": conclusion, "actions": actions, "answer": text}


def _react_loop(
    db: Session,
    ctx: Any,
    question: str,
) -> tuple[dict[str, Any], list[str], Optional[dict[str, Any]]]:
    """ReAct 多轮调度。返回 (parsed_answer, agents_called, llm_meta)。

    若 LLM 不支持 tools 或调用失败，抛 RuntimeError 由上层降级。
    """
    system = (
        "你是 MealKey AI 店长，服务中国外卖门店老板。你是运营总监，下面有 13 个专业 agent 部门。\n"
        "回答老板问题时，先调用必要的专业 agent 工具获取事实，再综合输出。\n"
        "规则：\n"
        "1. 只调用与问题相关的 agent（通常 1-3 个够用）；\n"
        "2. 拿到 agent 结果后，用老板听得懂的话总结，像资深运营经理；\n"
        "3. 最终回答必须输出 JSON：\n"
        '   {"conclusion":"一句话结论","reasons":["依据1","依据2"],"actions":["今天先做X"],"expected":"预计影响"}\n'
        "4. 不要编造 agent 没提供的数据；不要说「根据数据分析」，直接说结论。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"老板问题：{question}"},
    ]
    tools = _build_tools_schema()
    agents_called: list[str] = []
    llm_meta: Optional[dict[str, Any]] = None

    for round_idx in range(_MAX_REACT_ROUNDS):
        result = call_llm(
            purpose="general.consulting",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1500,
        )
        if not result.ok:
            raise RuntimeError(f"llm_failed: {result.reason}")

        llm_meta = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "tokens": result.total_tokens,
            "failover_used": result.failover_used,
            "rounds": round_idx + 1,
        }

        # 无 tool_calls = 最终回答
        if not result.tool_calls:
            parsed = _parse_final_answer(result.content)
            if not parsed.get("answer"):
                parsed["answer"] = result.content
            return parsed, agents_called, llm_meta

        # 有 tool_calls = 调用专业 agent，把结果塞回 messages 继续
        # 先把 assistant 的 tool_calls 消息加入历史
        messages.append(
            {
                "role": "assistant",
                "content": result.content or None,
                "tool_calls": result.tool_calls,
            }
        )
        for tool_call in result.tool_calls:
            func = tool_call.get("function", {})
            tool_name = func.get("name", "")
            call_id = tool_call.get("id", tool_name)
            # 解析工具参数（写入工具需要）
            raw_args = func.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                arguments = {}
            is_write_tool = tool_name in WRITE_TOOLS
            agent_result = _call_specialist_agent(db, ctx, tool_name, arguments if is_write_tool else None)
            if agent_result is not None:
                # 记录调用了哪些工具
                if is_write_tool:
                    agents_called.append(f"write:{tool_name}")
                else:
                    agents_called.append(AGENT_TOOLS[tool_name]["agent_key"])
                # 写入工具结果直接 JSON 化（已经是结构化 dict），query 工具走压缩
                if is_write_tool:
                    tool_output = _truncate(json.dumps(agent_result, ensure_ascii=False))
                else:
                    tool_output = _compact_agent_result(agent_result)
            else:
                tool_output = json.dumps({"error": f"unknown tool: {tool_name}"}, ensure_ascii=False)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": tool_output,
                }
            )

    # 超过轮数上限，强制收尾
    logger.warning("chief_agent ReAct hit round limit %d", _MAX_REACT_ROUNDS)
    final = call_llm(
        purpose="general.consulting",
        messages=messages + [{"role": "system", "content": "已达工具调用上限，请基于已有信息直接输出最终 JSON 回答，不要再调用工具。"}],
        temperature=0.3,
        max_tokens=800,
    )
    if final.ok:
        llm_meta["rounds"] = _MAX_REACT_ROUNDS + 1
        parsed = _parse_final_answer(final.content)
        parsed["answer"] = final.content
        return parsed, agents_called, llm_meta
    raise RuntimeError("react_exhausted_without_answer")


# ---------------------------------------------------------------------------
# 规则意图分类（降级路径用）
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("competition", ["竞争", "附近", "谁抢", "商圈", "对手", "竞品"]),
    ("menu", ["菜单", "加什么菜", "卖什么", "sku", "结构", "套餐缺口"]),
    ("product", ["主图", "标题", "单品", "牛肉饭", "爆品", "图片"]),
    # service 在 review 前：「差评回复」「话术」属于客服动作
    ("service", ["客服", "回复", "话术", "投诉", "怎么回复"]),
    ("review", ["评价", "差评", "评分", "口碑", "好评"]),
    ("growth", ["增长", "提升", "计划", "先做什么", "怎么涨", "下一步"]),
    ("ads", ["投流", "广告", "推广", "流量购买"]),
    ("crm", ["复购", "回头客", "流失", "老客", "新客"]),
    ("diagnosis", ["订单", "下降", "为什么", "诊断", "怎么了", "没人"]),
]


def _classify_intent(question: str) -> str:
    """规则意图分类（降级路径）。返回 agent_key。"""
    text = question.lower()
    for agent_key, keywords in _INTENT_KEYWORDS:
        if any(kw in text for kw in keywords):
            return agent_key
    return "growth"  # 默认给增长策略（今日主动作）


def _rule_fallback(
    db: Session,
    ctx: Any,
    question: str,
) -> ChiefAgentResponse:
    """纯规则降级：意图分类 + 调对应 agent + 模板汇总。"""
    from app.services.agents import build_single_agent_cached

    intent = _classify_intent(question)
    agents_called = [intent]

    try:
        result = build_single_agent_cached(
            db, ctx.store.id, intent, ctx=ctx, use_cache=False
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rule_fallback agent %s failed: %s", intent, exc)
        result = None

    if result is None:
        # 最终兜底：growth agent 的 today_priority
        try:
            growth = build_single_agent_cached(db, ctx.store.id, "growth", ctx=ctx, use_cache=False)
            priority = (growth or {}).get("today_priority") or "先执行今日主动作并观察核心指标。"
        except Exception:  # noqa: BLE001
            priority = "数据暂不足，建议先补齐门店资料后再诊断。"
        return ChiefAgentResponse(
            question=question,
            question_type=intent,
            mode="heuristic",
            conclusion=priority,
            actions=[priority],
            confidence="low",
            agents_called=["growth"],
            answer=priority,
        )

    # 从 agent 结果提取结论
    conclusion = (
        (result.get("meta") or {}).get("ai_narrative")
        or result.get("conclusion")
        or result.get("daily_summary")
        or result.get("executive_summary")
        or "已调用对应专业 agent，请参考下方建议。"
    )
    reasons = result.get("reasons") or result.get("evidence") or []
    actions = [a.get("title", "") for a in (result.get("priority_actions") or [])[:2]] if result.get("priority_actions") else []
    if not actions and result.get("next_actions"):
        actions = result.get("next_actions")[:2]
    expected = result.get("expected_impact") or ""

    answer = f"{conclusion}\n"
    if reasons:
        answer += "依据：" + "；".join(reasons[:2]) + "\n"
    if actions:
        answer += "建议：" + "；".join(actions)

    return ChiefAgentResponse(
        question=question,
        question_type=intent,
        mode="rule_fallback",
        conclusion=conclusion,
        reasons=reasons[:3],
        actions=actions[:3],
        expected=expected,
        confidence="medium",
        agents_called=agents_called,
        answer=answer,
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def answer_as_chief(
    db: Session,
    store_id: str,
    question: str,
    *,
    days: int = 7,
) -> ChiefAgentResponse:
    """店长 agent 主入口。接问题 → ReAct/降级 → 统一回答。"""
    from app.services.agent_context_cache import get_context

    ctx = get_context(db, store_id, days=days)
    if ctx is None:
        return ChiefAgentResponse(
            question=question,
            mode="heuristic",
            conclusion="门店数据不足，无法诊断。",
            answer="门店数据不足，无法诊断。请先补齐门店基础资料。",
            confidence="low",
        )

    # 降级链入口：LLM 配置 → ReAct；否则 → 规则
    if not is_llm_configured("general.consulting"):
        return _rule_fallback(db, ctx, question)

    try:
        parsed, agents_called, llm_meta = _react_loop(db, ctx, question)
        return ChiefAgentResponse(
            question=question,
            question_type="llm_react",
            mode="react",
            conclusion=parsed.get("conclusion", ""),
            reasons=parsed.get("reasons", []),
            actions=parsed.get("actions", []),
            expected=parsed.get("expected", ""),
            confidence="high",
            agents_called=agents_called,
            answer=parsed.get("answer", ""),
            llm=llm_meta,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chief_agent ReAct failed, falling back to rule: %s", exc)
        fallback = _rule_fallback(db, ctx, question)
        fallback.error = str(exc)[:200]
        fallback.mode = "rule_fallback"
        return fallback
