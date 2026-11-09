## ADDED Requirements

### Requirement: QQ 竞技排名支持显式 tag

系统 MUST 支持竞技排名、竞技排名统计、竞排名命令的可选 tag=<正整数>，允许其与现有选项任意排序；非法或重复 tag MUST 提示用法且不查询。

#### Scenario: 手动指定 tag
- **WHEN** 用户输入 `竞技排名 tag=40`
- **THEN** 系统 MUST 使用整数 40 查询排行榜，MUST NOT 查询时间标签接口或读写默认排行榜缓存
- **AND** 返回 defaultWeek MUST 为 40，后续周次计算与存档 MUST 使用该结果

#### Scenario: 省略 tag
- **WHEN** 用户输入不带 tag 的现有竞技排名命令
- **THEN** 系统 MUST 保持现有共享缓存行为，未命中时 MUST 使用时间标签接口 data.defaultWeek

#### Scenario: 非法或重复 tag
- **WHEN** 用户提供空值、非整数、非正整数或重复 tag
- **THEN** 系统 MUST 返回用法提示且 MUST NOT 调用排行榜查询

#### Scenario: 手动请求失败
- **WHEN** 手动 tag 对应排行榜查询失败
- **THEN** 系统 MUST 返回错误且 MUST NOT 回退为默认 tag 查询
