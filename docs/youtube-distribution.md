# AdsMind 发行中心（第一版）

在侧栏「发行中心」进入 YouTube 发行、发行记录和频道管理。定位为完整短剧成片发行，非逐集排期。

本版可登记频道资料，新建与编辑发行草稿，保存标题、简介/章节、封面地址、字幕备注、成片引用、语言与版本、受众、发行授权确认，以及立即/定时发布意向。定时输入明确采用北京时间 UTC+8，服务端保存带时区时间。素材库的视频行提供「去发行」，自动携带素材 ID 和文件名，仍需人工确认是完整剧集。当前素材库为广告素材库，不作为完整成片库自动认证。

草稿与频道保存到 APP 数据库，后端启动幂等创建 `app_distribution_drafts` 与 `app_distribution_channels`。按租户和应用隔离，同一应用内团队共享；写入使用 revision 防止覆盖其他人的更新。查看权限沿用 creatives 面板，编辑限 admin、super_admin、optimizer、designer。后续需要独立发行角色时再增加专属权限。

本版不含 Google OAuth、视频文件传输、自动排期任务、审核状态流转或 YouTube 数据同步。频道状态固定为待授权，发行任务固定为草稿，发布按钮禁用。发行检查总会提示授权/上传未完成，不能把准备检查理解为实际文件或版权检测。发行记录页是待接入说明，不展示模拟发布结果。封面只保存地址，字幕只保存备注。

## 验证

前端：`npm run build`、`npm test`。

在 backend 目录：`../.venv/bin/python -m unittest discover -s tests -p test_distribution.py -v`。

本地开发数据库验证：`ADSMIND_INTEGRATION_TESTS=1 ../.venv/bin/python -m unittest discover -s tests -p test_distribution.py -v`。使用专属测试应用编号，测试后自动清理临时行。覆盖持久保存、乐观锁、跨应用/租户隔离、输入校验与权限。
