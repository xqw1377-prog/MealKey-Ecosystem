"""低风险动作的可复制执行包。

系统暂不直接改美团后台。先给老板一份能贴去用的稿，并写清观察窗。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.services.action_registry import build_action_spec
from app.services.copy_humanize import humanize_operator_text

PACK_ACTIONS = {
    "change_main_image",
    "change_title",
    "batch_reply_negative_reviews",
    "reply_ordinary_reviews",
    "appeal_pack",
    "ops_hint",
}


def infer_pack_action_type(*, title: str = "", action_type: str = "", blob: str = "") -> str:
    explicit = str(action_type or "").strip()
    if explicit in PACK_ACTIONS:
        return explicit
    text = f"{title} {blob}"
    if re.search(r"主图|换图|首图", text):
        return "change_main_image"
    if re.search(r"标题|品名", text) and not re.search(r"主图", text):
        return "change_title"
    if re.search(r"差评|回差评", text):
        return "batch_reply_negative_reviews"
    if re.search(r"好评未回|待回复好评|普通评价|回好评", text):
        return "reply_ordinary_reviews"
    if re.search(r"申诉|举证|恶意评价|不实评价", text):
        return "appeal_pack"
    return ""


def _object_name(title: str, fallback: str = "当前商品") -> str:
    raw = str(title or "").strip()
    matched = re.search(r"把(.+?)(?:的)?(?:主图|标题|图)", raw)
    if matched:
        return matched.group(1).strip() or fallback
    matched = re.search(r"(.+?)(?:主图|标题)", raw)
    if matched and len(matched.group(1)) <= 12:
        return matched.group(1).strip() or fallback
    return fallback


def build_execution_pack(
    action_type: str,
    *,
    object_name: str = "",
    title: str = "",
) -> Optional[dict[str, Any]]:
    kind = infer_pack_action_type(action_type=action_type, title=title)
    if kind not in PACK_ACTIONS:
        kind = "ops_hint"
    name = humanize_operator_text(object_name) or _object_name(title)
    pack = _pack_body(kind, name=name, title=title)
    pack.update(
        {
            "goal": pack.get("goal") or f"推进「{humanize_operator_text(title) or name}」",
            "observe_hours": pack.get("observe_hours") or 48,
            "success_metric": humanize_operator_text(pack.get("success_metric") or "点击率"),
            "success_target": pack.get("success_target") or "",
            "guardrail": humanize_operator_text(pack.get("guardrail") or "转化率不能明显下降"),
        }
    )
    pack["action_spec"] = build_action_spec(
        kind,
        object_name=name,
        title=pack.get("title") or title,
        pack=pack,
        reason=pack.get("current_problem") or pack.get("goal") or "",
    )
    return pack


def _pack_body(kind: str, *, name: str, title: str) -> dict[str, Any]:
    if kind == "change_main_image":
        return {
            "action_type": kind,
            "title": f"换主图执行包 · {name}",
            "object_name": name,
            "suggested_image_url": f"https://cdn.mealky.local/hero/{name or 'item'}.jpg",
            "goal": f"提高{name}点击率",
            "current_problem": "产品主体太小，份量感弱",
            "copy_text": (
                f"【{name} · 主图替换说明】\n"
                "目标：提高点击率。\n"
                "当前问题：产品主体太小，份量感弱。\n"
                "素材：真实餐品照片 1 张。\n"
                "生成要求：主体占画面 60% 以上，强化份量，保持真实，不出现平台违规文字。\n"
                "成功标准：点击率 +8% 以上。\n"
                "观察窗口：48 小时。\n"
                "风险：转化率下降不超过 3%。不要同时改标题或价格。"
            ),
            "steps": [
                "打开美团商家端，进入该商品编辑",
                "按说明替换主图并保存",
                "回来点「已修改」，进入 48 小时观察",
            ],
            "watch": "48 小时后系统回来看点击率。无效就撤回，不要连续试第二版。",
            "how_to_use": "先复制执行包到美团后台改。改完必须回到这里点「已修改」，MealKey 才知道这件事做了。",
            "observe_hours": 48,
            "success_metric": "点击率",
            "success_target": "+8%",
            "guardrail": "转化率下降不超过 3%",
        }
    if kind == "change_title":
        suggested = f"{name}｜现炒·足量热饭"
        return {
            "action_type": kind,
            "title": f"改标题执行包 · {name}",
            "object_name": name,
            "suggested_title": suggested,
            "goal": f"提高{name}点击率，转化率不下降",
            "current_problem": "标题信息弱，第一眼看不出份量和卖点",
            "copy_text": (
                f"【{name} · 标题稿】\n"
                f"建议标题：{suggested}\n"
                "结构：品类词 + 一份量或口感卖点，20 字内，避免极限词。\n"
                "成功标准：点击率回升。\n"
                "观察窗口：48 小时。\n"
                "风险：转化率下降不超过 3%。不要同时换主图。"
            ),
            "steps": [
                "确认建议标题",
                "让 MealKey 写回平台并读回",
                "读回成功后进入 48 小时观察",
            ],
            "watch": "48 小时后看点击率和转化率。无效就改回原标题。",
            "how_to_use": "确认后我会帮你改到平台，读回成功才算做完。也可以自己改完点「已修改」。",
            "observe_hours": 48,
            "success_metric": "点击率",
            "success_target": "回升",
            "guardrail": "转化率下降不超过 3%",
        }
    if kind == "batch_reply_negative_reviews":
        return {
            "action_type": kind,
            "title": "差评回复执行包",
            "goal": "把集中差评归因后回复，止住评分下滑",
            "current_problem": "差评集中，未及时按原因回复",
            "copy_text": (
                "【差评回复稿】\n"
                "先致歉，复述客人提到的问题，给具体补偿或改进，不辩解、不推锅。\n"
                "份量/口味类：非常抱歉这次没达到您的预期。已反馈后厨，下一单为您加一份，也欢迎私信我处理。\n"
                "配送/包装类：抱歉让您收到时体验不好。我们已在查包装和配送环节，需要补救请直接回我。"
            ),
            "steps": [
                "打开美团评价页，选待回复差评",
                "按模板改一处具体细节后发送",
                "回来点「已修改」，进入 48 小时观察",
            ],
            "watch": "48 小时后看是否还有同类差评，以及评分是否止跌。",
            "how_to_use": "先复制回复稿到美团评价页发送。发完必须回到这里点「已修改」。",
            "observe_hours": 48,
            "success_metric": "评分",
            "success_target": "止跌",
            "guardrail": "不要对好评套用差评模板",
        }
    if kind == "reply_ordinary_reviews":
        reply = "感谢您的认可，我们会继续保持口味和出餐速度。欢迎再来。"
        return {
            "action_type": kind,
            "title": "普通好评回复执行包",
            "object_name": name,
            "reply_text": reply,
            "goal": "把积压的普通好评及时回掉，保持店铺温度",
            "current_problem": "有普通好评还没回",
            "copy_text": (
                "【普通好评回复稿】\n"
                f"建议回复：{reply}\n"
                "只回 4 星及以上，不套用差评致歉模板，不承诺赔偿。"
            ),
            "steps": [
                "确认这是普通好评，不是差评",
                "让 MealKey 写回平台并读回",
                "读回成功后进入观察",
            ],
            "watch": "48 小时后看是否还有未回好评积压。",
            "how_to_use": "确认后我会帮你回复普通好评，读回成功才算做完。差评请你自己看过再回。",
            "observe_hours": 48,
            "success_metric": "待回复好评",
            "success_target": "清掉积压",
            "guardrail": "不要用这条路径回复差评",
        }
    if kind == "appeal_pack":
        return {
            "action_type": kind,
            "title": "评价申诉执行包",
            "object_name": name or "当前店铺",
            "appeal_reason": "疑似不实或恶意评价，需补齐订单/聊天/现场证据后提交申诉。",
            "appeal_template": (
                "【申诉说明】\n"
                "该评价疑似与实际履约情况不符，请平台复核。\n"
                "已附：订单记录、沟通截图、现场处理说明。\n"
                "诉求：核验评价真实性，并按平台规则处理。"
            ),
            "evidence_needed": "订单记录、沟通截图、现场说明，至少一份可核验证据",
            "goal": "把疑似恶意/不实评价整理成可提交申诉包",
            "current_problem": "已有疑似不实评价，但证据分散，尚未形成可提交申诉材料",
            "copy_text": (
                "【评价申诉包】\n"
                "先整理订单记录、沟通截图、现场处理说明，再提交平台申诉。\n"
                "没有证据不要硬申。提交后要读回工单号，避免只停在“好像交了”。"
            ),
            "steps": [
                "补齐订单、聊天、现场处理等申诉证据",
                "让 MealKey 提交申诉并读回工单号",
                "记录平台返回结果，继续跟进是否受理",
            ],
            "watch": "提交后继续看平台是否受理。若暂无自动结果，只记录已提交与工单号，不假装申诉成功。",
            "how_to_use": "先补齐证据，再让我提交。读回工单号后，这件事才算进入跟进。",
            "observe_hours": 48,
            "success_metric": "申诉已提交",
            "success_target": "拿到工单号",
            "guardrail": "没有证据不要提交申诉",
        }
    label = humanize_operator_text(title) or name
    return {
        "action_type": "ops_hint",
        "title": f"执行包 · {label}",
        "goal": f"完成「{label}」并进入观察",
        "current_problem": "",
        "copy_text": f"【{label}】\n按当前方案在美团后台做完，然后回到 MealKey 点「已修改」。",
        "steps": ["在美团后台完成这一步", "回到这里点「已修改」", "进入观察窗口，等待结果"],
        "watch": "48 小时后系统回来检查有没有效果。",
        "how_to_use": "人去平台执行没关系。关键是回来告诉 MealKey：这件事做了。",
        "observe_hours": 48,
        "success_metric": "经营结果",
        "success_target": "按方案推进",
        "guardrail": "不要同时叠多个动作",
    }


def pack_from_card(card: Any) -> Optional[dict[str, Any]]:
    title = str(getattr(card, "title", "") or getattr(card, "get", lambda *_: "")("title") or "")
    if isinstance(card, dict):
        title = str(card.get("title") or "")
    action_type = ""
    actions = getattr(card, "actions", None) if not isinstance(card, dict) else card.get("actions")
    actions = actions or []
    if actions:
        first = actions[0]
        action_type = str(getattr(first, "kind", None) or (first.get("kind") if isinstance(first, dict) else "") or "")
        if action_type in {"adopt", "execute", "focus_intent", "scroll"}:
            action_type = ""
    blob = " ".join(
        [
            title,
            str((card.get("why_now") if isinstance(card, dict) else getattr(card, "why_now", "")) or ""),
            str((card.get("ai_judgment") if isinstance(card, dict) else getattr(card, "ai_judgment", "")) or ""),
        ]
    )
    kind = infer_pack_action_type(title=title, action_type=action_type, blob=blob) or "ops_hint"
    return build_execution_pack(kind, object_name=_object_name(title), title=title)
