from __future__ import annotations

import time
from typing import Any, Mapping

import httpx
from nonebot import logger


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        verify: bool = True,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.verify = verify
        self.default_headers = dict(default_headers or {})

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        content: bytes | None = None,
        timeout: float | None = None,
        verify: bool | None = None,
    ) -> dict[str, Any]:
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        last_error: str | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=timeout or self.timeout,
                    verify=self.verify if verify is None else verify,
                    headers=merged_headers,
                ) as client:
                    response = client.request(
                        method.upper(),
                        url,
                        params=params,
                        json=json_body,
                        content=content,
                    )
                if response.status_code >= 400:
                    return {
                        "error": f"http_status_{response.status_code}",
                        "status_code": response.status_code,
                        "text": response.text,
                    }
                try:
                    return response.json()
                except Exception:
                    return {"error": "invalid_json", "status_code": response.status_code, "text": response.text}
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = str(exc)
                if attempt < self.retries:
                    time.sleep(self.backoff_seconds * (2**attempt))
                    continue
                logger.warning(f"http request failed: method={method} url={url} error={exc}")
                return {"error": "request_failed", "message": last_error}
            except Exception as exc:
                logger.warning(f"http request unexpected error: method={method} url={url} error={exc}")
                return {"error": "request_failed", "message": str(exc)}

        return {"error": "request_failed", "message": last_error or "unknown"}

