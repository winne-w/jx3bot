# JJC 排名与对局查询

## Purpose

定义 JJC 排名展示和角色已同步对局查询的稳定口径，确保统计与赛季隔离行为可验证。

## Requirements

### Requirement: 已同步对局按当前赛季隔离

系统 MUST 仅返回 `season_id` 与当前 `config.CURRENT_SEASON` 精确匹配的角色已同步 3v3 对局。

#### Scenario: 新赛季查询历史角色
- **WHEN** 当前赛季配置已切换且角色有历史赛季投影
- **THEN** 历史赛季投影不出现在 `synced-role-matches` 的分页结果中

### Requirement: 推栏峰值详情使用统一统计口径

系统 MUST 使用与峰值分布卡一致的时间范围和排名口径生成展开详情。

#### Scenario: 查看十四日游戏最高分详情
- **WHEN** 用户展开统计页中的峰值排行
- **THEN** 展开列表与对应分布卡使用相同的候选集合和分数定义
