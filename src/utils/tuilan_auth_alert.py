from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Optional, Set

import config as cfg

logger = logging.getLogger(__name__)

_AUTH_FAILURE_MARKERS = (
    "请重新登录",
    "请先登录",
    "未登录",
    "登录失效",
    "登录过期",
    "登录已过期",
    "登录状态失效",
    "票据失效",
    "票据过期",
    "票据错误",
    "无效票据",
    "ticket invalid",
    "ticket expired",
    "invalid ticket",
    "expired ticket",
    "token invalid",
    "token expired",
    "invalid token",
    "expired token",
    "not logged in",
    "unauthorized",
)
_STRICT_TICKET_MARKERS = (
    "票据失效",
    "票据过期",
    "票据错误",
    "无效票据",
    "ticket invalid",
    "ticket expired",
    "invalid ticket",
    "expired ticket",
)
_TUILAN_CONTEXT_MARKERS = ("推栏", "ticket", "票据")
_TUILAN_STATE_MARKERS = ("失效", "过期", "无效", "错误", "登录", "invalid", "expired")
_SUCCESS_CODES = (0, 200)

_state_lock = threading.Lock()
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_async_qq_sender: Optional[Callable[[str], Awaitable[bool]]] = None
_sync_email_sender: Optional[Callable[[str, Optional[str]], bool]] = None
_last_alert_fingerprint: Optional[str] = None
_last_alert_monotonic: Optional[float] = None
_retry_backoff_seconds: float = 300.0
_background_tasks: Set[asyncio.Task[Any]] = set()


def register_alert_handlers(
    *,
    async_qq_sender: Optional[Callable[[str], Awaitable[bool]]] = None,
    sync_email_sender: Optional[Callable[[str, Optional[str]], bool]] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """Register delivery callbacks from upper layers (plugins/infra) via dependency inversion."""
    global _async_qq_sender, _sync_email_sender, _main_loop
    with _state_lock:
        if async_qq_sender is not None:
            _async_qq_sender = async_qq_sender
        if sync_email_sender is not None:
            _sync_email_sender = sync_email_sender
        if loop is not None:
            _main_loop = loop


def clear_runtime_handlers() -> None:
    """Clear NoneBot runtime loop and QQ sender on shutdown (keeps fallback email sender)."""
    global _async_qq_sender, _main_loop
    with _state_lock:
        _async_qq_sender = None
        _main_loop = None


def reset_alert_state() -> None:
    """Reset in-memory throttle state (for tests or manual reset)."""
    global _last_alert_fingerprint, _last_alert_monotonic
    with _state_lock:
        _last_alert_fingerprint = None
        _last_alert_monotonic = None


def _ticket_fingerprint(ticket: str) -> str:
    cleaned = ticket.strip()
    if not cleaned:
        return "<empty>"
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def is_tuilan_auth_error(response: Any, *, strict_tuilan_only: bool = False) -> bool:
    """Return True when an upstream Tuilan (or ticket-bearing jx3api) response indicates auth failure.

    When ``strict_tuilan_only=True`` (for jx3api endpoints that carry both JX3API TOKEN and
    Tuilan TICKET), generic 401/403 or ``invalid token`` responses are ignored unless they
    explicitly reference Tuilan/ticket semantics.
    """
    if isinstance(response, dict):
        status = response.get("status_code")
        code = response.get("code")
        if status == 429 or code == 429:
            return False

        msg_parts = [
            _text(response.get("msg")),
            _text(response.get("message")),
            _text(response.get("error")),
            _text(response.get("text")),
        ]
        combined = " ".join(part for part in msg_parts if part).lower()

        if strict_tuilan_only:
            failed = (
                bool(response.get("error"))
                or status not in (None, 0, 200)
                or (code is not None and code not in _SUCCESS_CODES)
            )
            if not failed or not combined:
                return False
            if any(marker in combined for marker in _STRICT_TICKET_MARKERS):
                return True
            return any(ctx in combined for ctx in _TUILAN_CONTEXT_MARKERS) and any(
                st in combined for st in _TUILAN_STATE_MARKERS
            )

        if status in (401, 403) or code in (401, 403):
            return True

        failed = (
            bool(response.get("error"))
            or status not in (None, 0, 200)
            or (code is not None and code not in _SUCCESS_CODES)
        )
        if not failed or not combined:
            return False
        if any(marker in combined for marker in _AUTH_FAILURE_MARKERS):
            return True
        if any(ctx in combined for ctx in _TUILAN_CONTEXT_MARKERS) and any(
            st in combined for st in _TUILAN_STATE_MARKERS
        ):
            return True
        return False

    if isinstance(response, str):
        lowered = response.strip().lower()
        if not lowered:
            return False
        if strict_tuilan_only:
            if any(marker in lowered for marker in _STRICT_TICKET_MARKERS):
                return True
            return any(ctx in lowered for ctx in _TUILAN_CONTEXT_MARKERS) and any(
                st in lowered for st in _TUILAN_STATE_MARKERS
            )
        return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)

    return False


def _redact_secrets(raw: str) -> str:
    redacted = raw
    for key in ("TICKET", "TOKEN", "TUILAN_COOKIE", "TUILAN_SECRET_KEY"):
        secret = str(getattr(cfg, key, "") or "").strip()
        if secret and len(secret) >= 6 and secret in redacted:
            redacted = redacted.replace(secret, "***")
    return redacted


def extract_error_summary(response: Any) -> str:
    """Build a concise, secret-safe summary (redacts before truncating)."""
    if isinstance(response, dict):
        parts = []
        status = response.get("status_code")
        code = response.get("code")
        if status is not None:
            parts.append(f"http={status}")
        if code is not None:
            parts.append(f"code={code}")
        raw_msg = _text(
            response.get("msg")
            or response.get("message")
            or response.get("text")
            or response.get("error")
        )
        if raw_msg:
            safe_msg = _redact_secrets(raw_msg)[:120]
            parts.append(f"msg={safe_msg}")
        return ", ".join(parts) if parts else "未知鉴权错误"

    raw_text = _text(response)
    if not raw_text:
        return "未知鉴权错误"
    return _redact_secrets(raw_text)[:120]


def _build_alert_message(*, source: str, response: Any, fingerprint: str) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = extract_error_summary(response)
    return (
        "⚠️ 推栏 Token（TICKET）鉴权失败提醒\n"
        f"来源：{source}\n"
        f"错误：{summary}\n"
        f"时间：{now_str}\n"
        f"当前 TICKET 指纹：{fingerprint}\n"
        "请及时更新推栏 Token，可私聊机器人发送：/修改配置 TICKET=<新值>"
    )


def _apply_failure_backoff(
    *,
    fingerprint: str,
    cooldown: float,
    clock: Callable[[], float],
) -> None:
    """Shorten cooldown to 5 minutes when all delivery channels fail."""
    global _last_alert_monotonic
    with _state_lock:
        if _last_alert_fingerprint == fingerprint:
            _last_alert_monotonic = clock() - max(0.0, cooldown - _retry_backoff_seconds)


def _send_email_fallback(message: str) -> bool:
    with _state_lock:
        email_sender = _sync_email_sender
    if email_sender is None:
        return False
    try:
        return bool(email_sender(message, "推栏 Token 鉴权失效提醒"))
    except Exception as exc:
        logger.warning(f"tuilan_auth_alert 邮件降级发送异常: {exc}")
        return False


async def _deliver_alert(
    message: str,
    *,
    fingerprint: str,
    cooldown: float,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    with _state_lock:
        qq_sender = _async_qq_sender

    sent_qq = False
    if qq_sender is not None:
        try:
            sent_qq = bool(await qq_sender(message))
        except Exception as exc:
            logger.warning(f"tuilan_auth_alert QQ 私聊发送异常: {exc}")

    if sent_qq:
        logger.warning(f"tuilan_auth_alert 已通过 QQ 私聊通知管理员（ticket_fp={fingerprint}）")
        return True

    logger.warning(f"tuilan_auth_alert QQ 私聊不可用或失败，尝试降级发送邮件（ticket_fp={fingerprint}）")
    sent_email = await asyncio.to_thread(_send_email_fallback, message)
    if sent_email:
        logger.warning(f"tuilan_auth_alert 已通过邮件降级通知管理员（ticket_fp={fingerprint}）")
        return True

    _apply_failure_backoff(fingerprint=fingerprint, cooldown=cooldown, clock=clock)
    return False


def _track_task(task: asyncio.Task[Any]) -> None:
    _background_tasks.add(task)

    def _on_done(done: asyncio.Task[Any]) -> None:
        _background_tasks.discard(done)
        if not done.cancelled():
            exc = done.exception()
            if exc is not None:
                logger.warning(f"tuilan_auth_alert 后台告警任务异常: {exc!r}")

    task.add_done_callback(_on_done)


def _schedule_on_loop(
    loop: asyncio.AbstractEventLoop,
    coro: Awaitable[Any],
    *,
    cross_thread: bool,
) -> bool:
    if not cross_thread:
        task = loop.create_task(coro)
        _track_task(task)
        return True

    def _spawn() -> None:
        try:
            task = loop.create_task(coro)
            _track_task(task)
        except RuntimeError:
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]

    try:
        loop.call_soon_threadsafe(_spawn)
        return True
    except RuntimeError:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]
        return False


def maybe_notify_tuilan_auth_error(
    *,
    source: str,
    response: Any,
    force: bool = False,
    strict_tuilan_only: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Detect Tuilan auth failure and schedule throttled admin QQ notification (email fallback)."""
    global _last_alert_fingerprint, _last_alert_monotonic

    if not force and not is_tuilan_auth_error(response, strict_tuilan_only=strict_tuilan_only):
        return False

    ticket = str(getattr(cfg, "TICKET", "") or "")
    fingerprint = _ticket_fingerprint(ticket)
    cooldown = float(max(60, int(getattr(cfg, "TUILAN_AUTH_ALERT_COOLDOWN_SECONDS", 3600) or 3600)))
    now = clock()

    with _state_lock:
        if (
            _last_alert_fingerprint == fingerprint
            and _last_alert_monotonic is not None
            and (now - _last_alert_monotonic) < cooldown
        ):
            return False
        _last_alert_fingerprint = fingerprint
        _last_alert_monotonic = now
        target_loop = _main_loop

    message = _build_alert_message(source=source, response=response, fingerprint=fingerprint)

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is not None and running_loop.is_running():
        coro = _deliver_alert(message, fingerprint=fingerprint, cooldown=cooldown, clock=clock)
        if _schedule_on_loop(running_loop, coro, cross_thread=False):
            return True

    if target_loop is not None and target_loop.is_running():
        coro = _deliver_alert(message, fingerprint=fingerprint, cooldown=cooldown, clock=clock)
        if _schedule_on_loop(target_loop, coro, cross_thread=True):
            return True

    # 无可用事件循环（例如独立 CLI/worker 进程）：直接同步降级发送邮件
    sent_email = _send_email_fallback(message)
    if sent_email:
        logger.warning(f"tuilan_auth_alert 无可用事件循环，已通过同步邮件降级通知（source={source}）")
        return True

    _apply_failure_backoff(fingerprint=fingerprint, cooldown=cooldown, clock=clock)
    logger.warning(f"tuilan_auth_alert 无可用事件循环且同步邮件发送失败（source={source}）")
    return False
