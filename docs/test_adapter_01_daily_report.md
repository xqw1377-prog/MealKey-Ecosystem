# TEST-ADAPTER-01 · Daily Report Test Fixture

**状态：DEV/TEST ONLY — 不可晋升为生产 Connector。**

这是产品锁定的测试夹具，用来证明：

```text
第三方日报 → adapter → Partial PlatformSnapshot / Facts
→ StoreState(test) → POIE → ODO
```

它 **不是** DATA-AS-01，也 **不是** 真实平台 Connector。

## 锁死字段

| 字段 | 值 |
|---|---|
| source | `external_daily_report_test` |
| environment | `test` |
| truth_eligible | `false` |
| writeback | disabled / `NOT_IMPLEMENTED` |
| provenance | `TEST_ONLY` |
| platform | `meituan_like` / `external_test`（永不宣称官方美团） |

实现名：`DailyReportTestConnector`。禁止命名或注册为 `MeituanConnector` / `ElemeConnector` / authorized-session。

## 不是什么

- 不是 DATA-AS-01 Merchant Authorized Collector
- 不接入 `AuthorizedSessionConnector`
- 不进入 `SUPPORTED_PLATFORMS` 生产平台表
- 不满足 Production Truth（与 synthetic 同类，`truth_resolution` 不可见）
- 生产环境（`settings.is_dev` 为 false）fail-closed，无静默回退

## Canonical facts

即使源里有曝光 / 进店率 / 下单率 / 客单价，也 **禁止** 反推绝对值：

| 字段 | 状态 |
|---|---|
| impressions | UNKNOWN（`exposure` 只留 extras） |
| visits | UNKNOWN；仅当源有显式绝对 `visits` 才透传 |
| orders | UNKNOWN |
| gmv | UNKNOWN |
| menu_items / reviews / competitors | UNAVAILABLE |

可保留为非规范测试输入：`entry_rate` / `order_rate` / `exposure` / `promotion_fee` / 评分 / `region_rank` / `repurchase_rate` / `bad_review_count`。

不完整快照是正确结果。用编造数字填满 MealKey 合同是 bug。

## 配置（默认关闭）

```text
DAILY_REPORT_TEST_ENABLED=1          # DEV/TEST 显式打开
DAILY_REPORT_TEST_BASE_URL=...       # 测试源根 URL；CI 必须 mock，禁止依赖公网主机
APP_ENV=dev|test                     # prod 一律拒绝
```

`/api/records` 当前无鉴权，**永远不是合法生产数据源**。

## 写回

禁用。`writeback()` / `post_platform_write(mode=daily_report_test)` / `resolve_connector` 均 fail-closed。
