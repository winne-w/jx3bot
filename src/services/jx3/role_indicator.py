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
class RoleIndicatorClient:
    """推栏：获取角色 indicator 信息。

    接口: POST /role/indicator
    body: {"role_id": "...", "zone": "...", "server": "...", "ts": "..."}
      (ts 由 tuilan_request 自动补充)

    返回:
      role_info.global_role_id —— SK01... 格式
      role_info.role_id
      role_info.name / zone / server
      person_info.person_id
    """

    role_indicator_url: str
    tuilan_request: Callable[[str, dict[str, Any]], Any]

    def get_role_indicator(
        self,
        *,
        role_id: str,
        zone: str,
        server: str,
    ) -> dict[str, Any]:
        url = self.role_indicator_url
        params = {
            "role_id": str(role_id),
            "zone": str(zone),
            "server": str(server),
        }

        logger.info(
            "推栏角色 indicator 请求: url={} params={}".format(
                url,
                json.dumps(params, ensure_ascii=False),
            )
        )

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                logger.warning("推栏角色 indicator 请求失败: 返回None")
                return {"error": "请求返回None"}

            if isinstance(result, dict) and "error" in result:
                logger.warning("推栏角色 indicator 请求失败: {}", result.get("error"))
                return result

            logger.info("推栏角色 indicator 请求成功")
            return result
        except Exception as exc:
            logger.exception("推栏角色 indicator 请求异常: {}", exc)
            return {"error": f"请求异常: {exc}"}
