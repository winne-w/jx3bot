# JJC 对局查询服务器下拉计划

状态：已实现，待提交
更新时间：2026-05-27

## 背景

`public/jjc-synced-matches.html` 当前要求用户手动输入服务器名，非技术用户容易输错。项目已有 `server_data.json`，启动时由 `src/plugins/jx3bot_handlers/cache_init.py` 从 JX3API 开服状态接口刷新，`src/infra/jx3api_get.py` 也使用这份数据校验服务器名。

## 目标

- 为前端提供一个只读区服列表 API，复用现有 `server_data.json`。
- 将 JJC 对局查询页面的服务器输入框改成下拉选择。
- 保留 URL 参数覆盖能力，便于不同部署路径调试。

## 改动范围

- `src/infra/jx3api_get.py`：补充读取区服列表的公共函数。
- `src/api/routers/servers.py`：新增 `GET /api/jx3/servers`，返回服务器名、分区、状态等基础字段。
- `src/api/__init__.py`：注册新增路由。
- `public/jjc-synced-matches.html`：服务器字段改为 `<select>`，页面启动时加载区服列表。
- `README.md`：补充新增 API 说明。

## 验证

```bash
python -m py_compile src/infra/jx3api_get.py src/api/routers/servers.py src/api/__init__.py
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-synced-matches.html','utf8'); [...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].forEach((m)=>new Function(m[1])); console.log('script ok')"
```

手工回归：

- 打开 `/jx3/jjc-synced-matches.html`，确认服务器下拉可加载并选择“梦江南”等区服。
- 区服列表加载失败时，页面降级为手动输入服务器，查询按钮保持可用。
- 查询时仍使用所选服务器和角色名调用原有 JJC 对局查询接口。

## 回滚

回滚新增 API、页面 select 改动和 README 说明；页面恢复为手工输入服务器名。

## 执行记录

2026-05-27：

- 已新增 `GET /api/jx3/servers`，复用 `server_data.json` 返回区服列表。
- 已将 `public/jjc-synced-matches.html` 的服务器输入改为下拉选择，支持 `server_list_api` 和 `server` URL 参数覆盖。
- 已更新 README API 列表。
- 已补充区服列表加载失败兜底：下拉框降级为同 `id/name` 的手动输入框，查询按钮保持可用。
- 已将对局详情加载失败提示改为固定用户文案，避免直接展示 HTTP/status_msg/error.message。
