# QQ 竞技排名手动指定 tag

## Why

当前 QQ 命令无法手动指定排行榜 tag；默认缓存未命中时依赖时间标签接口。需要允许用户直接查询指定 tag。

## What Changes

命令增加 tag=<正整数>，service 增加可选 tag 参数。指定 tag 跳过时间标签接口及默认排行榜缓存读写，结果 defaultWeek 使用实际 tag。非法输入在请求前拒绝，接口失败不回退默认查询。

## Capabilities

### Modified Capabilities

- `jjc-ranking`: QQ 查询可手动指定排行榜 tag。

## Impact

修改 config.py 命令正则、QQ ranking handler、JjcRankingService.query_jjc_ranking，补充离线测试与使用文档。不改变外部 API 请求格式和数据库结构。
