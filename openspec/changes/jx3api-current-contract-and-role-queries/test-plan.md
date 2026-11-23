# Test Plan

独立测试子agent先RED共享契约（新旧envelope、空/畸形、失败sentinel、token、资历迁址、POST在线无缓存）；feature子agent编写角色service和handler测试；root集成原回归、真实依赖与图片。禁止离线测试连接生产数据库/上游；线上只读冒烟使用现有配置，不记录凭据，不发群消息。
