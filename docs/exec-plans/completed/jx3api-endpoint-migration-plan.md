# JX3API 接口地址切换计划

更新时间：2026-05-07

## 背景

JX3API 当前官网文档已从首页 `https://www.jx3api.com/#/doc/user.welcome` 暴露新的 Docsify 文档目录。对照仓库现有调用后，部分历史接口路径已不在公开文档中，且空参探活返回 `code=404`、`请求的路径不存在`。

本计划只处理 JX3API 官方域名 `https://www.jx3api.com` 下的接口地址切换与降级，不处理推栏 `m.pvp.xoyo.com`、JX3BOX、万宝楼等其他外部服务。

## 目标

- 将明确有新文档地址且旧地址已 404 的接口切换到当前文档地址。
- 对当前公开文档没有等价新接口的功能做显式降级，避免继续静默请求 404。
- 保持命令入口和返回渲染逻辑尽量不变，减少用户侧行为变化。
- 将散落的 JX3API 硬编码地址逐步收口，后续更容易统一维护。

## 非目标

- 不重构全部外部请求链路。
- 不迁移推栏接口和竞技场官方接口。
- 不改 JX3API token、ticket 的配置来源。
- 不为已下线且没有文档替代的接口伪造兼容数据。

## 当前接口对照

### 需要切换

| 功能 | 当前代码位置 | 旧地址 | 当前文档地址 | 处理 |
|---|---|---|---|---|
| 烟花查询 | `config.py` | `/data/fireworks/records` | `/data/show/records` | 直接切换 |
| 奇遇查询 | `config.py` | `/data/luck/adventure` | `/data/event/records` | 直接切换 |
| 名片查询 | `config.py` | `/data/show/card` | `/data/card/record` | 直接切换 |
| 科举答题 | `src/plugins/jx3bot_handlers/exam.py` | `/data/exam/answer` | `/data/exam/search` | 直接切换 |
| 骗子查询 | `src/plugins/jx3bot_handlers/fraud.py` | `/data/fraud/detailed` | `/data/fraud/detail` | 直接切换 |
| 开服状态命令 | `src/plugins/status_monitor/commands.py` | `/data/server/status` | `/data/status/check` | 直接切换 |

### 需要降级或确认

| 功能 | 当前地址 | 问题 | 处理 |
|---|---|---|---|
| 装备查询 | `/data/role/attribute` | 旧地址实测 404；公开侧边栏无“装备属性”入口；孤立文档存在但接口不可用 | 暂不替换为 `/data/role/detail`，因为数据结构不等价；命令提示接口暂不可用 |
| 副本查询 | `/data/role/teamCdList` | 旧地址实测 404；公开文档未找到团队 CD 等价接口 | 命令提示接口暂不可用 |
| token 额度查询 | `/data/token/web-token` | 旧地址实测 404；只用于展示 `token剩余`，不参与业务鉴权 | 启动时不再阻断缓存初始化；配置页显示 `未知` 或移除该展示 |

### 暂不变更

| 功能 | 地址 |
|---|---|
| 竞技查询 | `/data/arena/recent` |
| 竞技排行 | `/data/arena/awesome` |
| 角色百战 | `/data/role/monster` |
| 百战首领 | `/data/active/monster` |
| 区服主服查询 | `/data/master/search` |
| 开服状态 | `/data/status/check` |
| 新闻资讯 | `/data/news/allnews` |
| 维护公告 | `/data/news/announce` |
| 技改记录 | `/data/skill/rework` |
| 活动日历 | `/data/active/calendar` |
| 资历查询 | `/data/tuilan/achievement` |

## 分层方案

### 配置层

- 更新 `config.py` 中 `API_URLS` 的烟花、奇遇、名片地址。
- 保留接口 key 不变，避免改动 handler 注册和调用方。
- 对装备、副本保留 key，但值不再作为可用接口直接调用；具体降级由 service/handler 处理。

### Handler 层

- `exam.py` 将硬编码地址切换为 `/data/exam/search`。
- `fraud.py` 将硬编码地址切换为 `/data/fraud/detail`。
- `status_monitor/commands.py` 将硬编码地址切换为 `/data/status/check`。
- 装备、副本入口在调用外部接口前返回明确提示，避免用户只收到“接口错误”。

### 初始化链路

- `cache_init.py` 中 `/data/token/web-token` 查询改为非关键路径。
- 额度查询失败不影响服务器数据缓存加载、百战图标同步和机器人启动。
- `src.utils.shared_data.tokendata` 默认保持 `None`，展示层格式化为 `未知`。

### 外部请求收口

本次只做低风险地址替换，不强制大改 `src.utils.defget`。后续若继续整理 JX3API 调用，可在 `src/infra/` 下新增 JX3API endpoint 常量或客户端封装，再把散落硬编码逐步迁移过去。

## 兼容策略

- 命令词保持不变：`烟花`、`奇遇`、`名片`、`答题`、`骗子/查人`、开服查询命令不变。
- 参数名保持不变：继续使用 `server`、`name`、`token`、`ticket`、`uid`、`subject`。
- 返回数据字段按新文档评估：
  - 烟花新接口返回字段与当前模板预期基本一致，重点确认 `sender`、`receiver`、`firework`、`time`。
  - 奇遇新接口返回 `event`、`level`、`status`、`time`，需确认当前渲染是否依赖旧字段名。
  - 名片新接口返回 `showAvatar`、`showHash`、`showIndex`，需确认当前名片渲染取图字段。
  - 科举新接口返回 `question`、`answer`、`correctness`，需确认格式化函数字段读取。
  - 骗子新接口返回 `server`、`tieba`、`data[].title/url/text/time`，需确认格式化函数字段读取。

如果新接口字段与现有解析不一致，只在对应 parser/service 中做字段适配，不改模板和命令入口。

## 实施步骤

1. 更新 `config.py` 中明确可切换的 JX3API 地址。
2. 更新 `exam.py`、`fraud.py`、`status_monitor/commands.py` 的硬编码旧地址。
3. 为装备查询和副本查询加显式不可用提示，避免继续访问 404 地址。
4. 调整 token 额度查询为非关键路径，并让配置查看中的 `token剩余` 在无数据时显示 `未知`。
5. 对新接口返回结构做最小字段兼容适配。
6. 更新必要文档：本计划状态、回归清单；如用户可见命令行为发生变化，同步 `README.md` 或 `docs/references/runbook.md`。

## 验证方案

### 自动检查

```bash
python -m py_compile config.py src/plugins/jx3bot_handlers/exam.py src/plugins/jx3bot_handlers/fraud.py src/plugins/jx3bot_handlers/queries.py src/plugins/jx3bot_handlers/mingpian.py src/plugins/status_monitor/commands.py src/plugins/jx3bot_handlers/cache_init.py src/plugins/config_manager.py
```

### 接口探活

无真实 token 时，只验证路径状态从 404 变为参数错误或权限错误：

```bash
curl -L "https://www.jx3api.com/data/show/records"
curl -L "https://www.jx3api.com/data/event/records"
curl -L "https://www.jx3api.com/data/card/record"
curl -L "https://www.jx3api.com/data/exam/search?subject=古琴&limit=1"
curl -L "https://www.jx3api.com/data/fraud/detail?uid=570790267"
curl -L "https://www.jx3api.com/data/status/check?server=长安城"
```

### 手工回归

使用真实 `TOKEN` / `TICKET` 后，在机器人里回归：

- `烟花 <服务器> <角色名>`
- `奇遇 <服务器> <角色名>`
- `名片 <服务器> <角色名>`
- `答题 <题目关键词>`
- `骗子 <QQ号>`
- 状态监控开服查询命令
- `属性/装分` 和 `副本/秘境` 应返回明确的接口不可用提示
- 管理配置查看中 `token剩余` 应显示 `未知` 或被移除，不应报错

## 风险

- JX3API 文档地址切换后，返回字段可能也有变化，模板渲染可能出现空字段。
- 装备和副本接口当前没有等价替代，功能会从“失败请求”变为“明确不可用提示”，这是用户可感知变化。
- `token/web-token` 移除后无法展示 token 剩余额度，但不影响业务 API 调用。
- 官网文档为动态维护内容，后续仍可能调整路径或权限。

## 回滚方案

- 可逐项回滚 `config.py` 和硬编码 URL，但旧地址当前已 404，回滚只能恢复旧行为，不能恢复功能。
- 降级提示可回滚为原请求逻辑，但不建议，因为会继续产生无效请求。
- token 额度展示可单独恢复，不影响核心查询接口。

## 状态

- 2026-05-07：已完成官网文档对照和旧接口探活，计划待执行。
- 2026-05-07：已完成代码切换与降级处理。
  - `config.py` 中烟花、奇遇、名片地址已切到当前文档地址。
  - 科举、骗子、开服命令硬编码地址已切换。
  - 装备、秘境入口已改为明确不可用提示，不再请求旧 404 地址。
  - token 额度查询已从启动关键路径移除，配置查看无数据时显示 `未知`。
  - 已同步 `docs/references/runbook.md` 回归清单。
  - 已完成 `py_compile` 检查；无 token 探活确认新路径返回参数错误、权限错误或 success，不再返回旧路径不存在。
