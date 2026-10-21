# 素材与剧目分析口径

## 范围与安全边界

`GET /api/asset-analysis/report` 是 tenant/application 作用域内的只读分析接口，页面入口为
`/asset-analysis`。接口只接受已验证应用的 owner、admin、editor、viewer；全局登录身份、租户成员关系、
应用归属与应用角色仍由现有隔离中间件和 `require_application_role` 校验。

本功能不新增数据库迁移，不写预算、广告草稿、素材、映射或平台对象，不触发同步、上传、广告创建和任何
真实平台写接口。它也不使用名称猜测来建立归因关系。

## 数据链路

- APP：剧目主档、应用剧目引用、素材主档与版本、应用素材引用、创意组引用、广告草稿/执行快照、平台素材映射。
- BIZ：当前应用所拥有广告账户范围内的 `biz_attribution_ad_daily`。
- 唯一归集键：`platform + account_id + platform_asset_id` 必须与日报的 `video_id` 或
  `creative_id` 精确一致。零命中记为未映射日报，多素材命中记为歧义日报，两者都不分摊。
- 素材仅使用当前应用引用的有效版本；剧目仅通过素材主档的显式 `drama_id` 汇总。未关联剧目单列。
- 草稿只用于展示追溯关系；执行快照与普通草稿快照分别标记，不反推平台执行结果。

## 金额、时间和完整性

- 归因日报金额按源表契约为 USD，不做汇率转换；同时返回并展示广告账户原币种和 IANA 时区。
- 日期使用账户本地日 `ds_account_local`；返回请求日期范围、来源截止时间和逐日趋势。
- 没有事实行时，消耗、归因收入、曝光、点击、安装、转化和 ROI 均为 `null`，不是 0。
- `complete`：当前有效版本已上传，筛选范围内所有有效平台映射均精确命中日报，且事实覆盖到结束日期。
- `delayed`：映射命中，但事实日期尚未覆盖结束日期。
- `partial`：只命中部分有效映射，或平台上传覆盖不完整。
- `unmapped`：当前有效版本没有平台映射。
- `not_uploaded`：本地版本尚未完成上传且没有更高优先级的覆盖状态。
- `missing_version`：应用素材引用没有可解析的有效版本。
- `no_platform_data`：已有映射，但日期范围内没有可关联的日报。

ROI 仅在对象为 `complete`、有事实行、结束日期已覆盖且消耗大于 0 时返回；否则 `roi=null` 并返回
`roi_reason`。剧目下任一素材不完整时，剧目 ROI 也保持为空。

## 筛选与下钻

`dimension=material|drama` 切换汇总维度；支持 `date_from`、`date_to`、`platform`、`account_id`、
`coverage_status`、`query`、`page` 和 `page_size`。服务端完成筛选、排序和分页。页面行点击后可查看
覆盖原因、指标截止、账户币种/时区、素材版本、创意组和广告草稿/快照链路。

## 已知限制

- 当前只使用可区分归因收入的 `biz_attribution_ad_daily`，不混入把缺失收入默认成 0 的 legacy 报表。
- 没有平台素材映射或平台日报素材标识时不会用文件名、广告名或剧名猜测。
- 跨币种不合计；当前来源金额契约统一为 USD，但账户原币种仍作为来源元数据展示。
- 该分析不证明平台实时状态，也不替代同步健康检查或财务结算。

## 验证

```bash
cd backend
../.venv/bin/python -m unittest tests.test_asset_analysis -v
../.venv/bin/python -m unittest discover -s tests -v

cd ../frontend
npm test -- --run
npm run build
npx eslint src/pages/AssetAnalysisPage.tsx src/services/asset-analysis.ts \
  src/services/__tests__/asset-analysis.test.ts src/app/router.tsx src/app/menu-config.ts
```

真实 HTTP 与浏览器验收必须使用独立测试数据库。不得为通过验收而连接生产数据库或借用不明确归属的
本地开发库。
