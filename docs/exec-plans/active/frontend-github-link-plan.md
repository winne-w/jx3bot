# 前端页面添加 GitHub 链接计划

## 目标

在 Web 前端页面添加项目 GitHub 地址，方便用户提 issue 反馈问题。

## 变更范围

- `public/jjc-ranking-stats.html`: 页脚已有数据来源链接，在其旁边增加 GitHub issue 链接
- `templates/qun.html`: QQ 机器人功能卡片底部增加 GitHub 地址

## 不涉及

- 不修改其他 Jinja2 模板（它们渲染为图片用于 QQ 消息，不直接面向用户浏览）
- 不修改 API 路由

## 实施步骤

1. 在 `public/jjc-ranking-stats.html` 的 `<footer>` 中增加 GitHub 链接，文案为 "遇到问题？在 GitHub 提 issue"，链接到 `https://github.com/winne-w/jx3bot/issues`
2. 在 `templates/qun.html` 的 `.footer` 中增加 GitHub 地址

## 验证

- 浏览器打开 `public/jjc-ranking-stats.html`，确认页脚显示 GitHub 链接且可点击
- 确认 `templates/qun.html` 渲染后底部显示 GitHub 地址

## 回滚

直接 revert 相关改动即可。
