import sys
from collections import OrderedDict
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.operating_demands.catalog import DEMANDS

families = OrderedDict()
for demand in DEMANDS:
    families.setdefault(demand.family, []).append(demand)

labels = {
    "profit": "利润与经营真相 1-10",
    "campaign": "平台活动、价格与套餐 11-20",
    "ads": "流量、推广与广告 21-30",
    "product": "商品、菜单与店铺表现 31-40",
    "order": "订单下降与增长归因 41-50",
    "review": "评价、退款、投诉与客服 51-60",
    "crm": "顾客、复购与 CRM 61-70",
    "competition": "商圈、竞品与排名 71-80",
    "fulfillment": "履约、产能与门店执行 81-90",
    "chain": "多平台、连锁与经营管理 91-100",
}
loop_label = {"A": "A 全自动", "B": "B 审批", "C": "C 人机"}
cov_label = {"green": "绿 骨架", "yellow": "黄 最后一公里", "red": "红 实体缺口"}

sections = []
for fam, items in families.items():
    rows = []
    for demand in items:
        rows.append(
            "<tr>"
            f"<td>{demand.id}</td>"
            f"<td>{escape(demand.question)}</td>"
            f"<td>{loop_label[demand.loop]}</td>"
            f'<td class="{demand.coverage}">{cov_label[demand.coverage]}</td>'
            "</tr>"
        )
    sections.append(
        f"<h2>{labels[fam]}</h2>"
        "<table><tr><th>#</th><th>老板真正会问的问题</th><th>闭环</th><th>当前</th></tr>"
        + "".join(rows)
        + "</table>"
    )

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MealKey Operating Demand Library V1</title>
  <style>
    :root {{ --bg:#111318; --panel:#1a1d24; --line:#2a2f3a; --text:#e8eaef; --muted:#9aa3b2; --accent:#c9a227; --ok:#3d9a6a; --warn:#c9842a; --bad:#c45c4a; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font:14px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }}
    .wrap {{ max-width:980px; margin:0 auto; padding:28px 20px 64px; }}
    h1 {{ font-size:24px; font-weight:650; margin:0 0 8px; }}
    h2 {{ font-size:18px; font-weight:650; margin:28px 0 12px; }}
    p {{ margin:0 0 12px; color:var(--muted); }}
    .lead {{ color:var(--text); font-size:15px; }}
    .callout {{ border:1px solid var(--line); border-left:3px solid var(--ok); background:var(--panel); padding:12px 14px; border-radius:8px; margin-bottom:16px; }}
    .callout.warn {{ border-left-color:var(--warn); }}
    .callout b {{ display:block; margin-bottom:4px; color:var(--text); }}
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:16px 0; }}
    .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; }}
    .stat strong {{ display:block; font-size:22px; margin-bottom:4px; }}
    .stat span {{ color:var(--muted); font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; margin:8px 0 16px; }}
    th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; font-size:12px; }}
    tr:nth-child(even) td {{ background:rgba(255,255,255,0.02); }}
    td.green {{ color:var(--ok); }}
    td.yellow {{ color:var(--warn); }}
    td.red {{ color:var(--bad); }}
    .cards {{ display:grid; gap:10px; grid-template-columns:repeat(3,1fr); }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; }}
    .card h3 {{ margin:0 0 8px; }}
    .card p {{ margin:0; }}
    a {{ color:var(--accent); }}
    @media (max-width:720px) {{ .stats, .cards {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>MealKey Operating Demand Library V1</h1>
    <p class="lead">100 个经营问题，不是 100 个按钮。老板只面对一个 AI 店长。</p>
    <div class="callout"><b>验收标准</b>不是「能回答多少个外卖问题」，而是这 100 种经营需求里，有多少能从问题出现一直活到 Result。</div>
    <div class="stats">
      <div class="stat"><strong>50</strong><span>A 全自动闭环</span></div>
      <div class="stat"><strong>40</strong><span>B 审批式闭环</span></div>
      <div class="stat"><strong>10</strong><span>C 人机闭环</span></div>
      <div class="stat"><strong>47 / 47 / 6</strong><span>绿骨架 / 黄最后一公里 / 红实体缺口</span></div>
    </div>
    <div class="callout warn"><b>这是工程能力覆盖率，不是生产验证率</b>94% 的需求能被现有架构承接。不要因为这 100 问再造 100 个模块。黄/红项不假装已经写回平台或改完后厨。</div>
    <h2>老板真正只问 5 件事</h2>
    <div class="cards">
      <div class="card"><h3>现在发生什么了？</h3><p>异常、利润、订单、评价、竞品。</p></div>
      <div class="card"><h3>为什么？现在该怎么办？</h3><p>Diagnosis + Next Best Action。核心是第 50 问：今天只该做哪一件事。</p></div>
      <div class="card"><h3>能不能替我做？有没有用？</h3><p>Execution → Result → Strategy Memory。</p></div>
    </div>
    <p>契约链：Demand → Trigger → Business Truth → Playbook → Actions → Profit/Risk Gate → Execution → Metric → Observation → Result → Memory</p>
    <p>相关冻结稿：<a href="/commercial-os">Commercial OS</a> · <a href="/competitive-strategy">竞争战略</a></p>
    {''.join(sections)}
  </div>
</body>
</html>
"""
out = Path(__file__).resolve().parents[1] / "app" / "static" / "operating-demands-v1.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size} bytes)")
