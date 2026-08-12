from __future__ import annotations
from app.schemas.agents import AgentKey

AGENT_LABELS: dict[AgentKey, str] = {
    "competition": "商圈竞争洞察 Agent",
    "menu": "菜单智能分析 Agent",
    "product": "商品优化 Agent",
    "storefront": "线上装修诊断 Agent",
    "diagnosis": "经营诊断 Agent",
    "growth": "增长策略 Agent",
    "promo": "平台活动 Agent",
    "ads": "投流 Agent",
    "crm": "用户关系 Agent",
    "service": "AI 客服 Agent",
    "review": "评分评价 Agent",
    "store_matrix": "线上门店增长 Agent",
}

ACTION_HISTORY_DAYS = 21
