## 自动化验证

```bash
.venv/bin/python -m unittest tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend
.venv/bin/python -m py_compile src/storage/mongo_repos/jjc_ranking_stats_repo.py src/api/routers/jjc_ranking_stats.py
node -e "...new Function(script)..."
openspec validate jjc-ranking-season-history --strict
git diff --check
```

结果：63 个单元测试通过；Python 编译、页面内联脚本语法、OpenSpec 严格校验和 diff 空白检查均通过。

覆盖项：

- 赛季按最近快照降序与默认赛季；字符串和历史数值赛季兼容。
- 指定赛季完整历史、未知赛季及空赛季参数。
- 原有 `action=list` 未分页、分页和元数据返回兼容。
- 前端赛季接口、空状态、失败恢复、请求失效保护与切换加载态。

## Mongo 冒烟

连接本地已配置 Mongo 后，`action=seasons` 对应仓储结果为：

- 可用赛季：`暗影千机`、`山海源流`
- 默认赛季：`暗影千机`
- 默认赛季完整历史：175 条
- 最早周次：`第1周 周5 10:28`

验证仅执行只读查询；初始化连接时会运行项目既有的幂等索引检查。
