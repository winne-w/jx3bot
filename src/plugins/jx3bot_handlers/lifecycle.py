from __future__ import annotations

from datetime import datetime
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot


def register(driver: Any, bot_status: dict[str, Any]) -> None:
    def save_status() -> None:
        try:
            with open(bot_status["status_file"], "w", encoding="utf-8") as file_handle:
                for key, value in bot_status.items():
                    if key != "status_file":
                        file_handle.write(f"{key}={value}\n")
        except Exception as exc:
            logger.warning(f"保存状态失败: {exc}")

    def load_status() -> None:
        try:
            with open(bot_status["status_file"], "r", encoding="utf-8") as file_handle:
                for line in file_handle:
                    line = line.strip()
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key in bot_status:
                        bot_status[key] = float(value)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning(f"加载状态失败: {exc}")

    @driver.on_startup
    async def startup_handler() -> None:
        load_status()
        bot_status["startup_time"] = datetime.now().timestamp()
        save_status()
        logger.info(
            f"机器人启动于 {datetime.fromtimestamp(bot_status['startup_time']).strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @driver.on_bot_connect
    async def connect_handler(bot: Bot) -> None:
        bot_status["last_connect_time"] = datetime.now().timestamp()
        bot_status["connection_count"] += 1
        save_status()
        logger.info(f"机器人已连接，这是第 {int(bot_status['connection_count'])} 次连接")

    @driver.on_bot_disconnect
    async def disconnect_handler(bot: Bot) -> None:
        now = datetime.now().timestamp()
        bot_status["last_offline_time"] = now
        if bot_status["last_connect_time"] > 0:
            bot_status["offline_duration"] = now - bot_status["last_connect_time"]
        save_status()
        logger.info(f"机器人已断开连接于 {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')}")

