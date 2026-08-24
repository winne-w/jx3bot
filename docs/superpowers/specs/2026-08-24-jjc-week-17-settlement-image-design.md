# 第 17 周竞技场结算图片临时脚本设计

## 目标

提供一个仅在本地运行的临时脚本：从 MongoDB 中读取第 17 周的竞技场排名统计快照，生成一张可直接作为 OneBot V11 `MessageSegment.image` 内容发送到 QQ 的 PNG 图片。

## 范围

脚本只读取 `jjc_ranking_stat_summaries`，复用 QQ `竞技排名` 命令现有的统计字段、Jinja 模板和图片渲染能力。它不调用在线排行榜接口，不写入 MongoDB，也不注册新的 QQ 命令。

## 数据选择

查询条件为 `default_week=17`。优先选择 `week_info` 含“结算周”的快照；如缺失该标记，回退到该周 `generated_at`（再以 `timestamp`）最新的快照。未找到任何快照时，脚本以非零退出并说明原因。

## 渲染与输出

读取所选快照的 `current_season`、`week_info` 和 `kungfu_statistics`，调用现有 `render_combined_ranking_image` 与 `竞技场心法排名统计.html`，生成与默认 QQ `竞技排名` 一致的一张汇总图。输出 PNG 至 `mpimg/` 的带时间戳文件名；同时打印绝对路径，供调用方传入 `MessageSegment.image`。

默认不展示橙武占比，与 QQ 命令未带“橙武占比”参数时一致。

## 失败处理与验证

脚本在 Mongo 不可连接、缺少快照、统计字段为空或模板渲染失败时输出明确错误并返回非零状态。测试覆盖结算快照优先、回退选择和空结果；本地冒烟会运行脚本并检查输出文件是非空 PNG。
