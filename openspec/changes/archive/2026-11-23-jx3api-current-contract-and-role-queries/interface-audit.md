# Interface Audit

文档来源：https://www.jx3api.com/#/arena/recent 与 https://www.jx3api.com/openapi，读取日期2026-11-23。15端点均使用status/detail。源码盘点含config、defget.fetch_json、status_monitor直接httpx入口及根jjc_query.py。

| 功能 | 当前路径 | 修复要点 |
|---|---|---|
|烟花|`/firework/records`|header token；receiver/mapName/firework字段投影|
|奇遇|`/event/records`|header token；nullable time→未知显示|
|战绩|`/arena/recent`|保留上轮status/detail及header token|
|名片|`/card/record`|header token；showAvatar/showHash已真实核对|
|百战|`/monster/records`|header token；保留旧角色字段投影|
|资历|`/role/achievement`|替代/tuilan/achievement；class=3；真实未绑定404提示|
|日常|`/active/calendar`|公开接口；lucky及weekly投影|
|科举|`/exam/search`|公开接口；index→id|
|骗子|`/fraud/detail`|header token；角色UID范围；dict/list投影；失败不冒称无记录|
|开服|`/server/status/check`|公开接口；单服list/dict安全选择；保留事件时间语义|
|维护公告|`/news/announce`|catid→id；CST时间；失败明确提示|
|新闻|`/news/records`|同上；保留id水位/失败不覆盖|
|技改|`/skill/rework`|CST时间；消费者兼容字符串和epoch|
|装备属性（新增）|`/calcd/attribute`|header token；完整装备/面板；无需ticket|
|在线状态（新增）|`/role/online/status`|POST JSON ticket/query；header token；不缓存|

推栏m.pvp.xoyo.com、万宝楼、魔盒奖励、NapCat及自有API保持原链路。旧副本/团队CD接口仍不在当前文档内，保持明确暂不可用提示，不虚构替代接口。
