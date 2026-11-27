"""Unified canonical kungfu catalog (pure domain rules, stdlib only)."""
from dataclasses import dataclass
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_CATEGORIES = frozenset({"dps", "healer", "tank"})


@dataclass(frozen=True)
class KungfuSpec:
    id: int
    pinyin: str
    name: str
    category: str
    school: str
    aliases: Tuple[str, ...]
    display_order: int
    in_jjc_catalog: bool = True


KUNGFU_CATALOG: Tuple[KungfuSpec, ...] = (
    KungfuSpec(
        id=10003,
        pinyin="yijin",
        name="易筋经",
        category="dps",
        school="少林",
        aliases=("易筋", "yj", "yjj", "输出少林", "少林dps"),
        display_order=1,
    ),
    KungfuSpec(
        id=10014,
        pinyin="zixia",
        name="紫霞功",
        category="dps",
        school="纯阳",
        aliases=("紫霞", "气纯", "zx", "zxg", "qc"),
        display_order=2,
    ),
    KungfuSpec(
        id=10015,
        pinyin="taixu",
        name="太虚剑意",
        category="dps",
        school="纯阳",
        aliases=("太虚", "剑纯", "txjy", "jc"),
        display_order=3,
    ),
    KungfuSpec(
        id=10021,
        pinyin="huajian",
        name="花间游",
        category="dps",
        school="万花",
        aliases=("花间", "hj", "hjy"),
        display_order=4,
    ),
    KungfuSpec(
        id=10028,
        pinyin="lijing",
        name="离经易道",
        category="healer",
        school="万花",
        aliases=("离经", "奶花", "花奶", "lj", "ljyd", "nh", "hn"),
        display_order=5,
    ),
    KungfuSpec(
        id=10026,
        pinyin="aoxue",
        name="傲血战意",
        category="dps",
        school="天策",
        aliases=("傲血", "ax", "axzy", "输出天策", "天策dps"),
        display_order=6,
    ),
    KungfuSpec(
        id=10062,
        pinyin="tielao",
        name="铁牢律",
        category="tank",
        school="天策",
        aliases=("铁牢", "tll", "策t", "天策t", "ct", "tct"),
        display_order=7,
    ),
    KungfuSpec(
        id=10081,
        pinyin="bingxin",
        name="冰心诀",
        category="dps",
        school="七秀",
        aliases=("冰心", "冰秀", "bx", "bxj"),
        display_order=8,
    ),
    KungfuSpec(
        id=10080,
        pinyin="yunshang",
        name="云裳心经",
        category="healer",
        school="七秀",
        aliases=("云裳", "奶秀", "秀奶", "ys", "ysxj", "nx", "xn"),
        display_order=9,
    ),
    KungfuSpec(
        id=10175,
        pinyin="dujing",
        name="毒经",
        category="dps",
        school="五毒",
        aliases=("dj", "输出五毒", "五毒dps"),
        display_order=10,
    ),
    KungfuSpec(
        id=10176,
        pinyin="butian",
        name="补天诀",
        category="healer",
        school="五毒",
        aliases=("补天", "奶毒", "毒奶", "bt", "btj", "nd", "dn"),
        display_order=11,
    ),
    KungfuSpec(
        id=10145,
        pinyin="cangjian",
        name="山居剑意",
        category="dps",
        school="藏剑",
        aliases=("山居", "sj", "sjjy"),
        display_order=12,
    ),
    KungfuSpec(
        id=10144,
        pinyin="wenshui",
        name="问水诀",
        category="dps",
        school="藏剑",
        aliases=("问水", "ws", "wsj"),
        display_order=13,
    ),
    KungfuSpec(
        id=10225,
        pinyin="tianluo",
        name="天罗诡道",
        category="dps",
        school="唐门",
        aliases=("天罗", "田螺", "tlgd"),
        display_order=14,
    ),
    KungfuSpec(
        id=10224,
        pinyin="jingyu",
        name="惊羽诀",
        category="dps",
        school="唐门",
        aliases=("惊羽", "鲸鱼", "jy", "jyj"),
        display_order=15,
    ),
    KungfuSpec(
        id=10390,
        pinyin="fenshan",
        name="分山劲",
        category="dps",
        school="苍云",
        aliases=("分山", "fs", "fsj", "输出苍云", "苍云dps"),
        display_order=16,
    ),
    KungfuSpec(
        id=10389,
        pinyin="tiegu",
        name="铁骨衣",
        category="tank",
        school="苍云",
        aliases=("铁骨", "tg", "tgy", "苍云t", "盾t", "cyt"),
        display_order=17,
    ),
    KungfuSpec(
        id=10268,
        pinyin="xiaochen",
        name="笑尘诀",
        category="dps",
        school="丐帮",
        aliases=("笑尘", "丐帮", "xc", "xcj", "gb"),
        display_order=18,
    ),
    KungfuSpec(
        id=10242,
        pinyin="fenying",
        name="焚影圣诀",
        category="dps",
        school="明教",
        aliases=("焚影", "fy", "fysj", "输出明教", "明教dps"),
        display_order=19,
    ),
    KungfuSpec(
        id=10243,
        pinyin="mingzun",
        name="明尊琉璃体",
        category="tank",
        school="明教",
        aliases=("明尊", "mz", "mzllt", "明教t", "喵t", "mjt"),
        display_order=20,
    ),
    KungfuSpec(
        id=10447,
        pinyin="mowen",
        name="莫问",
        category="dps",
        school="长歌",
        aliases=("mw", "输出长歌", "长歌dps"),
        display_order=21,
    ),
    KungfuSpec(
        id=10448,
        pinyin="xiangzhi",
        name="相知",
        category="healer",
        school="长歌",
        aliases=("奶歌", "歌奶", "xz", "ng", "gn"),
        display_order=22,
    ),
    KungfuSpec(
        id=10464,
        pinyin="beiao",
        name="北傲诀",
        category="dps",
        school="霸刀",
        aliases=("北傲", "霸刀", "霸刀山庄", "ba", "baj", "bd"),
        display_order=23,
    ),
    KungfuSpec(
        id=10533,
        pinyin="linghai",
        name="凌海诀",
        category="dps",
        school="蓬莱",
        aliases=("凌海", "蓬莱", "lh", "lhj", "pl"),
        display_order=24,
    ),
    KungfuSpec(
        id=10585,
        pinyin="yinlong",
        name="隐龙诀",
        category="dps",
        school="凌雪阁",
        aliases=("隐龙", "凌雪", "凌雪阁", "ylj", "lx", "lxg"),
        display_order=25,
    ),
    KungfuSpec(
        id=10627,
        pinyin="wufang",
        name="无方",
        category="dps",
        school="药宗",
        aliases=("wf", "输出药宗", "药宗dps"),
        display_order=26,
    ),
    KungfuSpec(
        id=10626,
        pinyin="lingsu",
        name="灵素",
        category="healer",
        school="药宗",
        aliases=("奶药", "药奶", "ls", "ny", "yn"),
        display_order=27,
    ),
    KungfuSpec(
        id=10698,
        pinyin="gufeng",
        name="孤锋诀",
        category="dps",
        school="刀宗",
        aliases=("孤锋", "刀宗", "gf", "gfj", "dz"),
        display_order=28,
    ),
    KungfuSpec(
        id=10756,
        pinyin="shanhai",
        name="山海心诀",
        category="dps",
        school="万灵山庄",
        aliases=("山海", "万灵", "万灵山庄", "sh", "shxj", "wl", "wlsz"),
        display_order=29,
    ),
    KungfuSpec(
        id=10786,
        pinyin="zhoutian",
        name="周天功",
        category="dps",
        school="段氏",
        aliases=("周天", "段氏", "zt", "ztg", "ds"),
        display_order=30,
    ),
    KungfuSpec(
        id=10615,
        pinyin="taixuan",
        name="太玄经",
        category="dps",
        school="衍天宗",
        aliases=("太玄", "衍天", "衍天宗", "txj", "yt", "ytz"),
        display_order=31,
    ),
    KungfuSpec(
        id=10821,
        pinyin="youluo",
        name="幽罗引",
        category="dps",
        school="无相楼",
        aliases=("幽罗", "无相", "无相楼", "yly", "wx", "wxl"),
        display_order=32,
    ),
    KungfuSpec(
        id=10002,
        pinyin="xisui",
        name="洗髓经",
        category="tank",
        school="少林",
        aliases=("洗髓", "xs", "xsj", "少林t", "和尚t", "slt", "hst"),
        display_order=33,
        in_jjc_catalog=False,
    ),
)

AMBIGUOUS_KUNGFU_ALIASES: Dict[str, Tuple[str, ...]] = {
    "七秀": ("冰心诀", "云裳心经"),
    "万花": ("花间游", "离经易道"),
    "纯阳": ("紫霞功", "太虚剑意"),
    "天策": ("傲血战意", "铁牢律"),
    "少林": ("易筋经", "洗髓经"),
    "五毒": ("毒经", "补天诀"),
    "唐门": ("天罗诡道", "惊羽诀"),
    "明教": ("焚影圣诀", "明尊琉璃体"),
    "苍云": ("分山劲", "铁骨衣"),
    "长歌": ("莫问", "相知"),
    "药宗": ("无方", "灵素"),
    "藏剑": ("山居剑意", "问水诀"),
    "tl": ("铁牢律", "天罗诡道"),
    "tx": ("太虚剑意", "太玄经"),
    "yl": ("隐龙诀", "幽罗引"),
    "cy": ("紫霞功", "太虚剑意", "分山劲", "铁骨衣"),
}

for _school, _shortcuts in {
    "七秀": ("qx", "xx", "7x"),
    "万花": ("wh", "hh"),
    "纯阳": (),
    "天策": ("tc", "天策府"),
    "少林": ("sl", "hs", "和尚"),
    "五毒": ("wd", "5d"),
    "唐门": ("tm",),
    "明教": ("mj",),
    "苍云": (),
    "长歌": ("cg", "长歌门"),
    "药宗": ("yz", "btyz", "北天药宗"),
    "藏剑": ("cj", "藏剑山庄"),
}.items():
    for _shortcut in _shortcuts:
        AMBIGUOUS_KUNGFU_ALIASES[_shortcut] = AMBIGUOUS_KUNGFU_ALIASES[_school]


class KungfuAliasError(ValueError):
    """A maintained spelling maps to more than one canonical kungfu."""


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _build_indexes() -> Tuple[
    Dict[str, KungfuSpec],
    Dict[int, KungfuSpec],
    Dict[str, KungfuSpec],
    Dict[str, Tuple[str, ...]],
    Dict[str, str],
    Dict[str, Tuple[str, ...]],
]:
    by_name: Dict[str, KungfuSpec] = {}
    by_id: Dict[int, KungfuSpec] = {}
    by_pinyin: Dict[str, KungfuSpec] = {}
    aliases_by_name: Dict[str, Tuple[str, ...]] = {}
    seen_orders = set()

    for spec in KUNGFU_CATALOG:
        if not isinstance(spec.id, int) or isinstance(spec.id, bool) or spec.id <= 0:
            raise ValueError("Invalid kungfu id: {!r}".format(spec.id))
        if spec.id in by_id:
            raise ValueError("Duplicate kungfu id: {}".format(spec.id))
        if not spec.pinyin or spec.pinyin in by_pinyin:
            raise ValueError("Invalid or duplicate kungfu pinyin: {!r}".format(spec.pinyin))
        if not spec.name or spec.name in by_name:
            raise ValueError("Invalid or duplicate kungfu name: {!r}".format(spec.name))
        if spec.category not in ALLOWED_CATEGORIES:
            raise ValueError("Invalid kungfu category for {}: {!r}".format(spec.name, spec.category))
        if spec.display_order in seen_orders:
            raise ValueError("Duplicate kungfu display_order: {}".format(spec.display_order))
        seen_orders.add(spec.display_order)
        by_id[spec.id] = spec
        by_pinyin[spec.pinyin] = spec
        by_name[spec.name] = spec
        aliases_by_name[spec.name] = spec.aliases

    alias_index: Dict[str, str] = {}
    for name, aliases in aliases_by_name.items():
        for alias in (name, *aliases):
            key = _normalize(alias)
            if not key or (key in alias_index and alias_index[key] != name):
                raise ValueError("Conflicting kungfu alias: " + alias)
            alias_index[key] = name

    ambiguous_index: Dict[str, Tuple[str, ...]] = {}
    for alias, choices in AMBIGUOUS_KUNGFU_ALIASES.items():
        key = _normalize(alias)
        if not key or key in alias_index or len(set(choices)) < 2 or any(name not in by_name for name in choices):
            raise ValueError("Invalid ambiguous kungfu alias: " + alias)
        if key in ambiguous_index and ambiguous_index[key] != choices:
            raise ValueError("Conflicting ambiguous kungfu alias: " + alias)
        ambiguous_index[key] = choices

    return by_name, by_id, by_pinyin, aliases_by_name, alias_index, ambiguous_index


(
    KUNGFU_BY_NAME,
    KUNGFU_BY_ID,
    KUNGFU_BY_PINYIN,
    KUNGFU_ALIASES,
    _ALIAS_INDEX,
    _AMBIGUOUS_INDEX,
) = _build_indexes()


def resolve_kungfu_alias(value: Any) -> Optional[str]:
    """Resolve a whole spelling; unknown/non-text returns None, ambiguity raises."""
    if not isinstance(value, str):
        return None
    key = _normalize(value)
    if key in _AMBIGUOUS_INDEX:
        raise KungfuAliasError(
            "心法别名“{}”不唯一，请使用完整心法名：{}".format(
                value.strip(), "、".join(_AMBIGUOUS_INDEX[key])
            )
        )
    return _ALIAS_INDEX.get(key)


def build_kungfu_meta() -> Dict[str, Dict[str, str]]:
    """Build {pinyin: {'name': name, 'category': category}} for all 33 kungfus."""
    return {
        spec.pinyin: {"name": spec.name, "category": spec.category}
        for spec in KUNGFU_CATALOG
    }


def get_jjc_catalog_specs() -> Tuple[KungfuSpec, ...]:
    """Return the 32 JJC matchup catalog specs ordered by display_order."""
    return tuple(
        sorted(
            (spec for spec in KUNGFU_CATALOG if spec.in_jjc_catalog),
            key=lambda spec: spec.display_order,
        )
    )


def healer_names() -> List[str]:
    return [spec.name for spec in KUNGFU_CATALOG if spec.category == "healer"]


def dps_names() -> List[str]:
    return [spec.name for spec in KUNGFU_CATALOG if spec.category == "dps"]


def tank_names() -> List[str]:
    return [spec.name for spec in KUNGFU_CATALOG if spec.category == "tank"]


def category_for_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    spec = KUNGFU_BY_NAME.get(name.strip())
    return spec.category if spec is not None else None


def name_by_id(kungfu_id: Any) -> Optional[str]:
    if isinstance(kungfu_id, bool):
        return None
    if isinstance(kungfu_id, int):
        spec = KUNGFU_BY_ID.get(kungfu_id)
        return spec.name if spec is not None else None
    if isinstance(kungfu_id, str):
        raw = kungfu_id.strip()
        if raw.isascii() and raw.isdigit():
            spec = KUNGFU_BY_ID.get(int(raw))
            return spec.name if spec is not None else None
    return None
