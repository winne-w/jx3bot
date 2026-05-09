# JJC 橙武名称白名单判断规划

状态：已完成
更新时间：2026-05-09

执行记录：

- 已完成：新增 `config.py` 橙武名称白名单配置。
- 已完成：新增 JJC 橙武判断 helper，并接入 summary、图片渲染、API legacy summary 和前端明细判断。
- 已完成：新生成的统计明细写入 `weapon_name`；队友缓存也补充 `weapon_name`，便于前端高亮判断。
- 已完成：补充单测和语法验证。
- 已完成：旧时间戳页面也需要准确展示，已提供历史快照矫正脚本，为旧 details / legacy 单文件补齐 `weapon_name`，并重算拆分目录 `summary.json` 橙武计数。
- 已完成：已执行全量历史矫正，共覆盖 117 个旧单文件快照和 1 个拆分目录快照；复查 `1776988810`、`1778203754` dry-run 均为 0 待改动。
- 已完成：数据库设计文档已补充 `weapon_name` 字段说明和矫正脚本引用。

## 背景

当前 JJC 排行榜统计页、图片渲染和 API summary 中，橙武判断统一近似为：

```python
str(member.get("weapon_quality")) == "5"
```

游戏新出了俗称“小橙武”的武器后，外部接口返回的 `weapon.quality` 仍可能是 `"5"`，导致这些武器被算进橙武占比，并在前端紫武模式中被过滤掉。后续改为维护“橙武名称白名单”：只有名称在白名单里的武器才按橙武处理，其他武器即使 `quality=5` 也按非橙武处理。

本次先基于最新排行榜快照 `1778203754` 做数据对比：

- 榜单时间：`2026-05-08 09:29:14 CST`
- 快照来源：`data/jjc_ranking_stats/1778203754`
- 武器原始字段来源：Mongo `role_jjc_cache`
- `top_1000` 有效角色：996
- 缓存命中：996
- `weapon_quality = 5`：812 人，93 个唯一武器条目
- `weapon_quality = 4`：182 人，45 个唯一武器条目
- `weapon_quality = None`：2 人

临时分析报告：

- `/tmp/jjc_weapon_quality_report_1778203754.json`

报告中 `weapon_quality=5` 同时包含真橙武和小橙武，因此后续不应继续只按 `quality == 5` 判断橙武。

## 橙武名称配置清单

以下清单来自最新快照 `1778203754` 的 `top_1000` 样本，已排除已确认按非橙武处理的小橙武名称。开发只维护这份“橙武名称”配置；不再维护小橙武排除配置。

```python
JJC_LEGENDARY_WEAPON_NAMES = {
    "钗蝶语双",
    "七月嘉树",
    "万象金声",
    "幽微夜",
    "蜕骨",
    "伏魔悲音",
    "意真",
    "长安",
    "掠炎",
    "金乌回首",
    "栖贤韵",
    "瀚海引",
    "镇恶",
    "仙灵",
    "暴龙震江",
    "烛微刀",
    "碧血豪侠",
    "伏龙阳焰",
    "天下宏愿",
    "龙鲤",
    "银羽雪辉",
    "子不语",
    "碧岚幽炎",
    "逾潮声",
    "静雨",
    "折枝花满",
    "昭佛光",
    "烬灭",
}
```

后续补充方向：

- 如果发现新的真橙武名称，只补充到 `JJC_LEGENDARY_WEAPON_NAMES`。
- 小橙武、紫武、未知武器不需要单独列入配置；不在橙武名称配置里的，一律不算橙武。

## 目标

- 建立统一的 JJC 橙武判断规则：`weapon_quality == "5"` 且武器名在橙武名称配置里，才算橙武。
- 橙武名称集合必须作为配置项维护，业务判断函数只读取配置，不在判断分支里散写名称。
- JJC 统计 summary、details、图片渲染、前端紫武模式使用同一判断函数。
- 小橙武不再计入橙武占比，紫武模式中应保留小橙武角色。
- 新生成的统计快照落盘保留 `weapon_name`，避免前端只能看到 `weapon_quality` 而无法执行名称白名单判断。
- 兼容并矫正已有历史快照；历史数据优先使用 `weapon_name`，缺失时读取旧结构里的 `weapon.name`，两者都没有时按“名称未命中白名单”处理为非橙武。

## 非目标

- 不改变心法判定逻辑。
- 不修改外部接口请求协议。
- 不改变 JJC 角色身份模型、`role_jjc_cache` 集合结构和缓存 TTL。
- 不新增运行时管理界面；本次只把橙武名称做成仓库内配置项，后续如需要再接入运行时配置。

## 当前数据观察

最新快照的 `details` 文件中，成员只保存了：

- `weapon_icon`
- `weapon_quality`
- 角色、分数、心法、身份等字段

没有保存：

- `weapon.name`
- `weapon` 原始结构

实际武器原始字段存在于 Mongo `role_jjc_cache.weapon`，实施时只需要从其中提取 `name` 写入统计明细：

```json
{
  "quality": "5",
  "name": "钗蝶语双"
}
```

最终业务规则不使用 `ui_id`、样本人数或图标特征，只使用 `weapon_quality + weapon_name`，其中 `weapon_name` 必须命中橙武名称配置。

## 规则方案

新增集中判断 helper，建议放在 service 层可复用模块，例如：

- `src/services/jx3/weapon_quality.py`

核心函数：

```python
def is_jjc_legendary_weapon(weapon_quality: Any, weapon_name: Optional[str] = None) -> bool:
    ...
```

判断规则：

1. 先把 `weapon_quality` 转成字符串。
2. 如果 `weapon_quality != "5"`，返回 `False`。
3. 如果能取得 `weapon_name`，只有命中橙武名称集合才返回 `True`，否则返回 `False`。
4. 如果历史数据没有 `weapon_name`，但有旧结构 `weapon.name`，先使用 `weapon.name` 按名称集合判断。
5. 如果两个名称字段都缺失，返回 `False`；最终口径是“指定名称的是橙武，其他都不是”。

橙武规则只维护名称集合，不使用 `ui_id` 判断。首批配置名单以本文“橙武名称配置清单”为准。

## 涉及文件

- `config.py`
  - 新增 `JJC_LEGENDARY_WEAPON_NAMES` 配置项，维护橙武名称集合。
- `src/services/jx3/weapon_quality.py`
  - 从配置项读取橙武名称集合。
  - 新增 `is_jjc_legendary_weapon(weapon_quality, weapon_name)`，按 `quality == "5"` 且名称在橙武名称集合判断。
  - 新增 `extract_member_weapon_name()`，兼容读取新字段 `weapon_name` 和旧字段 `weapon.name`。
- `src/services/jx3/jjc_ranking.py`
  - `get_ranking_kungfu_data()` 写入 members 时补充 `weapon_name`。
  - `_build_summary_payload()` 计算 `legendary_count_map` 时改用统一 helper。
  - `save_ranking_stats()` 新产物写入增强后的 details。
- `src/api/routers/jjc_ranking_stats.py`
  - 兼容旧快照构建 summary 时，优先使用 `weapon_name`，缺失时读取旧结构 `weapon.name`，仍未取得名称则按非橙武处理。
  - 返回 details 时不剥离新增 `weapon_name` 字段。
- `src/renderers/jx3/jjc_ranking.py`
  - 图片中的橙武占比改用统一 helper。
- `public/jjc-ranking-stats.html`
  - 增加同一份橙武名称集合，基于 `weapon_quality + weapon_name` 按同规则判断。
  - 紫武模式过滤从 `String(member.weapon_quality) !== "5"` 改为“不是橙武”：`weapon_quality != "5"` 或 `weapon_name` 不在橙武名称集合。
  - 橙武高亮从单纯 `weapon_quality == "5"` 改为 `weapon_quality == "5"` 且 `weapon_name` 在橙武名称集合。
  - 兼容旧详情：优先读取 `weapon_name`，缺少时读取旧结构 `weapon.name`，两者都没有时按非橙武处理。
- `tests/`
  - 新增或扩展 JJC 橙武判断、summary 统计、前端兼容相关测试。
- `scripts/fix_jjc_ranking_weapon_names.py`
  - 新增历史快照矫正脚本。
  - 读取指定或全部 `data/jjc_ranking_stats/<timestamp>/details/.../*.json`，按成员身份从 Mongo `role_jjc_cache` 补齐 `weapon_name`。
  - 重算 `summary.json` 中各范围、各 lane、各心法的 `legendary_count_map`。
  - 支持 dry-run，默认不写入；确认后通过 `--write` 落盘。

## 数据结构调整

新生成的 details member 建议补充字段：

```json
{
  "weapon_icon": "https://...",
  "weapon_quality": "5",
  "weapon_name": "钗蝶语双"
}
```

summary 中继续保留已有：

```json
{
  "legendary_count_map": {
    "云裳心经": 61
  }
}
```

但其计算口径改为 `weapon_quality == "5"` 且 `weapon_name` 在橙武名称集合，不再直接等同于 `weapon_quality == "5"`。

兼容策略：

- 新快照：使用 `weapon_quality + weapon_name` 判断。
- 旧拆分快照：通过 `scripts/fix_jjc_ranking_weapon_names.py --write` 补齐 details 中的 `weapon_name`，并重算 `summary.json` 的 `legendary_count_map`。
- 旧单文件快照：脚本补齐 members 中的 `weapon_name`；API 动态构建 summary 时使用同一白名单判断。
- 兜底：如果旧数据缺少 `weapon_name`，但仍保留 `weapon.name`，则从旧结构读取名称；两者都缺失时按非橙武处理。

## 实施步骤

1. 基于本文“橙武名称配置清单”落地首批橙武名称配置。
2. 在 `config.py` 新增 `JJC_LEGENDARY_WEAPON_NAMES`，保存已确认的橙武名称。
3. 新增 `src/services/jx3/weapon_quality.py`，从配置读取橙武名称集合并实现 `is_jjc_legendary_weapon()`。
4. 为判断 helper 增加单测，覆盖：
   - 当前赛季真橙武 `quality=5` 且名称在橙武集合时返回 `True`。
   - 小橙武即使 `quality=5`，只要名称不在橙武集合，也返回 `False`。
   - `quality=4` 返回 `False`。
   - 字段缺失时按非橙武处理。
5. 修改 `JjcRankingService.get_ranking_kungfu_data()` 的 member 构建逻辑，把 `weapon_name` 写入统计明细。
6. 修改 summary 计算、API legacy summary 构建和图片渲染的橙武占比判断，统一使用 helper。
7. 修改前端紫武模式和橙武高亮判断，使用同一橙武名称集合；缺少名称时按非橙武处理。
8. 重新生成一份最新排行榜统计快照，核对小橙武从橙武占比中移除，并出现在紫武模式中。
9. 根据实际改动补充必要文档，例如 API/运行回归说明；若不改接口路径，只需在本计划中记录执行结果。
10. 新增历史快照矫正脚本，支持指定 timestamp 或全量扫描。
11. 先对最新快照 dry-run，确认可补齐 `weapon_name` 与橙武计数变化；再按用户确认执行写入。
12. 脚本写入后重新打开旧时间戳页面，确认紫武模式与橙武占比按白名单口径展示。

## 验证

自动化：

```bash
python -m unittest tests.test_jjc_weapon_quality
python -m py_compile src/services/jx3/weapon_quality.py src/services/jx3/jjc_ranking.py src/api/routers/jjc_ranking_stats.py src/renderers/jx3/jjc_ranking.py
```

已执行：

```bash
python -m unittest tests.test_jjc_weapon_quality
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile scripts/fix_jjc_ranking_weapon_names.py
python -m py_compile src/services/jx3/weapon_quality.py src/services/jx3/jjc_ranking.py src/services/jx3/kungfu.py src/api/routers/jjc_ranking_stats.py src/renderers/jx3/jjc_ranking.py config.py
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]); scripts.forEach((s,i)=>new Function(s)); console.log('scripts ok', scripts.length)"
```

结果：全部通过。

若测试整合进现有文件：

```bash
python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_weapon_quality
```

前端语法检查：

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]); scripts.forEach((s,i)=>new Function(s)); console.log('scripts ok', scripts.length)"
```

数据回归：

- 已执行全量历史矫正：

```bash
python scripts/fix_jjc_ranking_weapon_names.py --write
```

- 覆盖范围：117 个旧单文件快照，1 个拆分目录快照 `1778203754`。
- 最新拆分目录复查：

```bash
python scripts/fix_jjc_ranking_weapon_names.py --timestamp 1778203754
```

结果：`members_changed=0`，`summary_count_changes=0`。

- 旧单文件样本复查：

```bash
python scripts/fix_jjc_ranking_weapon_names.py --timestamp 1776988810
```

结果：`members_changed=0`，`summary_count_changes=0`。

- 对比 `summary.legendary_count_map`，确认小橙武相关角色不再计入橙武数。
- 打开 `public/jjc-ranking-stats.html`：
  - 全部排名中小橙武角色正常展示。
  - 紫武排名中小橙武角色保留。
  - 真橙武角色仍被过滤并保持橙武高亮。
- 抽查 details member，确认包含 `weapon_name`。

## 风险与回滚

- 风险：橙武名称配置不完整，真橙武会被归入非橙武。缓解方式是定期用最新快照更新名称集合。
- 风险：同名武器跨品级或跨赛季复用名称时，纯名称白名单可能误伤。当前按用户确认口径执行，不使用 `ui_id`。
- 风险：部分历史快照无法从缓存补齐武器名；按最终口径这类记录不计入橙武，避免继续把小橙武或未知 quality=5 武器误算为橙武。
- 回滚：撤回 helper 调用和前端判断，恢复 `weapon_quality == "5"` 旧逻辑；新 details 中多出的字段为向后兼容字段，不影响旧读路径。

## 后续补充

- 橙武名称列表作为 `config.py` 配置项维护，不使用 `ui_id` 判断。
- 是否需要把 `/tmp/jjc_weapon_quality_report_1778203754.json` 的精简版纳入仓库文档，作为规则制定依据。
- 是否需要对历史最新快照执行一次离线修正，还是只从下一次生成开始生效。
