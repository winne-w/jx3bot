# Review

独立API盘点覆盖13在用+2新增路径及三类HTTP入口。测试agent复核normalizer/请求认证和消费者；consumer agent复核uid、公告、status及role用例，无未关闭阻断。root整合并跑完整回归、真实生产依赖验证。

已关闭的review问题包括：失败detail=success误判，truthy error响应被字段投影，公告业务失败误报无记录，规范time被date覆盖，在线null/list顶层响应崩溃，UID Unicode/超长数字转换异常，fraud对象/records响应漏条目，奇遇nullable时间及单服开服list。

安全检查：新请求令牌使用header，ticket仅指定请求；新POST默认TLS验证、零重试、不缓存。模板显式autoescape，在线严格唯一身份和布尔值，appLogin不作为游戏在线；不记录凭据，不发实际QQ消息；生产配置仅合并API/正则差异。原有非本次变更的配置/日志安全债不在本次扩大处理。

验证限制：生产原5项排名通知测试有2项与当前生产已发布逻辑不一致，baseline精确复现；最终候选108项生产依赖通过。离线fixture不证明每个角色都被第三方收录；真实资历样本404为魔盒未绑定/未收录限制，需在验收报告保留。

最终实查增量已关闭URLquery uid丢失；新闻当前/历史id统一字符串，避免旧缓存数字类型导致重复推送。测试113项本地全绿、108项最终生产依赖全绿。
