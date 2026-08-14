"""Operating Benchmark — MealKey 200 个经营需求的覆盖率引擎。

不是 Feature List,是产品基准。
每个需求映射到: 当前覆盖率 + 关联代码 + 缺失能力。

用途:
1. 换模型/改 Prompt/改 Playbook 后,问"200个Case能闭环多少"
2. 明确 ¥300/月 AI 店长的服务边界
3. 指导开发优先级(先补 P0 未覆盖需求)
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operating_demand import OperatingDemand


# ═══════════════════════════════════════════════════════════
# 200 个经营需求(浓缩版,每条含核心字段)
# ═══════════════════════════════════════════════════════════

DEMANDS: list[dict[str, Any]] = [
    # ── 1-10: 利润与经营真相 ──
    {"id":1,"cat":"利润真相","q":"今天哪家店在亏钱？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.diagnose_profit_change"},
    {"id":2,"cat":"利润真相","q":"昨天利润为什么掉了？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.diagnose_profit_change"},
    {"id":3,"cat":"利润真相","q":"每卖一单赚多少钱？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.calculate_profit"},
    {"id":4,"cat":"利润真相","q":"哪些SKU赚钱哪些亏？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.calculate_profit"},
    {"id":5,"cat":"利润真相","q":"哪个活动吃掉了利润？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.diagnose_profit_change"},
    {"id":6,"cat":"利润真相","q":"投流订单还有利润吗？","loop":"A","cov":"covered","pri":"P0","svc":"domain_skills.analyze_ads"},
    {"id":7,"cat":"利润真相","q":"为什么到手率下降？","loop":"A","cov":"covered","pri":"P0","svc":"sensing.build_profit_state"},
    {"id":8,"cat":"利润真相","q":"退款赔付吃了多少利润？","loop":"A","cov":"partial","pri":"P1","svc":"decision_core.calculate_profit"},
    {"id":9,"cat":"利润真相","q":"食材包装成本变化影响？","loop":"A","cov":"covered","pri":"P0","svc":"cost_import + decision_core"},
    {"id":10,"cat":"利润真相","q":"本月利润目标能完成吗？","loop":"A","cov":"covered","pri":"P0","svc":"goal_engine + profit forecast"},

    # ── 11-20: 活动价格套餐 ──
    {"id":11,"cat":"活动决策","q":"这个活动参不参加？","loop":"B","cov":"covered","pri":"P0","svc":"decision_core.calculate_campaign"},
    {"id":12,"cat":"活动决策","q":"叠加券会不会亏？","loop":"A","cov":"covered","pri":"P0","svc":"decision_core.overlay_detection"},
    {"id":13,"cat":"活动决策","q":"最低安全到手价？","loop":"B","cov":"covered","pri":"P0","svc":"decision_core.profit_floor"},
    {"id":14,"cat":"活动决策","q":"哪些店/品/时段最划算？","loop":"B","cov":"covered","pri":"P1","svc":"decision_core.calculate_campaign"},
    {"id":15,"cat":"活动决策","q":"活动快结束要不要续？","loop":"B","cov":"covered","pri":"P1","svc":"experiment_attribution"},
    {"id":16,"cat":"活动决策","q":"该涨价还是降价？","loop":"B","cov":"partial","pri":"P1","svc":"product_agent pricing"},
    {"id":17,"cat":"活动决策","q":"怎么提高碗均价？","loop":"B","cov":"covered","pri":"P1","svc":"menu_agent bundles"},
    {"id":18,"cat":"活动决策","q":"什么套餐组合适合卖？","loop":"B","cov":"covered","pri":"P1","svc":"menu_agent bundle_opportunities"},
    {"id":19,"cat":"活动决策","q":"引流品该不该限量？","loop":"B","cov":"covered","pri":"P1","svc":"menu_agent cleanup"},
    {"id":20,"cat":"活动决策","q":"3天前参加的活动有效吗？","loop":"A","cov":"covered","pri":"P0","svc":"experiment_attribution.evaluate_experiment"},

    # ── 21-30: 流量推广广告 ──
    {"id":21,"cat":"投流诊断","q":"推广花的钱赚回来了吗？","loop":"A","cov":"covered","pri":"P0","svc":"domain_skills.analyze_ads"},
    {"id":22,"cat":"投流诊断","q":"广告预算该加还是减？","loop":"B","cov":"partial","pri":"P1","svc":"ads_agent + analyze_ads"},
    {"id":23,"cat":"投流诊断","q":"预算会不会午高峰前烧完？","loop":"B","cov":"partial","pri":"P1","svc":"ads_agent budget_forecast"},
    {"id":24,"cat":"投流诊断","q":"预算从下午移到午餐？","loop":"B","cov":"partial","pri":"P1","svc":"ads_agent time_shift"},
    {"id":25,"cat":"投流诊断","q":"ROI好但预算没花完？","loop":"B","cov":"partial","pri":"P1","svc":"domain_skills.analyze_ads"},
    {"id":26,"cat":"投流诊断","q":"ROI差该减多少？","loop":"B","cov":"partial","pri":"P1","svc":"domain_skills.analyze_ads"},
    {"id":27,"cat":"投流诊断","q":"付费转化下降原因？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner"},
    {"id":28,"cat":"投流诊断","q":"订单增长来自自然还是广告？","loop":"A","cov":"covered","pri":"P0","svc":"ads_agent natural_vs_paid"},
    {"id":29,"cat":"投流诊断","q":"搜索曝光排名掉了？","loop":"B","cov":"partial","pri":"P1","svc":"traffic_agent seo"},
    {"id":30,"cat":"投流诊断","q":"多平台广告预算怎么分？","loop":"B","cov":"partial","pri":"P2","svc":"matrix_agents"},

    # ── 31-40: 商品菜单 ──
    {"id":31,"cat":"商品优化","q":"招牌CTR为什么掉了？","loop":"A","cov":"covered","pri":"P0","svc":"product_agent + diagnosis_reasoner"},
    {"id":32,"cat":"商品优化","q":"主图该不该换？","loop":"B","cov":"covered","pri":"P0","svc":"product_agent change_main_image"},
    {"id":33,"cat":"商品优化","q":"标题怎么改更容易被点？","loop":"B","cov":"covered","pri":"P0","svc":"product_agent change_title"},
    {"id":34,"cat":"商品优化","q":"描述怎么改更转化？","loop":"B","cov":"covered","pri":"P1","svc":"product_agent change_description"},
    {"id":35,"cat":"商品优化","q":"首页第一屏摆什么？","loop":"B","cov":"covered","pri":"P1","svc":"menu_agent menu_structure"},
    {"id":36,"cat":"商品优化","q":"菜单结构有没有问题？","loop":"B","cov":"covered","pri":"P1","svc":"menu_agent"},
    {"id":37,"cat":"商品优化","q":"僵尸SKU该删吗？","loop":"B","cov":"partial","pri":"P1","svc":"menu_agent cleanup"},
    {"id":38,"cat":"商品优化","q":"爆款售罄补货还是换主推？","loop":"C","cov":"partial","pri":"P1","svc":"work_thread + ops_hint"},
    {"id":39,"cat":"商品优化","q":"新品为什么没跑起来？","loop":"A","cov":"covered","pri":"P0","svc":"product_agent diagnosis"},
    {"id":40,"cat":"商品优化","q":"给照片生成更适合的主图？","loop":"B","cov":"covered","pri":"P1","svc":"product_agent image_optimization"},

    # ── 41-50: 订单下降与归因 ──
    {"id":41,"cat":"订单归因","q":"为什么今天订单掉了？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner + feature_engine"},
    {"id":42,"cat":"订单归因","q":"为什么曝光掉了？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner"},
    {"id":43,"cat":"订单归因","q":"为什么看到店不点进来？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner ctr"},
    {"id":44,"cat":"订单归因","q":"为什么进店不下单？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner cvr"},
    {"id":45,"cat":"订单归因","q":"订单没掉但客单下降？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner aov"},
    {"id":46,"cat":"订单归因","q":"为什么新客减少？","loop":"A","cov":"partial","pri":"P1","svc":"customer_agent"},
    {"id":47,"cat":"订单归因","q":"为什么老客复购下降？","loop":"A","cov":"partial","pri":"P1","svc":"customer_agent"},
    {"id":48,"cat":"订单归因","q":"午餐大概多少订单？","loop":"A","cov":"partial","pri":"P1","svc":"operating_rhythm forecast"},
    {"id":49,"cat":"订单归因","q":"下降是天气还是自身？","loop":"A","cov":"covered","pri":"P0","svc":"diagnosis_reasoner multi_factor"},
    {"id":50,"cat":"订单归因","q":"现在只该做哪一件事？","loop":"B","cov":"covered","pri":"P0","svc":"POIE + priority_arbiter"},

    # ── 51-60: 评价退款投诉 ──
    {"id":51,"cat":"评价闭环","q":"新差评哪些要马上处理？","loop":"A","cov":"covered","pri":"P0","svc":"trigger_bad_reviews"},
    {"id":52,"cat":"评价闭环","q":"差评是产品/门店/骑手/顾客？","loop":"A","cov":"covered","pri":"P0","svc":"review_nlp + diagnosis"},
    {"id":53,"cat":"评价闭环","q":"这条评价怎么回复？","loop":"A","cov":"covered","pri":"P0","svc":"execution_pack batch_reply"},
    {"id":54,"cat":"评价闭环","q":"普通评价能自动回复吗？","loop":"B","cov":"partial","pri":"P1","svc":"platform_write reply_review"},
    {"id":55,"cat":"评价闭环","q":"严重投诉找谁处理？","loop":"C","cov":"covered","pri":"P0","svc":"POIE alert_owner"},
    {"id":56,"cat":"评价闭环","q":"正常退款还是恶意骗赔？","loop":"A","cov":"partial","pri":"P1","svc":"refund_analysis"},
    {"id":57,"cat":"评价闭环","q":"能自动整理申诉证据吗？","loop":"B","cov":"partial","pri":"P1","svc":"execution_pack appeal"},
    {"id":58,"cat":"评价闭环","q":"这个顾客赔不赔赔多少？","loop":"B","cov":"partial","pri":"P1","svc":"refund_decision"},
    {"id":59,"cat":"评价闭环","q":"哪些投诉快超24h SLA？","loop":"A","cov":"covered","pri":"P0","svc":"POIE sla_check"},
    {"id":60,"cat":"评价闭环","q":"差评重复根因是什么？","loop":"A","cov":"covered","pri":"P0","svc":"strategy_memory + review_nlp"},

    # ── 61-70: 顾客CRM ──
    {"id":61,"cat":"顾客CRM","q":"谁是我的高价值顾客？","loop":"A","cov":"partial","pri":"P1","svc":"customer_agent segments"},
    {"id":62,"cat":"顾客CRM","q":"哪些老客在沉睡？","loop":"A","cov":"partial","pri":"P1","svc":"customer_agent churn"},
    {"id":63,"cat":"顾客CRM","q":"新客怎么提高二次下单？","loop":"B","cov":"partial","pri":"P1","svc":"crm_agent"},
    {"id":64,"cat":"顾客CRM","q":"高频顾客给什么权益？","loop":"B","cov":"partial","pri":"P2","svc":"crm_agent loyalty"},
    {"id":65,"cat":"顾客CRM","q":"哪些顾客可能流失？","loop":"A","cov":"partial","pri":"P1","svc":"customer_agent churn_risk"},
    {"id":66,"cat":"顾客CRM","q":"不同人群发什么券？","loop":"B","cov":"partial","pri":"P2","svc":"crm_agent coupon_targeting"},
    {"id":67,"cat":"顾客CRM","q":"现在该召回哪批顾客？","loop":"B","cov":"partial","pri":"P2","svc":"crm_agent reactivation"},
    {"id":68,"cat":"顾客CRM","q":"上次召回有效吗？","loop":"A","cov":"partial","pri":"P1","svc":"experiment_attribution"},
    {"id":69,"cat":"顾客CRM","q":"投诉顾客怎么修复？","loop":"B","cov":"partial","pri":"P2","svc":"crm_agent recovery"},
    {"id":70,"cat":"顾客CRM","q":"顾客长期价值多少？","loop":"A","cov":"partial","pri":"P2","svc":"customer_agent ltv"},

    # ── 71-80: 竞品排名 ──
    {"id":71,"cat":"竞品分析","q":"谁才是真竞争对手？","loop":"A","cov":"partial","pri":"P1","svc":"competition_agent"},
    {"id":72,"cat":"竞品分析","q":"搜索/商圈排名升降？","loop":"A","cov":"partial","pri":"P1","svc":"competition_agent ranking"},
    {"id":73,"cat":"竞品分析","q":"哪个对手刚改价？","loop":"A","cov":"partial","pri":"P1","svc":"competition_collection"},
    {"id":74,"cat":"竞品分析","q":"哪个对手开始/结束大促？","loop":"A","cov":"partial","pri":"P1","svc":"competition_collection"},
    {"id":75,"cat":"竞品分析","q":"对手换了什么爆品/主图？","loop":"A","cov":"partial","pri":"P1","svc":"competition_collection"},
    {"id":76,"cat":"竞品分析","q":"对手为什么突然跑起来？","loop":"A","cov":"partial","pri":"P1","svc":"competition_agent diagnose"},
    {"id":77,"cat":"竞品分析","q":"商圈有空缺价格带？","loop":"A","cov":"partial","pri":"P2","svc":"competition_agent price_gap"},
    {"id":78,"cat":"竞品分析","q":"商圈有产品机会？","loop":"A","cov":"partial","pri":"P2","svc":"competition_agent opportunity"},
    {"id":79,"cat":"竞品分析","q":"对手降价要不要跟？","loop":"B","cov":"partial","pri":"P0","svc":"decision_core match_competitor + profit_gate"},
    {"id":80,"cat":"竞品分析","q":"进商圈Top3怎么走？","loop":"B","cov":"partial","pri":"P1","svc":"growth_agent"},

    # ── 81-90: 履约产能 ──
    {"id":81,"cat":"履约产能","q":"异常关店/营业时间错了？","loop":"B","cov":"partial","pri":"P1","svc":"POIE store_status"},
    {"id":82,"cat":"履约产能","q":"爆款售罄谁去补货？","loop":"C","cov":"partial","pri":"P1","svc":"work_thread stockout"},
    {"id":83,"cat":"履约产能","q":"接单/打印/设备异常？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":84,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":85,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":86,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":87,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":88,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":89,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":90,"cat":"履约产能","q":"整改任务做了没？","loop":"C","cov":"partial","pri":"P1","svc":"work_thread + evidence"},

    # ── 91-100: 多平台连锁 ──
    {"id":91,"cat":"多平台","q":"多平台今天赚多少？","loop":"A","cov":"partial","pri":"P0","svc":"platform_sync merge_multi"},
    {"id":92,"cat":"多平台","q":"同品不同平台价格冲突？","loop":"B","cov":"partial","pri":"P1","svc":"multi_platform price_check"},
    {"id":93,"cat":"多平台","q":"流量预算往哪个平台倾斜？","loop":"B","cov":"partial","pri":"P1","svc":"matrix_agents budget_allocation"},
    {"id":94,"cat":"连锁","q":"20家店最好最差是哪家？","loop":"A","cov":"covered","pri":"P0","svc":"matrix_agents ranking"},
    {"id":95,"cat":"连锁","q":"不同类型店不同打法？","loop":"A","cov":"covered","pri":"P0","svc":"matrix_agents clustering"},
    {"id":96,"cat":"连锁","q":"A店策略复制到类似店？","loop":"B","cov":"covered","pri":"P0","svc":"strategy_memory cross_store"},
    {"id":97,"cat":"连锁","q":"这周最重要的经营变化？","loop":"A","cov":"covered","pri":"P0","svc":"night_learn weekly_summary"},
    {"id":98,"cat":"连锁","q":"本月淘汰/强化哪些策略？","loop":"A","cov":"covered","pri":"P0","svc":"strategy_memory lifecycle"},
    {"id":99,"cat":"连锁","q":"一个厨房要不要再开线上店？","loop":"B","cov":"partial","pri":"P2","svc":"growth_agent expansion"},
    {"id":100,"cat":"连锁","q":"全年营销节奏怎么排？","loop":"B","cov":"partial","pri":"P2","svc":"annual_planning"},

    # ═══════════════════════════════════════════════════════════
    # 第二批 101-200
    # ═══════════════════════════════════════════════════════════

    # ── 101-110: 财务结算对账 ──
    {"id":101,"cat":"","q":"","loop":"","cov":"partial","pri":"P0","svc":""},
    {"id":102,"cat":"财务对账","q":"哪些补贴应到账没到？","loop":"A","cov":"partial","pri":"P1","svc":""},
    {"id":103,"cat":"财务对账","q":"哪些佣金扣得异常？","loop":"A","cov":"partial","pri":"P1","svc":""},
    {"id":104,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":105,"cat":"财务对账","q":"退款三方金额结清没？","loop":"A","cov":"partial","pri":"P1","svc":""},
    {"id":106,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":107,"cat":"财务对账","q":"哪个平台结算造成现金流压力？","loop":"A","cov":"partial","pri":"P2","svc":""},
    {"id":108,"cat":"财务对账","q":"未来7天预计回多少钱？","loop":"A","cov":"partial","pri":"P2","svc":""},
    {"id":109,"cat":"财务对账","q":"哪些扣款值得申诉？","loop":"B","cov":"partial","pri":"P1","svc":""},
    {"id":110,"cat":"财务对账","q":"月底对账缺哪些凭证？","loop":"A","cov":"partial","pri":"P2","svc":""},

    # ── 111-120: 平台规则合规 ──
    {"id":111,"cat":"规则合规","q":"平台改规则哪些门店受影响？","loop":"A","cov":"partial","pri":"P1","svc":""},
    {"id":112,"cat":"规则合规","q":"营业执照/许可快到期？","loop":"B","cov":"partial","pri":"P1","svc":""},
    {"id":113,"cat":"规则合规","q":"店铺信息缺失/过期/错误？","loop":"A","cov":"partial","pri":"P2","svc":""},
    {"id":114,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":115,"cat":"规则合规","q":"邀评方法会不会违规？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":116,"cat":"","q":"","loop":"","cov":"partial","pri":"P0","svc":""},
    {"id":117,"cat":"规则合规","q":"处罚原因/影响/申诉截止？","loop":"B","cov":"partial","pri":"P1","svc":""},
    {"id":118,"cat":"规则合规","q":"申诉证据够不够？","loop":"B","cov":"partial","pri":"P1","svc":""},
    {"id":119,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":120,"cat":"规则合规","q":"不同平台规则怎么全合规？","loop":"B","cov":"partial","pri":"P2","svc":""},

    # ── 121-130: 新店冷启动 ──
    {"id":121,"cat":"新店启动","q":"上线前还有什么没准备好？","loop":"A","cov":"partial","pri":"P1","svc":"MOS readiness_check"},
    {"id":122,"cat":"新店启动","q":"第一周最重要的三件事？","loop":"B","cov":"partial","pri":"P1","svc":"priority_arbiter"},
    {"id":123,"cat":"新店启动","q":"第一版应该上多少SKU？","loop":"B","cov":"partial","pri":"P1","svc":"menu_agent cold_start"},
    {"id":124,"cat":"新店启动","q":"引流/主推/利润/形象款怎么分？","loop":"B","cov":"partial","pri":"P1","svc":"menu_agent roles"},
    {"id":125,"cat":"新店启动","q":"营业时间怎么设？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":126,"cat":"新店启动","q":"配送范围开多大？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":127,"cat":"新店启动","q":"前7天值不值得让利润换订单？","loop":"B","cov":"partial","pri":"P1","svc":"profit_gate cold_start"},
    {"id":128,"cat":"新店启动","q":"第7天冷启动健康吗？","loop":"A","cov":"partial","pri":"P1","svc":"health_score"},
    {"id":129,"cat":"新店启动","q":"什么时候算结束冷启动？","loop":"A","cov":"partial","pri":"P2","svc":"milestone_check"},
    {"id":130,"cat":"新店启动","q":"30天后值不值得继续投入？","loop":"B","cov":"partial","pri":"P2","svc":"roi_assessment"},

    # ── 131-140: 排班人效 ──
    {"id":131,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":132,"cat":"排班人效","q":"哪个工序卡住出餐？","loop":"C","cov":"partial","pri":"P1","svc":""},
    {"id":133,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":134,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":135,"cat":"排班人效","q":"高峰前备多少半成品？","loop":"C","cov":"partial","pri":"P1","svc":""},
    {"id":136,"cat":"排班人效","q":"爆单时该缩菜单？","loop":"B","cov":"partial","pri":"P1","svc":"menu_patch capacity"},
    {"id":137,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":138,"cat":"排班人效","q":"骑手等待卡在炒制/打包/交接？","loop":"C","cov":"partial","pri":"P2","svc":""},
    {"id":139,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":140,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},

    # ── 141-150: 原料SKU生命周期 ──
    {"id":141,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":142,"cat":"SKU生命周期","q":"原料涨价换配方/份量/供应商？","loop":"B","cov":"partial","pri":"P1","svc":""},
    {"id":143,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":144,"cat":"SKU生命周期","q":"现有食材适合开发什么新品？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":145,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":146,"cat":"SKU生命周期","q":"换季哪些商品该减少曝光？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":147,"cat":"SKU生命周期","q":"哪些SKU进入生命周期末期？","loop":"B","cov":"partial","pri":"P1","svc":"menu_agent lifecycle"},
    {"id":148,"cat":"SKU生命周期","q":"爆款在不同商圈不同口味？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":149,"cat":"SKU生命周期","q":"哪些套餐增加复杂度没贡献利润？","loop":"A","cov":"partial","pri":"P1","svc":"menu_agent bundle_analysis"},
    {"id":150,"cat":"SKU生命周期","q":"新品跑多少单才能判断留砍？","loop":"B","cov":"partial","pri":"P1","svc":"experiment_attribution"},

    # ── 151-160: 数字门店内容 ──
    {"id":151,"cat":"内容治理","q":"店铺页面跟季节/活动脱节？","loop":"A","cov":"partial","pri":"P2","svc":"storefront_agent"},
    {"id":152,"cat":"内容治理","q":"商品图与出品差异太大？","loop":"C","cov":"partial","pri":"P2","svc":""},
    {"id":153,"cat":"内容治理","q":"主图素材疲劳CTR衰减？","loop":"A","cov":"covered","pri":"P1","svc":"product_agent ctr_decline"},
    {"id":154,"cat":"内容治理","q":"天气/节日来了怎么换内容？","loop":"B","cov":"partial","pri":"P2","svc":"storefront_agent seasonal"},
    {"id":155,"cat":"内容治理","q":"50家店品牌视觉各做各的？","loop":"A","cov":"partial","pri":"P2","svc":"matrix_agents brand_check"},
    {"id":156,"cat":"内容治理","q":"哪些店用过期价格/套餐？","loop":"A","cov":"partial","pri":"P1","svc":"storefront_agent version_check"},
    {"id":157,"cat":"内容治理","q":"抖音/小红书关注变成订单了？","loop":"A","cov":"partial","pri":"P2","svc":""},
    {"id":158,"cat":"内容治理","q":"什么内容提升品牌搜索？","loop":"A","cov":"partial","pri":"P2","svc":""},
    {"id":159,"cat":"内容治理","q":"破纪录/新品/反馈值得传播？","loop":"B","cov":"partial","pri":"P3","svc":""},
    {"id":160,"cat":"内容治理","q":"AI图片文案上线前哪些要确认？","loop":"B","cov":"partial","pri":"P1","svc":"execution_policy ASK_APPROVAL"},

    # ── 161-170: 下单体验 ──
    {"id":161,"cat":"下单体验","q":"顾客备注执行比例？","loop":"C","cov":"partial","pri":"P2","svc":""},
    {"id":162,"cat":"下单体验","q":"哪种备注最易漏掉？","loop":"C","cov":"partial","pri":"P2","svc":""},
    {"id":163,"cat":"下单体验","q":"餐具/调料/发票哪类易错？","loop":"C","cov":"partial","pri":"P2","svc":""},
    {"id":164,"cat":"","q":"","loop":"","cov":"partial","pri":"P1","svc":""},
    {"id":165,"cat":"下单体验","q":"近距离好评远距离差评限制半径？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":166,"cat":"","q":"","loop":"","cov":"partial","pri":"P2","svc":""},
    {"id":167,"cat":"下单体验","q":"投诉是图片/描述和实际不一致？","loop":"A","cov":"partial","pri":"P1","svc":"review_nlp expectation_gap"},
    {"id":168,"cat":"下单体验","q":"爆单时关闭复杂定制？","loop":"B","cov":"partial","pri":"P2","svc":""},
    {"id":169,"cat":"下单体验","q":"质量不稳定该主动停售？","loop":"B","cov":"partial","pri":"P1","svc":"POIE quality_alert"},
    {"id":170,"cat":"下单体验","q":"哪些售后可修改信息提前避免？","loop":"B","cov":"partial","pri":"P1","svc":"review_nlp prevention"},

    # ── 171-180: 连锁总部治理 ──
    {"id":171,"cat":"总部治理","q":"总部要求20家店做了几家？","loop":"C","cov":"partial","pri":"P1","svc":"matrix_agents execution_tracking"},
    {"id":172,"cat":"总部治理","q":"哪些店总拖延经营任务？","loop":"A","cov":"partial","pri":"P1","svc":"matrix_agents task_compliance"},
    {"id":173,"cat":"总部治理","q":"哪些店反复犯同一种错？","loop":"A","cov":"partial","pri":"P1","svc":"strategy_memory pattern_detection"},
    {"id":174,"cat":"总部治理","q":"哪些店适合新策略试验？","loop":"B","cov":"partial","pri":"P2","svc":"matrix_agents ab_testing"},
    {"id":175,"cat":"总部治理","q":"统一策略哪些门店例外？","loop":"B","cov":"partial","pri":"P2","svc":"matrix_agents store_overrides"},
    {"id":176,"cat":"总部治理","q":"哪些店数据质量差不该AI决策？","loop":"A","cov":"partial","pri":"P1","svc":"MOS data_quality_check"},
    {"id":177,"cat":"总部治理","q":"哪些店长经常拒绝AI建议？","loop":"A","cov":"partial","pri":"P2","svc":"adoption_tracking"},
    {"id":178,"cat":"总部治理","q":"同策略不同店差异来自哪？","loop":"A","cov":"partial","pri":"P1","svc":"strategy_memory attribution_analysis"},
    {"id":179,"cat":"总部治理","q":"成功经验值得升级为SOP？","loop":"B","cov":"partial","pri":"P2","svc":"strategy_memory sop_promotion"},
    {"id":180,"cat":"总部治理","q":"新策略从2家安全灰度到100家？","loop":"B","cov":"partial","pri":"P2","svc":"matrix_agents rollout"},

    # ── 181-190: AI治理 ──
    {"id":181,"cat":"AI治理","q":"为什么昨天没提醒我？","loop":"A","cov":"covered","pri":"P0","svc":"action_trace.explain"},
    {"id":182,"cat":"AI治理","q":"为什么A比B更重要？","loop":"A","cov":"covered","pri":"P0","svc":"priority_arbiter.explain"},
    {"id":183,"cat":"AI治理","q":"用了哪些数据缺哪些？","loop":"A","cov":"covered","pri":"P0","svc":"data_provenance"},
    {"id":184,"cat":"AI治理","q":"这个结论多大把握？","loop":"A","cov":"covered","pri":"P0","svc":"confidence_display"},
    {"id":185,"cat":"AI治理","q":"什么都不做最坏损失多少？","loop":"A","cov":"covered","pri":"P0","svc":"impact_forecast"},
    {"id":186,"cat":"AI治理","q":"AI做错了能快速撤销？","loop":"B","cov":"covered","pri":"P0","svc":"execution_plan.rollback"},
    {"id":187,"cat":"AI治理","q":"哪些动作可以交给AI？","loop":"B","cov":"covered","pri":"P0","svc":"execution_policy trust_level"},
    {"id":188,"cat":"AI治理","q":"哪些必须老板批准？","loop":"B","cov":"covered","pri":"P0","svc":"execution_policy ASK_APPROVAL"},
    {"id":189,"cat":"AI治理","q":"不同角色给AI什么权限？","loop":"B","cov":"covered","pri":"P1","svc":"execution_policy roles"},
    {"id":190,"cat":"AI治理","q":"旧数据/缺失数据做出不可靠判断？","loop":"A","cov":"partial","pri":"P0","svc":"data_quality_alert"},

    # ── 191-200: 实验策略有效期 ──
    {"id":191,"cat":"策略有效期","q":"这周最多干3件事哪3件？","loop":"B","cov":"covered","pri":"P0","svc":"priority_arbiter top3"},
    {"id":192,"cat":"策略有效期","q":"哪些问题该观察不该现在动？","loop":"A","cov":"covered","pri":"P0","svc":"POIE OBSERVE mode"},
    {"id":193,"cat":"策略有效期","q":"两个方案先测试哪个？","loop":"B","cov":"partial","pri":"P1","svc":"experiment_design"},
    {"id":194,"cat":"策略有效期","q":"能同时改价格主图活动吗？","loop":"B","cov":"covered","pri":"P0","svc":"single_variable_constraint"},
    {"id":195,"cat":"策略有效期","q":"实验很差什么时候止损？","loop":"B","cov":"covered","pri":"P0","svc":"stop_conditions"},
    {"id":196,"cat":"策略有效期","q":"短期下降什么时候值得继续？","loop":"A","cov":"partial","pri":"P1","svc":"patience_rule"},
    {"id":197,"cat":"策略有效期","q":"有效是真有效还是天气/补贴干扰？","loop":"A","cov":"partial","pri":"P0","svc":"confound_check"},
    {"id":198,"cat":"策略有效期","q":"经验只适用这家还是同类门店？","loop":"B","cov":"partial","pri":"P1","svc":"strategy_memory generalization"},
    {"id":199,"cat":"策略有效期","q":"哪些Strategy Memory已过时该失效？","loop":"A","cov":"covered","pri":"P0","svc":""},
    {"id":200,"cat":"策略有效期","q":"下月最值得验证的假设是什么？","loop":"B","cov":"partial","pri":"P2","svc":"hypothesis_generation"},
]


_FAMILY_CAT = {
    "profit": "利润真相",
    "campaign": "活动决策",
    "ads": "投流诊断",
    "product": "商品优化",
    "order": "订单归因",
    "review": "评价闭环",
    "crm": "顾客CRM",
    "competition": "竞品分析",
    "fulfillment": "履约产能",
    "chain": "连锁",
}

# 101-200 中被写坏的问句；1-100 以经营契约 catalog 为准。
_RESTORE = {
    101: ("财务对账", "平台结算和我自己算的利润对得上吗？", "A"),
    104: ("财务对账", "活动补贴成本和预期一致吗？", "A"),
    106: ("财务对账", "推广花费和平台账单对得上吗？", "A"),
    114: ("规则合规", "商品名/描述会不会违规下架？", "B"),
    116: ("规则合规", "经营资质和公示信息缺了会不会被罚？", "B"),
    119: ("规则合规", "商品图、价格、描述是否完整一致？", "A"),
    131: ("排班人效", "一周里忙闲差这么大，排班该怎么调？", "C"),
    133: ("排班人效", "人效低是人多了还是单少了？", "A"),
    134: ("排班人效", "高峰缺人、低谷闲人，怎么按天排？", "C"),
    137: ("排班人效", "该固定班还是按历史单量排？", "B"),
    139: ("排班人效", "缺人时先保出餐还是先保打包？", "C"),
    140: ("排班人效", "人效目标定多少才合理？", "B"),
    141: ("SKU生命周期", "哪些SKU可以共用食材降低损耗？", "B"),
    143: ("SKU生命周期", "哪些商品份量不稳定、损耗高？", "C"),
    145: ("SKU生命周期", "新品是不是在抢老品的订单？", "A"),
    164: ("下单体验", "远距离送达是不是把口味做差了？", "A"),
    166: ("下单体验", "包装问题反复出现，该不该升级包装？", "B"),
}

_SVC_FILL = {
    83: "ops_diagnosis.diagnose_device_health",
    84: "ops_diagnosis.diagnose_fulfillment",
    85: "ops_diagnosis.diagnose_fulfillment",
    86: "ops_diagnosis.diagnose_fulfillment",
    87: "ops_diagnosis.diagnose_fulfillment",
    88: "ops_diagnosis.diagnose_fulfillment",
    89: "ops_diagnosis.diagnose_fulfillment",
    101: "ops_diagnosis.diagnose_financial_reconciliation",
    102: "ops_diagnosis.diagnose_settlement_detail",
    103: "ops_diagnosis.diagnose_settlement_detail",
    104: "ops_diagnosis.diagnose_financial_reconciliation",
    105: "ops_diagnosis.diagnose_settlement_detail",
    106: "ops_diagnosis.diagnose_financial_reconciliation",
    107: "ops_diagnosis.diagnose_settlement_detail",
    108: "ops_diagnosis.diagnose_settlement_detail",
    109: "ops_diagnosis.diagnose_settlement_detail",
    110: "ops_diagnosis.diagnose_settlement_detail",
    111: "platform_intel + compliance_check",
    112: "compliance_check",
    113: "compliance_check",
    114: "compliance_check",
    115: "compliance_check",
    116: "compliance_check",
    117: "compliance_check",
    118: "execution_pack appeal",
    119: "compliance_check",
    120: "compliance_check",
    125: "ops_diagnosis.diagnose_new_store_setup",
    126: "ops_diagnosis.diagnose_new_store_setup",
    131: "ops_diagnosis.diagnose_fulfillment",
    132: "ops_diagnosis.diagnose_staffing",
    133: "ops_diagnosis.diagnose_staffing",
    134: "ops_diagnosis.diagnose_staffing",
    135: "ops_diagnosis.diagnose_staffing",
    137: "ops_diagnosis.diagnose_fulfillment",
    138: "ops_diagnosis.diagnose_staffing",
    139: "ops_diagnosis.diagnose_staffing",
    140: "ops_diagnosis.diagnose_staffing",
    141: "ops_diagnosis.diagnose_sku_lifecycle",
    142: "ops_diagnosis.diagnose_sku_strategy",
    143: "ops_diagnosis.diagnose_sku_lifecycle",
    144: "ops_diagnosis.diagnose_sku_strategy",
    145: "ops_diagnosis.diagnose_sku_lifecycle",
    146: "ops_diagnosis.diagnose_sku_strategy",
    148: "ops_diagnosis.diagnose_sku_strategy",
    152: "ops_diagnosis.diagnose_content_health",
    157: "ops_diagnosis.diagnose_content_health",
    158: "ops_diagnosis.diagnose_content_health",
    159: "ops_diagnosis.diagnose_content_health",
    161: "ops_diagnosis.diagnose_order_detail",
    162: "ops_diagnosis.diagnose_order_detail",
    163: "ops_diagnosis.diagnose_order_detail",
    164: "ops_diagnosis.diagnose_order_experience",
    165: "ops_diagnosis.diagnose_order_detail",
    166: "ops_diagnosis.diagnose_order_experience",
    168: "ops_diagnosis.diagnose_order_detail",
    199: "memory_lifecycle",
}


def _garbled(text: str) -> bool:
    return not (text or "").strip() or any(ord(ch) < 32 for ch in text)


def _normalize_demands() -> None:
    from app.services.operating_demands.catalog import by_id

    for d in DEMANDS:
        if 1 <= d["id"] <= 100:
            item = by_id(d["id"])
            d["q"] = item.question
            d["loop"] = item.loop
            if _garbled(str(d.get("cat") or "")):
                d["cat"] = _FAMILY_CAT.get(item.family, item.family)
        restored = _RESTORE.get(d["id"])
        if restored and _garbled(str(d.get("q") or "")):
            d["cat"], d["q"], d["loop"] = restored
        if not str(d.get("svc") or "").strip():
            d["svc"] = _SVC_FILL.get(d["id"], "")


_normalize_demands()


def seed_demands(db: Session) -> int:
    """初始化/更新 200 个需求到数据库。已存在的行按基准表回写问句与覆盖口径。"""
    existing = {row.demand_id: row for row in db.execute(select(OperatingDemand)).scalars()}
    written = 0
    for d in DEMANDS:
        fields = dict(
            category=d["cat"],
            question=d["q"],
            loop_type=d["loop"],
            coverage_status=d["cov"],
            priority=d["pri"],
            service_module=d.get("svc", ""),
        )
        row = existing.get(d["id"])
        if row is None:
            db.add(OperatingDemand(demand_id=d["id"], **fields))
            written += 1
            continue
        changed = False
        for key, value in fields.items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed = True
        if changed:
            written += 1
    if written:
        db.commit()
    return written


def benchmark_report(db: Session) -> dict[str, Any]:
    """生成覆盖率报告。"""
    all_demands = list(db.execute(select(OperatingDemand)).scalars())
    if not all_demands:
        seed_demands(db)
        all_demands = list(db.execute(select(OperatingDemand)).scalars())

    total = len(all_demands)
    covered = sum(1 for d in all_demands if d.coverage_status == "covered")
    partial = sum(1 for d in all_demands if d.coverage_status == "partial")
    not_covered = sum(1 for d in all_demands if d.coverage_status == "not_covered")

    by_category: dict[str, dict[str, int]] = {}
    for d in all_demands:
        cat = d.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "covered": 0, "partial": 0, "not_covered": 0}
        by_category[cat]["total"] += 1
        by_category[cat][d.coverage_status] += 1

    by_loop: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for d in all_demands:
        by_loop[d.loop_type] = by_loop.get(d.loop_type, 0) + 1

    by_priority: dict[str, int] = {}
    for d in all_demands:
        by_priority[d.priority] = by_priority.get(d.priority, 0) + 1

    # P0 覆盖率
    p0_demands = [d for d in all_demands if d.priority == "P0"]
    p0_covered = sum(1 for d in p0_demands if d.coverage_status in ("covered", "partial"))

    return {
        "total_demands": total,
        "covered": covered,
        "partial": partial,
        "not_covered": not_covered,
        "coverage_pct": round((covered + partial * 0.5) / total * 100, 1) if total else 0,
        "p0_total": len(p0_demands),
        "p0_covered_or_partial": p0_covered,
        "p0_coverage_pct": round(p0_covered / len(p0_demands) * 100, 1) if p0_demands else 0,
        "by_category": by_category,
        "by_loop_type": by_loop,
        "by_priority": by_priority,
    }


def get_demands_by_status(db: Session, status: str, limit: int = 50) -> list[dict[str, Any]]:
    """按覆盖率状态查需求。"""
    rows = list(
        db.execute(
            select(OperatingDemand)
            .where(OperatingDemand.coverage_status == status)
            .order_by(OperatingDemand.demand_id)
            .limit(limit)
        ).scalars()
    )
    return [
        {
            "demand_id": r.demand_id,
            "category": r.category,
            "question": r.question,
            "loop_type": r.loop_type,
            "priority": r.priority,
            "service_module": r.service_module,
        }
        for r in rows
    ]
