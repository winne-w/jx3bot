"""Maintained kungfu aliases; research and conventions: docs/references/kungfu-aliases.md.

Static project data, never fetched at runtime. Add ambiguous spellings only to
AMBIGUOUS_KUNGFU_ALIASES; never silently overwrite an existing alias owner.
"""
import unicodedata
from typing import Dict, Optional, Tuple

KUNGFU_ALIASES: Dict[str, Tuple[str, ...]] = {
    "易筋经": ("易筋", "yj", "yjj", "输出少林", "少林dps"),
    "洗髓经": ("洗髓", "xs", "xsj", "少林t", "和尚t", "slt", "hst"),
    "紫霞功": ("紫霞", "气纯", "zx", "zxg", "qc"),
    "太虚剑意": ("太虚", "剑纯", "txjy", "jc"),
    "花间游": ("花间", "hj", "hjy"),
    "离经易道": ("离经", "奶花", "花奶", "lj", "ljyd", "nh", "hn"),
    "傲血战意": ("傲血", "ax", "axzy", "输出天策", "天策dps"),
    "铁牢律": ("铁牢", "tll", "策t", "天策t", "ct", "tct"),
    "冰心诀": ("冰心", "冰秀", "bx", "bxj"),
    "云裳心经": ("云裳", "奶秀", "秀奶", "ys", "ysxj", "nx", "xn"),
    "毒经": ("dj", "输出五毒", "五毒dps"),
    "补天诀": ("补天", "奶毒", "毒奶", "bt", "btj", "nd", "dn"),
    "山居剑意": ("山居", "sj", "sjjy"),
    "问水诀": ("问水", "ws", "wsj"),
    "天罗诡道": ("天罗", "田螺", "tlgd"),
    "惊羽诀": ("惊羽", "鲸鱼", "jy", "jyj"),
    "分山劲": ("分山", "fs", "fsj", "输出苍云", "苍云dps"),
    "铁骨衣": ("铁骨", "tg", "tgy", "苍云t", "盾t", "cyt"),
    "笑尘诀": ("笑尘", "丐帮", "xc", "xcj", "gb"),
    "焚影圣诀": ("焚影", "fy", "fysj", "输出明教", "明教dps"),
    "明尊琉璃体": ("明尊", "mz", "mzllt", "明教t", "喵t", "mjt"),
    "莫问": ("mw", "输出长歌", "长歌dps"),
    "相知": ("奶歌", "歌奶", "xz", "ng", "gn"),
    "北傲诀": ("北傲", "霸刀", "霸刀山庄", "ba", "baj", "bd"),
    "凌海诀": ("凌海", "蓬莱", "lh", "lhj", "pl"),
    "隐龙诀": ("隐龙", "凌雪", "凌雪阁", "ylj", "lx", "lxg"),
    "无方": ("wf", "输出药宗", "药宗dps"),
    "灵素": ("奶药", "药奶", "ls", "ny", "yn"),
    "孤锋诀": ("孤锋", "刀宗", "gf", "gfj", "dz"),
    "山海心诀": ("山海", "万灵", "万灵山庄", "sh", "shxj", "wl", "wlsz"),
    "周天功": ("周天", "段氏", "zt", "ztg", "ds"),
    "太玄经": ("太玄", "衍天", "衍天宗", "txj", "yt", "ytz"),
    "幽罗引": ("幽罗", "无相", "无相楼", "yly", "wx", "wxl"),
}

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
# School abbreviations also require the same explicit choice.
for _school, _shortcuts in {
    "七秀": ("qx", "xx", "7x"), "万花": ("wh", "hh"), "纯阳": (),
    "天策": ("tc", "天策府"), "少林": ("sl", "hs", "和尚"), "五毒": ("wd", "5d"),
    "唐门": ("tm",), "明教": ("mj",), "苍云": (), "长歌": ("cg", "长歌门"),
    "药宗": ("yz", "btyz", "北天药宗"), "藏剑": ("cj", "藏剑山庄"),
}.items():
    for _shortcut in _shortcuts:
        AMBIGUOUS_KUNGFU_ALIASES[_shortcut] = AMBIGUOUS_KUNGFU_ALIASES[_school]


class KungfuAliasError(ValueError):
    """A maintained spelling maps to more than one canonical kungfu."""


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _build_index():
    index = {}
    for name, aliases in KUNGFU_ALIASES.items():
        for alias in (name, *aliases):
            key = _normalize(alias)
            if not key or (key in index and index[key] != name):
                raise ValueError("Conflicting kungfu alias: " + alias)
            index[key] = name
    ambiguous = {}
    for alias, choices in AMBIGUOUS_KUNGFU_ALIASES.items():
        key = _normalize(alias)
        if not key or key in index or len(set(choices)) < 2 or any(name not in KUNGFU_ALIASES for name in choices):
            raise ValueError("Invalid ambiguous kungfu alias: " + alias)
        if key in ambiguous and ambiguous[key] != choices:
            raise ValueError("Conflicting ambiguous kungfu alias: " + alias)
        ambiguous[key] = choices
    return index, ambiguous


_ALIAS_INDEX, _AMBIGUOUS_INDEX = _build_index()


def resolve_kungfu_alias(value: str) -> Optional[str]:
    """Resolve a whole spelling; unknown/non-text returns None, ambiguity raises."""
    if not isinstance(value, str):
        return None
    key = _normalize(value)
    if key in _AMBIGUOUS_INDEX:
        raise KungfuAliasError("心法别名“{}”不唯一，请使用完整心法名：{}".format(value.strip(), "、".join(_AMBIGUOUS_INDEX[key])))
    return _ALIAS_INDEX.get(key)
