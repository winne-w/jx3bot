# JJC 同步日志增强：输出角色昵称、服务器、对局时间

## 目标

在竞技场同步的日志输出中增加当前同步的角色昵称、服务器名称、对局时间，方便排查同步进度和问题定位。

## 变更文件

- `src/services/jx3/jjc_match_data_sync.py`

## 具体改动

1. `_sync_one_role`：在 try 块开头增加 `logger.info("JJC 开始同步角色: {} / {}", server, name)`
2. `_sync_match_detail`：增加 `server`、`name` 参数，在拉取对局详情时输出 `logger.info("JJC 同步对局详情: match_id={} match_time={} server={} name={}", ...)`，match_time 转为可读时间字符串
3. `_sync_one_role` 中对 `_sync_match_detail` 的调用处传入 server/name

## 验证

```bash
python -m py_compile src/services/jx3/jjc_match_data_sync.py
```

## 回滚

还原文件即可。
