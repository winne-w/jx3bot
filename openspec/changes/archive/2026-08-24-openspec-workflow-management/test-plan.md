# 测试与验证记录

## 已执行

- `node --version`：通过（v22.20.0）。
- `npm --version`：通过（10.9.3）。
- `npx --yes @fission-ai/openspec@latest --help`：通过。
- `npx --yes @fission-ai/openspec@latest init --tools codex --no-animation --force`：通过，生成仓库级 OpenSpec 配置与 Codex skills。
- `git diff --check`：通过。
- 新流程入口引用扫描：`PROJECT_CONTEXT.md`、`docs/PLANS.md`、`README.md`、`docs/exec-plans/index.md` 与开发指南不再把 `docs/requirements/` 作为未来需求入口。

## 网络排障与严格校验

默认代理路径下，npm 对 `repositories.myhexin.com` 的 registry 元数据请求报 `EAI_AGAIN` 并重试，导致 `npx ...@latest` 超时。镜像根地址可访问；显式移除 `HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY` 后，CLI `list` 正常列出两个 active change。

已使用绕过代理的环境运行：

```bash
npx --yes @fission-ai/openspec@latest validate openspec-workflow-management --strict
npx --yes @fission-ai/openspec@latest validate jjc-match-season --strict
```

两项均输出 `Change '<id>' is valid` 并退出 0。当前 CLI 版本的 `validate` 参数必须使用 change id，而非目录路径。
