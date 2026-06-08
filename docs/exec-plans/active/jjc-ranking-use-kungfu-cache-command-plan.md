# JJC 排名统计使用缓存心法命令计划

## 背景

当前 QQ 命令「竞技排名统计」会逐个角色调用实时心法查询流程，已有 `role_jjc_cache` 心法缓存但统计入口没有显式复用开关。用户希望输入「竞技排名统计 缓存心法」时可以直接使用缓存的心法，避免每次统计都请求外部心法接口。

## 目标

- 「竞技排名统计 缓存心法」触发统计时，心法解析优先读取已有心法缓存。
- 「竞排名 缓存心法」作为线上常用简称，同样触发缓存心法统计。
- 缓存命中时不再请求实时心法接口或 defget 竞技场数据。
- 缓存未命中时保留现有实时查询与兜底逻辑，保证统计结果尽量完整。
- 普通「竞技排名统计」行为保持不变。

## 边界：缓存心法作为独立 token

- 使用 `message_text.split()` 按空白字符分词后判断 `"缓存心法" in tokens`。
- 入口正则接受 `竞技排名`、`竞技排名统计`、`竞排名` 三种前缀，并允许 `拆分`、`橙武占比`、`缓存心法`、`debug` 作为独立参数组合。
- 「不缓存心法」不会匹配：因为 `split()` 将其作为单个 token `"不缓存心法"`，不等于 `"缓存心法"`。
- 同理，`"禁用缓存心法"`、`"关闭缓存心法"` 等均不会意外启用缓存模式。

## 涉及文件

- `src/plugins/jx3bot_handlers/jjc_ranking.py`
  - 解析消息文本中的「缓存心法」参数。
  - 将 `use_cached_kungfu` 透传给 service。
  - 调整等待提示文案，便于识别缓存模式。
- `config.py`
  - 更新「竞技排名」入口正则，兼容 `竞排名` 简称并允许 `缓存心法` 参数进入 handler。
- `src/plugins/jx3bot.py`
  - 复核注册调用；当前通过关键字透传 service 方法，无需代码修改。
- `src/services/jx3/jjc_ranking.py`
  - `get_ranking_kungfu_data` 增加 `use_cached_kungfu` 参数。
  - `get_user_kungfu` 增加 `prefer_cache` 参数，开启时先调用 `JjcCacheRepo.load_kungfu_cache`。
  - 缓存未命中继续现有实时查询路径。
- `tests/test_jjc_ranking_history_win_kungfu.py`
  - 增加缓存优先命中时不调用实时查询/defget 的回归测试。

## 验证

- 运行 `python -m unittest tests.test_jjc_ranking_history_win_kungfu`。
- 运行 `python -m py_compile src/plugins/jx3bot_handlers/jjc_ranking.py src/plugins/jx3bot.py src/services/jx3/jjc_ranking.py`。

## 风险与回滚

- 风险：只有缓存中没有心法时才会回落实时查询；如果缓存心法较旧，统计结果会按用户显式选择优先展示旧缓存。
- 原始/旧缓存命中时可能缺少 `weapon`、`weapon_quality`、`teammates` 等辅助元数据；下游统计与渲染代码已统一使用 `.get()` 访问这些字段，缺失时不会崩溃。
- 回滚：移除新增参数和 handler 解析即可恢复原行为，不涉及数据迁移。

## 执行状态

- [x] 计划创建
- [x] 代码实现
- [x] 自动化验证
