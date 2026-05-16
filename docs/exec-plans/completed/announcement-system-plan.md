# 系统公告功能实现计划

本计划实现系统公告与更新说明功能。管理员通过 QQ 机器人命令管理公告；用户访问 `jjc-ranking-stats.html` 时，若存在未看过的最新日期公告则弹窗，弹窗内展示公告列表并支持下滑加载更多。

## 需求

- 公告弹窗：打开 jjc-ranking 页面时，检查 `localStorage` 是否已看过最新日期公告，未看过则弹窗
- 弹窗内公告列表：首次展示最新一条公告（hero 区）+ 前 5 条历史公告列表，弹窗内下滑加载更多
- 前端 localStorage 记录用户已看公告日期；看过则直到有新日期公告才再次弹窗
- 通过 QQ 机器人管理员命令管理公告

## 涉及文件

| 文件 | 操作 |
|------|------|
| `src/infra/mongo.py` | 修改：`announcements` 集合 2 个索引 |
| `src/storage/mongo_repos/announcement_repo.py` | 新建：CRUD + 分页 + 最新日期查询 |
| `src/api/routers/announcements.py` | 新建：`/latest-date`、`/list` 两个端点 |
| `src/api/__init__.py` | 修改：注册新路由 |
| `src/plugins/announcement_admin.py` | 新建：`/公告添加`、`/公告列表`、`/公告删除` |
| `public/jjc-ranking-stats.html` | 修改：新增公告弹窗 CSS + HTML + JS |
| `docs/design-docs/database-design.md` | 修改：新增集合文档 |

## 前端改动要点

- 在 jjc-ranking-stats.html 中新增 `.modal-overlay#announcement-modal`
- 弹窗内：hero 区（最新公告）+ 历史公告列表（IntersectionObserver 无限滚动）
- 复用现有 `openModal()`/`closeModal()`/`unwrapResponse()` 模式
- Escape 关闭顺序：match → role → announcement

## 验证方式

1. `python -m py_compile` 所有新文件
2. 启动 bot，确认 MongoDB 索引创建无报错
3. `curl /api/announcements/latest-date` 和 `/api/announcements/list` 验证 API
4. QQ 发送管理命令验证权限和功能
5. 浏览器打开 jjc-ranking-stats.html：无公告或已看过不弹窗，有新公告弹窗可下滑加载更多

## 状态

已实现后端部分，前端集成进行中。
