## ADDED Requirements

### Requirement: 竞技排名历史按赛季列出

系统 MUST 提供竞技排名快照中可用赛季的列表，并标识最新排名快照所属赛季，供客户端建立赛季选择器。响应数据 MUST 为 `{seasons: [{name, latest_timestamp}], default_season}`；`seasons` MUST 按 `latest_timestamp` 降序排列，`default_season` MUST 等于首个赛季的 `name`，无赛季时为 `null`。

#### Scenario: 查询可用赛季

- **WHEN** 客户端请求竞技排名赛季列表
- **THEN** 系统返回所有具有排名统计快照的赛季名称及其最近快照时间，并返回最新快照所属的默认赛季名称

### Requirement: 获取一个赛季的完整历史快照

系统 MUST 支持客户端按赛季请求排名快照元数据，并返回该赛季的全部快照，不得受其他赛季快照数量或全局分页窗口影响。响应数据 MUST 为 `{season, items, total}`；每个 `items` 元素 MUST 包含 `timestamp`、`generated_at`、`ranking_cache_time`、`default_week`、`current_season`、`week_info`、`is_settlement` 与 `snapshot_kind`，且 `items` MUST 按 `timestamp` 降序排列。

#### Scenario: 查询当前赛季完整历史

- **WHEN** 客户端请求当前赛季的排名历史
- **THEN** 系统只返回该赛季的全部快照元数据，包含其最早周次的快照

#### Scenario: 切换查询历史赛季

- **WHEN** 客户端选择并请求另一个可用赛季
- **THEN** 系统只返回所选赛季的全部快照元数据

#### Scenario: 请求不存在的赛季

- **WHEN** 客户端请求没有排名快照的赛季
- **THEN** 系统返回空历史列表而非其他赛季的快照

### Requirement: 页面按选择赛季展示快照

竞技排名页面 MUST 在初始加载时选择最新排名快照所属赛季，并在赛季下拉框中展示所有可用赛季；切换选择后，页面 MUST 使用所选赛季的完整历史快照更新周次和快照选择器。页面 MUST 忽略已被后续赛季选择取代的历史请求响应；加载失败时 MUST 保留最近一次成功展示的数据并显示错误。

#### Scenario: 初始加载页面

- **WHEN** 用户打开竞技排名页面
- **THEN** 页面展示所有可选赛季，并加载最新排名快照所属赛季的完整历史快照

#### Scenario: 用户切换赛季

- **WHEN** 用户在赛季下拉框选择另一个赛季
- **THEN** 页面请求该赛季的完整历史快照，且不展示先前赛季的周次或快照选项

#### Scenario: 没有可用赛季

- **WHEN** 赛季列表为空
- **THEN** 页面显示无可用历史快照的空状态，且不请求赛季历史

#### Scenario: 赛季历史加载失败

- **WHEN** 用户切换赛季后的历史请求失败
- **THEN** 页面保留最近一次成功展示的周次和快照，并显示加载错误
