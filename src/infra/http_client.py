from __future__ import annotations

import asyncio
import datetime
import email.utils
import time
from typing import Any, Dict, Mapping, Optional

import httpx
from nonebot import logger
from src.utils.jjc_query_observability import (foreground_safe_logger, query_stage,
    query_outbound, query_failure)

logger = foreground_safe_logger(logger, component="http")

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_SHARED_ASYNC_CLIENTS: Dict[bool, httpx.AsyncClient] = {}
_SHARED_ASYNC_CLIENT_LOOPS: Dict[bool, asyncio.AbstractEventLoop] = {}


def _get_shared_async_client(verify: bool) -> httpx.AsyncClient:
    verify_key = bool(verify)
    loop = asyncio.get_running_loop()
    client = _SHARED_ASYNC_CLIENTS.get(verify_key)
    client_loop = _SHARED_ASYNC_CLIENT_LOOPS.get(verify_key)
    if client is not None and not client.is_closed and client_loop is loop:
        return client
    client = _REAL_ASYNC_CLIENT(verify=verify_key)
    _SHARED_ASYNC_CLIENTS[verify_key] = client
    _SHARED_ASYNC_CLIENT_LOOPS[verify_key] = loop
    return client


async def close_shared_async_clients() -> None:
    try:
        current_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    items = list(_SHARED_ASYNC_CLIENTS.items())
    loops = dict(_SHARED_ASYNC_CLIENT_LOOPS)
    _SHARED_ASYNC_CLIENTS.clear()
    _SHARED_ASYNC_CLIENT_LOOPS.clear()

    for verify_key, client in items:
        if client.is_closed:
            continue
        client_loop = loops.get(verify_key)
        if client_loop is not None and current_loop is not None and client_loop is not current_loop:
            continue
        try:
            await client.aclose()
        except Exception as exc:
            logger.warning(f"failed to close shared async http client: verify={verify_key} error={exc}")


def _retry_after_seconds(value):
    try:
        return max(1, int(value))
    except (ValueError, TypeError):
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            return max(1, int((parsed - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        verify: bool = True,
        default_headers: Optional[Mapping[str, str]] = None,
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
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json_body: Optional[Any] = None,
        content: Optional[bytes] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
    ) -> Dict[str, Any]:
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        last_error: Optional[str] = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=timeout or self.timeout,
                    verify=self.verify if verify is None else verify,
                    headers=merged_headers,
                ) as client:
                    query_outbound()
                    with query_stage("http"):
                        response = client.request(
                            method.upper(),
                            url,
                            params=params,
                            json=json_body,
                            content=content,
                        )
                if response.status_code >= 400:
                    query_failure("upstream_rejected")
                    error_result = {
                        "error": f"http_status_{response.status_code}",
                        "status_code": response.status_code,
                        "text": response.text,
                    }
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        error_result["retry_after_seconds"] = _retry_after_seconds(retry_after)
                    return error_result
                try:
                    return response.json()
                except Exception:
                    return {"error": "invalid_json", "status_code": response.status_code, "text": response.text}
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                query_failure("timeout" if isinstance(exc, httpx.TimeoutException) else "transport", exc)
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


    async def arequest_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json_body: Optional[Any] = None,
        content: Optional[bytes] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
    ) -> Dict[str, Any]:
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        effective_verify = self.verify if verify is None else verify
        effective_timeout = timeout or self.timeout

        last_error: Optional[str] = None
        for attempt in range(self.retries + 1):
            try:
                if httpx.AsyncClient is _REAL_ASYNC_CLIENT:
                    client = _get_shared_async_client(effective_verify)
                    query_outbound()
                    with query_stage("http"):
                        response = await client.request(
                            method.upper(),
                            url,
                            params=params,
                            json=json_body,
                            content=content,
                            headers=merged_headers,
                            timeout=effective_timeout,
                        )
                else:
                    async with httpx.AsyncClient(
                        timeout=effective_timeout,
                        verify=effective_verify,
                        headers=merged_headers,
                    ) as client:
                        query_outbound()
                        with query_stage("http"):
                            response = await client.request(
                                method.upper(),
                                url,
                                params=params,
                                json=json_body,
                                content=content,
                            )
                if response.status_code >= 400:
                    query_failure("upstream_rejected")
                    error_result = {
                        "error": f"http_status_{response.status_code}",
                        "status_code": response.status_code,
                        "text": response.text,
                    }
                    if response.status_code == 429:
                        error_result["retry_after"] = response.headers.get("Retry-After")
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        error_result["retry_after_seconds"] = _retry_after_seconds(retry_after)
                    return error_result
                try:
                    return response.json()
                except Exception:
                    return {"error": "invalid_json", "status_code": response.status_code, "text": response.text}
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                query_failure("timeout" if isinstance(exc, httpx.TimeoutException) else "transport", exc)
                last_error = str(exc)
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff_seconds * (2**attempt))
                    continue
                logger.warning(f"http request failed: method={method} url={url} error={exc}")
                return {"error": "request_failed", "message": last_error}
            except Exception as exc:
                logger.warning(f"http request unexpected error: method={method} url={url} error={exc}")
                return {"error": "request_failed", "message": str(exc)}

        return {"error": "request_failed", "message": last_error or "unknown"}
