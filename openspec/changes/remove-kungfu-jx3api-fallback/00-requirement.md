# 移除心法查询的 JX3API 兜底

最新交付状态：用户后续已授权创建PR及正式发布，两文件已部署并通过就绪/短时观察；详情以[06-delivery.md](06-delivery.md)为准，下文保留各阶段记录。

日期：2026-11-25。状态：2026-11-25 用户已确认方案范围；执行计划已确认；本地实现及双版本回归完成，未部署。

## 需求

所有心法查询在推栏失败、缺少角色身份、榜单未匹配或没有可用心法时，不得再请求 JX3API 作为兜底，也不得从 JX3API 竞技历史中补出心法。

保留推栏正常查询、现有心法缓存读取和本地当前赛季胜场心法推断。全部可用来源均无结果时保持未知/失败，不能伪造心法成功。不清理既有缓存或历史快照。本需求不包含发布与重启。

## 调查依据

实际仓库为 WSL Ubuntu /home/songjingjing/codes/jx3bot，分支 feat/jjc-safe-live-refresh，调查时 HEAD 53815bb。工作区已有大量未提交改动，后续只增量修改本需求相关内容，不覆盖已有工作。

src/services/jx3/jjc_ranking.py 的 get_user_kungfu 在推栏流程结束后通过 defget_get(jjc_query_url) 主动请求 JX3API，再调用 update_kungfu_cache，并从 history 提取胜场心法。

同文件 update_kungfu_cache 在推栏未得到心法后，从调用方传入的 jjc_data.history 提取心法，是另一条需要移除的数据兜底路径。

singletons.py 将 src.infra.jx3api_get.get 和竞技查询 URL 注入 JjcRankingService。通用竞技查询命令和 arena_recent 也直接使用 JX3API；它们不是本需求指定的推栏失败后心法兜底。

## 验收目标

推栏失败、不匹配、身份缺失、返回空心法和异常场景下，心法流程的 JX3API 请求数均为零。传入带心法的 JX3API 历史也不能产生心法结果。本地合法缓存和推栏成功场景继续正常；本地无结果时输出未知或明确失败，其他竞技查询功能维持既有行为。
