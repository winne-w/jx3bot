# TDD 测试计划

## 自动化矩阵

service：显式 tag 绕过时间标签和共享缓存，已有其他周缓存不影响结果；结果 defaultWeek 与传入值一致；默认缓存命中不调用接口；未命中用 defaultWeek 而非列表最大值；时间标签错误保持兼容；手动排行榜 error、非零 code、异常不回退；非法 service tag 请求前拒绝。

命令：三个别名、现有选项任意排序、空白；无参数保持原调用；显式值准确透传；空值、非数字、零、负数、小数、重复 tag 提示且不查询；无关选项仍不匹配；周次计算、存档、图片参数一致。

## 命令

RED/GREEN 分别运行 `.venv/bin/python -m unittest tests.test_jjc_ranking_explicit_tag -v` 与 `.venv/bin/python -m unittest tests.test_jjc_ranking_command_tag tests.test_config_regex -v`。

整合回归：`.venv/bin/python -m unittest tests.test_jjc_ranking_explicit_tag tests.test_jjc_ranking_command_tag tests.test_config_regex tests.test_jjc_ranking_history_win_kungfu tests.test_status_monitor_jobs_admin_notification`。

语法检查：`.venv/bin/python -m py_compile config.py src/plugins/jx3bot_handlers/jjc_ranking.py src/services/jx3/jjc_ranking.py`。OpenSpec：`openspec validate jjc-ranking-explicit-tag --strict`。

## 手工回归

在连接 QQ 和合法推栏凭据的环境发送 `竞技排名 tag=40`、`竞排名 拆分 tag=40 缓存心法`、`竞技排名 tag=abc` 及不带 tag 命令；核对实际可用 tag、图片周次、错误提示及日志中无时间标签请求。离线测试不代替在线验收，不在本次自动执行中请求生产接口或发送 QQ。

## 结果

A RED：service 7 tests，13 个子场景因方法不支持 tag 产生预期 TypeError；已有默认路径通过。A GREEN：同命令 7 tests 通过，另与历史心法回归联合 49 tests 通过。

B RED：命令与正则 9 tests，22 个失败子场景，分别是未透传 tag、非法 tag 仍调用查询、正则不匹配 tag。B GREEN：同命令 9 tests 通过；另补空 tag 后接缓存心法边界并复跑通过。

主 agent 整合执行上述五模块回归：63 tests，0.090s，OK。语法检查、OpenSpec 严格校验通过。

环境发现：Python 实际为 3.13，原 service 测试在 asyncio 线程池关闭阶段挂起，faulthandler 栈位于 Runner.close。测试用 async 函数隔离 to_thread 调度，仍执行 API 边界替身并检查真实 service 返回和调用参数；生产代码未为测试作修改。此测试不验证 Python 线程调度机制。

在线 QQ/推栏与真实图片渲染未执行，按以上手工路径在部署环境验证。
