# 最近 3v3 对局装备查询方案

## Problem

现有装备查询上游已失效，无法再获取通用角色当前装备。仓库已有推栏对局详情能力和装备快照解析，但没有面向 QQ `属性/装分` 命令的独立查询用例。

## Goals

- 以最近 3v3 对局详情替换已失效的装备查询能力。
- 最大化复用本地身份和已有推栏客户端，避免散写外部 HTTP 请求。
- 让用户明确知道展示的是对局时快照，而非实时面板。

## Non-Goals

- 不伪造或推断角色当前装备。
- 不改变 JJC 同步 worker、历史对局页或存储集合结构。
- 不在查询失败时使用本地历史详情作为备用数据源。

## Current State

`src/plugins/jx3bot_handlers/queries.py` 的装备 matcher 当前直接返回不可用提示。`src/services/jx3/match_detail.py` 已能解析推栏对局详情中的装备、属性和装分字段；`RoleIdentityRepo` 已能按同服同名选取最佳本地身份，并支持身份字段合并写入。现有 JJC inspection/sync service 也已封装推栏 history/detail 客户端。

## Proposed Solution

新增一个位于 `src/services/jx3/` 的装备查询编排 service，入口仅传入 `server` 与 `name`，输出面向渲染的结构化结果或稳定错误码。它先通过 `RoleIdentityRepo.find_best_by_name_with_id()` 读取本地身份；如果没有可用的 `role_id` 和 `zone`，则通过 infra 中的 JX3API 客户端请求 `/role/detail`，再通过既有 repo upsert 接口合并写回角色身份。

取得身份后，service 调用既有推栏 indicator 客户端取得 `global_role_id`，调用既有 match history client，过滤 3v3 记录并按 `start_time` 降序选择第一条。随后调用 match detail client，按规范化服务器和角色名从两队玩家中精确取出一个目标。service 将 raw `armors`、`metrics`、`body_qualities` 和 `equip_score` 等数据转换为模板所需的装备位和面板字段；handler 只负责参数解析、调用 service、渲染和发送。

## Data and Storage Impact

不新增集合、字段、索引或 TTL。只有 JX3API 补齐成功时，更新既有 `role_identities` 中缺失的 `role_id`、`zone`、`global_id`、服务器和角色画像字段；更新规则复用仓储已有的身份强度和时间保护，避免低可信输入覆盖较强身份。

## API and UI Impact

QQ 命令名称和参数保持不变。成功图片标题采用“最近 3v3 对局装备快照”，并展示对局时间、角色、服务器、心法、总装分及拆分。图片含所有装备位的名称、品质、精炼、附魔、五彩石，以及推栏返回的属性指标和 body qualities。失败文字需区分身份未解析、没有 3v3、详情未包含角色/装备和上游异常。

2026-07-29 调整展示口径：总装分必须等于 `equip_score + equip_strength_score + stone_score`，不再展示三项拆分；模板不展示任何 `mount1` 至 `mount4` 五彩石槽位、ID 或属性。属性区域使用白名单，从 `body_qualities` 取会心、无双、破招、会心效果、加速、内功防御、外功防御、化劲、根骨，并从 `max_hp` 补气血；上游未提供的破防和基础攻击力不显示。装备项继续显示名称、品质、精炼和附魔文字。

## Risks and Rollback

推栏详情是历史快照，故在标题与时间位置持续标注其含义。身份数据可能陈旧或角色转服，故只接受同服同名精确匹配，JX3API 补齐只合并缺失字段。推栏接口失败时不使用陈旧装备，返回明确错误。回滚方式是恢复装备 matcher 的当前不可用提示，不影响 JJC 同步和既有缓存数据。

## Confirmation

2026-07-28：用户确认本方案。
