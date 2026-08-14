"""Golden Case Library — 经典外卖经营案例库 + 匹配引擎。

30 个蒸馏案例,覆盖外卖经营最高频的场景。
每个案例都是: 什么情况 → 正确诊断 → 该做什么 → 不该做什么 → 经验教训。

匹配引擎: 新问题进来时,按信号标签匹配最相似的案例,
给 chief_agent 和诊断引擎提供"经验参考"。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.golden_case import GoldenCase


# ═══════════════════════════════════════════════════════════
# 30 个经典案例
# ═══════════════════════════════════════════════════════════

CASES: list[dict[str, Any]] = [
    # ── 订单下降类 ──
    {
        "code": "GC-001", "category": "order_drop", "source": "distilled", "confidence": 0.92,
        "title": "CTR持续下降导致订单减少",
        "scenario": "老板问: 最近订单一直在掉,不知道为什么",
        "facts": {"orders_delta": -12, "impressions_delta": 2, "ctr_delta": -18, "cvr_delta": 1, "price_changed": False, "competitor_changed_image": True},
        "missing_facts": [],
        "expected_diagnosis": "点击竞争力下降: 曝光稳定但CTR跌 → 主图/首屏竞争力问题,而非流量问题",
        "forbidden_diagnosis": "直接归因平台限流/天气;直接建议加CPC",
        "expected_action": "检查主图与竞品对比,做主图A/B测试",
        "forbidden_action": "立即大幅降价;盲目加CPC(会放大低CTR的损失)",
        "execution_mode": "ASK_APPROVAL",
        "success_metric": "CTR", "observation_window_hours": 48,
        "guardrail": "CVR不得下降超过5%",
        "actual_result": "换主图后CTR从3.1%恢复到4.5%,订单回升8%",
        "lesson": "曝光稳但CTR跌,先查图片竞争力,不要花钱买流量补",
        "tags": "ctr,order_drop,主图,曝光稳定",
    },
    {
        "code": "GC-002", "category": "order_drop", "source": "distilled", "confidence": 0.88,
        "title": "曝光骤降导致订单下降",
        "scenario": "老板问: 今天突然没单了",
        "facts": {"orders_delta": -25, "impressions_delta": -30, "ctr_delta": 2, "cvr_delta": 0, "activity_ended": True},
        "expected_diagnosis": "活动到期导致曝光骤降,非商品问题",
        "forbidden_diagnosis": "归因菜品质量;建议立即换图",
        "expected_action": "续活动或开新活动恢复曝光;检查活动到期日历",
        "forbidden_action": "在曝光低时改主图(会进一步降低数据量,影响A/B测试可信度)",
        "execution_mode": "AUTO_AND_REPORT",
        "success_metric": "曝光量", "observation_window_hours": 24,
        "actual_result": "续活动后曝光恢复,订单回到正常水平",
        "lesson": "曝光突降先查活动/营业状态,不要急着改商品",
        "tags": "exposure_drop,order_drop,activity,曝光",
    },
    {
        "code": "GC-003", "category": "order_drop", "source": "distilled", "confidence": 0.85,
        "title": "CVR下降但CTR正常",
        "scenario": "老板问: 有点进来但不下单",
        "facts": {"orders_delta": -8, "impressions_delta": 0, "ctr_delta": 0, "cvr_delta": -15, "price_changed": False, "new_negative_review": True},
        "expected_diagnosis": "转化环节问题: 差评/价格感知/商品描述/套餐吸引力",
        "expected_action": "检查近期差评内容 + 优化商品描述和套餐组合",
        "forbidden_action": "降价(可能是差评导致信任度下降,降价不一定解决)",
        "execution_mode": "ASK_APPROVAL",
        "success_metric": "CVR", "observation_window_hours": 72,
        "guardrail": "利润率不得低于底线",
        "lesson": "CTR正常CVR跌,查差评和转化链路,不要直接降价",
        "tags": "cvr,order_drop,差评,转化",
    },
    # ── 利润异常类 ──
    {
        "code": "GC-004", "category": "profit_loss", "source": "distilled", "confidence": 0.90,
        "title": "GMV涨了但利润反而下降",
        "scenario": "老板问: 营业额涨了但钱没多,是不是哪里不对",
        "facts": {"gmv_delta": 15, "profit_delta": -8, "orders_delta": 20, "ads_spend_delta": 60, "subsidy_delta": 30},
        "expected_diagnosis": "买流水: GMV增长主要靠广告和补贴驱动,边际利润为负",
        "forbidden_diagnosis": "归因食材成本上涨",
        "expected_action": "减少广告投放/优化ROAS;检查活动补贴是否过大",
        "forbidden_action": "继续加大投放(GMV涨≠利润涨,会越烧越多)",
        "execution_mode": "ASK_APPROVAL",
        "success_metric": "贡献利润率",
        "actual_result": "减少30%低效广告后,GMV降5%但利润回升12%",
        "lesson": "GMV涨利润跌,先查广告和补贴,不要追流水",
        "tags": "profit,gmv,ads,subsidy,买流水",
    },
    {
        "code": "GC-005", "category": "profit_loss", "source": "distilled", "confidence": 0.87,
        "title": "到手率突然下降",
        "scenario": "老板问: 同样卖这么多,到手怎么少了",
        "facts": {"take_home_rate_delta": -5, "gmv_delta": 0, "commission_delta": 2, "subsidy_delta": 8},
        "expected_diagnosis": "佣金率或商家补贴占比上升导致到手率下降",
        "expected_action": "检查是否有新活动增加了商家承担比例;对账佣金明细",
        "forbidden_action": "直接涨价(可能影响转化)",
        "lesson": "到手率下降查佣金和补贴明细,不要直接涨价",
        "tags": "profit,take_home,commission,subsidy",
    },
    # ── 差评类 ──
    {
        "code": "GC-006", "category": "bad_review", "source": "distilled", "confidence": 0.91,
        "title": "差评集中提到份量少",
        "scenario": "老板问: 最近差评突然变多了",
        "facts": {"bad_review_rate": 25, "review_themes": ["份量少", "吃不饱"], "avg_rating_delta": -0.3},
        "expected_diagnosis": "份量问题: 可能是标准执行不到位或成本优化导致缩量",
        "expected_action": "统一出品标准,核查后厨是否擅自减量;考虑增加份量或调整价格预期",
        "forbidden_action": "只回复差评不解决问题(差评会持续出现)",
        "execution_mode": "ASK_APPROVAL",
        "success_metric": "差评率", "observation_window_hours": 168,
        "actual_result": "统一份量标准后,份量相关差评减少70%",
        "lesson": "差评集中同一主题=系统性问题,改根因比回复差评重要",
        "tags": "review,份量,差评,系统性",
    },
    {
        "code": "GC-007", "category": "bad_review", "source": "distilled", "confidence": 0.83,
        "title": "包装相关差评频发",
        "scenario": "老板问: 好几个顾客说汤洒了",
        "facts": {"bad_review_rate": 15, "review_themes": ["洒", "漏", "破"], "packaging_cost": 1.5},
        "expected_diagnosis": "包装不达标: 低成本包装导致运输中破损",
        "expected_action": "升级包装(汤品用密封盒+防漏盖),成本增加约¥0.5-1/单但差评损失更大",
        "forbidden_action": "忽略(包装差评会持续拉低评分和排名)",
        "lesson": "包装升级的成本远低于差评损失,优先修",
        "tags": "review,包装,洒漏,差评",
    },
    {
        "code": "GC-008", "category": "bad_review", "source": "distilled", "confidence": 0.80,
        "title": "远距离差评多但近距离好评多",
        "scenario": "老板问: 店铺评分被远距离的差评拉低了",
        "facts": {"near_rating": 4.8, "far_rating": 3.5, "far_complaints": ["凉", "慢", "化了"]},
        "expected_diagnosis": "配送距离影响体验: 远距离配送导致温度/口感下降",
        "expected_action": "缩减远距离配送范围或增加保温包装",
        "forbidden_action": "对所有顾客统一处理",
        "lesson": "近距离好评远距离差评,限制配送半径或加保温",
        "tags": "review,距离,配送,口感",
    },
    # ── 活动决策类 ──
    {
        "code": "GC-009", "category": "campaign", "source": "distilled", "confidence": 0.89,
        "title": "满减活动叠加导致亏钱",
        "scenario": "老板问: 平台推荐我参加满30减8,划算吗",
        "facts": {"sku_price": 29.9, "food_cost": 14.0, "packaging_cost": 2.0, "commission_rate": 0.18, "discount": 8, "platform_subsidy": 3, "existing_coupon": 5},
        "expected_diagnosis": "叠加后单均利润接近0甚至为负",
        "expected_action": "计算叠加后实收-成本,如果利润率<15%则不参加或缩范围",
        "forbidden_action": "只看平台推荐的'预计增量'就参加",
        "actual_result": "叠加后每单亏¥0.3,100单/天=每天亏¥30",
        "lesson": "活动要算叠加后的真实单均利润,不是看表面折扣",
        "tags": "campaign,满减,叠加,profit",
    },
    {
        "code": "GC-010", "category": "campaign", "source": "distilled", "confidence": 0.85,
        "title": "活动参加了但效果不明显",
        "scenario": "老板问: 参加了3天活动,好像没什么效果",
        "facts": {"orders_delta_during_campaign": 3, "expected_lift": 15, "ads_spend_during": 200},
        "expected_diagnosis": "活动曝光不足或活动力度不够吸引力",
        "expected_action": "检查活动是否在列表页展示了;考虑加大折扣或配合推广",
        "forbidden_action": "盲目续期(可能只是活动设置有问题)",
        "lesson": "活动没效果先查展示位和曝光,不是直接续",
        "tags": "campaign,effect,曝光,活动效果",
    },
    # ── 竞品类 ──
    {
        "code": "GC-011", "category": "competition", "source": "distilled", "confidence": 0.82,
        "title": "竞品降价了要不要跟",
        "scenario": "老板问: 对面那家降价了,我要不要也降",
        "facts": {"competitor_price_drop": 3, "our_margin": 0.15, "our_ctr": 4.2, "competitor_ctr": 3.5},
        "expected_diagnosis": "我方CTR高于竞品,有竞争力,不需要跟降",
        "expected_action": "保持价格,通过优化图片/套餐/服务差异化竞争",
        "forbidden_action": "跟降(会直接损失利润,且可能引发价格战)",
        "lesson": "CTR高于竞品时不要跟降,用差异化竞争保利润",
        "tags": "competition,price,降价,竞品",
    },
    {
        "code": "GC-012", "category": "competition", "source": "distilled", "confidence": 0.78,
        "title": "竞品换了更好的主图",
        "scenario": "老板问: 对面那家突然订单涨了很多",
        "facts": {"competitor_image_changed": True, "competitor_ctr_delta": 35, "our_orders_delta": -10},
        "expected_diagnosis": "竞品通过主图升级提升了点击竞争力,分流了我们的曝光",
        "expected_action": "也升级主图,但不照抄竞品,用差异化角度",
        "forbidden_action": "降价应对(根因是图片不是价格)",
        "lesson": "竞品换图导致分流,我们的对策也是优化图片",
        "tags": "competition,image,ctr,竞品,主图",
    },
    # ── 投流类 ──
    {
        "code": "GC-013", "category": "ads", "source": "distilled", "confidence": 0.88,
        "title": "CPC持续上涨",
        "scenario": "老板问: 广告费越来越贵了",
        "facts": {"cpc_trend": 25, "roas": 2.5, "ctr_delta": -5},
        "expected_diagnosis": "CPC上涨可能是竞争加剧或素材衰退",
        "expected_action": "更新广告素材;调整出价策略;暂停高CPC低转化时段",
        "forbidden_action": "硬扛(CPC上涨+ROAS不变=利润被侵蚀)",
        "lesson": "CPC涨了不更新素材,就是在白烧钱",
        "tags": "ads,cpc,roas,投流",
    },
    {
        "code": "GC-014", "category": "ads", "source": "distilled", "confidence": 0.86,
        "title": "ROAS很低但还在投",
        "scenario": "老板问: 广告到底有没有用",
        "facts": {"roas": 1.3, "cpc": 3.5, "daily_cost": 400, "take_home_rate": 0.6},
        "expected_diagnosis": "ROAS<保本线,每花¥1广告只回来¥1.3 GMV,扣利润率后亏损",
        "expected_action": "暂停低效时段,分析哪些时段/关键词转化好",
        "forbidden_action": "继续投(ROAS<2通常在亏钱)",
        "lesson": "ROAS低于2先停,查哪些时段在白烧",
        "tags": "ads,roas,投流,亏损",
    },
    # ── 新品类 ──
    {
        "code": "GC-015", "category": "new_product", "source": "distilled", "confidence": 0.80,
        "title": "新品上线后没跑起来",
        "scenario": "老板问: 上周上的新品一单都没卖",
        "facts": {"new_item_orders_7d": 0, "new_item_impressions": 50, "new_item_position": "page2"},
        "expected_diagnosis": "新品曝光不足: 在第2页,几乎没被看到",
        "expected_action": "调到首页 + 给予初始曝光(推广或套餐捆绑)",
        "forbidden_action": "立即下架(可能只是曝光不够,不是产品问题)",
        "lesson": "新品没单先查曝光位置,不要急着下架",
        "tags": "new_product,新品,曝光,page2",
    },
    {
        "code": "GC-016", "category": "new_product", "source": "distilled", "confidence": 0.77,
        "title": "两个新品互相抢订单",
        "scenario": "老板问: 上了两个新品,总量没涨",
        "facts": {"item_a_orders_delta": 15, "item_b_orders_delta": 12, "total_orders_delta": 2},
        "expected_diagnosis": "新品互斥: 两个新品抢的是同一批顾客,没有增量",
        "expected_action": "保留转化率高的那个,砍掉另一个;或差异化定位",
        "forbidden_action": "同时保留两个(分散曝光,都不够量)",
        "lesson": "总量没涨=互斥,留转化率高的,砍另一个",
        "tags": "new_product,互斥,新品,订单",
    },
    # ── 履约类 ──
    {
        "code": "GC-017", "category": "fulfillment", "source": "distilled", "confidence": 0.84,
        "title": "出餐越来越慢",
        "scenario": "老板问: 最近差评都说等太久",
        "facts": {"meal_prep_rate_delta": -8, "orders_delta": 15, "slow_complaints": 8},
        "expected_diagnosis": "订单增长超过产能: 出餐率下降是产能瓶颈信号",
        "expected_action": "高峰前多备半成品;简化复杂SKU;考虑增加人手",
        "forbidden_action": "继续接单不限制(出餐慢→差评→降权,恶性循环)",
        "lesson": "出餐率下降=产能到顶,高峰前多备料或缩菜单",
        "tags": "fulfillment,出餐,慢,产能",
    },
    {
        "code": "GC-018", "category": "fulfillment", "source": "distilled", "confidence": 0.81,
        "title": "商责取消率突然变高",
        "scenario": "老板问: 最近好多取消单",
        "facts": {"merchant_cancel_rate": 3.5, "cancel_reasons": ["售罄", "来不及"]},
        "expected_diagnosis": "售罄或来不及: 库存管理或产能问题",
        "expected_action": "爆款提前多备;设置库存预警;高峰前确认备料",
        "forbidden_action": "不管(商责取消率高会被平台降权)",
        "lesson": "商责取消查售罄和来不及,根因是备料和产能",
        "tags": "fulfillment,取消,售罄,产能",
    },
    # ── 菜单优化类 ──
    {
        "code": "GC-019", "category": "menu", "source": "distilled", "confidence": 0.83,
        "title": "僵尸SKU拖累店铺",
        "scenario": "老板问: 店铺评分上不去",
        "facts": {"total_skus": 35, "zero_order_skus": 12, "low_rating_skus": 5},
        "expected_diagnosis": "过多0单/低评分SKU拉低店铺整体表现",
        "expected_action": "停售0单SKU;优化或下架低评分SKU",
        "forbidden_action": "保留(僵尸SKU占曝光位,稀释有效SKU的数据)",
        "lesson": "0单SKU要果断停售,留着只会有害",
        "tags": "menu,僵尸sku,停售,菜单优化",
    },
    {
        "code": "GC-020", "category": "menu", "source": "distilled", "confidence": 0.79,
        "title": "套餐增加了复杂度但没贡献利润",
        "scenario": "老板问: 套餐卖得还行但后厨忙不过来",
        "facts": {"bundle_count": 8, "bundle_margin_avg": 0.10, "single_item_margin": 0.25},
        "expected_diagnosis": "套餐过多+利润低+制作复杂,占用后厨产能",
        "expected_action": "精简到3-4个高利润套餐,砍掉复杂度高的低利润套餐",
        "forbidden_action": "继续加套餐(复杂度增加→出餐慢→差评)",
        "lesson": "套餐不在多,3-4个高利润的比8个低利润的好",
        "tags": "menu,套餐,利润,复杂度",
    },
    # ── CRM类 ──
    {
        "code": "GC-021", "category": "crm", "source": "distilled", "confidence": 0.76,
        "title": "老客复购率下降",
        "scenario": "老板问: 以前经常来的客人不来了",
        "facts": {"repurchase_rate_delta": -8, "new_customer_share": 55},
        "expected_diagnosis": "新客占比上升但老客流失: 可能是体验下降或被竞品分流",
        "expected_action": "分析老客流失时间点;考虑定向发券召回;检查同期是否有差评/体验下降",
        "forbidden_action": "只做拉新(拉新成本远高于留客)",
        "lesson": "老客流失比新客减少更危险,先查流失原因",
        "tags": "crm,复购,老客,流失",
    },
    # ── 特殊场景 ──
    {
        "code": "GC-022", "category": "weather", "source": "distilled", "confidence": 0.88,
        "title": "下雨天订单激增是好事吗",
        "scenario": "老板问: 今天下雨单特别多",
        "facts": {"orders_delta": 40, "weather": "暴雨", "meal_prep_rate_delta": -12, "cancel_rate_delta": 2},
        "expected_diagnosis": "天气驱动的增量: 需求暴涨但产能跟不上,出餐率和满意度在下降",
        "expected_action": "控制接单节奏,优先保证出餐质量;如果来不及果断暂停接单",
        "forbidden_action": "来者不拒全接(出餐慢→差评→雨天高峰变成差评高峰)",
        "lesson": "雨天爆单要控制节奏,出餐质量比单量重要",
        "tags": "weather,雨天,产能,出餐",
    },
    {
        "code": "GC-023", "category": "seasonal", "source": "distilled", "confidence": 0.75,
        "title": "换季后某些SKU销量骤降",
        "scenario": "老板问: 天气热了汤面卖不动了",
        "facts": {"hot_item_orders_delta": -35, "season": "summer", "cold_item_orders_delta": 20},
        "expected_diagnosis": "季节性需求转移: 正常现象,不是产品问题",
        "expected_action": "减少热食曝光;增加凉菜/饮品;推出夏季限定",
        "forbidden_action": "在淡季大力推广不合适宜的产品(浪费曝光)",
        "lesson": "换季销量下降先看品类属性,不要盲目优化",
        "tags": "seasonal,换季,夏季,菜单",
    },
    {
        "code": "GC-024", "category": "holiday", "source": "distilled", "confidence": 0.80,
        "title": "节假日后订单断崖",
        "scenario": "老板问: 长假过后突然没单了",
        "facts": {"orders_delta": -30, "context": "post_holiday", "audience": "写字楼"},
        "expected_diagnosis": "节后效应: 写字楼客流恢复延迟,正常现象",
        "expected_action": "节后第一周适度降价或推优惠套餐刺激回归",
        "forbidden_action": "恐慌性大幅降价(会破坏价格锚,之后涨不回来)",
        "lesson": "节后低谷是正常的,小幅刺激即可,不要大幅降价",
        "tags": "holiday,节后,写字楼,订单下降",
    },
    # ── 设备/技术 ──
    {
        "code": "GC-025", "category": "device", "source": "distilled", "confidence": 0.85,
        "title": "某天订单突然为0",
        "scenario": "老板问: 今天一单都没有,是不是出问题了",
        "facts": {"orders_today": 0, "orders_yesterday": 85, "store_open": True},
        "expected_diagnosis": "设备/网络故障: 营业中但0单大概率是接单设备问题",
        "expected_action": "立即检查接单设备、网络、平台营业状态",
        "forbidden_action": "以为是淡季不管(0单几乎一定是技术问题)",
        "lesson": "营业中0单=设备故障,必须立即排查",
        "tags": "device,0单,故障,接单",
    },
    # ── 高级经营 ──
    {
        "code": "GC-026", "category": "strategy", "source": "distilled", "confidence": 0.78,
        "title": "同时改了多个变量导致无法归因",
        "scenario": "老板问: 上周换了图又改了价又加了活动,现在不知道哪个有效",
        "facts": {"changes_made": ["change_image", "adjust_price", "join_campaign"], "orders_delta": 10},
        "expected_diagnosis": "多变量同时变更: 无法判断增量来自哪个动作",
        "expected_action": "下次一次只改一个变量(单变量实验原则)",
        "forbidden_action": "假设所有动作都有效并全部继续(可能其中某个在拖后腿)",
        "lesson": "一次只改一个变量,否则永远不知道什么有效",
        "tags": "strategy,实验,归因,多变量",
    },
    {
        "code": "GC-027", "category": "strategy", "source": "distilled", "confidence": 0.82,
        "title": "低价引流品的正确用法",
        "scenario": "老板问: 那个9.9的特价到底要不要继续",
        "facts": {"loss_leader_price": 9.9, "loss_leader_margin": -0.05, "loss_leader_orders": 40, "cross_sell_rate": 15},
        "expected_diagnosis": "引流品亏¥0.5/单但15%带来连带订单,整体ROI为正",
        "expected_action": "继续引流但监控连带率;如果连带率<10%则缩限",
        "forbidden_action": "只看引流品自身利润就砍掉(忽略连带贡献)",
        "lesson": "引流品看连带率,不看自身利润",
        "tags": "strategy,引流品,连带,低价",
    },
    {
        "code": "GC-028", "category": "strategy", "source": "distilled", "confidence": 0.80,
        "title": "爆款售罄的正确处理",
        "scenario": "老板问: 招牌菜卖完了怎么办",
        "facts": {"best_seller_sold_out": True, "peak_hours_left": 2, "current_orders": 60},
        "expected_diagnosis": "爆款售罄影响转化和排名,需要快速决策",
        "expected_action": "尽快补货;同时推替代品到首页;在描述标注'今日限量'",
        "forbidden_action": "直接下架(售罄比下架好,能保持曝光)",
        "lesson": "爆款售罄推替代品,不要直接下架",
        "tags": "strategy,售罄,爆款,替代品",
    },
    # ── 新店 ──
    {
        "code": "GC-029", "category": "new_store", "source": "distilled", "confidence": 0.77,
        "title": "新店第一周最重要的三件事",
        "scenario": "老板问: 新店刚上线,先做什么",
        "facts": {"store_age_days": 3, "menu_items": 8, "reviews": 0, "ctr": 2.1},
        "expected_diagnosis": "新店冷启动期: 首要任务是建信任(评分)和获曝光,不是优化利润",
        "expected_action": "1)确保出品质量拿前10条好评;2)设置合理引流价;3)推广获取初始曝光",
        "forbidden_action": "一上来就追求高利润(新店没评分没排名,利润无从谈起)",
        "lesson": "新店第一周建信任比赚钱重要,好评和曝光优先",
        "tags": "new_store,冷启动,新店,好评",
    },
    {
        "code": "GC-030", "category": "new_store", "source": "distilled", "confidence": 0.74,
        "title": "新店30天健康度评估",
        "scenario": "老板问: 开了一个月了,这个店行不行",
        "facts": {"store_age_days": 30, "avg_daily_orders": 45, "avg_rating": 4.6, "repurchase_rate": 22, "ctr": 3.8},
        "expected_diagnosis": "冷启动完成: 订单、评分、复购都达标,可以进入正常经营阶段",
        "expected_action": "逐步减少引流品占比;开始优化利润结构;建立常规经营节奏",
        "forbidden_action": "继续冷启动策略(过度让利,利润上不来)",
        "lesson": "评分>4.5+日单>30+复购>20% = 冷启动成功,该转正常经营",
        "tags": "new_store,30天,健康度,冷启动完成",
    },
]


def seed_cases(db) -> int:
    """初始化案例库。幂等。"""
    existing_codes = set(
        db.execute(select(GoldenCase.case_code)).scalars()
    )
    inserted = 0
    for case in CASES:
        if case["code"] in existing_codes:
            continue
        record = GoldenCase(
            case_code=case["code"],
            category=case["category"],
            title=case["title"],
            scenario=case["scenario"],
            facts_json=json.dumps(case.get("facts", {}), ensure_ascii=False),
            missing_facts_json=json.dumps(case.get("missing_facts", []), ensure_ascii=False) if case.get("missing_facts") else None,
            expected_diagnosis=case.get("expected_diagnosis", ""),
            forbidden_diagnosis=case.get("forbidden_diagnosis"),
            expected_action=case.get("expected_action", ""),
            forbidden_action=case.get("forbidden_action"),
            execution_mode=case.get("execution_mode", "ASK_APPROVAL"),
            success_metric=case.get("success_metric"),
            observation_window_hours=case.get("observation_window_hours"),
            guardrail=case.get("guardrail"),
            actual_result=case.get("actual_result"),
            lesson=case.get("lesson", ""),
            tags=case.get("tags", ""),
            source=case.get("source", "distilled"),
            confidence=case.get("confidence", 0.8),
        )
        db.add(record)
        inserted += 1
    if inserted:
        db.commit()
    return inserted


def match_cases(
    db,
    *,
    signals: dict[str, Any] | None = None,
    question: str = "",
    category: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """根据经营信号/问题/类别匹配最相似的案例。

    匹配逻辑:
    1. 如果有 category → 先按类别筛
    2. 如果有 question → 按关键词匹配 tags/scenario
    3. 如果有 signals → 按 facts 字段匹配
    """
    query = select(GoldenCase)

    if category:
        query = query.where(GoldenCase.category == category)

    all_cases = list(db.execute(query).scalars())
    if not all_cases:
        return []

    scored: list[tuple[float, GoldenCase]] = []

    for case in all_cases:
        score = 0.0

        # 按问题关键词匹配 tags
        if question:
            q_lower = question.lower()
            tags = (case.tags or "").lower()
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            for tag in tag_list:
                if tag in q_lower:
                    score += 3.0
            # 匹配 scenario
            if case.scenario and any(kw in case.scenario for kw in question.split() if len(kw) > 1):
                score += 1.0

        # 按 signals 匹配 facts
        if signals:
            try:
                facts = json.loads(case.facts_json) if case.facts_json else {}
                for key, value in signals.items():
                    if key in facts:
                        case_val = facts[key]
                        # 数值类:相近则加分
                        if isinstance(value, (int, float)) and isinstance(case_val, (int, float)):
                            if case_val != 0:
                                diff_ratio = abs(value - case_val) / max(abs(value), abs(case_val))
                                if diff_ratio < 0.3:
                                    score += 2.0
                            elif value == case_val:
                                score += 2.0
                        # 布尔类
                        elif isinstance(value, bool) and case_val == value:
                            score += 1.5
                        # 字符串类
                        elif isinstance(value, str) and value.lower() in str(case_val).lower():
                            score += 1.0
            except (json.JSONDecodeError, TypeError):
                pass

        # 基础分:confidence
        score += case.confidence * 0.5

        if score > 0:
            scored.append((score, case))

    scored.sort(key=lambda x: -x[0])

    return [
        {
            "case_code": case.case_code,
            "category": case.category,
            "title": case.title,
            "scenario": case.scenario,
            "facts": json.loads(case.facts_json) if case.facts_json else {},
            "expected_diagnosis": case.expected_diagnosis,
            "forbidden_diagnosis": case.forbidden_diagnosis,
            "expected_action": case.expected_action,
            "forbidden_action": case.forbidden_action,
            "lesson": case.lesson,
            "confidence": case.confidence,
            "match_score": round(score, 2),
        }
        for score, case in scored[:limit]
    ]
