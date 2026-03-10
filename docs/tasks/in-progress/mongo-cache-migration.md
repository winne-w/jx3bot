# Task: Mongo Cache Migration

状态：进行中
更新时间：2026-03-10

## 目标

- 把当前分散的文件缓存和运行态 JSON 数据迁移到 Mongo
- 在不破坏现有分层约束的前提下，把读写路径收口到 `src/storage/`
- 用可回退的方式完成迁移，避免一次性切换导致机器人功能回归
- 后续实现按 TDD 开发，先写测试再写实现

## 当前关联执行文档

- `docs/exec-plans/active/mongo-cache-migration-plan.md`
- `docs/exec-plans/active/mongo-cache-migration-mapping.md`

## 当前进展

### 已完成

- 已新增 `src/storage/` 下的 Mongo settings / provider / ports / singletons / adapter 基础设施
- 已落地集合与索引初始化：
  - `cache_entries`
  - `jjc_ranking_cache`
  - `jjc_kungfu_cache`
  - `group_reminders`
  - `wanbaolou_subscriptions`
  - `jjc_ranking_stats`
- 已接入 Mongo 主路径并保留文件回退：
  - `status_monitor` JSON 缓存
  - `server_data.json`
  - `server_master_cache.json`
  - `jjc_ranking_cache.json`
  - `data/cache/kungfu/*.json`
  - `data/group_reminders.json`
  - `data/wanbaolou_subscriptions.json`
  - `data/jjc_ranking_stats/*.json`
- 已完成第二批后置项的接入：
  - `data/wanbaolou_alias_cache.json` 对应 `wanbaolou/alias_cache`
  - `data/baizhan_images/baizhan_data.json` 对应 `baizhan/latest_meta`
- 已补回填与核对脚本：
  - `scripts/mongo_backfill.py`
  - `scripts/mongo_verify.py`
- 已跑通一次真实 Mongo 索引初始化、回填和核对
- 已补最小自动化测试，覆盖 repo 行为、API fallback、脚本映射与第二批缓存接入

### 当前观察结果

- `cache_entries` 已写入首批与第二批可用缓存元数据
- `jjc_kungfu_cache` 历史数据已导入过，但多数旧文档会因 TTL 与过期时间被自动清理
- `wanbaolou_alias_cache` 代码已支持 Mongo；当前工作区没有旧缓存文件，需等待运行期刷新或后续生成后再落库
- `jjc_ranking_cache`、`group_reminders` 当前工作区没有旧文件样本，因此未回填出历史文档

### 未完成

- 仍处于“双读优先 Mongo、双写保留文件”的过渡阶段，尚未切到 Mongo 单写
- `wanbaolou_subscriptions` / `group_reminders` 已具备最小 CRUD，但插件层仍保留部分文件兼容逻辑
- 缺真实 Mongo 集成测试与完整回归清单验证
- 缺“切单写 / 回滚 / 删除旧路径”的明确执行步骤和验收记录

## 任务范围

首批纳入：

- `status_monitor` JSON 缓存
- `server_data.json`
- `jjc_ranking_cache.json`
- `data/cache/kungfu/*.json`
- `server_master_cache.json`
- `data/group_reminders.json`
- `data/wanbaolou_subscriptions.json`
- `data/jjc_ranking_stats/*.json`

暂不纳入：

- `groups.json`
- `runtime_config.json`
- `restart_info.json`
- `waiguan.json`
- 图片文件缓存
- 进程内短 TTL 内存缓存

## 任务拆分

### T1. Mongo 存储边界设计

交付物：

- `src/storage/` 下的 port 列表
- Mongo adapter 列表
- singleton / factory 装配方案

要求：

- 业务层只依赖 repo/port，不直接依赖 Mongo 驱动
- 不新增插件层直接写库
- 命名与现有 `json_adapter` / `mongo_adapter` 方向保持一致

完成标准：

- 明确每类数据由哪个 repo 负责
- 明确哪些走 `cache_entries`，哪些走独立集合
- 产出对应的测试清单，作为后续实现入口

### T2. Mongo 基础设施接入

交付物：

- Mongo 连接配置约定
- 库名和集合名约定
- 索引初始化方案

要求：

- 配置来源走环境变量或 `config.py`
- 不硬编码敏感连接信息
- TTL 索引只给真正可丢弃的缓存

完成标准：

- 能在空库中创建所需集合和索引
- 索引清单与执行文档一致
- 有基础连接与索引初始化测试

当前状态：已完成基础实现与真实库验证；真实实例已完成 `ping`、建索引和集合落地。

### T3. 通用缓存 repo 落地

覆盖对象：

- `status_monitor` 各类缓存
- `server_data`
- `server_master_cache`

交付物：

- 通用缓存 port / repo
- Mongo adapter
- 旧文件兼容读取策略

要求：

- 保留 `namespace + key` 读写模型
- 读路径支持 Mongo 未命中回退文件
- 写路径在过渡期支持双写

完成标准：

- 通用缓存不再需要在插件/service 中拼文件路径
- 有 repo 级 cache hit / miss / file fallback 测试

当前状态：已完成主路径接入；仍保留插件层文件兼容代码，后续再做单写切换。

### T4. JJC 缓存 repo 落地

覆盖对象：

- `jjc_ranking_cache`
- `jjc_kungfu_cache`
- `jjc_ranking_stats`

交付物：

- JJC Mongo repo
- 历史快照查询接口适配方案

要求：

- 保留现有 `cache_time` 语义
- 保留心法缓存完整性判定
- `jjc_ranking_stats` 支持 `list/read(timestamp)` 现有行为

完成标准：

- 竞技场排行榜、心法缓存、统计快照都能通过 repo 访问
- 有心法缓存完整性判定测试和 stats list/read 测试

当前状态：已完成主路径接入、API 适配、文件回退回填与最小测试。

### T5. 运行态数据 repo 落地

覆盖对象：

- `group_reminders`
- `wanbaolou_subscriptions`

交付物：

- 提醒任务 repo
- 万宝楼订阅 repo

要求：

- 提醒任务必须支持启动恢复 `pending`
- 订阅必须支持按用户查询、按物品查询、删除已触发项
- 不再依赖整文件覆盖写

完成标准：

- 提醒和订阅逻辑都不再直接读写 JSON 文件
- 有提醒恢复、订阅增删改查和触发后删除测试

当前状态：已完成 Mongo repo 和最小 CRUD；仍保留文件兼容层，尚未完全下线 JSON 主路径。

### T6. 数据回填脚本

交付物：

- 一次性导入脚本
- 导入结果报告格式

要求：

- 支持跳过不存在文件
- 支持坏数据容错
- 支持幂等运行

完成标准：

- 可从当前仓库文件数据安全导入 Mongo
- 重复执行不会制造重复文档
- 有样例导入、幂等和坏数据容错测试

当前状态：已完成 `mongo_backfill.py`，并在真实实例执行过至少一轮回填。

### T7. 双读双写过渡

交付物：

- 迁移期间的兼容策略
- 切换开关或明确切换步骤

要求：

- 先读 Mongo，未命中回退文件
- 过渡期先双写
- 日志中要能分辨 Mongo 命中、文件回退、双写失败

完成标准：

- 在不清理旧文件的情况下可以稳定运行一个观察周期
- 有双读双写行为测试

当前状态：已落地“先读 Mongo、未命中回退文件、文件命中后回填 Mongo、写入双写”；尚未完成观察周期与切换结论。

### T8. 切单写与清理旧路径

交付物：

- 文件写入下线清单
- 兼容逻辑删除清单

要求：

- 先停文件写，再观察
- 最后再删文件回读
- 删除前确认回填、恢复和 API 查询均正常

完成标准：

- 首批范围内不再依赖旧 JSON 文件作为主存储
- 删除文件路径前已有 Mongo 主路径测试覆盖

当前状态：未开始。

## 建议实施顺序

1. T1 `Mongo 存储边界设计`
2. T2 `Mongo 基础设施接入`
3. T3 `通用缓存 repo 落地`
4. T4 `JJC 缓存 repo 落地`
5. T5 `运行态数据 repo 落地`
6. T6 `数据回填脚本`
7. T7 `双读双写过渡`
8. T8 `切单写与清理旧路径`

## TDD 执行规则

1. 每个任务先补失败测试
2. 测试通过后再接业务调用点
3. 新增兼容逻辑必须有测试证明存在必要性
4. 删除旧文件逻辑前必须先有回归测试兜底

建议每个任务都按这三个提交阶段推进：

1. `test`: 先提交失败测试
2. `impl`: 提交最小实现让测试变绿
3. `cleanup`: 删除重复逻辑并补文档

## 依赖关系

- T2 依赖 T1
- T3 / T4 / T5 依赖 T2
- T6 依赖 T3 / T4 / T5 至少完成数据模型定义
- T7 依赖 T3 / T4 / T5
- T8 依赖 T6 / T7 和完整回归验证

## 风险点

1. `jjc_kungfu_cache` 不是简单 TTL 缓存
   - 命中条件还依赖 `weapon_checked`、`teammates_checked` 和队友数据完整性

2. `group_reminders` 带启动恢复语义
   - 迁移后必须验证 `pending` 任务恢复和重试逻辑

3. `wanbaolou_subscriptions` 当前允许重复订阅
   - 迁移时不能误做去重，避免行为变化

4. `status_monitor` 现有缓存缺统一边界
   - 迁移时容易把插件层逻辑和存储细节继续耦合

5. `jjc_ranking_stats` 有 HTTP API 读路径
   - 切换后不能只保证写入成功，还要保证列表和读取接口兼容

## 验收口径

### 功能验收

- 竞技场排行榜查询命中 Mongo 缓存且行为不变
- 心法缓存命中与失效行为不变
- 开服/新闻/技改/兑换码去重缓存跨重启仍有效
- 提醒创建、查看、取消、启动恢复、发送后置完成状态都正常
- 万宝楼订阅新增、查看、取消、触发后删除行为正常
- `GET /api/jjc/ranking-stats` 的 `list/read` 行为正常

### 工程验收

- 首批迁移范围内的主读写路径进入 `src/storage/`
- `plugins` 和 `services` 不再新增裸 `open(...)`
- Mongo 索引和字段设计与执行文档一致
- 对应测试覆盖 Mongo 主路径，而不是只覆盖旧文件兼容路径

## 文档联动

实施阶段如果开始改代码，至少同步这些文档：

- `project-architecture.md`
- `README.md`
- `docs/references/runbook.md`
- `docs/exec-plans/active/mongo-cache-migration-plan.md`
- `docs/exec-plans/active/mongo-cache-migration-mapping.md`

## 当前建议

如果要真正开始实施，下一步最合理的是先做 T1：

- 把 `src/storage/` 的 port / adapter / singleton 结构设计定下来
- 再决定每条业务链路怎么接入 Mongo repo

否则直接动代码，很容易把“迁 Mongo”写成“各处散着查库”。
