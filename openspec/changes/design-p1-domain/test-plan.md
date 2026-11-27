# P1 统一领域规则层测试与验证记录（test-plan.md）

日期：2026-11-26  
环境：Python 3.9.25 与 Python 3.13.2

## 自动化验证

1. **架构依赖方向检查**：
   - `grep -rn "from src\.services" src/storage/`：输出为空（0 处反向导入）。
   - `tests/test_domain_role_name_and_identity.py` 内置 AST 架构守护测试验证 `src/domain/` 零外部层依赖、`src/storage/` 零 `src.services` 依赖。
2. **Python 3.9 语法与分片单测**：
   - 三个并行子任务均完成各自全部新增与改动文件的 Python 3.9 `py_compile` 与单测（P1-A 88 项、P1-B 130 项、P1-C 94 项全通过）。
3. **Python 3.13 整合回归**：
   - 联合运行 14 个核心及新增测试模块（`test_domain_kungfu_catalog`, `test_domain_role_name_and_identity`, `test_scripts_common_mongo`, `test_kungfu_aliases`, `test_role_identity_matching`, `test_role_identity_repo`, `test_role_identity_jjc_kungfu`, `test_jjc_kungfu_policy`, `test_jjc_snapshot_repo`, `test_jjc_match_detail_hydration`, `test_jjc_ranking_equipment_policy`, `test_jjc_ranking_display`, `test_backfill_jjc_match_facts`, `test_recover_jjc_role_identities`）：**274 项全部 OK（3 项真实 Mongo 用例按预期跳过）**。
