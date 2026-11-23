# 装备图标展示

## Purpose / Big Picture
用户要求装备、五行石等依赖魔盒或推栏图片展示；在既有fix/arena-recent-response-20261123分支继续实现、测试、提交推送和精确部署。复用项目既有魔盒icon/{iconId}.png规则，7529/2351/11751真实PNG已验证。

## Progress
- [x] 核对接口iconId及图标URL
- [x] 测试子agent独立验证、service/template并行实现与独立复核
- [x] 真实图片与失败回退验证
- [ ] commit/push、备份和精确部署验收

## Surprises & Discoveries
图标为48×48 PNG；通用截图函数不会在set_content之后确认图片完成，故不把新增外链直接交给截图抢时序。

## Decision Log
service保留原名字字段，另加安全图标模型。装备图标、五行石/五彩石/有效附魔支持图片；五行石等级显示短标记。渲染器只在装备模板中调用有界infra预取并嵌入data URI；其他模板不受影响。不修改通用截图、第三方API或数据库。

## Context and Orientation
service role_queries.py + 装备查询.html由feature子agent负责；root实现infra/jx3box_icons.py及renderers/jx3/equipment_icons.py和image.py装备专用接入；test子agent只写test_equipment_icons.py。

## Plan of Work
仅允许固定魔盒图标域名及正整数ID；4并发、总预算6秒、单图32KiB、尺寸不超过256、最多128独立图标；成功有界内存LRU缓存256项/24小时，失败文字回退。保留自动高度、所有13件、24面板和原始采集时间。

## Concrete Steps
针对安全URL、重复去重、超时/错误/缺icon、输入不变和图片模板做测试；生成真实目标图片确认图标可见。部署按既有原组合逐文件hash守卫、备份、停启验证；只部署本次文件，失败条件恢复。

## Validation and Acceptance
图片中五行石显示图标+等级，不再重复完整文字；无icon/下载失败仍完整显示名称，13件不丢失。独立回归及Python3.9生产依赖通过；真实截图检查与4worker/QQ/HTTP就绪。

## Outcomes & Retrospective
本地Python3.13与真实生产组合Python3.9.9各110项通过，0skip；其中新25图标、旧16角色。测试与实现并行，测试落盘时实现已存在，实际首次全GREEN，不宣称RED。独立复核关闭client构造/退出异常回退与PNG块CRC校验缺口。真实13件/24面板保持；35图标节点中32有有效ID并全部加载（15独立PNG），3缺ID的附魔按名称回退。冷预取2.840秒，PNG2238×6028、919809字节，已人工查看完整装备与五行石图片/七级角标。强制加载失败时完整名称可见且不生成外链。首次prepare在完成候选后因旧脚本读取manifest中的config项报KeyError，已改为独立配置指纹，真实源/候选hash复核通过；未在该阶段修改生产。待commit/push及上线验证。


线上首次冷加载验证中，3秒总预算/2秒单图时限导致部分有效ID图标未加载，文字回退正确但首个五行石也可能回退，未计最终验收通过。单独实读PNG7529握手2.474秒、2351为1.347秒、11751为0.433秒，均HTTP200/CRC有效；因此调整总预取6秒、HTTP单次4.5秒，仍4并发/原体积和缓存限制，属于根据真实网络选择图标加载预算，不修改任何既有业务请求时限。原失败记录保留。
