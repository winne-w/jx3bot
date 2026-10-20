> 2026-10-09 用户决定回退共享推栏预算桶：已恢复直连，移除预算配置、CAS 桶及官方请求范围限制；本文预算相关内容为历史方案，不代表当前运行行为。最新摘要任务、冷却和来源限频仍保留。

# 官方出口预算实施范围

先阅读 PROJECT_CONTEXT.md 以及本目录 design.md 的第 3、4、6、7 节；实现 tasks 1.1–1.4（合并为一个可评审交付），不提交 git，不改其他任务文件，不调用官方接口。不派生子代理。

拥有文件：src/infra/tuilan_budget.py（替换临时实现）、src/infra/tuilan_client.py、src/storage/mongo_repos/tuilan_request_budget_repo.py、src/utils/tuilan_request.py、tests/test_tuilan_budget.py 与新增官方出口测试。允许改 config.py 的 TUILAN_* 配置；不要改 src/infra/mongo.py，由主代理集成必要索引。通用 HTTP client 如需改动仅增加 Retry-After 返回，避免大范围重构。

接口约定：tuilan_request(url, params=None) 签名保持不变，所有实际 HTTP 请求受共享预算控制。新增 infra/tuilan_client.py 中 request_scope(traffic_class='interactive', max_attempts=4, retries=1) 上下文管理器，通过 ContextVar 传播至 asyncio.to_thread，用于一次轻量任务累计请求成本；默认其他调用归 background 类别。提供 protection_status() -> dict：state 为 ready/disabled/invalid_config/upstream_paused/budget_unavailable，供主代理在接受轻量任务前检查；这些函数不可联网官方。拒绝结果统一 {'error': 'tuilan_budget_exhausted' 或 'tuilan_upstream_paused' 或 'tuilan_budget_unavailable', 'retry_after_seconds': 正数}；不返回凭据。

预算必须同步 PyMongo 跨进程 CAS 单文档，majority 写关注，有界分钟桶保守滚动 60 分钟/24 小时，配置指纹、并发租约、端点间隔和30/70流量份额。不能以进程内门禁代替。生产保护启用时配置缺失必须拒绝联网；功能默认关闭保持老路径兼容，但临时硬编码5秒门禁必须移除。轻量刷新只能保护启用时使用。重试每次新签名、每次预算许可，401/403/业务鉴权暂停，429尊重Retry-After。续跑后台无预算应返回明确状态。

严格 Python3.9 typing；测试先失败再实现，测试使用内存 collection double 或本地 HTTP stub，不请求官方；主代理会提供隔离真实 Mongo URI 做跨进程复测。确保现有 tuilan_request import 在 nonebot 安装时不再因为 logging 未定义失败，签名失败也不会泄漏许可。

完成报告写入本目录 budget-report.md，返回文件列表、测试、接口和剩余风险。不要修改 tasks.md 或其他工作区用户改动。
