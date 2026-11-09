# JJC 展示页面文案与同步状态简化计划

状态：已完成，已归档
更新时间：2026-05-29

## 背景

排名展示页 `public/jjc-ranking-stats.html` 与已同步对局页 `public/jjc-synced-matches.html` 复用了一部分对局列表和详情弹窗渲染逻辑。当前列表会展示“X段局”，详情弹窗地图直接展示数字地图 ID；已同步对局页还展示了身份信息与同步细节卡片，干扰用户查看对局结果。

## 目标

- 两个页面的对局列表不再出现“X段局”，改为只展示“X段”。
- 两个页面的对局详情地图按固定映射展示中文名称，未知值保留原值或 `-`。
- 已同步对局页不展示 `identity-grid` 与 `sync-grid` 模块。
- 已同步对局页列表条目不展示“详情同步”和“保存时间”。
- 已同步对局页列表条目不展示对局段位；本地已保存对局列表数据可能没有 `avg_grade`，避免展示无意义的 `-`。
- 已同步对局页列表上方保留“最后同步时间”；同步状态只有 queued 时展示“已排队，第 N 位”，其他状态统一展示“未在排队”。
- 已同步对局页面向非技术用户优化文案，避免在用户界面展示 `global_id`、“本地已保存”、“落库”、“身份”、“缓存”、“接口”等技术词。

## 改动范围

- `public/jjc-ranking-stats.html`
  - 新增地图 ID 到中文名称的前端映射函数。
  - 调整近期对局列表分段文案。
  - 对局详情地图字段走映射函数。
- `public/jjc-synced-matches.html`
  - 同步以上列表/详情展示。
  - 移除页面主体中的身份卡片和同步卡片渲染。
  - 简化列表行元信息、移除对局段位字段，并调整列表上方同步状态文案。
  - 将用户可见文案调整为“可查看对局”“更新对局”“详情更新时间”等非技术表达。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 增加 queued 角色队列位置计算，排序口径与 worker 领取一致：`priority` 降序、`queued_at` 升序。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 序列化同步状态时为 queued 状态补充 `queue_position`。

## 验证

- 前端脚本语法检查：

```bash
node -e "const fs=require('fs'); for (const f of ['public/jjc-ranking-stats.html','public/jjc-synced-matches.html']) { const html=fs.readFileSync(f,'utf8'); [...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].forEach((m)=>new Function(m[1])); } console.log('scripts ok')"
```

- Python 语法检查：

```bash
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_sync_repo.py
```

- 手工回归：
  - 打开排名页角色近期对局，确认列表是“X段”，详情地图是中文名。
  - 打开已同步对局页，确认搜索结果不显示身份和同步细节卡片，列表不显示对局段位，只展示开始时间/时长，列表上方只显示“未在排队”或“已排队，第 N 位”和最后同步时间。
  - 确认已同步对局页用户可见区域不再出现 `global_id`、“本地已保存”、“落库”、“身份”、“缓存”、“接口”等技术词。

## 执行记录

2026-05-27：

- 已完成两个页面的分段文案、地图名称映射与已同步对局页展示简化。
- 已为 queued 同步状态补充 `queue_position`，前端据此展示“已排队，第 N 位”。
- 已按线上反馈移除已同步对局页列表中的对局段位字段，避免缺少 `avg_grade` 时展示 `-`。
- 已优化已同步对局页用户文案，降低非技术用户理解成本。
- 已执行验证：
  - `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_sync_repo.py`
  - `node -e "const fs=require('fs'); for (const f of ['public/jjc-ranking-stats.html','public/jjc-synced-matches.html']) { const html=fs.readFileSync(f,'utf8'); [...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].forEach((m)=>new Function(m[1])); } console.log('scripts ok')"`
  - `python -m unittest tests.test_jjc_ranking_inspect.TestJjcSyncedRoleInspect`

2026-05-29：

- 已随提交 `99b01e6` 落地并归档到 `completed/`。

## 回滚

回滚上述文件改动，并更新 `docs/exec-plans/index.md`。
