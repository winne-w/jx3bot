# Acceptance

2026-11-24 15:06:15+08启动代码f3cbacdac396e97c84c518002c1233f04672faca，已push到fix/arena-recent-response-20261123。精确部署3运行文件：equipment_query.py、kungfu_aliases.py（新增）、qun.html；同一容器/镜像，config.py/runtime_config/.env.prod/compose/start哈希均未变。生产源码CAS、备份和manifest位于/root/jx3bot-releases/kungfu-aliases-20261124。

独立别名表覆盖33标准名与165唯一别名，歧义单列；来源表记录调研与项目缩写约定。20独立别名+31查询及119既有回归，共170测试，Python3.13本地与Python3.9.9生产依赖均通过、0跳过，diff-check通过。独立复核无确定阻断。

候选和部署后真实只读查询均通过：桃桃白糖 bx PVE为冰心诀/秘境挑战；奶秀/秀奶 PVP与单项全角ＮＸ为云裳心经/竞技对抗，均苍生铸世13件装备。tl/cy/tx/yl和七秀明确歧义，洗髓/少林T通过映射单测但无该心法真实已收录角色样本。未向QQ发送消息。HTTP正常、QQ connected、4个started_at>=容器新启动时间的bot worker在线，源码hash与manifest匹配。

证据：私有release目录verification-summary.json；容器/tmp/kungfu-aliases-20261124内test-summary.json和deployed-smoke.json（另已拷贝host）。回滚仅恢复两既有文件并删除新增映射，保留期间其他源码/配置改动；不涉及数据迁移。
