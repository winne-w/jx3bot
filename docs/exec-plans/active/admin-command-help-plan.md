# 管理员命令帮助入口计划

状态：实现中
更新时间：2026-05-07

## 背景

现有普通 `帮助` 入口只展示群配置和常用功能状态，不覆盖 `/重启`、`/查看配置`、`/修改配置`、`/jjc同步...` 等管理员命令。维护者需要一个仅管理员可见的 QQ 命令说明入口。

## 目标

- 新增 `/管理帮助` 命令。
- 仅 `config.py` 中 `ADMIN_QQ` 管理员可查看。
- 返回配置/重启命令、JJC 同步命令和普通帮助入口说明。

## 非目标

- 不改普通 `帮助` 图片模板。
- 不改变现有 `/重启`、`/查看配置`、`/修改配置`、`/jjc同步...` 行为。
- 不新增数据库、HTTP API 或定时任务。

## 涉及文件

- `src/plugins/config_manager.py`
  - 新增 `on_command("管理帮助")`。
  - 复用 `ADMIN_QQ` 权限判断。
- `docs/references/runbook.md`
  - 补充手工回归入口和预期。

## 实施步骤

1. 在 `config_manager.py` 新增 `/管理帮助` matcher。
2. 非管理员返回无权限提示。
3. 管理员返回现有管理命令说明。
4. 更新运行手册。
5. 执行编译检查。

## 验证

```bash
python -m py_compile src/plugins/config_manager.py
```

手工回归：

- 管理员在 QQ 发送 `/管理帮助`，应返回管理员命令说明。
- 非管理员发送 `/管理帮助`，应返回无权限提示。

## 回滚

- 删除 `config_manager.py` 中 `/管理帮助` matcher。
- 删除 `docs/references/runbook.md` 中对应回归说明。
