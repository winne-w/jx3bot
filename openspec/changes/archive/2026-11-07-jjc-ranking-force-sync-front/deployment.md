# 生产发布与验收记录

2026-11-07，用户明确授权开发、测试、review、commit 和发布。实现提交 `e1ee55ef4405dce771721e967adca853cf799749` 已推送 `origin/feat/jjc-safe-live-refresh`，北京时间 11:09:56 重启发布，最终验收通过。

## 发布范围与验证

仅替换 5 个运行文件：同步 repo、排名 service、Mongo 索引初始化、QQ handler 和定时入口。生产与 Git 基线的换行差异归一比较；前四文件语义基线与 HEAD 一致，定时入口保留线上已发布的离线统计修复，仅追加 `_sync_request` 透传条件。config.py 与 runtime_config.json 字节哈希全程不变，其他任务工作区变更保持未提交。

本地双版本各原 388 项加评审后 3 项共 391 项通过，含 9 项真实隔离 Mongo。随后导出独立暂存快照，Python 3.13 完整 372 项、Python 3.9 完整 381 项（含 9 项 Mongo）通过；生产候选在本地 Python 3.13 另跑 9 项 Mongo 通过。随机测试库已清理，loopback:27029 服务已关闭。

生产 Python 3.9.9 首跑 372 项有 7 项失败，全部在原生产源码及同配置复现。5 项由线上已开启心法缓存/刷新开关而测试默认关闭导致；另 2 项为 Git 测试仍假设旧 QQ 在线门禁。候选测试进程内临时将两开关设为 0（各功能用例仍自行 patch 启用），并采用对应已部署离线统计的测试夹具，382 项全部通过、无跳过。原始失败、基线对照和最终日志均保留；没有修改生产运行配置或把其他任务的测试混入本次实现提交。

三路子 agent 只读初评、定向复评通过；提交独立性补修与发布/回滚脚本也定向只读复评通过。评审者未执行项目测试或发布。

## 停止、升级与恢复

发布前确认仅一个 bot 容器、4 个内部完整同步 worker，无独立旧 bot/worker。保存原全局状态，使用观察值 CAS 暂停新领取，有界等待后仍有在途任务，受控停止容器并确认所有写进程停止，再逐文件原子替换、启动。没有清理旧租约；中断任务沿既有到期恢复机制处理。源码替换/启动异常会调用私有回滚；暂停后 drain/stop/外部写者检查异常则保持暂停或停止，人工检查，不继续启动。

重启后 Running=true、RestartCount=0，应用启动完成，日志 Traceback=0，QQ 已连接。5 文件哈希全部匹配候选；两集合 `idx_status_ranking_front` 精确匹配新排序，生产 queryPlanner 都使用索引且没有阻塞 SORT。4 个 worker 的 started_at 均为本次重启后，心跳新鲜。就绪后仅撤销本次暂停，恢复发布前未暂停状态，4 个 worker 均重新 syncing；如期间出现其他原因暂停则不会覆盖。

公网 sync/status、workers、queued 队列与 ranking-stats API 均 HTTP 200、status_code=0；队列页面 HTTP 200。

## 有界线上业务冒烟

暂停期间选一个现有排名来源、当前赛季且冷却尚未到期的真实角色，先保存 queue/identity canonical BSON preimage。调用正式 repo 排名入队接口：cooldown 立即 queued、同轮重复请求 queued_at 不变、下一轮新请求更新 batch/order 且位置为 1，身份队列仍只有一条，失败计数与同步水位保留。该验证自身未调用上游或发送消息，没有手工触发全量排名统计或重算旧快照。

恢复后自然 worker 已领取该角色并完成同步，回到 cooldown、fail_count=0、front/pending 清空。syncing 收到后续请求、失败重试及高并发竞争主要由隔离自动化覆盖；未在生产伪造失败/在途状态，未模拟千人统计耗时或测吞吐。

## 备份与回滚

私有证据目录 `/mnt/sata6-1/jx3bot-releases/ranking-front-20261107-e1ee55ef4405/`，权限受限，包含 backup、candidate、manifest、原环境、原暂停状态、drain/deployment、原始/对照/最终测试、startup/health、索引、公网验证、queue-smoke preimage/结果及自然 worker 结果。部署用基线、候选、回滚脚本与转换器均有哈希；本地操作证据在 workspace `_diagnostics/2026-11-07-jjc-front/`。

如回滚，先核对源码未漂移并停止全部 bot/worker/dispatcher/统计生产者。运行 release 内 rollback.py：同镜像、网络和原环境，仅启动转换脚本，配置/源码只读挂载、持久化 release 可写挂载，PYTHONPATH=/app；转换器核对 Mongo URI 指纹，备份以新唯一文件名 canonical Extended JSON 逐条 flush/fsync 后 CAS 更新。pending 合并最新参数为普通 queued，保留更高人工 priority、审计、水位与 request_order，disabled 不复活，无 pending 的在途租约不变，front/pending 清空。两集合残留为 0、转换数与持久化 preimage 条数一致后才恢复旧 allowlist 并启动。异常/CAS 失配保持停机，保留部分备份，重试换新文件名。保留新旧索引和全部比赛/身份/队列数据，恢复后检查就绪再按原暂停状态处理。

转换器已在隔离真实 Mongo 的两队列演练参数/优先级/审计/水位/disabled/普通租约/幂等，canonical JSON 修正后复验通过；最终私有脚本语法检查通过。未执行生产回滚。
