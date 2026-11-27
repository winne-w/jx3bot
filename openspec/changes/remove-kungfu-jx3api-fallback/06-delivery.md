# GitHub PR 与生产发布（2026-11-25）

用户明确要求创建GitHub PR并部署到正式环境。独立分支fix/remove-kungfu-jx3api-fallback，以最新main 8a21a2b为基线，只应用本需求增量；原dirty工作区保持不动。

## PR候选验证

独立PR工作树新行为及历史胜场测试Python3.13/3.9各47项通过。扩大组各326项，21失败/6错误；对照未修改main的同组321项，27个失败ID逐项一致，两版均无新增失败。原dirty整合工作区双版各372通过是另一组明确来源的证据，不冒充独立PR全量通过。main不存在的四个未跟踪延迟测试文件未混入PR。

## 生产候选

当前线上源与本地dirty状态不同，基于线上原文件构造两文件补丁；原get_user_kungfu与update_kungfu_cache逐方法对照本次修改前快照完全相同，新get_user_kungfu采用已review版本，其他生产逻辑保持。备份与发布目录为/root/jx3bot-releases/remove-kungfu-jx3api-20261125，仅包含两生产文件候选、备份和发布证据。

197个源/静态/配置文件hash守卫。生产同Docker镜像、network none、read-only加tmpfs隔离验证实际生产src及两文件overlay，Python3.9共47项通过，生产尚未替换。后续将记录实际应用、重启、API与worker就绪及观察结果。

## 正式发布完成（最新状态）

用户已明确授权创建GitHub PR和部署。PR：https://github.com/winne-w/jx3bot/pull/17，修复提交6c4d115，PR保持打开，未合并main。

正式环境仅替换jjc_ranking.py和singletons.py两个生产文件，同容器、同镜像，197个源/静态/配置文件hash守卫确认其余文件不变。重启开始时间为 2026-11-25T22:38:09+08:00，容器实际启动时间为 2026-11-25T14:38:10.309565968Z，2026-11-25T22:39:17+08:00 完成就绪验证。备份和回滚工具保存在/root/jx3bot-releases/remove-kungfu-jx3api-20261125。

实际旧进程在SIGTERM后60秒仍未退出，由Docker发送SIGKILL，旧进程exit137；新进程正常初始化。就绪与后续129.2秒、5个样本观察中，四个worker均绑定新bot PID且心跳新鲜；容器持续运行，未额外重启/OOM，启动及完整有界日志没有Traceback/导入/类型/语法错误。公网seasons接口五次HTTP200、status_code0。未强制触发真实角色查询或排名统计，不把静态删除和离线测试当作实际上游查询成功。

发布前同步队列已因推栏战局历史403鉴权失败处于全局暂停。发布后paused及pause_updated_at保持原值；四个worker在线但维持暂停，本次不更换凭据、不恢复队列。

发布脚本review发现的“停止命令失败后可能跳过恢复”问题已于apply前修正并复核关闭；发生停止尝试即进入已知hash状态的恢复路径。实际发布无回滚。PR独立工作树的扩大回归仍有与main完全一致的27项既有失败，未引入新增失败；详情见上文和evidence/pr-baseline-comparison.json。

生产证据摘要见evidence/production-deployment.json。上述正式发布状态优先于本change较早的“仅本地/未部署”历史记录。
