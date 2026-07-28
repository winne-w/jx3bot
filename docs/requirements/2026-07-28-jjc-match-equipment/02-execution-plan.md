# 最近 3v3 对局装备查询执行计划

本执行计划遵循 `docs/PLANS.md`，是本需求的持续记录。

## Purpose / Big Picture

将 `属性/装分` QQ 命令从已下线的通用装备接口，改为展示目标角色最新一场 3v3 对局发生时的装备与属性快照。身份优先来自本地 Mongo；身份不足时由 JX3API 补齐并回写；再通过推栏 indicator、history、detail 查询。

## Progress

- [x] 已确认需求、方案和设计。
- [x] 补齐 JX3API 角色详情身份回写。
- [x] 实现最近 3v3 装备查询 service。
- [x] 接入 QQ 命令与模板。
- [x] 完成验证、review 与验收记录。

## Surprises & Discoveries

- `role_identities` 可按规范化同服同名选最佳身份，但普通角色可能缺失 `role_id`、`game_role_id`、`zone`。
- history 必须按 `pvp_type=3` 过滤并按 `match_time/start_time` 倒序，不能依赖上游顺序。
- 现有 `装备查询.html` 消费下线接口的 `panelList/equipList`，不能消费 `armors/metrics/body_qualities`。
- 2026-07-28 验证中，141 个指定单元测试通过；测试输出中的身份归档、快照缺失与参与者投影 warning 是 mock 异常分支的预期日志，未形成失败。
- 本次没有可安全复用的真实 QQ/OneBot 与在线角色环境，因此未执行 QQ 运行时成功图或失败提示冒烟；此项保留为部署后手工回归，不以离线单测替代。

## Decision Log

- 2026-07-28：本地身份优先；未命中或参数不足时调用 `/role/detail` 并回写。
- 2026-07-28：无身份、无 3v3、无装备均直接提示；不读取历史 Mongo 对局兜底。
- 2026-07-28：新增独立 `JjcMatchEquipmentService`；handler 不直接访问数据库或外部接口。
- 2026-07-28：命令不变，替换 `装备查询.html` 的输入契约并固定显示快照提示。

## Outcomes & Retrospective

实现、离线验证、review 与验收记录已完成。2026-07-28 执行了指定的 141 项单元测试、相关文件的 Python 编译检查和 `git diff --check`，均以退出码 0 结束。离线覆盖了本地身份命中、JX3API 身份补齐回写、最新 3v3 选择、同服同名精确匹配、无对局/详情/装备及上游失败、渲染快照声明和 handler 失败提示。真实 QQ、Mongo 和上游 JX3API/推栏联通性仍依赖部署环境；查询链路设计上不会以 Mongo 历史对局或装备快照作 fallback。

## Context and Orientation

入口为 `src/plugins/jx3bot_handlers/queries.py:zhuangfen_to_image()`；参数继续由 `src/services/jx3/command_context.py:resolve_server_and_name()` 解析。既有边界包括 `src/infra/jx3api_get.py:get()`、`RoleIdentityRepo`、`MatchHistoryClient`、`MatchDetailClient` 与推栏 indicator fetcher。单例在 `src/services/jx3/singletons.py` 装配。

新 service 返回成功结构：

```python
{"ok": True, "snapshot": {
    "server": "唯我独尊", "role_name": "桃桃白糖", "match_id": 123,
    "match_time": 1780000000, "kungfu": "冰心诀",
    "equip_score": 0, "equip_strength_score": 0, "stone_score": 0,
    "armors": [], "metrics": [], "body_qualities": [],
}}
```

失败结构固定为 `{"ok": False, "code": "...", "message": "..."}`。`query_context.py` 仅将成功快照转换为渲染 context。

## Plan of Work

先添加来源准确的角色详情 upsert，随后以测试驱动方式实现 service：身份完整时不请求 JX3API，身份不足时补齐并回写。service 严格选择最新 3v3、精确匹配同服同名玩家。最后修改 handler、模板和运行手册，并完成自动化与线上手工回归。

## Concrete Steps

### Task 1: JX3API 角色详情身份回写

**Files:**

- Modify: `src/storage/mongo_repos/role_identity_repo.py`
- Test: `tests/test_role_identity_repo.py`

- [x] **Step 1: 写入下列失败测试。**

```python
async def test_upsert_from_jx3api_role_detail_records_source(self) -> None:
    repo = RoleIdentityRepo(db=FakeDb())
    await repo.upsert_from_jx3api_role_detail(
        server="唯我独尊", name="桃桃白糖", zone="电信区",
        role_id="29528125", global_id="270215977651548656",
    )
    saved = repo.db.role_identities.docs[0]
    self.assertEqual(saved["role_id"], "29528125")
    self.assertEqual(saved["game_role_id"], "29528125")
    self.assertEqual(saved["zone"], "电信区")
    self.assertEqual(saved["sources"], ["jx3api_role_detail"])
```

- [x] **Step 2: 验证 RED。**

Run: `python -m unittest tests.test_role_identity_repo.TestRoleIdentityRepo.test_upsert_from_jx3api_role_detail_records_source`

Expected: `AttributeError`，因为方法尚不存在。

- [x] **Step 3: 加入最小仓储方法并复用 `_upsert_identity()`。**

```python
async def upsert_from_jx3api_role_detail(
    self, server: str, name: str, *, zone: Optional[str],
    role_id: Optional[str], global_id: Optional[str], cache_repo: Any = None,
) -> Dict[str, Any]:
    return await self._upsert_identity(
        server=server, name=name, zone=zone, game_role_id=role_id,
        role_id=role_id, global_id=global_id,
        source="jx3api_role_detail", cache_repo=cache_repo,
    )
```

- [x] **Step 4: 验证 GREEN。**

Run: `python -m unittest tests.test_role_identity_repo`

Expected: 全部通过。

### Task 2: 最近 3v3 装备查询 service

**Files:**

- Create: `src/services/jx3/jjc_match_equipment.py`
- Modify: `config.py`
- Modify: `src/services/jx3/singletons.py`
- Test: `tests/test_jjc_match_equipment.py`

- [x] **Step 1: 写入失败测试。**

```python
async def test_query_uses_local_identity_and_latest_3v3_detail(self) -> None:
    result = await service.query(server="唯我独尊", name="桃桃白糖")
    self.assertTrue(result["ok"])
    self.assertEqual(result["snapshot"]["match_id"], 102)
    role_detail_fetcher.assert_not_awaited()

async def test_query_backfills_missing_identity_from_jx3api(self) -> None:
    result = await service.query(server="唯我独尊", name="桃桃白糖")
    self.assertTrue(result["ok"])
    identity_repo.upsert_from_jx3api_role_detail.assert_awaited_once()

async def test_query_returns_no_recent_3v3_without_local_fallback(self) -> None:
    result = await service.query(server="唯我独尊", name="桃桃白糖")
    self.assertEqual(result["code"], "no_recent_3v3")
```

- [x] **Step 2: 验证 RED。**

Run: `python -m unittest tests.test_jjc_match_equipment`

Expected: `ModuleNotFoundError: No module named 'src.services.jx3.jjc_match_equipment'`。

- [x] **Step 3: 实现 service 与装配。**

在 `config.py` 增加 `API_URLS["角色详情"] = "https://www.jx3api.com/role/detail"`。service 注入 `RoleIdentityRepo`、角色详情 async fetcher、indicator fetcher、`MatchHistoryClient`、`MatchDetailClient`、`tuilan_request` 与缓存 repo。`singletons.py` 使用既有 `get()`、`cfg.TOKEN` 和现有推栏客户端装配单例。

核心路径必须是：

```python
identity = await identity_repo.find_best_by_name_with_id(server, name)
if not has_tuilan_seed(identity):
    response = await role_detail_fetcher(server=server, name=name)
    detail = parse_role_detail(response)  # roleId, zoneName, globalId
    identity = await identity_repo.upsert_from_jx3api_role_detail(
        server, name, zone=detail["zone"], role_id=detail["role_id"],
        global_id=detail.get("global_id"), cache_repo=cache_repo,
    )
indicator = await fetch_indicator(identity["role_id"], identity["zone"], server)
history = await asyncio.to_thread(history_client.get_mine_match_history,
    global_role_id=indicator_global_role_id, size=20, cursor=0)
match = latest_3v3(history["data"])
detail = await asyncio.to_thread(detail_client.get_match_detail_obj, match_id=match["match_id"])
player = find_exact_player(detail, server, name)
return build_success_snapshot(player, match)
```

`latest_3v3()` 兼容 `pvp_type/pvpType/type`，仅允许值 3，按 `match_time/start_time/startTime` 整数值倒序。`find_exact_player()` 遍历 team1/team2 的 `players_info`，只接受规范化同服同名的唯一玩家，且 `armors` 必须为非空 list。service 内按 endpoint 加 asyncio 锁。错误 code 固定为 `role_identity_unavailable`、`indicator_unavailable`、`no_recent_3v3`、`match_detail_unavailable`、`target_player_not_found`、`equipment_unavailable`。

- [x] **Step 4: 验证 GREEN。**

Run: `python -m unittest tests.test_jjc_match_equipment`

Expected: 本地命中、JX3API 回写、最新时间选择、跨服同名、缺对局、缺装备与上游错误均通过。

### Task 3: 渲染模型、模板与 QQ 命令

**Files:**

- Modify: `src/services/jx3/query_context.py`
- Modify: `templates/装备查询.html`
- Modify: `src/plugins/jx3bot_handlers/queries.py`
- Test: `tests/test_jjc_match_equipment.py`

- [x] **Step 1: 写入失败测试。**

```python
def test_build_latest_match_equipment_spec_marks_snapshot_time_and_scores(self) -> None:
    spec = build_latest_match_equipment_spec(snapshot=SNAPSHOT, random_text="x")
    self.assertEqual(spec.template_name, "装备查询.html")
    self.assertEqual(spec.context["title"], "最近 3v3 对局装备快照")
    self.assertEqual(spec.context["snapshot"]["match_id"], 102)
    self.assertIn("对局时间", spec.context["match_time_label"])
```

- [x] **Step 2: 验证 RED。**

Run: `python -m unittest tests.test_jjc_match_equipment.TestEquipmentRenderSpec.test_build_latest_match_equipment_spec_marks_snapshot_time_and_scores`

Expected: 缺少 `build_latest_match_equipment_spec`。

- [x] **Step 3: 实现渲染和入口。**

`query_context.py` 增加 `build_latest_match_equipment_spec(snapshot, random_text, time_filter)`，返回 `RenderSpec(template_name="装备查询.html", width=1180, height="ck")`，context 只有 `title`、`snapshot`、`match_time_label`、`text`。移除旧 `build_zhuangfen_spec()` 对下线 `panelList/equipList` 的依赖。

`装备查询.html` 显示标题、角色、区服、心法、对局时间、总装分/装备分/精炼分/五彩石分；遍历 `snapshot.armors` 输出 icon、name、quality、strength_evel、permanent_enchant、temporary_enchant、mount1 至 mount4；遍历 `snapshot.metrics` 和 `snapshot.body_qualities` 输出属性。底部固定文本为“数据为最近 3v3 对局发生时的装备快照，不代表当前实时面板”。

handler 解析参数后调用 service；失败用 `send_text(bot, event, result["message"], at_user=True)`，成功构建 spec 并经 `render_and_send_template_image()` 发送。handler 不直接访问 Mongo、JX3API 或推栏。

- [x] **Step 4: 验证 GREEN。**

Run: `python -m unittest tests.test_jjc_match_equipment tests.test_jjc_match_detail_hydration tests.test_jjc_ranking_inspect`

Expected: 全部通过。

### Task 4: 文档、验证、review 与验收

**Files:**

- Modify: `docs/references/runbook.md`
- Create: `docs/requirements/2026-07-28-jjc-match-equipment/03-test-plan.md`
- Create: `docs/requirements/2026-07-28-jjc-match-equipment/04-review.md`
- Create: `docs/requirements/2026-07-28-jjc-match-equipment/05-acceptance.md`

- [x] **Step 1: 更新手工回归文档。**

将“属性/装分接口暂不可用”替换为：对有近期 3v3 的角色执行 `属性 <服务器> <角色>`，确认快照提示、对局时间、装备、属性和三项装分；对无 3v3 或未知角色确认直接提示、不会读取本地历史对局。

- [x] **Step 2: 写入测试、review 和验收文档。**

`03-test-plan.md` 记录：

```bash
python -m unittest tests.test_role_identity_repo tests.test_jjc_match_equipment tests.test_jjc_match_detail_hydration tests.test_jjc_ranking_inspect
python -m py_compile config.py src/storage/mongo_repos/role_identity_repo.py src/services/jx3/jjc_match_equipment.py src/services/jx3/query_context.py src/services/jx3/singletons.py src/plugins/jx3bot_handlers/queries.py
git diff --check
```

`04-review.md` 核对分层、身份保护、同名跨服、token 脱敏、错误语义、模板快照提示与文档一致性。`05-acceptance.md` 记录真实成功/失败命令、自动化输出、上游风险和回滚步骤。

- [x] **Step 3: 运行验证并填入真实结果。**

Expected: 所有单测和 `py_compile` 通过，`git diff --check` 无输出，QQ 手工验证覆盖成功图与失败提示。

## Validation and Acceptance

验收时，本地身份完整的角色不请求 JX3API 仍返回最新 3v3 快照；身份不足时 JX3API 补齐并回写后成功；无身份、无 3v3、详情缺角色或缺装备时不读历史 Mongo 而给出明确提示；结果图包含完整装备、精炼、附魔、五彩石、总装分与三项拆分、属性面板、对局时间和快照声明。Task 4 中列出的自动化命令必须全部通过。
