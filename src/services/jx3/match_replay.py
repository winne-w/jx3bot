from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchReplayClient:
    """推栏：获取 3c 战局回放数据。

    接口: POST /3c/mine/match/replay
    body: {"match_id": 123, "ts": "..."}  (ts 由 tuilan_request 自动补充)

    replay players[].role_id 可用于身份补全。
    replay players[].global_role_id 是数字字符串，不可作为 SK01 global_role_id 写入。
    """

    match_replay_url: str
    tuilan_request: Callable[[str, dict[str, Any]], Any]

    def get_match_replay(self, *, match_id: int) -> dict[str, Any]:
        url = self.match_replay_url
        params = {"match_id": int(match_id)}

        logger.info(
            "推栏战局回放请求: url={} params={}".format(
                url,
                json.dumps(params, ensure_ascii=False),
            )
        )

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                logger.warning("推栏战局回放请求失败: 返回None")
                return {"error": "请求返回None"}

            if isinstance(result, dict) and "error" in result:
                logger.warning("推栏战局回放请求失败: %s", result.get("error"))
                return result

            logger.info("推栏战局回放请求成功")
            return result
        except Exception as exc:
            logger.exception("推栏战局回放请求异常: %s", exc)
            return {"error": f"请求异常: {exc}"}
