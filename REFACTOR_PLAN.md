# 重构计划（不包含 wanbaolou）

更新时间：2025-12-18

目标：
- 调用链清晰、边界明确（plugins / services / infra / utils）
- 降低跨模块耦合与反向依赖
- 收敛全局状态与缓存读写入口
- 日志/错误处理一致，便于排障

## 设计约束（必须遵守）

### 依赖方向（禁止反向依赖）
- 固定依赖方向：`plugins -> services -> infra`（`utils` 为低层工具，只能被依赖）
- `services` 禁止依赖 `nonebot.adapters.*` / `Bot` / `MessageSegment` 等表现层对象（避免 service 里直接发送消息）
- `renderers` 只负责“模板渲染/图片生成/发送封装”，不放业务规则；建议由 `plugins` 或极薄的 presenter 层调用

### singletons / infra 边界（避免新的“大杂烩”）
- `src/services/jx3/singletons.py`：只做对象实例组装（repo/client/service/env），不继续新增业务逻辑；如需兼容旧调用，可短期保留“薄门面函数”，但必须标注为兼容层并控制增长
- `src/infra/*`：只放“外部世界适配器”（HTTP/文件/截图/邮件/重试/鉴权/日志上下文），不放业务规则与统计逻辑

### 日志与错误处理（统一口径）
- 全项目逐步替换 `print()` 为 `nonebot.logger`/`loguru`，日志包含命令/服务器/接口/必要时 request_id
- 对外部请求统一错误包装与降级策略（超时、重试、不可用时的兜底提示），避免各模块自实现

### 安全与配置（严禁硬编码敏感信息）
- 禁止在代码中硬编码：账号密码、邮箱收件人、Cookie、secret_key、内网 IP/端口等；统一收口到 `config.py` 或环境变量
- 重构过程中如发现敏感信息，优先做“提取配置 + 兼容默认值 + 文档说明”，避免在 diff 中继续扩散

## 进度总览

- [~] 1. 稳定 `services` 共享依赖（singletons 边界清晰）
- [ ] 2. 拆分 `src/plugins/status_monitor.py` 为模块包
- [ ] 3. 统一 `groups.json` 的读写链路（全项目只走 `GroupConfigRepo`）
- [ ] 4. 抽取共享 HTTP Client（新增 infra 层）
- [ ] 5. 瘦身 `src/utils/defget.py`（按职责拆分）
- [ ] 6. 降低 `src/services/jx3/jjc_ranking.py` 职责（client/repo/service/renderer）
- [ ] 7. 补齐“手工回归清单”（不引入新测试框架）

标记说明：
- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成

---

## 1. 稳定 `services` 共享依赖（singletons 边界清晰）

状态：进行中（已完成基础落地，后续需继续收敛边界）

### 已完成
- [x] 下沉 `jjc_ranking_service` 到 `src/services/jx3/singletons.py`，解除 `status_monitor` 对 `src/plugins/jx3bot.py` 的依赖
- [x] 引入 `GroupConfigRepo`：`src/services/jx3/group_config_repo.py`
- [x] 在 `src/services/jx3/singletons.py` 导出 `group_config_repo`
- [x] `src/plugins/jx3bot.py` 的 help 读取群配置改为使用 `group_config_repo.load`

### 待完成（约束/规范）
- [x] `src/services/jx3/singletons.py` 只保留“对象实例（repo/client/service/env）”，不继续新增业务逻辑函数
- [ ] 如需保留兼容门面函数：命名与注释明确“compat/facade”，并限制数量（不在 singletons 继续膨胀）
- [ ] 为后续新增的共享对象制定规则：优先放到 `src/infra/*`，再由 singletons 组装

---

## 2. 拆分 `src/plugins/status_monitor.py` 为模块包

状态：未开始

拆分目标（保持行为不变，先“搬家”后“优化”）：
- [x] 创建目录 `src/plugins/status_monitor/`
- [x] `src/plugins/status_monitor/__init__.py`：插件入口/注册（对外保持一致）
- [ ] `src/plugins/status_monitor/jobs.py`：scheduler 定时任务定义（只负责调 service）
- [ ] `src/plugins/status_monitor/commands.py`：管理员命令（只负责调 service）
- [x] `src/plugins/status_monitor/notify.py`：邮件/告警通道封装（后续可迁移到 infra）
- [x] `src/plugins/status_monitor/storage.py`：缓存/落盘（后续与统一缓存合并）
- [ ] 保持旧 import 路径可用（如需要，提供兼容 re-export）
- [ ] 顺手清理明显硬编码敏感信息：邮箱账号/收件人、内网地址、Cookie、用户名密码等（改为从 `config.py`/环境变量读取）

---

## 3. 统一 `groups.json` 的读写链路

状态：未开始（`jx3bot` 已接入；`status_monitor` 仍有大量自实现）

- [ ] 删除/替换 `src/plugins/status_monitor.py` 内部的 `load_groups/save_groups`
- [ ] 所有读写群配置统一改为 `src/services/jx3/singletons.py` 导出的 `group_config_repo.load/save`
- [ ] 禁止新增 `open('groups.json')` 直接读写的实现

---

## 4. 抽取共享 HTTP Client（新增 infra 层）

状态：未开始

- [ ] 新增 `src/infra/http_client.py`：统一超时、重试、UA、错误包装、日志上下文
- [ ] 明确 async 语义：在 async 调用链内禁止使用阻塞 HTTP（例如 `requests`），必要时改为 `httpx.AsyncClient`
- [ ] 让 `tuilan_request` 逐步复用该 client（先做兼容封装，避免一次性重写）
- [ ] 让 `jiaoyiget`/其他请求逐步复用该 client

---

## 5. 瘦身 `src/utils/defget.py`（按职责拆分）

状态：未开始

- [ ] 把纯函数/小工具迁到 `src/utils/`（保持依赖最小）
- [ ] 把 IO/网络/截图相关迁到 `src/infra/`
- [ ] 逐步减少 `from src.utils.defget import ...` 的导入面（目标：只剩少量兼容导出）
- [ ] 确保 `services` 不直接依赖“截图/模板渲染/发送消息”等表现层能力（需要则经由 `plugins`/`renderers`）

---

## 6. 降低 `src/services/jx3/jjc_ranking.py` 职责

状态：未开始

建议拆分（分阶段落地）：
- [ ] `JjcApiClient`：仅负责请求、校验、错误归一化
- [ ] `JjcCacheRepo`：仅负责文件缓存读写（ranking/kuangfu）
- [ ] `JjcRankingService`：仅负责流程编排（缓存策略、降级策略）
- [ ] 渲染保持在 `src/renderers/`（service 只产出结构化数据）
- [ ] 将 `print()` 全面替换为 `nonebot.logger`/`loguru`（带 request_id/server/name 等上下文）
- [ ] 从 service 移除 `Bot/Event/MessageSegment` 相关逻辑（发送图片/文本留在 handler/renderer）

---

## 7. 补齐“手工回归清单”

状态：未开始

- [ ] 在开始大拆分前先补一个最小清单（能跑通“核心功能不挂”）
- [ ] 在本文件末尾追加“回归步骤/触发词/关键路径”清单
- [ ] 每次拆分后更新清单（确保能快速验证核心功能：帮助、竞技、缓存、推送等）
