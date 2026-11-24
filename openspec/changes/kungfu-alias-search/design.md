# 方案

新增src/services/jx3/kungfu_aliases.py，KUNGFU_ALIASES维护标准心法名→唯一别名tuple，AMBIGUOUS_KUNGFU_ALIASES维护歧义输入→标准名候选；覆盖现有catalog33心法（32目录心法加洗髓经），包括山居与问水。纯函数resolve_kungfu_alias做NFKC、首尾空白清理、casefold、完整token匹配，未知返回None，歧义抛带候选的KungfuAliasError。只用Python标准库，不加运行JSON读写/数据库/网络。标准名优先，构造索引时拒绝重复归属/不合法候选，维护测试保证catalog同步。

中文简称及俗称按调研人工收录，用户给定别名直接纳入；字母缩写为显式维护的输入约定，不动态猜拼音、不做包含匹配/编辑距离。门派多心法名及其常见缩写明确歧义，包括藏剑（山居/问水）。tl为铁牢/天罗，cy为纯阳/苍云四候选；xz仅相知、xc为笑尘。体型称谓和容易贬损的外号不纳入。

装备parser的裸尾参数与心法=/kungfu=共用resolver，输出标准名，传给现有records/detail和缓存URL；数据选择、响应校验仍只比较标准名。完整服务器后的角色token或唯一角色token优先保留，防止角色名bx被吞；裸心法筛选仍放在角色后。同义词重复也拒绝。未知显式别名提示，歧义给出候选和完整名用法。旧命令及无筛选行为兼容。

README/群帮助增加例子，docs/references/kungfu-aliases.md提供完整33心法（32目录心法加洗髓经）映射表和调研来源。回滚仅恢复equipment_query.py及帮助模板并移除新增映射文件；无配置或数据迁移。
