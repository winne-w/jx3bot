# GitHub PR 与生产发布（2026-11-25）

用户明确要求创建GitHub PR并部署到正式环境。独立分支fix/remove-kungfu-jx3api-fallback，以最新main 8a21a2b为基线，只应用本需求增量；原dirty工作区保持不动。

## PR候选验证

独立PR工作树新行为及历史胜场测试Python3.13/3.9各47项通过。扩大组各326项，21失败/6错误；对照未修改main的同组321项，27个失败ID逐项一致，两版均无新增失败。原dirty整合工作区双版各372通过是另一组明确来源的证据，不冒充独立PR全量通过。main不存在的四个未跟踪延迟测试文件未混入PR。

## 生产候选

当前线上源与本地dirty状态不同，基于线上原文件构造两文件补丁；原get_user_kungfu与update_kungfu_cache逐方法对照本次修改前快照完全相同，新get_user_kungfu采用已review版本，其他生产逻辑保持。备份与发布目录为/root/jx3bot-releases/remove-kungfu-jx3api-20261125，仅包含两生产文件候选、备份和发布证据。

197个源/静态/配置文件hash守卫。生产同Docker镜像、network none、read-only加tmpfs隔离验证实际生产src及两文件overlay，Python3.9共47项通过，生产尚未替换。后续将记录实际应用、重启、API与worker就绪及观察结果。
