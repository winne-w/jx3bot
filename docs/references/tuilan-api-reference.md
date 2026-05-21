# 推栏接口参考

更新时间：2026-05-19

本文记录基于 `Stream-2026-05-19 13_44_18.har` 和实测请求整理出的推栏接口形态。敏感请求头如 `token`、`Cookie`、`X-Sk`、`deviceid`、`clientkey`、`sign` 不在本文记录具体值。

## 公共约定

- Host: `https://m.pvp.xoyo.com`
- 方法：抓包中的业务接口均为 `POST`
- 请求体：JSON
- 公共入参：多数接口需要 `ts`，格式为 `yyyyMMddHHmmssSSS`
- 公共响应：通常为 `{"code": 0, "msg": "success", "data": ...}`
- HAR 中部分响应为 `base64 + br`，解码后是 JSON。

## 对局历史

### `/3c/mine/match/history`

入参：

```json
{
  "global_role_id": "SK01-...",
  "size": 6,
  "cursor": 0,
  "ts": "20260519054220529"
}
```

出参 `data[]` 主要字段：

| 字段 | 说明 |
|---|---|
| `match_id` | 对局 ID，可继续请求 `match/detail` 或 `match/replay` |
| `won` / `mvp` | 胜负与 MVP |
| `start_time` / `end_time` | 对局开始/结束 Unix 秒 |
| `kungfu` | 心法标识 |
| `total_mmr` / `mmr` | 当前分/本场分差 |
| `level` / `avg_grade` | 段位/均装等 |
| `global_role_id` | 对局记录中的全局 ID 字段；实测可能不是请求入参的同一个 `SK01-...` |
| `zone` / `server` | 区服 |
| `pvp_type` | 实测 3 表示 3v3 |
| `videoNum` / `hidden` | 录像数量/隐藏状态 |

### `/3d/mine/match/history`

入参与响应结构和 `/3c/mine/match/history` 一致。

实测结论：

- 使用同一请求体请求 `/3c/mine/match/history` 与 `/3d/mine/match/history`，完整 JSON 响应完全一致。
- 两个端点可共用同一个请求模型。
- 目前不能仅凭路径中的 `3c` / `3d` 判断是否为 3v3，仍应以返回项 `pvp_type` 为准。

## 对局详情

### `/3c/mine/match/detail`

入参：

```json
{
  "match_id": 255946971,
  "ts": "20260519054222245"
}
```

出参 `data` 主要字段：

| 字段 | 说明 |
|---|---|
| `match_id` / `match_time` | 对局 ID 和对局时间 |
| `basic_info` | 录像地址、截图、地图、类型、时长等 |
| `team1` / `team2` | 双方队伍 |
| `team*.players_info[]` | 玩家详情 |

`players_info[]` 主要字段：

```text
role_name, global_role_id, role_id, person_id, person_name, person_avatar,
zone, server, total_count, win_count, win_rate, mvp_count, mmr, score,
total_score, ranking, kungfu, kungfu_id, mvp, equip_score,
equip_strength_score, stone_score, max_hp, metrics, armors, talents,
body_qualities, odd, fight_seconds
```

实测限制：

- HAR 中 `players_info[].role_id` 字段存在但值全为空字符串。
- HAR 中 `players_info[].global_role_id` 字段存在但值全为空字符串。
- 可用字段主要是 `person_id`、`server`、`role_name`、`kungfu`、`kungfu_id` 等。

### `/3d/mine/match/detail`

入参与响应结构和 `/3c/mine/match/detail` 一致。

实测限制同上：`players_info[].role_id` 与 `players_info[].global_role_id` 字段存在但为空。

## 对局回放

### `/3c/mine/match/replay`

入参：

```json
{
  "match_id": 255946971,
  "ts": "20260519054222470"
}
```

出参 `data` 主要字段：

| 字段 | 说明 |
|---|---|
| `match_id` | 对局 ID |
| `match_duration` | 对局时长 |
| `replay[]` | 技能事件，含 `ts`、`skillId`、`skillName`、`casterId`、`targetId` |
| `skill_cate` | 技能分类 |
| `players[]` | 参战玩家 |

`players[]` 主要字段：

```text
role_id, global_role_id, role_name, kungfu_id, kungfu_name, kungfu_icon,
team, treat_trend, attack_trend
```

实测结论：

- HAR 中 `/3c/mine/match/replay` 的 `players[].role_id` 全部有值。
- Mongo 中任取一条已同步对局 `match_id=253750209` 请求 `/3c/mine/match/replay`，返回 6 个玩家且 `role_id` 全部有值。
- `players[].global_role_id` 是纯数字字符串，和 `/role/indicator`、`match/history` 使用的 `SK01-...` 不是同一格式，不能直接当作同步主键使用。

### `/3d/mine/match/replay`

入参与响应结构和 `/3c/mine/match/replay` 一致。

## 个人历史与身份

### `/mine/match/person-history`

入参：

```json
{
  "person_id": "94c7572462894548b8573950332ab9b2",
  "size": 10,
  "cursor": 0,
  "ts": "20260519054254182"
}
```

出参 `data[]` 主要字段：

```text
match_id, won, official_recommended, mvp, start_time, end_time,
kungfu, total_mmr, mmr, level, avg_grade, global_role_id, zone,
server, pvp_type, hidden, person_name, person_id, person_avatar,
role_name, status, medalUrl, videoNum
```

实测限制：

- 返回 `global_role_id`、`zone`、`server`、`role_name`、`person_id`。
- 不返回 `role_id`。

### `/role/indicator`

入参：

```json
{
  "role_id": "29528125",
  "zone": "电信区",
  "server": "唯我独尊",
  "ts": "20260519054220529"
}
```

出参 `data` 主要字段：

| 字段 | 说明 |
|---|---|
| `person_info.person_id` | 推栏个人 ID |
| `person_info.person_name` | 推栏昵称 |
| `role_info.global_role_id` | `SK01-...` 格式全局角色 ID |
| `role_info.role_id` | 角色 ID |
| `role_info.name` | 角色名 |
| `role_info.zone` / `role_info.server` | 区服 |
| `indicator[]` | 指标数组 |

实测结论：

- `/role/indicator` 不能直接用 `global_role_id` 查询。
- 必须先有 `role_id + zone + server`。
- 如果只有 `global_role_id`，可先通过 `match/history` 找 `match_id`，再通过 `match/replay` 找 `role_id`，最后请求 `/role/indicator`。

### `/mine/performance/home-page`

入参：

```json
{
  "person_id": "94c7572462894548b8573950332ab9b2",
  "ts": "20260519054253797"
}
```

出参 `data` 主要字段：

```text
match_type, metrics, performance, role_info, person_info
```

`role_info` 含：

```text
global_role_id, role_id, name, force, body_type, camp, zone, server
```

注意：

- 该接口可通过 `person_id` 拿到一个角色的 `role_id/global_role_id`。
- 返回角色可能是用户主页/当前展示角色，不一定等于某场对局中的目标角色，使用时必须用 `server + role_name` 等字段再次校验。

## 表现统计

### `/3c/mine/performance/trends/recent` 与 `/3d/mine/performance/trends/recent`

入参：

```json
{
  "global_role_id": "SK01-...",
  "ts": "20260519054221114"
}
```

出参 `data[]`：

```text
match_date, mmr, win_rate
```

### `/3c/mine/performance/kungfu` 与 `/3d/mine/performance/kungfu`

入参：

```json
{
  "global_role_id": "SK01-...",
  "ts": "20260519054220529"
}
```

出参 `data[]`：

```text
name, skills[]
```

`skills[]`：

```text
name, icon, success_times, times, accuracy
```

## 装备

### `/mine/equip/get-role-equip`

入参：

```json
{
  "server": "唯我独尊",
  "zone": "电信区",
  "game_role_id": "29528125",
  "ts": "20260519054224814"
}
```

出参成功时包含装备、奇穴、属性等大对象。

实测限制：

- 接口有权限限制。
- 非当前账号可访问角色可能返回 HTTP 400，响应如 `{"code": -1, "msg": "this role id not belong to you", "data": null}`。

## 配置与登录态

### `/conf/server-mapping`

入参：`{"ts": "..."}`

出参包含 `mine[]`、`globalConf[]`、客户端配置、启动图等。

### `/user/login-token`

入参：`{"ts": "..."}`

出参是当前登录用户信息，包括 `id`、`nickName`、`avatarUrl`、`personNum`、`defaultPassport`、`personTags` 等。

### `/time/now`

入参：`{"ts": "..."}`

出参：`data.serverMts`，服务器毫秒时间。

## 身份补全建议链路

已知 `global_role_id`，想查 `/role/indicator`：

1. 请求 `/3c/mine/match/history` 或 `/3d/mine/match/history`，拿最近 `match_id`、`server`、`role_name` 等上下文。
2. 请求 `/3c/mine/match/replay` 或 `/3d/mine/match/replay`，从 `players[]` 中按规范化 `role_name + server` 匹配目标玩家，拿 `role_id`。
3. 使用 `role_id + zone + server` 请求 `/role/indicator`。

同步数据中发现新玩家：

1. `match/detail` 提供 `person_id + server + zone + role_name`，但 `role_id/global_role_id` 可能为空。
2. `match/replay` 可通过 `match_id` 补同场玩家的 `role_id`。
3. 使用 `role_id + zone + server` 请求 `/role/indicator`，补 `SK01-... global_role_id`、`role_id`、`person_id`、区服和角色名。
4. `person-history` 只作为 fallback：入口角色缺 `global_role_id` 且无法通过 `role_id + zone + server` 查 indicator 时，可用 `person_id` 补 `SK01-... global_role_id`，但必须做角色级校验。
5. 后续写入角色身份时，应记录本次角色信息来自哪场对局以及对局发生时间。

同步入口角色：

1. `/mine/match/history` 只能用 `SK01-... global_role_id` 查询。
2. 管理命令、CLI、对局发现、治理脚本补录的可执行同步入口，最终都必须有 `SK01-... global_role_id`。
3. 只有 `role_id` 不能直接拉 history；应先走 `/role/indicator` 拿 `SK01-... global_role_id`。
4. `match/replay.players[].global_role_id` 是纯数字字符串，不可作为 history 的 `global_role_id`。
