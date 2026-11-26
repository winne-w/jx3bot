"""统一运行时配置注册表、读写、解析与脱敏工具。"""

from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Dict, Optional, Tuple, Union


DEFAULT_RUNTIME_CONFIG_FILE = "runtime_config.json"


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    value_type: type
    description: str
    allow_modify: bool = True
    sensitive: bool = False
    min_value: Optional[int] = None
    max_value: Optional[int] = None


_SPEC_LIST: Tuple[ConfigSpec, ...] = (
    ConfigSpec(
        key="TOKEN",
        value_type=str,
        description="JX3API 访问令牌",
        allow_modify=True,
        sensitive=True,
    ),
    ConfigSpec(
        key="TICKET",
        value_type=str,
        description="推栏接口票据",
        allow_modify=True,
        sensitive=True,
    ),
    ConfigSpec(
        key="MONGO_URI",
        value_type=str,
        description="MongoDB 连接字符串（仅只读查看）",
        allow_modify=False,
        sensitive=True,
    ),
    ConfigSpec(
        key="SESSION_data",
        value_type=int,
        description="GET 请求缓存时间（秒）",
        allow_modify=True,
        sensitive=False,
    ),
    ConfigSpec(
        key="calendar_time",
        value_type=int,
        description="每日日常推送小时（0-23）",
        allow_modify=True,
        sensitive=False,
    ),
    ConfigSpec(
        key="STATUS_check_time",
        value_type=int,
        description="开服状态检查间隔（分钟）",
        allow_modify=True,
        sensitive=False,
    ),
    ConfigSpec(
        key="JJC_SYNC_WORKER_COUNT",
        value_type=int,
        description="Bot 内置 JJC 同步 worker 数量（0 表示关闭）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
    ),
    ConfigSpec(
        key="JJC_SYNC_DISPATCHER_ENABLED",
        value_type=int,
        description="是否启用 JJC 同步调度器（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_SYNC_DISPATCHER_IDLE_SLEEP",
        value_type=int,
        description="JJC 同步调度器空闲休眠秒数",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_SYNC_DISPATCHER_BATCH_SIZE",
        value_type=int,
        description="JJC 同步调度器单批任务数",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_SYNC_DISPATCHER_TARGET_PER_WORKER",
        value_type=int,
        description="每个 JJC 同步 worker 目标积压任务数",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_RANKING_KUNGFU_CACHE_ENABLED",
        value_type=int,
        description="是否启用排名心法缓存（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_KUNGFU_REFRESH_ENABLED",
        value_type=int,
        description="是否启用心法后台刷新（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_KUNGFU_REFRESH_SECONDS",
        value_type=int,
        description="心法后台刷新周期（秒）",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_KUNGFU_MAX_STALE_SECONDS",
        value_type=int,
        description="心法缓存最大允许过期时间（秒）",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_KUNGFU_TRACK_SECONDS",
        value_type=int,
        description="心法追踪窗口时长（秒）",
        allow_modify=True,
        sensitive=False,
        min_value=1,
    ),
    ConfigSpec(
        key="JJC_ROLE_IDENTITY_RECOVERY_ENABLED",
        value_type=int,
        description="是否启用角色身份恢复开关（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_RANKING_DISPLAY_QUERY_ENABLED",
        value_type=int,
        description="是否启用排名展示查询开关（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_RANKING_DISPLAY_OVERLAY_ENABLED",
        value_type=int,
        description="是否启用排名展示叠加开关（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED",
        value_type=int,
        description="是否启用本地最新胜场装备开关（0/1）",
        allow_modify=True,
        sensitive=False,
        min_value=0,
        max_value=1,
    ),
    ConfigSpec(
        key="JJC_EQUIPMENT_MONGO_HOST",
        value_type=str,
        description="JJC 装备读取 Mongo 主机覆盖配置",
        allow_modify=True,
        sensitive=False,
    ),
)


RUNTIME_CONFIG_SPECS: Dict[str, ConfigSpec] = {
    spec.key: spec for spec in _SPEC_LIST
}
CONFIG_SPECS: Dict[str, ConfigSpec] = RUNTIME_CONFIG_SPECS


def _build_validator(spec: ConfigSpec) -> Optional[Callable[[Any], bool]]:
    if spec.min_value is None and spec.max_value is None:
        return None

    min_val = spec.min_value
    max_val = spec.max_value

    def _validate(value: Any) -> bool:
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        return True

    return _validate


def to_legacy_schema(
    specs: Optional[Dict[str, ConfigSpec]] = None,
) -> Dict[str, Dict[str, Any]]:
    """将统一 ConfigSpec 映射转换为 config_manager 兼容的 CONFIG_SCHEMA 字典。"""
    source = RUNTIME_CONFIG_SPECS if specs is None else specs
    schema: Dict[str, Dict[str, Any]] = {}
    for key, spec in source.items():
        schema[key] = {
            "type": spec.value_type,
            "sensitive": spec.sensitive,
            "allow_modify": spec.allow_modify,
            "validate": _build_validator(spec),
        }
    return schema


def read_runtime_config(
    path: Union[str, os.PathLike] = DEFAULT_RUNTIME_CONFIG_FILE,
) -> Union[Dict[str, Any], str]:
    """读取运行时 JSON 配置文件；不存在返回空字典，失败返回错误消息字符串。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return f"读取配置文件失败: {exc}"
    if not isinstance(data, dict):
        return "读取配置文件失败: 配置文件顶层必须是 JSON 对象"
    return data


def write_runtime_config(
    path: Union[str, os.PathLike],
    data: Dict[str, Any],
) -> Union[bool, str]:
    """写入运行时 JSON 配置文件；成功返回 True，失败返回错误消息字符串。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        return f"写入配置文件失败: {exc}"


def parse_config_value(
    key: str,
    raw: Any,
    specs: Optional[Dict[str, ConfigSpec]] = None,
) -> Tuple[Any, Optional[str]]:
    """根据配置规范解析并校验输入值，返回 (parsed_value, error_message)。"""
    source = RUNTIME_CONFIG_SPECS if specs is None else specs
    spec = source.get(key)
    if spec is None:
        return None, f"未知配置项: {key}"

    value_type = spec.value_type
    if value_type is int:
        if isinstance(raw, bool):
            return None, "数值类型配置项需要整数"
        try:
            value: Any = int(raw)
        except (TypeError, ValueError):
            return None, "数值类型配置项需要整数"
    elif value_type is str:
        value = str(raw)
    else:
        try:
            value = value_type(raw)
        except (TypeError, ValueError):
            return None, "配置项类型转换失败"

    validator = _build_validator(spec)
    if validator is not None and not validator(value):
        return None, "配置项值不合法"
    return value, None


def mask_sensitive_value(value: Any) -> str:
    """对敏感配置值进行脱敏展示。"""
    if value is None or value == "":
        return "未配置"
    text = str(value)
    if len(text) <= 3:
        return "已配置"
    return f"{text[:3]}***"
