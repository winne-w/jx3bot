# JJC 统计页拆分计划

完成时间：2026-04-27

## 当前进度

- 已完成：后端落盘拆分为 `summary + details`
- 已完成：`action=read` 优先返回 `summary.json`，并兼容旧单文件
- 已完成：新增 `GET /api/jjc/ranking-stats/details`
- 已完成：前端首屏改为只依赖 summary，展开时懒加载详情
- 已完成：新增历史数据迁移脚本 `scripts/migrate_jjc_ranking_stats.py`
- 已完成：回归验证、导出兼容确认、历史数据批量迁移执行

## 背景

当前 `/api/jjc/ranking-stats?action=read&timestamp=...` 直接返回完整统计文件。单个文件通常在 `2.9MB ~ 3.5MB`，包含：

- 首屏柱状图所需的心法分布摘要
- 各范围下重复展开的 `members`
- 每个成员下的 `teammates`

这导致两个直接问题：

- 页面首屏加载时间过长，前端必须先等待大 JSON 下载完成
- 代理层在转发大响应时容易触发缓冲落盘和磁盘占用问题

## 目标

- 把首屏响应缩小到只包含 summary
- 把角色明细改成按需请求
- 兼容已有历史统计数据，避免旧时间戳直接失效
- 保留现有页面能力：范围切换、紫武模式、导出

## 范围

本次改造覆盖：

- `src/services/jx3/jjc_ranking.py`
- `src/api/routers/jjc_ranking_stats.py`
- `public/jjc-ranking-stats.html`
- `data/jjc_ranking_stats/` 统计落盘结构
- 必要的迁移脚本与回归说明

本次不覆盖：

- JJC 心法判定逻辑本身
- 推送图片渲染逻辑
- 统计口径调整

## 现状判断

### 首屏真正需要的数据

- 赛季/榜单时间
- `top_1000/top_200/top_100/top_50`
- 每个范围下奶妈/DPS的：
  - `valid_count`
  - `distribution`
  - `list`
  - `min_score`
  - 橙武占比计算所需的聚合值

### 可以延迟加载的数据

- `members`
- `teammates`
- 角色武器图标和角色明细展开内容

## 目标结构

建议将单文件：

- `data/jjc_ranking_stats/<timestamp>.json`

改为目录结构：

- `data/jjc_ranking_stats/<timestamp>/summary.json`
- `data/jjc_ranking_stats/<timestamp>/details/<range>/<lane>/<kungfu>.json`

其中：

- `summary.json` 只保留首屏摘要
- `details/...` 仅保存单个范围、单个分组、单个心法的成员明细

## 接口方案

### 1. 保留列表接口

- `GET /api/jjc/ranking-stats?action=list`

仍然返回可用时间戳列表。

### 2. 缩小 read 接口

- `GET /api/jjc/ranking-stats?action=read&timestamp=<ts>`

改为只返回 `summary.json` 内容。

### 3. 新增详情接口

新增：

- `GET /api/jjc/ranking-stats/details?timestamp=<ts>&range=<range>&lane=<lane>&kungfu=<name>`

返回单个心法明细，供前端在展开时按需请求。

## 前端方案

### 首屏

- 页面初始只请求 `action=read`
- 只渲染分布条、占比、最低分
- 不再在首屏把全部 `detail-list` 一次性塞进 DOM

### 展开某个心法

- 用户首次展开时，请求 `details` 接口
- 前端对 `(timestamp, range, lane, kungfu)` 做本地缓存
- 二次展开直接复用已加载数据

### 导出

- 单卡导出和整页导出继续保留
- 若某些详情尚未加载：
  - 默认导出当前已加载内容
  - 不在导出时隐式触发全量详情请求

## 迁移策略

### 1. 新增一次性迁移脚本

新增脚本，例如：

- `scripts/migrate_jjc_ranking_stats.py`

职责：

- 扫描旧的 `data/jjc_ranking_stats/*.json`
- 拆出 `summary.json`
- 拆出对应 `details/...`
- 保留旧文件，便于回滚

### 2. 读路径兼容

在迁移完成前：

- 优先读取新目录结构
- 若新结构不存在，可临时回退读取旧文件并返回兼容结果

### 3. 清理旧结构

确认：

- 新接口稳定
- 前端已切换
- 历史数据迁移完成

之后再评估删除旧结构和兼容逻辑。

## 实施顺序

1. 后端落盘拆分：生成 `summary + details`
2. 新增 `details` 接口
3. `read` 改为只读 summary
4. 新增迁移脚本，处理已有历史文件
5. 前端改为展开时懒加载详情
6. 验证导出与紫武模式
7. 补充 runbook 回归路径

## 完成情况

1. 后端落盘拆分：已完成
2. 新增 `details` 接口：已完成
3. `read` 改为只读 summary：已完成
4. 新增迁移脚本，处理已有历史文件：已完成
5. 前端改为展开时懒加载详情：已完成
6. 验证导出与紫武模式：已完成
7. 补充 runbook 回归路径：已完成

## 验证点

- 首屏 `action=read` 响应体显著缩小
- 页面首屏加载时间明显下降
- 展开单个心法时可以正常加载详情
- 紫武模式下详情过滤逻辑仍正确
- 单卡导出仍可用
- 历史时间戳不会因为新结构上线而直接失效

## 风险

- 老数据迁移与新落盘结构并存期间，接口兼容分支容易变复杂
- 若详情接口参数设计不稳定，前端缓存键会反复变更
- 导出行为和懒加载存在天然张力，必须先明确“导出已加载内容”还是“导出前自动补全内容”

## 约束

- 先完成文档计划，再进行跨文件结构开发
- 新接口与落盘结构必须优先兼容已有历史数据
- 不在本次改造里顺手调整统计口径
