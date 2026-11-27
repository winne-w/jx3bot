# 测试验证记录：全站视觉风格统一（unify-visual-style）

日期：2026-11-26

## 1. 自动化测试矩阵

1. **TDD 先行（RED -> GREEN）**：
   - 新增 `tests/test_visual_style_unification.py`（11 个测试方法）并扩展 `tests/test_jjc_data_center_navigation.py`（共 10 个测试方法）。
   - 实现前运行确认 62 项子断言预期失败（RED）；实现及审查加固后全部转为 GREEN。
2. **双 Python 版本语法编译与单测回归（Python 3.9.25 + Python 3.13.2）**：
   - 编译检查文件：`src/infra/screenshot.py`、`src/renderers/jx3/jjc_ranking.py`、`src/renderers/jx3/image.py`、`src/services/jx3/query_context.py`、`src/services/jx3/role_queries.py`、`src/plugins/wanbaolou/__init__.py`、`src/plugins/jx3bot_handlers/trade.py`、`src/plugins/jx3bot_handlers/zili.py`、`src/plugins/jx3bot_handlers/help.py` 及测试文件。
   - 回归单测模块（16 个模块）：
     - `tests.test_visual_style_unification`
     - `tests.test_jjc_data_center_navigation`
     - `tests.test_jjc_ranking_stats_frontend`
     - `tests.test_jjc_matchups_frontend`
     - `tests.test_jjc_weapon_quality`
     - `tests.test_jjc_kungfu_display`
     - `tests.test_jjc_ranking_equipment_render`
     - `tests.test_jjc_ranking_equipment_frontend`
     - `tests.test_jjc_ranking_equipment_browser`
     - `tests.test_equipment_mobile`
     - `tests.test_equipment_icons`
     - `tests.test_equipment_query`
     - `tests.test_role_queries`
     - `tests.test_arena_recent_response`
     - `tests.test_jx3api_consumers`
     - `tests.test_jjc_live_refresh`
3. **Playwright Headless Chromium 离线全量渲染与零横向溢出巡检**：
   - 拦截全部外部 HTTP/HTTPS 请求，纯离线渲染全部 22 个活跃 QQ 模板（视口 `760px`、`device_scale_factor=2`，输出 `1520px` 宽 PNG），逐张断言 `scrollWidth <= clientWidth`（0 溢出）。
   - 离线路由模拟渲染全部 5 个 JJC 静态页面（桌面 `1440×900` + 移动 `390×844` 共 10 个视图），逐页断言零横向溢出、零未捕获前端异常。
4. **安全与边界回归用例**：
   - 群名/物品名含 `<梦江南><script>...` 时自动转义为 `&lt;梦江南&gt;`，无脚本注入或标签吞字；排名宏不发生双重转义。
   - 交易行部分价格/时间为 `None` 或 `<100` 铜币、竞技查询缺失时间戳或未知段位、百战整型加成字段及 `None` 技能等级均安全降级渲染，不抛 `TypeError`。

## 2. 无法离线验证的外部依赖与上线后手工冒烟路径

- 上线重启后手工触发一次 QQ 群指令：`竞技排名`、`战绩`、`装备`、`奇遇`、`外观`、`交易行`、`资历`、`百战`、`帮助`，确认真实 OneBot 图片发送与手机端显示效果。
- 浏览器访问 `/index.html`、`/jjc-synced-matches.html`、`/jjc-matchups.html`（确认顶栏无同步队列入口）并直接访问 `/jjc-sync-queue.html`（确认浅色壳层与实时队列刷新正常）。
