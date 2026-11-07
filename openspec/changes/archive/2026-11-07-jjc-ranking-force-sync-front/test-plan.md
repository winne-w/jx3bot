# TDD 测试与验收矩阵

状态：矩阵已完成本地验证与独立静态复评；证据见 acceptance.md。Q6 由确定性注入及真实并发覆盖；Q7 为关闭旧 client 后新 client/repo 的持久化恢复，未模拟 OS 完整重启。

| 编号 | 行为 | 证据 |
|---|---|---|
| Q1 | pending/cooldown/exhausted/failed/queued，priority=0/1/100 均新轮入队 | repo 单测及真实 Mongo |
| Q2 | disabled 跳过；syncing 不改租约与当前窗口 | repo 单测及真实 Mongo |
| Q3 | 同轮去重、旧轮不覆盖新轮、相同 cache_time 下一轮独立 | repo 与 service 单测 |
| Q4 | 新批次先于旧批次及普通高 priority，同批按 rank | 领取/列表/位置单测，Mongo 排序及 explain |
| Q5 | 同步中收到多轮仅保留最新，成功/失败后恰好补排一次 | repo 与真实 Mongo 并发 |
| Q6 | 请求与释放/领取交错不丢，旧租约不得释放 | 注入交错及 Mongo 并发 |
| Q7 | 中断、租约恢复、重启后待请求仍执行 | repo 与真实 Mongo |
| Q8 | unknown 有效身份即时入队，分组/保存补偿共享 run context | service 单测 |
| Q9 | 成功/失败无新请求仍沿用冷却/退避，已消费 front 清除 | 既有与新增回归 |
| Q10 | identity 主路径、legacy fallback 一致；普通任务缺字段兼容 | 两路径矩阵与 Mongo |

真实 Mongo 仅允许显式 loopback:27029 和随机隔离库。禁止外部推栏/生产数据库作为单测依赖。主 agent 顺序执行 TDD，完成后子 agent 只读评审方案、计划、diff 与证据。
