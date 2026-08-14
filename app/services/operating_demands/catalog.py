"""MealKey Operating Demand Library：100 条经营契约，不是 100 个功能。"""

from __future__ import annotations

from app.services.operating_demands.models import OperatingDemand

# 字段：id|code|question|loop|coverage|family|keywords|playbook|actions|forbidden_actions|forbidden_diagnosis|execution|metric|hours|truth|blockers|guardrail
_ROWS = r"""
1|STORE_LOSS|今天到底哪家店在亏钱？|A|green|profit|哪家店,亏钱,哪家在亏|store_pnl|标记亏损店并解释主因|立即关店|怪天气|AUTO|store_pnl|24|order_pnl,store_cost||
2|PROFIT_DROP|昨天利润为什么突然掉了？|A|green|profit|利润为什么,利润掉了,利润突然|profit,activity,ads,refund,cost|解释利润波动并给出止损动作|先加大补贴|怪天气|AUTO|profit|24|order_pnl,promo_cost,ad_spend||
3|UNIT_PROFIT|我每卖一单到底赚多少钱？|A|green|profit|每卖一单,一单赚,单均利润|unit_profit|给出单均到手利润|先冲单量|只看营业额|AUTO|unit_profit|24|order_pnl||
4|SKU_PROFIT|哪些 SKU 真赚钱，哪些越卖越亏？|A|green|profit|sku真赚钱,越卖越亏,哪些sku|sku_pnl|暂停或限量亏损SKU|立刻全线下架|只看销量|AUTO|sku_pnl|48|sku_cost,sku_orders||
5|CAMPAIGN_EATS_PROFIT|是哪个活动把利润吃掉了？|A|green|profit|哪个活动,活动把利润,活动吃掉|activity,profit|退出或改叠加规则|再报一个更大的活动|怪平台抽成|AUTO|promo_profit|48|promo_cost,order_pnl||
6|AD_ORDER_PROFIT|投流之后这些订单到底还有没有利润？|A|green|profit|投流之后,广告订单利润,投流利润|ads,unit_profit|保留赚钱投放、砍亏损投放|预算加倍|投了就一定赚钱|AUTO|paid_order_profit|48|ad_spend,order_pnl||
7|TAKEHOME_DROP|为什么最近到手率下降？|A|green|profit|到手率下降,到手率|takehome,activity,cost,ads|找出到手率下降主因|先降价冲量|只怪抽成|AUTO|take_home_rate|48|order_pnl,promo_cost||
8|REFUND_PROFIT|退款、赔付一共吃掉了多少利润？|A|yellow|profit|退款赔付,赔付吃掉,退款一共|refund,profit|量化退款赔付并分流处理|一律拒赔|都是恶意顾客|AUTO|refund_cost|48|refund_amount,payout_amount|refund_ledger|
9|COST_SHOCK|食材、包装成本变化对利润影响多少？|A|green|profit|食材成本,包装成本,成本变化对利润|cost,profit|量化成本冲击并给调价/换料建议|立刻全线涨价|忽略成本|AUTO|cost_impact|72|ingredient_cost,pack_cost||
10|MONTH_TARGET|按现在趋势，这个月利润目标还能完成吗？|A|green|profit|利润目标,这个月还能完成,目标还能|forecast,profit|给出完成概率与缺口动作|不管利润先冲量|目标一定能完成|AUTO|profit_forecast|168|order_pnl,goal||
11|JOIN_CAMPAIGN|这个平台活动我到底参不参加？|B|green|campaign|参不参加,要不要参加活动,报不报活动,官方活动,平台政策,最近活动,促销活动,有什么活动,最新政策|campaign_stack,unit_profit,new_repeat|给出参加/拒绝建议|无账就报名|活动一定能带来利润|ASK_APPROVAL|campaign_profit|72|promo_rules,unit_cost,current_coupons||利润门禁不通过不得参加
12|STACK_LOSS|这个活动和现有券叠加后会不会亏？|A|green|campaign|叠加后,会不会亏,券叠加|campaign_stack,unit_profit|算出叠加后到手价与单均利润|继续叠加|平台会补足差额|AUTO|stacked_profit|24|promo_rules,coupons,unit_cost||
13|SAFE_TAKEHOME|这个商品最低安全到手价是多少？|B|green|campaign|最低安全,安全到手价,到手价是多少|price_floor,unit_profit|给出安全到手价|先按活动价卖|可以卖亏获客|ASK_APPROVAL|safe_takehome|24|unit_cost,fee_rate||不得低于安全到手价
14|WHERE_TO_JOIN|哪些店、哪些商品、哪个时段参加最划算？|B|green|campaign|哪些店参加,哪个时段参加,哪些商品参加|store_diff,daypart,sku_pnl|按店/SKU/时段给出参加清单|全店全时段参加|所有店一套打法|ASK_APPROVAL|campaign_roi|48|store_pnl,sku_pnl,daypart||
15|RENEW_CAMPAIGN|这个活动快结束了，要不要续？|B|green|campaign|要不要续,活动快结束,续不续|campaign_effect,unit_profit|根据3天效果决定续/停/改|默认续上|没效果也要续|ASK_APPROVAL|campaign_effect|72|campaign_result||
16|PRICE_CHANGE|这个商品该不该涨价/降价，改多少？|B|yellow|campaign|该不该涨价,该不该降价,改多少价|price_elasticity,unit_profit,cvr|给出调价幅度建议|大幅降价|降价一定能涨单|ASK_APPROVAL|price_delta|72|unit_cost,cvr,orders|price_writeback|CVR不得下降>5%
17|RAISE_AOV|怎么把碗均价/客单提高但尽量不掉单？|B|green|campaign|碗均价,客单提高,提高客单|aov,bundle,menu|用套餐/加价购提客单|直接涨价|客单涨了订单一定掉|ASK_APPROVAL|aov|72|aov,orders,bundle||订单不得下降>8%
18|BEST_BUNDLE|什么套餐组合最适合现在卖？|B|green|campaign|什么套餐,套餐组合,最适合现在卖|bundle,sku_pnl,aov|给出当前最优套餐组合|堆最低价套餐|套餐越多越好|ASK_APPROVAL|bundle_profit|72|sku_cost,sku_orders||
19|LIMIT_TRAFFIC_SKU|低价引流品该不该限量、降位置？|B|green|campaign|低价引流,限量,降位置|traffic_sku,unit_profit,ctr|限量或降位置保护利润|继续主推亏损引流品|引流品必须一直置顶|ASK_APPROVAL|traffic_sku_pnl|48|sku_pnl,impressions||
20|CAMPAIGN_EFFECT|三天前参加的活动到底有没有效果？|A|green|campaign|三天前,活动有没有效果,活动效果|campaign_effect,profit,orders|回来核对活动结果|没看结果就再报|有单就等于有效果|AUTO|campaign_result|72|campaign_result,order_pnl||
21|ADS_ROI|今天推广花的钱赚回来了吗？|A|green|ads|推广花的钱,赚回来了吗,今天推广|ads_roi|给出当日推广回收结论|预算加倍|花了就一定能回本|AUTO|ads_roi|24|ad_spend,paid_orders,unit_profit||
22|BUDGET_UP_DOWN|今天广告预算该加还是该减？|B|yellow|ads|预算该加,预算该减,广告预算|ads_roi,budget_pace|给出加减预算建议|无账加预算|ROI好就无限加|ASK_APPROVAL|ads_roi|24|ad_spend,ads_roi|ads_api,ads_writeback|
23|BUDGET_BURN|预算会不会午高峰前就烧完？|B|yellow|ads|烧完,午高峰前,预算会不会|budget_pace,daypart|预警并建议控速|放任烧完|预算平均花就行|ASK_APPROVAL|budget_pace|8|hourly_spend|ads_api,ads_writeback|
24|SHIFT_DAYPART|钱应该从下午移到午餐时段吗？|B|yellow|ads|移到午餐,下午移到,时段预算|daypart,ads_roi|建议时段挪预算|平均分配|下午和午餐一样值|ASK_APPROVAL|daypart_roi|24|hourly_spend,hourly_orders|ads_api,ads_writeback|
25|SCALE_WINNER|ROI很好但预算没花出去，要不要放量？|B|yellow|ads|放量,预算没花,ROI很好|ads_roi,budget_pace|建议有上限放量|无上限放量|ROI好就不会变差|ASK_APPROVAL|ads_roi|24|ads_roi,budget_pace|ads_api,ads_writeback|利润门禁
26|CUT_LOSER|ROI已经很差了，应该减多少预算？|B|yellow|ads|ROI很差,减多少预算,应该减|ads_roi|按亏损幅度减预算|继续投放等反弹|再投就会好|ASK_APPROVAL|ads_roi|24|ads_roi,ad_spend|ads_api,ads_writeback|
27|PAID_CVR_DROP|付费流量转化突然下降是什么原因？|A|green|ads|付费流量,转化突然下降,付费转化|paid_cvr,landing,price,review|诊断付费转化下降|加预算硬冲|一定是平台限流|AUTO|paid_cvr|24|paid_cvr,landing_ctr||
28|ORGANIC_VS_PAID|今天订单增长到底来自自然流量还是广告？|A|green|ads|自然流量还是,广告还是自然,订单增长来自|organic_vs_paid|拆开自然/付费贡献|把增长都算广告功|分不清也先加广告|AUTO|order_source|24|organic_orders,paid_orders||
29|SEARCH_RANK|搜索曝光/关键词排名掉了怎么办？|B|yellow|ads|搜索曝光,关键词排名,排名掉了|search_rank,title,image,activity|先查标题主图活动再决定是否买词|立刻买词冲排名|一定是被限流|ASK_APPROVAL|search_rank|48|search_rank,impressions|search_rank_api|
30|CROSS_PLATFORM_BUDGET|多个平台的广告预算应该怎么分？|B|yellow|ads|多个平台,预算怎么分,广告预算分|cross_platform,ads_roi|按利润贡献分预算|平均分给各平台|哪个平台大就投哪个|ASK_APPROVAL|platform_roi|24|platform_ad_spend,platform_pnl|ads_api,multi_platform|
31|HERO_CTR_DROP|招牌商品 CTR 为什么突然掉了？|A|green|product|招牌,CTR为什么,ctr掉了|ctr,image,title,competition|诊断招牌点击竞争力|立刻降价|平台限流|AUTO|ctr|48|hero_ctr,impressions||
32|CHANGE_IMAGE|主图该不该换，应该换成什么？|B|green|product|主图该不该换,换成什么,换主图|ctr,image|给出换图方案并观察CTR|先降价|换图一定立刻涨单|ASK_APPROVAL|ctr|48|hero_ctr,image_asset||CVR不得下降>5%
33|CHANGE_TITLE|商品标题怎么改更容易被点？|B|green|product|标题怎么改,更容易被点,改标题|ctr,title|给出标题方案并写回观察|堆砌关键词|越长越好|ASK_APPROVAL|ctr|48|hero_ctr,title||
34|CHANGE_DESC|商品描述怎么改更容易转化？|B|green|product|描述怎么改,更容易转化,改描述|cvr,description|给出描述方案|只改文案不管价格|描述决定一切|ASK_APPROVAL|cvr|48|cvr,description||
35|FIRST_SCREEN|首页第一屏应该摆哪些商品？|B|green|product|第一屏,首页摆,首屏|first_screen,ctr,sku_pnl|重排首屏并观察进店|把最便宜的全放第一屏|销量高就该置顶|ASK_APPROVAL|entry_ctr|48|menu_rank,sku_pnl,ctr||
36|MENU_STRUCTURE|菜单结构是不是有问题？|B|green|product|菜单结构,菜单有问题|menu_structure,aov,cvr|诊断菜单结构并给调整|大改菜单|菜越多越好|ASK_APPROVAL|cvr|72|menu,cvr,aov||
37|ZOMBIE_SKU|哪些僵尸 SKU 应该暂停/删除？|B|yellow|product|僵尸,暂停删除,滞销sku|zombie_sku|暂停无流量无利润SKU|全删以免后患|留下来总会有人点|ASK_APPROVAL|zombie_count|72|sku_orders,impressions|menu_writeback|
38|SOLD_OUT|爆款售罄了，现在该补货还是换主推？|C|yellow|product|售罄,补货还是,换主推|sold_out,capacity,ctr|派单补货或切换主推|放空直到明天|售罄可以制造稀缺|HUMAN_TASK|hero_orders|24|inventory,hero_orders|inventory_signal|
39|NEW_SKU_STALL|新品上线以后为什么没跑起来？|A|green|product|新品,没跑起来,上线以后|new_sku,ctr,cvr,position|诊断新品曝光/点击/转化|立刻降价|新品需要时间自然起量|AUTO|new_sku_orders|72|new_sku_funnel||
40|GENERATE_IMAGE|给真实商品照片生成/选择更适合外卖的主图|B|green|product|生成主图,适合外卖,商品照片|image,ctr|选出或生成可上线主图|用网图假菜|越精修越好|ASK_APPROVAL|ctr|48|photo_asset,hero_ctr||
41|ORDER_DROP|为什么今天订单掉了？|A|green|order|订单掉了,怎么没单,没人下单,订单下降,今天没单|exposure,ctr,cvr,aov,activity,competition,review,fulfillment|按漏斗给出主因并行动|立即大幅降价|平台限流,怪天气|ASK_APPROVAL|orders|48|impressions,ctr,cvr,aov||CVR不得下降>5%
42|EXPOSURE_DROP|为什么曝光突然掉了？|A|green|order|曝光突然掉,为什么曝光,曝光掉了|exposure,activity,rank,ads|诊断曝光下降|立刻加预算|一定是限流|AUTO|impressions|24|impressions,rank,ad_spend||
43|ENTRY_CTR|为什么有人看到店却不点进来？|A|green|order|不点进来,看到店却,进店点击|ctr,image,title,first_screen|诊断进店点击|先降价|顾客口味变了|AUTO|entry_ctr|48|impressions,ctr||
44|CVR_DROP|为什么进店了但不下单？|A|green|order|不进店不下单,进店了但,不下单|cvr,price,review,bundle|诊断进店转化|先砸广告|进来的人都是随便看看|AUTO|cvr|48|cvr,rating,price||
45|AOV_DROP|为什么订单没掉但客单下降了？|A|green|order|客单下降,订单没掉,碗均价掉|aov,bundle,traffic_sku|诊断客单下降|再做一个更低价套餐|顾客更穷了|AUTO|aov|48|aov,orders,bundle||
46|NEW_CUSTOMER_DROP|为什么新客突然减少？|A|yellow|order|新客突然,新客减少|new_customer,activity,ads,rank|诊断新客下降|加大新客券|新客少是大盘问题|AUTO|new_customers|48|new_customers,campaign|crm_identity|
47|REPEAT_DROP|为什么老客复购突然下降？|A|yellow|order|老客复购,复购突然,老客不来|repeat,crm,review,quality|诊断复购下降|群发最大额券|老客喜新厌旧|AUTO|repeat_rate|72|repeat_orders,reviews|crm_identity|
48|LUNCH_FORECAST|午餐/晚餐今天大概会有多少订单，准备够吗？|A|yellow|order|大概会有多少,准备够吗,午餐晚餐今天|forecast,capacity|给出预测并核对产能|按昨天原样备|预测一定准|AUTO|forecast_orders|8|orders_history,capacity|capacity_signal|
49|EXTERNAL_VS_SELF|下降到底是天气/节假日/商圈，还是我们自己造成的？|A|green|order|天气还是,商圈还是,我们自己造成|market,exposure,ctr,cvr|先对照商圈再归因自身|先怪天气|一定是平台打压|AUTO|relative_orders|24|orders,market_orders,ctr||
50|NEXT_BEST|今天所有问题里，我现在只该做哪一件事？|B|green|order|只该做,现在最该,先做什么,最近生意,生意怎么了,今天只需要|priority,profit,orders,review,ads|只给出当前最该做的一件事|一次做二十件事|所有指标都要先看|ASK_APPROVAL|primary_metric|48|kpis,open_loops||
51|URGENT_REVIEWS|新差评来了，哪些需要马上处理？|A|green|review|新差评,马上处理,差评来了,看看评价,差评,处理评价|review_urgency,sla|排出立刻处理的差评|每条都先道歉赔钱|差评都会过去|AUTO|open_bad_reviews|24|reviews||
52|REVIEW_ATTRIBUTION|这个差评到底是产品、门店、骑手还是顾客问题？|A|green|review|差评到底是,产品门店骑手,责任判断|review_attr|给出责任归属|先怪骑手|都是顾客太严|AUTO|review_attr|24|review_text,order,delivery||
53|REVIEW_REPLY|这条评价应该怎么回复？|A|green|review|应该怎么回复,评价怎么回,这条评价|review_reply|生成可发送回复|套模板敷衍|回复越长越好|AUTO|reply_sent|24|review_text||
54|AUTO_REPLY_ORDINARY|普通评价能不能直接自动回复？|B|yellow|review|普通评价,自动回复,好评自动|ordinary_reply|按权限自动回复普通评价|差评也自动回|全部自动最省事|ASK_APPROVAL|ordinary_replied|24|reviews,permissions|review_writeback|
55|ESCALATE_COMPLAINT|严重投诉应该马上找谁处理？|C|green|review|严重投诉,马上找谁,投诉升级|complaint_escalation|派给店长/客服并催办|先赔钱了事|严重投诉可以先放着|HUMAN_TASK|complaint_sla|4|complaint||
56|MALICIOUS_REFUND|这是正常退款还是恶意骗赔？|A|yellow|review|恶意骗赔,正常退款还是,恶意退款|refund_risk|给出骗赔风险判断|一律拒赔|一律先赔|AUTO|refund_risk|24|refund_history,order,evidence|refund_signal|
57|APPEAL_PACK|能不能自动整理申诉证据并提交？|B|yellow|review|申诉证据,整理申诉,提交申诉|appeal_pack|打包证据并提交申诉|无证据硬申|申诉一定能赢|ASK_APPROVAL|appeal_submitted|48|photos,ticket,chat,order|appeal_writeback|
58|COMPENSATE|这个顾客要不要赔、赔多少？|B|yellow|review|要不要赔,赔多少|compensate,profit|给出赔付建议|高额安抚|不赔才有原则|ASK_APPROVAL|compensate_amount|24|order_pnl,complaint|compensate_policy|单笔赔付须老板确认
59|SLA_24H|哪些投诉马上要超过24小时 SLA？|A|green|review|24小时,超过sla,马上要超时|sla|列出即将超时工单|按进线顺序慢慢回|超时没关系|AUTO|sla_breach|4|complaint_age||
60|REPEAT_ROOT_CAUSE|最近差评重复出现的根因是什么，应该改什么？|A|green|review|差评重复,根因是什么,重复出现|review_theme,fulfillment|找出重复根因并改流程|只回复不改|都是个例|AUTO|repeat_theme|72|review_themes||
61|HIGH_VALUE|谁是我的高价值顾客？|A|yellow|crm|高价值顾客,谁是高价值|customer_value|列出高价值顾客|给所有人最大券|消费一次高就是高价值|AUTO|high_value_count|168|customer_orders|crm_identity|
62|SLEEPING|哪些老顾客正在沉睡？|A|yellow|crm|沉睡,老顾客正在,沉睡顾客|sleeping|列出沉睡老客|群发最大额券|沉睡就是流失定了|AUTO|sleeping_count|168|customer_orders|crm_identity|
63|SECOND_ORDER|新客怎么提高第二次下单率？|B|yellow|crm|第二次下单,新客怎么提高|second_order|给出二次下单动作|首单再降价|新客券越大越好|ASK_APPROVAL|second_order_rate|168|new_customers,second_orders|crm_identity|
64|HIGH_FREQ_BENEFIT|高频顾客该给什么权益？|B|yellow|crm|高频顾客,该给什么权益|high_freq_benefit|按利润给权益|一律免费|权益越多越忠诚|ASK_APPROVAL|repeat_rate|168|customer_orders,unit_profit|crm_identity|利润门禁
65|CHURN_RISK|哪些顾客最可能流失？|A|yellow|crm|最可能流失,流失顾客|churn_risk|列出流失风险名单|等他们投诉再挽回|流失不可预测|AUTO|churn_risk|168|customer_orders,reviews|crm_identity|
66|SEGMENT_COUPON|不同人群应该发什么券？|B|yellow|crm|不同人群,发什么券|segment_coupon,unit_profit|按人群发不同券|全场同一张券|发券一定能召回|ASK_APPROVAL|coupon_roi|72|segments,unit_profit|crm_identity|不得发到亏
67|RECALL_WHO|现在应该召回哪批顾客？|B|yellow|crm|召回哪批,应该召回|recall_who,profit|选出本次召回名单|全量召回|召回越多越好|ASK_APPROVAL|recall_roi|72|sleeping,unit_profit|crm_identity|
68|RECALL_EFFECT|上次召回到底有没有效果？|A|yellow|crm|上次召回,召回有没有效果|recall_effect|核对召回结果|没看结果再发一轮|有打开就有效|AUTO|recall_result|168|recall_campaign|crm_identity|
69|COMPLAINT_REPAIR|投诉过的顾客该怎么修复关系？|B|yellow|crm|投诉过的,修复关系|complaint_repair|一对一修复方案|发最大额券了事|投诉过就放弃|ASK_APPROVAL|repair_rate|72|complaint_customers|crm_identity|
70|LTV|不同顾客大概能贡献多少长期价值？|A|yellow|crm|长期价值,ltv,贡献多少|ltv|给出分群LTV|按一次消费判断|LTV可以精确到人|AUTO|ltv|168|customer_orders|crm_identity|
71|TRUE_RIVALS|谁才是这家店真正的竞争对手？|A|yellow|competition|真正的竞争,竞争对手是谁,谁才是|true_rivals|标出真正对手|把附近所有店当对手|品类相同就是对手|AUTO|rival_set|72|competitor_snapshots|competitor_snapshots|
72|RANK_MOVE|我的搜索/商圈排名升了还是掉了？|A|yellow|competition|商圈排名,搜索排名升了,排名掉了|rank_move|给出排名变化|立刻买词|排名掉了就是被打压|AUTO|rank|24|search_rank,area_rank|competitor_snapshots|
73|RIVAL_PRICE|哪个竞争对手刚改价格？|A|yellow|competition|刚改价格,对手改价,竞争对手刚|rival_price|列出对手价格变化|马上跟价|对手改价我们必须跟|AUTO|rival_price|24|competitor_prices|competitor_snapshots|
74|RIVAL_PROMO|哪个竞争对手刚开始/结束大促？|A|yellow|competition|对手大促,开始结束大促,竞争对手刚开始|rival_promo|列出对手活动变化|无账跟活动|大促必须对冲|AUTO|rival_promo|24|competitor_promos|competitor_snapshots|
75|RIVAL_HERO|竞争对手换了什么爆品、主图或套餐？|A|yellow|competition|对手换了,爆品主图套餐,竞争对手换|rival_hero|列出对手内容变化|照抄对手主图|对手换了我们也必须换|AUTO|rival_content|48|competitor_menu|competitor_snapshots|
76|RIVAL_SPIKE|为什么这家竞争店最近突然跑起来了？|A|yellow|competition|竞争店突然,突然跑起来,为什么这家竞争|rival_spike,price,promo,content,efficiency|归因对手上升|直接跟价|一定是平台扶持|AUTO|rival_orders|48|competitor_snapshots,promo,rank|competitor_snapshots|
77|PRICE_GAP|商圈里有没有空缺价格带？|A|yellow|competition|空缺价格带,价格带|price_gap|标出空缺价格带|做最低价填空|空价格带就该去占|AUTO|price_gap|72|market_prices,unit_cost|competitor_snapshots|利润门禁
78|PRODUCT_GAP|商圈里有没有还没人满足的产品机会？|A|yellow|competition|产品机会,还没人满足|product_gap|标出产品空位|看到缺口就上新|有缺口就有利润|AUTO|product_gap|72|market_menu,own_menu|competitor_snapshots|
79|FOLLOW_PRICE|对手降价了，我们到底要不要跟？|B|yellow|competition|要不要跟,对手降价,跟不跟价|profit_gate,unit_profit,rival_price|过利润门禁后再决定|立即跟价|不跟就会没单|ASK_APPROVAL|unit_profit|48|unit_cost,rival_price,cvr|competitor_snapshots|利润门禁不通过不得跟价
80|TOP3_PATH|我要进商圈 Top3，接下来具体怎么走？|B|yellow|competition|进商圈,top3,前三怎么走|rank,ctr,cvr,profit|给出分步路径|为冲排名先亏着|广告砸够就能进前三|ASK_APPROVAL|area_rank|168|rank,profit,ctr|competitor_snapshots|
81|WRONG_HOURS|店是不是异常关店/营业时间设置错了？|B|yellow|fulfillment|异常关店,营业时间,设置错了|hours,orders|核对营业时间并纠正|先加广告|没单就是没需求|ASK_APPROVAL|open_hours|4|hours,orders|hours_readback|
82|RESTOCK_WHO|爆款售罄了，谁去补货？|C|yellow|fulfillment|谁去补货,售罄了谁|restock,sold_out|派给具体的人补货|等下一班再说|售罄不影响曝光|HUMAN_TASK|hero_stock|8|inventory,hero_orders|inventory_signal|
83|DEVICE_MISS|接单/打印/设备异常导致漏单怎么办？|B|yellow|fulfillment|漏单,打印,设备异常,接单|device,missed_order|诊断设备并给恢复步骤|先用手机硬抗|漏单可以补救|ASK_APPROVAL|missed_orders|4|device_status,orders|device_signal|
84|SLOW_COOK|为什么最近出餐越来越慢？|C|red|fulfillment|出餐越来越慢,出餐慢|cook_time,capacity,sku|找出慢出餐SKU/班次并派整改|先减少接单不查原因|一定是骑手太早到|HUMAN_TASK|cook_time|24|cook_time,shift|kitchen_evidence|
85|MERCHANT_CANCEL|为什么商责取消突然变高？|C|red|fulfillment|商责取消,取消突然变高|merchant_cancel,stock,hours,device|找出商责取消原因并派整改|先怪顾客|取消高就关活动|HUMAN_TASK|merchant_cancel_rate|24|cancel_reason|kitchen_evidence|
86|SPILL|为什么最近包装洒漏很多？|C|red|fulfillment|包装洒漏,洒漏很多|spill,packaging|按SKU派包装整改|换更便宜包装|都是骑手颠簸|HUMAN_TASK|spill_rate|24|spill_reviews,sku|kitchen_evidence|
87|WRONG_ITEM|为什么漏餐错餐频繁发生？|C|red|fulfillment|漏餐,错餐,漏餐错餐|wrong_item,pack_check|按班次SKU派核对整改|口头提醒一次|都是偶发|HUMAN_TASK|wrong_item_rate|24|wrong_item,shift,sku|kitchen_evidence|
88|CAPACITY_PEAK|午高峰是不是马上要爆产能？|C|red|fulfillment|爆产能,午高峰马上,产能|capacity_peak,forecast|预警并派备人备料|继续接单|高峰扛一扛就过去|HUMAN_TASK|capacity_util|2|orders_pace,capacity|capacity_signal|
89|MATERIALS|原料/包装物料是不是快不够了？|C|red|fulfillment|原料不够,物料,包装物料,快不够了|materials,inventory|预警并派采购|用完再买|缺料可以先用替代|HUMAN_TASK|stockout_risk|8|inventory|inventory_signal|
90|RECTIFY_EVIDENCE|昨天让门店整改的事做没做，有没有证据？|C|yellow|fulfillment|整改,做没做,有没有证据|rectify_evidence|催办并核验证据|相信口头回复|整改过就一定有效|HUMAN_TASK|task_done|24|task,evidence|task_evidence|
91|MULTI_PLATFORM_PROFIT|美团+淘宝闪购+京东加起来，我今天到底赚多少？|A|yellow|chain|加起来,今天到底赚,美团淘宝京东|multi_platform_pnl|合并多平台利润|只看一个平台GMV|流水加总就是利润|AUTO|total_profit|24|platform_pnl|multi_platform|
92|PRICE_CONFLICT|同一个商品不同平台价格/活动冲突了吗？|B|yellow|chain|价格冲突,不同平台价格,活动冲突|price_conflict|列出冲突并给对齐建议|各平台各自最低|冲突没关系|ASK_APPROVAL|price_gap|24|platform_prices,promos|multi_platform|
93|PLATFORM_TILT|今天流量和预算应该往哪个平台倾斜？|B|yellow|chain|往哪个平台,预算倾斜,流量倾斜|platform_tilt,ads_roi,profit|按利润贡献倾斜|平均投放|单量大的平台优先|ASK_APPROVAL|platform_roi|24|platform_pnl,ads_roi|ads_api,multi_platform|
94|BEST_WORST_STORES|20家店里最好和最差的是哪几家？|A|green|chain|最好和最差,哪几家,20家店|store_rank|给出门店利润与问题排名|只看流水排名|最差店先关|AUTO|store_pnl|24|store_pnl||
95|STORE_PLAYBOOK|不同类型门店是不是应该用不同打法？|A|green|chain|不同类型门店,不同打法|store_type,playbook|按门店类型给打法|连锁必须统一活动|所有店一套券|AUTO|store_type_pnl|72|store_pnl,store_type||
96|COPY_STRATEGY|A店验证成功的策略能不能复制到类似门店？|B|green|chain|复制到,验证成功,类似门店|copy_strategy,memory|按相似度复制并设观察|强行全复制|成功一次就能规模化|ASK_APPROVAL|copy_lift|168|strategy_memory,store_similarity||
97|WEEK_CHANGE|这周最重要的经营变化是什么？|A|green|chain|这周最重要,经营变化,这周|week_change|只讲本周最重要变化|罗列全部指标|变化越多越全面|AUTO|week_delta|168|kpis||
98|MONTH_STRATEGY|这个月应该淘汰/强化哪些经营策略？|A|green|chain|淘汰,强化,经营策略|month_strategy,memory|根据结果强化或淘汰策略|凭感觉定下月|有效就永远有效|AUTO|strategy_keep|168|strategy_memory,results||
99|NEW_ONLINE_STORE|一个实体厨房要不要再开一个线上店/品牌？|B|yellow|chain|再开一个,线上店,新品牌|new_store,capacity,profit|评估产能与利润后再建议|先开了再说|多一个店就多一份流水|ASK_APPROVAL|new_store_profit|168|capacity,unit_profit|capacity_signal|
100|YEAR_CALENDAR|全年的营销节奏和季节策略应该怎么排？|B|yellow|chain|全年,营销节奏,季节策略|year_calendar,season|给出全年节奏草案|每周都做大促|节日必须最大折扣|ASK_APPROVAL|year_plan|720|seasonality,profit|seasonality|
"""


def _split(cell: str) -> tuple[str, ...]:
    cell = cell.strip()
    if not cell:
        return ()
    return tuple(part.strip() for part in cell.split(",") if part.strip())


def _parse_row(line: str) -> OperatingDemand:
    parts = line.split("|")
    if len(parts) != 17:
        raise ValueError(f"demand row field count {len(parts)}: {line[:80]}")
    (
        raw_id,
        code,
        question,
        loop,
        coverage,
        family,
        keywords,
        playbook,
        actions,
        forbidden_actions,
        forbidden_diagnosis,
        execution,
        metric,
        hours,
        truth,
        blockers,
        guardrail,
    ) = parts
    return OperatingDemand(
        id=int(raw_id),
        code=code,
        question=question,
        loop=loop,
        coverage=coverage,
        family=family,
        keywords=_split(keywords),
        playbook=_split(playbook),
        actions=_split(actions),
        forbidden_actions=_split(forbidden_actions),
        forbidden_diagnosis=_split(forbidden_diagnosis),
        execution=execution,
        metric=metric,
        window_hours=int(hours),
        truth=_split(truth),
        blockers=_split(blockers),
        guardrail=guardrail.strip(),
    )


DEMANDS: tuple[OperatingDemand, ...] = tuple(
    _parse_row(line) for line in _ROWS.strip().splitlines() if line.strip()
)

_BY_ID = {item.id: item for item in DEMANDS}
_BY_CODE = {item.code: item for item in DEMANDS}


def all_demands() -> tuple[OperatingDemand, ...]:
    return DEMANDS


def by_id(demand_id: int) -> OperatingDemand:
    return _BY_ID[demand_id]


def by_code(code: str) -> OperatingDemand:
    return _BY_CODE[code]


def coverage_counts() -> dict[str, int]:
    out = {"green": 0, "yellow": 0, "red": 0, "A": 0, "B": 0, "C": 0}
    for item in DEMANDS:
        out[item.coverage] += 1
        out[item.loop] += 1
    return out
