"""Operating Case Corpus — Source Whitelist V1（可执行登记）。

冻结：外部资料只能进 Case Library，不能直接进 Strategy Memory。
第一阶段只启用 phase=p0 的来源，禁止 50 个一起抓。
"""
from __future__ import annotations

from app.schemas.source_registry import SourceRegistryItem

P0_SOURCE_IDS = (
    "SRC-MT-COURSE-OPS",
    "SRC-MT-COURSE-DATA",
    "SRC-MT-COURSE-REVIEW",
    "SRC-MT-RULE-REVIEW",
    "SRC-MT-RESEARCH",
    "SRC-JD-OPEN",
    "SRC-DD-STORIES",
    "SRC-UE-OISHII",
    "SRC-DKD-KB",
    "SRC-BOOK-7STEPS",
    "SRC-TRD",
    "SRC-DKD-SEED",
)


def _s(
    no: int,
    source_id: str,
    *,
    publisher: str,
    title: str,
    url: str | None,
    source_type: str,
    authority: str,
    mode: str,
    focus: str,
    bias: str = "medium",
    copyright_mode: str = "platform_terms",
    rules: bool = False,
    prior: bool = True,
    training: bool = False,
    commercial: bool = False,
    research: bool = False,
    freq: str = "on_change",
    notes: tuple[str, ...] = (),
) -> SourceRegistryItem:
    p0 = source_id in P0_SOURCE_IDS
    return SourceRegistryItem(
        source_id=source_id,
        whitelist_no=no,
        publisher=publisher,
        title=title,
        canonical_url=url,
        source_type=source_type,  # type: ignore[arg-type]
        authority_level=authority,  # type: ignore[arg-type]
        ingestion_mode=mode,  # type: ignore[arg-type]
        commercial_bias=bias,  # type: ignore[arg-type]
        copyright_mode=copyright_mode,  # type: ignore[arg-type]
        allowed_for_rules=rules,
        allowed_for_case_prior=prior and not research,
        allowed_for_training=training,
        allowed_for_commercial_use=commercial,
        update_frequency=freq,  # type: ignore[arg-type]
        phase="p0" if p0 else "later",
        enabled=p0,
        research_zone=research,
        distill_focus=focus,
        notes=list(notes),
    )


WHITELIST: tuple[SourceRegistryItem, ...] = (
    _s(1, "SRC-MT-COURSE-OPS", publisher="美团", title="美团餐饮课堂：外卖经营系列课", url="https://xue.meituan.com/lesson/series/detail/8", source_type="course", authority="C2", mode="SEMI", focus="外卖运营方法、流量、促销、菜单、季节性、诊断框架"),
    _s(2, "SRC-MT-COURSE-HIT", publisher="美团", title="美团：70分钟教你打造外卖爆款", url="https://xue.meituan.com/lesson/detail/129", source_type="course", authority="C2", mode="SEMI", focus="六大产品体系、爆款/引流品、生命周期、选品"),
    _s(3, "SRC-MT-COURSE-18TIPS", publisher="美团", title="美团：外卖运营18个技巧", url="https://xue.meituan.com/lesson/detail/169", source_type="course", authority="C2", mode="SEMI", focus="搜索流量、营业时长、老客盘活、人效、视觉转化"),
    _s(4, "SRC-MT-COURSE-DATA", publisher="美团", title="美团：巧用数据指导餐厅高效运营", url="https://xue.meituan.com/lesson/detail/383", source_type="course", authority="C2", mode="SEMI", focus="客流、复购、生意贡献、利润问题如何由数据转成策略"),
    _s(5, "SRC-MT-COURSE-REVIEW", publisher="美团", title="美团：商户评价诚信管理官方课程", url="https://xue.meituan.com/lesson/detail/40523", source_type="course", authority="F", mode="AUTO_DIFF", focus="评价治理、违规边界、申诉与星级机制", rules=True, bias="low", freq="weekly"),
    _s(6, "SRC-MT-LECTURER-CAO", publisher="美团", title="美团曹欣韵课程集", url="https://xue.meituan.com/lecturer/detail/100", source_type="course", authority="C2", mode="SEMI", focus="曝光→进店→购买→复购、满减、推广、菜单、会员"),
    _s(7, "SRC-MT-LECTURER-ZHANG", publisher="美团", title="美团张鑫课程集", url="https://xue.meituan.com/lecturer/detail/116", source_type="course", authority="C2", mode="SEMI", focus="满减定价、线上经营入门、客流骤增后的承接"),
    _s(8, "SRC-MT-COURSE-TRAFFIC-REVIEW", publisher="美团", title="美团引流获客/评价进阶课程系列", url="https://xue.meituan.com/lesson/series/detail/40408", source_type="course", authority="C2", mode="SEMI", focus="星级、评价分析、列表页流量、用户运营"),
    _s(9, "SRC-MT-RULE-REVIEW", publisher="美团", title="美团外卖平台评价管理规范", url="https://rules-center.meituan.com/m/detail/guize/901", source_type="rule", authority="F", mode="AUTO_DIFF", focus="评分构成、复购、回复率、食安负反馈、服务负反馈", rules=True, bias="none", freq="weekly", notes=("P0 硬规则",)),
    _s(10, "SRC-MT-RULE-ONBOARD", publisher="美团", title="美团入网餐饮服务提供者审查登记规范", url="https://rules-center.meituan.com/m/detail/guize/386012", source_type="rule", authority="F", mode="AUTO_DIFF", focus="资质、入驻、经营资格、合规状态", rules=True, bias="none", freq="weekly"),
    _s(11, "SRC-MT-RULE-CONSUMER", publisher="美团", title="美团餐饮消费者权益保护规范", url="https://rules-center.meituan.com/m/detail/guize/381009", source_type="rule", authority="F", mode="AUTO_DIFF", focus="客诉、退款、赔付、商家责任边界", rules=True, bias="none", freq="weekly"),
    _s(12, "SRC-MT-RULE-DISCLOSURE", publisher="美团", title="美团外卖信息公示制度", url="https://rules-center.meituan.com/m/detail/guize/395005", source_type="rule", authority="F", mode="AUTO_DIFF", focus="证照、公示信息、页面与实际经营一致性", rules=True, bias="none", freq="weekly"),
    _s(13, "SRC-MT-RULE-FOODSAFE", publisher="美团", title="美团食品安全违法行为制止及报告规范", url="https://rules-center.meituan.com/m/detail/guize/392017", source_type="rule", authority="F", mode="AUTO_DIFF", focus="食安风险、异常升级、不可自动执行边界", rules=True, bias="none", freq="weekly"),
    _s(14, "SRC-MT-RESEARCH", publisher="美团研究院", title="美团研究院", url="https://mri.meituan.com/research/home", source_type="report", authority="F", mode="SEMI", focus="餐饮消费、服务消费、食安、品类趋势 Base Rate", bias="low", research=True, notes=("Base Rate 可进研究区；不直接当本店策略",)),
    _s(15, "SRC-MT-AI-MANAGER", publisher="美团", title="美团智能掌柜公开案例", url="https://xue.meituan.com/article/detail/42473", source_type="case_story", authority="C2", mode="SEMI", focus="AI建议→套餐设计→订单结果等闭环参考", notes=("重点研究竞品闭环，不作强因果",)),
    _s(16, "SRC-JD-RULE-INFO", publisher="京东", title="京东外卖商家信息违规处理规则", url=None, source_type="rule", authority="F", mode="AUTO_DIFF", focus="商品图片、信息发布、资质、违规及申诉", rules=True, bias="none", freq="weekly"),
    _s(17, "SRC-JD-OPEN", publisher="京东", title="京东外卖餐饮开放平台", url="https://opendj.jd.com/staticnew/widgets/doc/waimai.html", source_type="api_doc", authority="F", mode="AUTO_DIFF", focus="订单、门店、商品库存、售后、财务、取消审核等执行契约", rules=True, bias="none", freq="weekly", notes=("P0 执行契约",)),
    _s(18, "SRC-JD-RECEIPT", publisher="京东", title="京东外卖/秒送订单小票规范", url="https://opendj.jd.com/staticnew/widgets/introduce/orderPrintReceiptsRules.html", source_type="rule", authority="F", mode="AUTO_DIFF", focus="后厨、配送、商户三联单与履约数据结构", rules=True, bias="none"),
    _s(19, "SRC-ELE-AUTH", publisher="淘宝闪购/饿了么", title="淘宝闪购餐饮服务商平台授权体系", url="https://open-api.shop.ele.me/authorize", source_type="api_doc", authority="F", mode="AUTO_DIFF", focus="店铺/订单数据授权、服务商权限、接单权限边界", rules=True, bias="none", notes=("禁止接真实 OAuth 写回；只登记权限边界",)),
    _s(20, "SRC-ELE-TERMS", publisher="阿里巴巴", title="淘宝闪购/饿了么连锁商户服务协议与规则中心", url="https://terms.alicdn.com/legal-agreement/terms/suit_bu1_other/suit_bu1_other202111251946_14275.html", source_type="rule", authority="F", mode="AUTO_DIFF", focus="商户协议、平台规则变更、授权和合规边界", rules=True, bias="none", freq="weekly"),
    _s(21, "SRC-DD-STORIES", publisher="DoorDash", title="DoorDash Merchant Success Stories 总库", url="https://merchants.doordash.com/en-us/blog/topic/success-stories-home", source_type="case_story", authority="C2", mode="SEMI", focus="按品类、地区、规模抽取营销、广告、复购、直营订单案例", bias="high", notes=("P0 官方案例库；成功案例选择偏差",)),
    _s(22, "SRC-DD-COYO", publisher="DoorDash", title="DoorDash — Coyo Taco", url="https://merchants.doordash.com/en-us/success-stories/coyo-taco", source_type="case_story", authority="C2", mode="SEMI", focus="满额优惠、学生场景、Sponsored Listings、线上点单", bias="high"),
    _s(23, "SRC-DD-MYTHICAL", publisher="DoorDash", title="DoorDash — Mythical Pizza", url="https://merchants.doordash.com/en-us/success-stories/mythical-pizza", source_type="case_story", authority="C2", mode="SEMI", focus="淡季 Happy Hour、配送费优惠、大单客单、ROAS", bias="high"),
    _s(24, "SRC-DD-FARMHOUSE", publisher="DoorDash", title="DoorDash — Farmhouse Kitchen", url="https://merchants.doordash.com/en-us/success-stories/farmhouse-kitchen", source_type="case_story", authority="C2", mode="SEMI", focus="多门店广告投放、促销、ROAS、Listing 优化", bias="high"),
    _s(25, "SRC-DD-ARAUJOS", publisher="DoorDash", title="DoorDash — Araujo's Mexican Grill", url="https://merchants.doordash.com/en-us/success-stories/araujos-mexican-grill", source_type="case_story", authority="C2", mode="SEMI", focus="BOGO、DashPass、跨渠道会员、复购、门店蚕食", bias="high", notes=("优质 Case",)),
    _s(26, "SRC-DD-FIORELLA", publisher="DoorDash", title="DoorDash — Fiorella", url="https://merchants.doordash.com/en-nz/blog/success-story-fiorella", source_type="case_story", authority="C2", mode="SEMI", focus="新客促销、直营点餐、转化率、同店销售", bias="high"),
    _s(27, "SRC-DD-HAVANA", publisher="DoorDash", title="DoorDash — Made in Havana", url="https://merchants.doordash.com/en-us/success-stories/made-in-havana", source_type="case_story", authority="C2", mode="SEMI", focus="直营数字订单、品牌用户关系、线上→线下", bias="high"),
    _s(28, "SRC-UE-STORIES", publisher="Uber Eats", title="Uber Eats Merchant Success Stories 总库", url="https://merchants.ubereats.com/us/en/resources/success-stories/", source_type="case_story", authority="C2", mode="SEMI", focus="Ads、Offers、虚拟品牌、Direct、多店经营", bias="high"),
    _s(29, "SRC-UE-OISHII", publisher="Uber Eats", title="Uber Eats — Oishii Tokyo", url="https://merchants.ubereats.com/us/en/resources/success-stories/oishii-tokyo/", source_type="case_story", authority="C2", mode="SEMI", focus="小预算投广告→放量→Offers→新客→复购", bias="high", notes=("P0 完整链路",)),
    _s(30, "SRC-UE-DRAGON", publisher="Uber Eats", title="Uber Eats — Dragon King", url="https://merchants.ubereats.com/us/en/resources/success-stories/dragon-king/", source_type="case_story", authority="C2", mode="SEMI", focus="七店经营、广告+优惠、每天看评论和门店报告", bias="high"),
    _s(31, "SRC-DKD-KB", publisher="店客多", title="店客多品牌连锁运营系统公开知识库", url="https://www.diankeduo.cn/chain/", source_type="knowledge_base", authority="C1", mode="SEMI", focus="毛利、距离、订单、SKU、CPC、闭店、天气、活动、评价、CRM、IM", bias="high", copyright_mode="proprietary", notes=("P0 竞品语料；厂商归因不可当强因果",)),
    _s(32, "SRC-DKD-NEWS", publisher="店客多", title="店客多资讯中心/异常监控案例", url="https://www.diankeduo.cn/news/135", source_type="case_story", authority="C1", mode="SEMI", focus="闭店、上下架/售罄、活动到期、掉单分析", bias="high", copyright_mode="proprietary"),
    _s(33, "SRC-DV-LITTLE-CAESARS", publisher="Deliverect", title="Deliverect — Little Caesars", url="https://www.deliverect.com/en-us/customers/little-caesars", source_type="case_story", authority="C1", mode="SEMI", focus="多平台订单→POS、统一菜单、大规模订单集成", bias="high"),
    _s(34, "SRC-DV-SUSHI-YAMA", publisher="Deliverect", title="Deliverect — Sushi Yama", url="https://www.deliverect.com/en/customers/sushi-yama", source_type="case_story", authority="C1", mode="SEMI", focus="跨渠道菜单同步、商品 Snooze、自有配送、客单", bias="high"),
    _s(35, "SRC-DV-WOKWOK", publisher="Deliverect", title="Deliverect — Wok Wok", url="https://www.deliverect.com/en-us/customers/wok-wok", source_type="case_story", authority="C1", mode="SEMI", focus="多平台平板漏单/错误→统一订单流", bias="high"),
    _s(36, "SRC-DV-SPIN", publisher="Deliverect", title="Deliverect — SPIN NYC", url="https://www.deliverect.com/en/customers/spin", source_type="case_story", authority="C1", mode="SEMI", focus="高峰每单时间、虚拟品牌、跨平台菜单", bias="high"),
    _s(37, "SRC-DV-HEALTHY-POKE", publisher="Deliverect", title="Deliverect — Healthy Poke", url="https://www.deliverect.com/en/customers/healthy-poke", source_type="case_story", authority="C1", mode="SEMI", focus="平板过多、订单错误、门店中断、履约效率", bias="high"),
    _s(38, "SRC-YZ-PRIVATE", publisher="有赞", title="有赞餐饮真实私域案例库", url="https://www.youzan.com/blog/articles/77231", source_type="case_story", authority="C1", mode="SEMI", focus="平台流量→企业微信/会员→复购→私域订单", bias="high", notes=("不可把厂商归因当强因果",)),
    _s(39, "SRC-SQB-CAILINJI", publisher="收钱吧", title="收钱吧全来店 — 蔡林记", url="https://www.shouqianba.com/zh/about-us/customer-cases/cailinji", source_type="case_story", authority="C1", mode="SEMI", focus="堂食/外卖高峰冲突、统一订单、多渠道经营", bias="high"),
    _s(40, "SRC-SQB-TIANYEZHONG", publisher="收钱吧", title="收钱吧全来店 — 田野中", url="https://www.shouqianba.com/zh/about-us/customer-cases/tianyezhong", source_type="case_story", authority="C1", mode="SEMI", focus="日清日结、订货预测、巡店、堂食外卖数据统一", bias="high"),
    _s(41, "SRC-BOOK-7STEPS", publisher="美团 / 人民邮电出版社", title="《外卖运营7步法》· 美团", url="https://detail.youzan.com/show/goods?alias=3nrnxha0h72b5sq", source_type="book", authority="C1", mode="MANUAL", focus="线上开店、菜单、运营、出品、配送、客情、数据七层体系", copyright_mode="purchased", prior=True, training=False, notes=("P0 书籍；只存摘要/原则/引用，禁止整本切块灌库",)),
    _s(42, "SRC-BOOK-ELEME-GUIDE", publisher="饿了么商家学院 / 勺子课堂", title="《外卖运营实战指南》", url="https://www.megbook.com.hk/mall/detail.jsp?proID=3162211", source_type="book", authority="C1", mode="MANUAL", focus="店铺包装、营销、效率、成本", copyright_mode="purchased", notes=("旧平台技巧降权",)),
    _s(43, "SRC-BOOK-SUPER-OPS", publisher="饿了么", title="《外卖超级运营术》· 饿了么", url="https://tool.lu/book/1a/detail", source_type="book", authority="C1", mode="MANUAL", focus="开店→流量→进店→下单→数据 Funnel", copyright_mode="purchased"),
    _s(44, "SRC-BOOK-WAI-MAI-MGMT", publisher="孙勇兴 / 人民邮电出版社", title="《餐饮业外卖管理一本通》· 孙勇兴", url="https://www.megbook.com.tw/mall/detail.jsp?proID=3508224", source_type="book", authority="C1", mode="MANUAL", focus="订单、菜单、定价、包装配送、安全投诉、门店执行", copyright_mode="purchased"),
    _s(45, "SRC-BOOK-SONG-XUAN", publisher="宋宣", title="《从零开始做餐饮·经营篇》· 宋宣", url="https://www.aijiaocai.com/textbook/details?textbook_id=755636", source_type="book", authority="C1", mode="MANUAL", focus="利润、人效、食材成本、复购、客单、整盘经营", copyright_mode="purchased", notes=("Business Truth 重点",)),
    _s(46, "SRC-BOOK-YANHAN-2026", publisher="闫寒", title="《外卖爆单：7天从0到日销千单》· 闫寒 2026", url=None, source_type="book", authority="C1", mode="MANUAL", focus="当前平台环境、产品体系、定价、投放、转化、AI 工具", copyright_mode="purchased", notes=("新但成功叙事需降权",)),
    _s(47, "SRC-TRD", publisher="Meituan / Zenodo", title="TRD — Meituan Takeout Recommendation Dataset", url="https://explore.openaire.eu/search/result?pid=10.5281%2Fzenodo.8025855", source_type="dataset", authority="R", mode="DATASET", focus="用户、餐厅、SKU、点击序列、订单；曝光→兴趣→下单链", copyright_mode="open_license", prior=False, research=True, training=False, notes=("P0 研究；CC BY；只进 Research Zone",)),
    _s(48, "SRC-LADE", publisher="菜鸟", title="LaDe — Cainiao Last-mile Delivery Dataset", url="https://cainiaoai.github.io/LaDe-website/", source_type="dataset", authority="R", mode="DATASET", focus="履约/时效/高峰研究", copyright_mode="proprietary", prior=False, research=True, notes=("商业使用前重新核许可证",)),
    _s(49, "SRC-YELP-OPEN", publisher="Yelp", title="Yelp Open Dataset", url="https://business.yelp.com/data/resources/open-dataset/", source_type="dataset", authority="R", mode="DATASET", focus="差评 taxonomy、图片/商户画像研究", copyright_mode="education_only", prior=False, research=True, training=False, commercial=False, notes=("红线：官方教育用途，禁止当商用训练语料上线",)),
    _s(50, "SRC-FOODMATCH", publisher="arXiv", title="FoodMatch：真实外卖配送调度研究", url="https://arxiv.org/abs/2008.12905", source_type="paper", authority="R", mode="MANUAL", focus="订单 batching、骑手匹配、动态路网原理", copyright_mode="open_license", prior=False, research=True, notes=("提炼算法原理，不照搬策略",)),
    _s(0, "SRC-DKD-SEED", publisher="店客多 / MealKey 已掌握材料", title="已掌握的真实外卖运营资料（seed 001–003）", url=None, source_type="knowledge_base", authority="C1", mode="MANUAL", focus="异常营业、CPC 分时冲突样板、评价治理", bias="high", copyright_mode="proprietary", notes=("第一阶段必蒸馏；数字冲突必须两侧保留",)),
)


def all_sources() -> tuple[SourceRegistryItem, ...]:
    return WHITELIST


def by_id(source_id: str) -> SourceRegistryItem:
    return _BY_ID[source_id]


def enabled_sources() -> list[SourceRegistryItem]:
    return [item for item in WHITELIST if item.enabled]


def p0_sources() -> list[SourceRegistryItem]:
    return [item for item in WHITELIST if item.phase == "p0"]


def rule_sources(*, enabled_only: bool = True) -> list[SourceRegistryItem]:
    rows = enabled_sources() if enabled_only else list(WHITELIST)
    return [item for item in rows if item.allowed_for_rules and item.ingestion_mode == "AUTO_DIFF"]


def research_sources() -> list[SourceRegistryItem]:
    return [item for item in WHITELIST if item.research_zone]


_BY_ID = {item.source_id: item for item in WHITELIST}
