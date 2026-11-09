# JJC 最新战绩刷新测试记录

日期：2026-10-20。验收目标是直连回退后的最新摘要链路，官方请求全部使用 stub；真实数据库测试只连接本机临时 Mongo，不使用生产连接串。

## 自动化验证

以下第一组 67 项、第二组 31 项通过，共 98 项离线回归：

```bash
.venv/bin/python -m unittest tests.test_tuilan_request tests.test_jjc_live_refresh tests.test_jjc_live_refresh_routes tests.test_jjc_live_refresh_runtime tests.test_jjc_ranking_stats_router tests.test_jjc_data_center_navigation tests.test_jjc_ranking_stats_frontend tests.test_jjc_matchups_frontend
.venv/bin/python -m unittest tests.test_jjc_match_detail_hydration tests.test_jjc_sync_worker_runtime
```

新增路由覆盖有效提交、缺失/非字符串/空名称、HTTP 429/503 和 Retry-After、非可信转发头及可信代理链。生命周期覆盖幂等启动、停止取消、缺失来源密钥以及就绪检查/存储初始化异常隔离。先观察初始化和就绪检查异常回归报错，再修复为四项通过。

不同历史测试的 import stub 会污染同一解释器中的 nonebot logger。曾把以上所有模块一次合跑，详情测试遇到 stub 缺少 warning 的 AttributeError；分组使用独立解释器完成验证，不能将其描述为整仓单进程测试通过。

额外执行 `timeout 45s .venv/bin/python -m unittest tests.test_jjc_ranking_inspect`，全模块未在时限内结束（退出码 124），不计为通过。该模块与现有 inspect 源码没有内容变更；本次详情兼容性证据来自上述独立完成的 hydration、路由和同步 worker 测试。

隔离 MongoDB 7.0.16 仅监听 `127.0.0.1:27187`，数据目录 `/tmp/jjc-test-mongodb-data`。显式执行：

```bash
JJC_TEST_MONGO_URI='mongodb://127.0.0.1:27187/?serverSelectionTimeoutMS=1500' .venv/bin/python -m unittest -v tests.test_jjc_live_refresh_mongo
```

7 项全部通过，无跳过：跨进程相同角色去重、总容量、旧 generation 无法发布或释放新槽、空成功冷却、首屏先于第二页可读、快照与状态同版本、旧摘要合并与第二页失败保留、未知身份及来源限频。每个用例使用随机命名临时数据库并在结束时删除。此单节点测试不证明副本集故障转移。

## 浏览器与竞态

从项目根目录执行以下可复现脚本。浏览器脚本依赖已有 Playwright 和 Chromium，所有请求由本地页面或 fixture 响应，不需要启动 bot 或 HTTP 服务。

```bash
node openspec/changes/jjc-safe-live-refresh/history-race-smoke.cjs
.venv/bin/python openspec/changes/jjc-safe-live-refresh/browser-smoke.py
```

Node 直接提取真实页面函数，4 项定向竞态通过；Chromium 在 1920×1080 和 390×844 下共 20 项通过。覆盖关闭功能可读摘要、提交成功、精确十次轮询上限、503 保留历史、刷新中保留已加载页、旧角色 POST/轮询/分页成功和失败响应隔离，以及刷新与加载更多的两个并发方向。浏览器只将 3000ms 轮询延迟加速为 25ms；不验证真实上游耗时。无意外 console/pageerror，预期的 HTTP 503 已单独解释。截图写入 `/tmp/jjc-refresh-*.png`。

完整浏览器验证执行于 `/tmp/jjc-live-refresh-browser-qa.py`；将同一脚本保存到 change 时只把资源根改为相对脚本定位，保存路径的 Python 语法检查与资源路径核对通过。Node 在 change 内的最终保存路径已实际执行通过。

修复前真实浏览器在两个视口均复现第 1 页和第 3 页同时显示而第 2 页丢失；Node 四项均失败。修复增加刷新/分页互斥、搜索 token、刷新 generation 和角色快照校验后，同一组脚本通过。

## 兼容与文档

8 个修改/新增运行源码的 py_compile 和 Python 3.9 AST 语法检查通过；实际运行解释器为 Python 3.13，不宣称已在 Python 3.9 运行全部用例。`openspec validate jjc-safe-live-refresh --strict` 和 `git diff --check` 通过。共享预算历史文件保留为档案，当前 proposal/design/spec 只描述最终直连行为。

## 上线前手工验证

保持默认关闭。在部署环境配置有效凭据、来源密钥、可信代理后，检查 worker 在线、已知角色刷新、真实上游字段、公开状态和关闭开关后仍能读取本地摘要。此路径未在本轮执行；不得把本地 fixture 结果视为凭据有效性、官方限频或生产性能验收。
