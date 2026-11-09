# 开发验收记录

已实现：QQ 三个排名命令支持 tag=<正整数>，与原选项组合；显式 tag 跳过时间标签接口和默认排行榜缓存，结果 defaultWeek 为实际请求 tag；默认逻辑兼容，非法/重复参数提前提示，手动请求失败不回退。

验证：主 agent 五模块联合回归 63 tests 通过；独立 reviewer 同样 63 tests 通过；py_compile、Python 3.9 ast.parse 语法检查、OpenSpec 严格校验通过。RED/GREEN 记录见 test-plan.md。

限制：未连接 QQ/推栏生产服务，未做在线图片冒烟。历史 tag 的心法仍按原有逻辑获取；年份及赛季周次继续沿用原解析规则。

上线手工路径见 docs/references/runbook.md 与 test-plan.md。回滚本需求提交即可，无数据库迁移。本 change 暂保留 active，待用户在线验收后同步主规格并归档。
