# 修复 QQ 战绩查询响应适配

## Purpose / Big Picture
用户已明确授权按官方文档修复、测试、commit、push 和部署。11-23 20:41 的战绩查询因上游 status/detail 与旧 msg/data 契约不兼容而失败。官方文档 https://www.jx3api.com/#/arena/recent 的 /openapi 规定 token 请求头、server/name/ticket 查询参数，HTTP200 下以整数 status 判定业务成功。

## Design
仅为 /arena/recent 适配新响应：status=200 且 detail 为对象时映射 code=200/msg=success/data=detail；业务失败将字符串 detail 映射为旧错误提示，406保留旧专用提示；成功但detail类型错误应失败且不得伪装成功。旧code/msg/data不变；其他端点不变；不修改入参原对象。该端点的 token 移至请求头。空成功对象沿用无战绩提示。新结构业务失败打error标记，以免被现有缓存当作成功保存。不修改模板、存储或缓存策略本身。

## Progress
- [x] 读取线上日志、复现并核对官方 OpenAPI
- [x] 独立测试 agent 先编写失败契约测试，主执行者实现
- [x] Python3.13与真实生产Python3.9.9各24项测试通过；独立diff复核通过，渲染冒烟执行中
- [ ] 仅提交本次文件并推送独立修复分支
- [ ] 服务端源文件基线核对、备份、精确替换、重启及真实查询验证

## Surprises & Discoveries
原工作区存在大量未提交内容；本次独立工作树基于远端 feat/jjc-safe-live-refresh。GitHub SSH22不可用，SSH443已验证可用。

## Decision Log
新结构严格按文档整数status判断，不能仅凭HTTP200或存在detail判断成功。仅部署两个infra及一个query_context运行文件，以生产原始文件叠加本次补丁构造候选，不从旧Git基线整仓覆盖。

## Context and Orientation
涉及 src/infra/jx3api_compat.py 的响应适配及 src/infra/jx3api_get.py 的token传输；旧消费者 src/services/jx3/command_context.py 要求msg=success，query_context要求data。tests/test_arena_recent_response.py 由测试agent负责，其他文件由主执行者负责。

## Plan of Work
测试覆盖新旧成功、业务错误、406、错误类型、非arena隔离、输入不可变以及真实get调用参数；实现后运行现有兼容测试、渲染集成测试、Python3.9编译。测试和主执行者复核后，提交并推送修复分支。生产停容器后精确替换三个文件并启动，验证源码哈希、启动、四worker、有限真实查询和图片渲染。

## Concrete Steps
使用既有venv运行 unittest tests.test_jx3api_compat tests.test_arena_recent_response；验证无凭据入库。部署前备份三个生产文件并记录manifest，保持配置/容器镜像不变；失败则停容器还原备份并启动。

## Validation and Acceptance
成功响应通过旧命令消费并可渲染含战绩的HTML/图片；错误响应不冒充成功，其他端点无行为变化。真实目标查询成功才宣称修复验收；不发送QQ消息。备份保留用于条件回滚。

## Outcomes & Retrospective
独立测试先行19项，首次RED（16方法/子用例28处失败）后实现；最终新增19+既有5共24项在本地3.13及服务端3.9.9全部通过。独立复核关闭失败detail=success误判成功的边界。原始本地3.9缺cacheout，4项导入失败；随后在真实生产3.9.9依赖中加载候选模块跑全24通过，非跳过依赖或伪造测试环境。三个生产文件按文本归一化与基线一致，候选编译通过。线上查询与渲染冒烟仍在执行，发布记录后续补全。
