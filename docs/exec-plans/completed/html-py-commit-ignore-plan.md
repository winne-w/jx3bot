# HTML/Python 提交与忽略规则计划

更新时间：2026-05-19

## 目标

- 提交当前未提交的 `public/jjc-ranking-stats.html` 与 `scripts/audit_jjc_person_history_identity.py`
- 将 `data/jjc_identity_audit/` 加入 `.gitignore`，避免审计输出继续进入工作区
- 不纳入本次提交的其他本地改动保持原样

## 变更范围

- `public/jjc-ranking-stats.html`
- `scripts/audit_jjc_person_history_identity.py`
- `.gitignore`
- `docs/exec-plans/index.md`
- `docs/exec-plans/active/html-py-commit-ignore-plan.md`

## 实施步骤

1. 读取当前 diff，确认仅提交指定的 `.html`、`.py` 改动内容。
2. 更新 `.gitignore`，新增 `data/jjc_identity_audit/` 忽略规则。
3. 暂存上述目标文件与本计划文档，不包含其他未提交文件。
4. 依据分支名和变更内容生成 commit message，执行 `git commit`。

## 验证

- `git status --short` 确认仅目标文件被暂存/提交
- `git diff --cached --stat` 确认提交范围
- `git status --short` 提交后确认其他非目标改动仍保留在工作区

## 风险与回滚

- 风险：误把其他本地修改一起提交
- 控制：只对明确文件执行 `git add`
- 回滚：如提交内容有误，后续使用 `git revert <commit>` 回退本次提交

## 完成记录

- 代码提交：`bc39606`
- 收尾状态：已提交指定 HTML/Python 改动，已忽略 `data/jjc_identity_audit/`，本计划归档至 completed。
