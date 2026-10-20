# 方案：复用字段的查询 ID 修复

日期：2026-10-20。总体方案及详细执行计划已获用户批准，TDD实现/review闭环中。旧草案中的独立查询对象、三个恢复集合、新验证字段、后台任务和页面轮询全部撤销。

## 事实与语义

| 角色 | 历史服务器/名字 | 遗留 ID | 当前服务器 | 当前可用 ID |
| --- | --- | --- | --- | --- |
| 小耶猫 | 唯我独尊/小耶猫 | 31300496 | 梦江南 | 34945120 |
| 颜魉 | 龙争虎斗/颜魉 | 44421059 | 唯我独尊 | 31755654 |
| 盖伊伊 | 梦江南/柚木普 | 34971082 | 乾坤一掷 | 26691973 |

转服被观察的对局分别为 256550414、257596618、257855260：detail 含新服务器但 role_id 为空，原始 replay 按精确数字身份命中当前可用 ID。共核对 596/65/106 份现存详情。实时 week=43 原始排行榜确认颜魉/盖伊伊；小耶猫不在当前榜，实时 replay/indicator 一致。

本次样本中 gameRoleId、replay.role_id、indicator.role_info.role_id 同义，本地 game_role_id/role_id 保持兼容语义。replay.global_role_id 是项目 global_id 数字身份；indicator.global_role_id 是 SK01，供 history 使用。不声称所有来源永远等价。

错误链为 kungfu.merge_replay_global_ids_into_match_detail 只补 global_id，投影传空 ID，role_identity_repo._update_existing 更新 server/name、跳过空 ID并推进整体水位；upsert_from_indicator 不带对局时间，fill-only 拒绝正确非空 ID。真实快照离线复现三例；同场补齐也因严格 > 被拒。

## 最小结构

继续使用现有 repo/service/client。共享编排必要时新增 role_identity_recovery.py 小函数模块，返回普通字典，不新增领域类、服务实例或持久任务。singletons 只允许必要装配。普通历史写入保留真实对局规则，严格实时验证入口才可替换 ID。页面只解析本地已收录身份，不创建角色，成功缓存走原路径；排名复用已有原始响应。

为使“先单角色试点再放开自动写入”真实成立，拟增加唯一发布配置 JJC_ROLE_IDENTITY_RECOVERY_ENABLED，默认0。它只控制新增的公开/排名/同步自动恢复探测与ID发布，普通查询缓存和始终生效的仓储安全保护不关闭。CLI显式apply仍须独立授权/验证，不被该开关隐式授权。该配置项不是新增Mongo业务字段/对象；config.py及既有runtime配置白名单支持，并在本计划中明确提交用户审核。第一次重启保持0，CLI试点通过后仅修改此获批配置为1，第二次重启加载。关掉后不恢复旧资料、不解除已验证组合保护。

## 验证与条件更新

先查当前 ID，成功且身份一致不换 ID。空 role_info、真实 3c 空字段或缺查询参数才探测；网络、鉴权、限流失败停止本轮，不当旧 ID 证据。

候选来自成功 indicator 原始 role_info、既有角色/排行缓存、已知 replay。过期数据只作 locator，保留所有不同 (zone,server,role_id)，时间只排序，不能只留最新。页面只查有限索引命中/明确 match_id，不扫全历史、不临时拉整榜。

可发布必须原始 indicator 成功，请求/响应 ID、zone/server 一致、目标 SK01 一致；原始 replay 中精确数字 global_role_id 对应 role_id 与候选一致且无多义。同名、复制的缓存键 global_id、SK01 单独相同不替代独立映射。SK01 变化、缺数字身份或主键冲突列未解决，不做自动迁移。

CAS 覆盖 _id/identity_key/global_id/SK01、原 server/zone/两个 ID、既有画像水位/刷新标记；区分缺失和 null，matched_count 非 1 不强写。仅更新两个 ID和既有观测元数据，不变更主键、名字、服务器、区服、person_id、SK01、对局水位及同步进度。独立小 ID-only CAS 方法比泛用 force/ids_only 多开关更清楚时允许使用，但不得新增领域对象。

save_kungfu_cache 也接收非 indicator 兜底，不能按 source 标签授予覆盖权。现有 refresh_indicator_fields_by_id 按 _id 无条件写入必须收口，不能成为旁路。

## 历史组合保护

复用 global_role_id_refreshed_at（严格校验对应请求开始时间）与 global_role_id_refresh_source（明确严格验证来源值）。旧普通标记不自动提升，不加 profile_verified_at/revision 等字段。

保护 server/name 及规范化字段、zone、两个 ID 的组合。严格观测建立后，历史/未验证来源不能部分改写冲突组合；早于观测的历史输入拒绝冲突，更晚/同时间冲突也须先验证当前 indicator，不仅凭对局时间获得覆盖权。无严格标记者保留原兼容规则，不冻结同步状态。不把 > 改成 >=。

相关投影读取既有标记。枚举 _update_existing、refresh_indicator_fields_by_id、upgrade_identity、sync repo 直接写入及回填调用，确保无受保护字段旁路。普通刷新不清除严格标记或虚构新的严格观测；沿用/推进标记须保持验证契约，回归刷新 TTL，避免每轮重复请求。CAS 挡验证期间竞态，组合规则挡完成后的迟到写入。

本期采用保守边界：严格标记建立后若发现需要改变server/name/zone的再次转服/改名，拒绝部分迁移并记录unresolved，交受控专项核验；即使新证据有效也不偷偷突破本期ID-only写契约。本期不承诺该类后续迁移自动恢复，不冻结无冲突同步状态。完整组合迁移若需自动化，必须另行确认范围。

ID-only 覆盖前显式复用 role_identities_history 的旧快照和既有 archive_reason/archive_source。归档失败不更新；归档成功但 CAS 失配的快照不能当修复数。存量执行以操作记录、matched_count 和回读为准，无新审计集合/字段。

## 页面有界探测

复用既有串行上游方式，在现有 service 内使用有界进程内同角色合并和失败冷却：默认 180 秒、容量 1024、探测并发 1；重启丢失冷却，不承诺跨进程合并，发布前确认单 bot 前提。跨进程数据正确性由 CAS 保证。

单请求最多当前 indicator 1、候选 indicator 2、必要 history 1、replay 1，共 5 个逻辑调用，底层重试另计。探测 deadline 默认 15 秒，超时不再发起调用、迟到结果不发布；不能声称 asyncio 能取消线程内 HTTP，底层 client 必须有限超时。候选耗尽返回原错误，不无界重试，不新增前端轮询或恢复状态协议。

deadline到期后，实际在途HTTP未结束前仍占用探测许可；不可因await取消就释放锁，让其他角色无限叠加线程。调用完成才释放许可，迟到结果丢弃；许可占用期间其他探测有界等待或返回原错误。五次是最大值，预算不足允许未解决，不保证两个候选都完成证明。

force_refresh 只控制战绩缓存，不绕过恢复冷却、探测数量或验证权限。公开请求与运维脚本的额度分别有界，不声称存在跨进程/全站共享限额。

只缓存本次成功响应。CAS 失败重读，不将旧响应缓存到已变化身份。缓存保存失败不回滚正确 ID，但如实报告、允许下次查；API 结构、路由和 identity_only 边界不变。

## 一次性恢复

scripts/recover_jjc_role_identities.py提供inventory/verify/apply/verify-applied/rollback。默认只读，不调 init_mongo/建索引；显式apply才写历史归档、两个ID/既有标记。CLI保守不写缓存，备份关联cache后先标applied_unverified，后续公开API验收写真实成功缓存；因此CLI回滚不删除后来缓存。apply不能直接用旧verify结果，每条重新实时验证，fsync后再检查观测未过15秒才CAS。

inventory读全量身份和全部保留缓存/历史/排名不同locator；额外replay扫描用显式--replay-scan-limit流式限量，报告requested/scanned/limit/may_be_truncated，未扫描不当健康。CLI单并发、调用最小间隔1秒、每命令最多20角色；批准设计run上限120，实现为降低跨批记账复杂度保守收紧同run为100（包含全部子命令/主动API预留），耗尽停止，不连续新建run绕限。鉴权/429立即停。

verify/apply/verify-applied及运维主动force_refresh可能产生的上游调用，按同一run操作记录累计，不同命令不能重置额度。每批最多20而不是保证20，100次含apply及复验，剩余额度不足时缩批或留applied_unverified。公开API没有可信调用计数时保守按请求上限5次预留，不能把未知计零；可证明缓存命中才记零。自然公众流量另计，不虚称CLI限制全站。

verify-applied默认直接只读身份/操作记录，必要时直接只读上游，不调用可能写缓存/自愈的公开API，仍共用run预算和间隔；公开业务API验收单列为允许缓存/恢复写入的线上操作，手工curl不能称严格零写验证。probe上限与角色整个发布生命周期调用数不是一个口径。

受控本地文件按 run_id/manifest hash/commit 记录 before/expected-after、字段存在状态与证据，先 flush/fsync 备份再写库，失败即停。完整备份含关联缓存、不含凭据，不提交原始清单。继续执行先回读、重验，不盲跳。回滚用 after-image CAS，只恢复本次字段及缺失状态、包括观测标记；只条件失效本次缓存，不覆盖后续缓存或恢复过期战绩。无新运行时 JSON 缓存，操作文件只服务显式运维命令。

## 发布与覆盖边界

本地 TDD、独立 review、真实 Python3.9/隔离 Mongo和回滚演练通过后才 commit。制品仅从绿色 commit 的 allowlist 导出，逐文件哈希，不打包dirty tree。发布前固定生产全部相关源码/依赖基线manifest，在隔离副本叠加实际制品并跑相关验证；缺失未发布依赖或不能证明组合兼容则停止。运行版本记录目标基线manifest+overlay release SHA+制品hash，不伪称整个生产目录等于该commit。

生产/app绑定挂载，先暂停同步、确认无旧写者，停止容器、替换文件、启动容器。相关独立Python writer必须实际停止或升级后重启并证明重新加载，替换磁盘文件不算重载。不重启宿主机、compose down或无故重建镜像，配置只允许备份后修改获批启用项，其他凭据/配置保留。代码和数据分别备份/回滚。

首次启动恢复开关保持0，健康后小耶猫单角色apply，核对身份、公开API和真实页面、健康对照；试点通过后开启该项，第二次受控重启加载并验证自愈/持久性，随后分批。两次容器重启属于G0批准范围，不自行增加第三次。所有涉及独立worker实际重载并验证后才恢复同步，额外进程重启范围不明则重新确认。当前指标取执行时响应，不写死706场。

全库线索盘点不等于全库上游普查。旧 1104 是“最新单一证据”的差异数，不是完整候选/故障名单。无候选、冲突、无数据、上游失败单列；未知不标健康，不保证重复访问一定发现候选。外部原始证据保留在操作空间 _diagnostics/2026-10-20-role-identity-recovery，Git 只提交最小脱敏 fixture/摘要。
