# Task: JJC Ranking Stats Split

状态：已完成
完成时间：2026-04-27

## 目标

- 缩小 JJC 统计页首屏响应
- 将成员明细改为展开时按需请求
- 为已有历史统计文件提供迁移路径

## 当前关联执行文档

- `docs/exec-plans/completed/jjc-ranking-stats-split-plan.md`

## 结果

- JJC 统计页首屏接口改为返回轻量 `summary`
- 成员明细改为按需请求的 `details` 接口
- 页面改为展开时懒加载详情
- 历史统计数据迁移脚本已补齐并完成执行验证
- 新旧数据结构在过渡期可兼容读取

## 完成标准

- `action=read` 不再返回全量 `members`
- 页面首屏仅依赖 summary 数据即可渲染
- 用户展开心法时可按需加载详情
- 历史时间戳可通过迁移或兼容逻辑继续访问

## 已完成

- 后端 `summary + details` 落盘拆分
- `details` 接口设计与实现
- 前端详情懒加载改造
- 历史数据迁移脚本补齐
- 线上验证与迁移执行完成
