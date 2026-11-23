# Design

共享infra适配JX3API正文status/detail至code/msg/data，按端点校验成功payload对象/数组，业务失败不缓存且不可误判success，空对象在数组接口映射空列表；兼容既有code/msg/data，非JX3API来源不改契约。所有需token端点改请求头；ticket仅在文档要求的接口发送。资历路径迁/role/achievement，class=3保持合并语义。

在既有字段适配上修复新闻id/time、奇遇nullable time、大区状态单服数组，空响应消费者安全失败。公共日历/新闻/技改/科举及status_monitor直连JSON均通过同一normalizer；业务失败需明确提示，不冒充无记录。

装备以/calcd/attribute?format=calcd读取已收录装备/面板；保留原始条目，service将真实itemName/itemQuality/iconId等投影为展示模型，属性格式和值依真实响应处理，展示采集cacheTime而非当前在线装备，旧模板适配或替换。命令装备/属性/装分，显式区服或群绑定。在线走POST /role/online/status，header token，JSON ticket/query数组；不使用12分钟查询缓存。只把onlineStatus或gameLogin明确布尔值解释为游戏状态，appLogin不代表游戏在线；空/缺字段/身份不匹配显示未知，不能冒称离线。命令在线/在线状态/角色在线。

配置只加URL/正则，不携带凭据。上线保留生产config全部现有运行值，按受审文本补丁合并新增键；禁止用Git版config覆盖现网。新能力注册于现有薄handler，service负责领域及展示模型，infra负责外部POST。不更改JJC Mongo/worker生命周期或数据。
