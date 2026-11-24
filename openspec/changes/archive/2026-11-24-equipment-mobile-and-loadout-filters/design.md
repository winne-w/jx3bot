# Design

视图改为760 CSS像素宽、主要文字30~34px，紧凑角色/心法/类型/赛季标题，12项代表性属性大数值网格；按治疗/攻击及配装类型选择指标，只使用上游percent而不臆算百分比。装备保持全部13行：大图标+名称、精炼星级、石头图标、短属性名、单行来源及附魔；省略逐条数值和重复说明。保留cacheTime与已收录标记，不从参考图复制头像、广告或二维码。

保留无筛选/attribute。新增/calcd/detail（必须kungfu,type）和/calcd/records（返回元数据equipList），两者注册status/detail适配。命令支持装备 [服务器] 角色 [完整心法] [pve/pvp/秘境挑战/竞技对抗/休闲/通用]，及心法=、类型=明确选项。旧三组handler输入保持兼容，新RegexGroup可为一组原始参数。重复/冲突/未知选项显示用法，不误拼成角色名。

同时指定两项直接查detail；部分指定先records精确筛选。单项筛选取有明确cacheTime的唯一最新匹配，并在卡片标明真实组合；时间缺失或同时间多组合要求补齐。不得回退当前配装冒充指定配装。详情返回心法/类型冲突须报错；显示详情实际seasonName/cacheTime，不承诺可任选历史赛季。通过URL query编码kungfu/type/format，沿用现有参数合并和按URL隔离的缓存，避免不同组合串数据。

领域查询编排新equipment_query.py；手机展示模型新equipment_mobile.py，由role_queries已有构建器调用。handler保持参数提取/调用/发送薄逻辑。外部查询复用既有fetch_jx3api_or_raise注入，整体45秒等待预算；无筛选行为兼容。config只加新地址/设备命令正则，不覆盖生产其他值。
