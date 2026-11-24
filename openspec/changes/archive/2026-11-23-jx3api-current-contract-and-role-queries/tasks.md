# Execution Plan

## Purpose / Big Picture
按官方文档恢复所有现用接口和两项角色查询，使用既有修复分支，完成测试、复核、commit/push与精确发布。

## Progress
- [x] 读取源码/官方OpenAPI，真实装备及在线响应只读侦察
- [x] 子agent测试先行及全调用点独立审计
- [x] root统一infra适配/请求参数和旧consumer边界，子agent实现装备与在线用例
- [x] 集成回归、双版本真实依赖、图片验证及独立review
- [x] commit/push并校验远端SHA，运行补丁88d779b
- [x] 原生产组合备份、18文件逐文件补丁、同容器重启及有限真实只读验收

## Surprises & Discoveries
13个既有JX3API端点均使用status/detail；旧资历路径移除。装备/calcd/attribute返回13件装备、列表面板和equipScore；在线返回列表，字段onlineStatus/gameLogin与appLogin独立。该目标资历返回魔盒绑定404，为真实业务限制。

## Decision Log
用户本轮明确全修和分支范围，直接推进实现；无须重复询问方案批准。计划/测试/review独立记录于本change。测试agent只写独立契约测试文件，feature agent仅负责指定角色用例文件，root负责infra/消费者/文档和最终部署。

## Context and Orientation
运行Python3.9+；分层plugins→services→infra/storage。入口src/plugins/jx3bot.py与handlers/queries.py，旧通用查询infra/jx3api_get.py/compat.py，其他fetch_json与status_monitor有直连normalizer，必须覆盖。原主工作区dirty保持不动。

## Plan of Work
盘点覆盖表先于实现。测试先RED验证共享envelope/路径/token及失败；角色新用例覆盖在线/离线/未知/上游失败和装备新结构、空面板、错误参数、命令注册、无缓存。逐消费者检视新闻/技改/资历/百战/名片/奇遇/烟花/科举/骗子/开服/日常。新旧fixture与真实有限读取分开。

## Concrete Steps
运行24项原arena回归、新contract与role命令模块，现有相关服务测试；Python3.9编译和真实依赖单测。候选在服务端私有目录用生产依赖加载测试，明确patch清单和源hash。生产脚本对源文件及config受审片段CAS，备份后停容器替换再启动；守卫失败不覆盖，启动/冒烟失败条件还原备份。

## Validation and Acceptance
15端点覆盖表完整；新成功可消费/业务失败可解释；装备图片和真实在线查询通过，不把app登录当游戏在线，不主动发QQ消息。HTTP启动、QQ连接、4worker及源码/配置守卫通过，新增配置仅预期键。

## Outcomes & Retrospective
代码与独立审查完成。全新契约测试首次RED为21方法/278失败子用例+11错误；consumer首次16项中6失败5错误；角色首次模块缺失RED。最终本地相关113项全绿。真实生产依赖Python3.9.9上候选112项中110通过、2项排名通知测试失败；对未打补丁的实际生产jobs.py复跑原5项，原样复现同2项断言失败，确认与本次更改无关。剔除该旧测试模块后最终候选其余108项在真实生产依赖中全部通过，无跳过。未修改旧排名逻辑或放宽测试。

候选按生产全源码叠加18文件受审补丁生成，保留生产其他未提交功能。首次诊断补丁因无换行EOF导致格式损坏，改用Git原生diff后保留了原CRLF相关失败证据；在私有候选归一换行后逐hunk精确check/apply通过，未修改生产。


最终v4候选15端点真实有限GET/在线只读POST均验证完成；14端点业务成功，资历目标因魔盒未绑定404且提示正确。科举以李白命中成功；首次剑网3关键词未匹配返回400，保留业务失败证据。真实发现fraud URL uid被后加params覆盖，修复parse_qsl合并后返回正常记录并补回归，未误把必填错误当作空记录。装备13件/面板24项，PNG2238×5196、742679字节，SHA256 94f68f363dd8088520071a53c64171111b62abd118c0d2d683cf38fff1933db8，已人工查看完整无截断。在线目标明确游戏离线，独立appLogin=true不影响结论。


## Production Result

2026-11-23 21:24:55+08同容器重新启动，21:25:46启动完成，21:25:54 QQ连接，21:26:34最终运行守卫通过。生产为原完整组合叠加88d779b三新/十五修改文件补丁，不表示全仓运行状态等同该Git提交。18源文件hash均与私有manifest一致，配置仅允许API_URLS装备/在线/资历及REGEX装备/在线变化，AST证明其余配置未改；runtime_config/.env/compose/start脚本哈希未改，同容器同镜像restart_count=0，4个重启后fresh full worker在线，HTTP status_code0。

部署后4关键端点（战绩、装备、骗子、在线）真实验收全部成功，装备13/面板24，图片与候选哈希一致，游戏离线状态正确。补充真实旧consumer验收：烟花23条与奇遇76条的模板HTML渲染通过、百战156技能可解析、名片有效头像元数据、更新命令可匹配最新版本公告。未发QQ群测试消息，未主动触发调度或推送。

服务端私有目录/root/jx3bot-releases/jx3api-current-contract-20261123保存完整候选、backup、before/deployment/verification-summary、补丁和脚本。回滚仅在当前源仍等于本次候选哈希时停容器恢复15个原文件、条件删除3个新增文件，再启动并做同样守卫；未知漂移不覆盖，配置备份含真实值只保留私有目录。没有改写业务Mongo事实、队列或水位。
