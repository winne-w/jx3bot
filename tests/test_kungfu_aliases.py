import importlib
import unicodedata
import unittest

from src.services.jx3.jjc_kungfu_meta import get_jjc_kungfu_catalog


def normalized(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


class TestKungfuAliasTable(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("src.services.jx3.kungfu_aliases")

    def test_mapping_covers_current_catalog_plus_explicitly_supported_xisui(self):
        names = {item["name"] for item in get_jjc_kungfu_catalog()}
        self.assertEqual(32, len(names))
        self.assertEqual(names | {"洗髓经"}, set(self.module.KUNGFU_ALIASES))
        for name, aliases in self.module.KUNGFU_ALIASES.items():
            with self.subTest(name=name):
                self.assertIsInstance(aliases, tuple)
                self.assertTrue(aliases)
                self.assertTrue(all(isinstance(value, str) and value.strip() for value in aliases))

    def test_each_configured_alias_has_one_owner_and_resolves_to_that_owner(self):
        owners = {}
        for name, aliases in self.module.KUNGFU_ALIASES.items():
            for alias in aliases:
                with self.subTest(name=name, alias=alias):
                    key = normalized(alias)
                    self.assertTrue(key)
                    if key in owners:
                        self.assertEqual(owners[key], name, "normalized alias belongs to multiple kungfus")
                    owners[key] = name
                    self.assertEqual(name, self.module.resolve_kungfu_alias(alias))
                    self.assertEqual(name, self.module.resolve_kungfu_alias("  " + alias.upper() + "  "))

    def test_all_canonical_names_remain_accepted(self):
        for row in get_jjc_kungfu_catalog():
            with self.subTest(name=row["name"]):
                self.assertEqual(row["name"], self.module.resolve_kungfu_alias(row["name"]))
                self.assertEqual(row["name"], self.module.resolve_kungfu_alias(" " + row["name"] + " "))

    def test_xiu_aliases_distinguish_damage_and_healing_specializations(self):
        for value in ("冰心", "bx", "BX", "ｂｘ", "ＢＸ", "  Bx  "):
            with self.subTest(value=value):
                self.assertEqual("冰心诀", self.module.resolve_kungfu_alias(value))
        for value in ("奶秀", "秀奶", "nx", "NX", "ｎｘ"):
            with self.subTest(value=value):
                self.assertEqual("云裳心经", self.module.resolve_kungfu_alias(value))

    def test_xz_and_xc_are_distinct_unique_shortcuts(self):
        self.assertEqual("相知", self.module.resolve_kungfu_alias("xz"))
        self.assertEqual("笑尘诀", self.module.resolve_kungfu_alias("xc"))

    def test_full_initials_distinguish_kungfus_with_ambiguous_short_initials(self):
        for alias, expected in (("txjy", "太虚剑意"), ("txj", "太玄经"), ("ylj", "隐龙诀"), ("yly", "幽罗引")):
            with self.subTest(alias=alias):
                self.assertEqual(expected, self.module.resolve_kungfu_alias(alias))

    def test_xisui_full_name_and_tank_aliases_are_supported_without_changing_jjc_catalog(self):
        self.assertNotIn("洗髓经", {row["name"] for row in get_jjc_kungfu_catalog()})
        parser = importlib.import_module("src.services.jx3.equipment_query")
        for value in ("洗髓经", "洗髓", "少林T", "少林t", "和尚t", "XS"):
            with self.subTest(value=value):
                self.assertEqual("洗髓经", self.module.resolve_kungfu_alias(value))
                command = parser.parse_equipment_command("桃桃白糖 " + value, server_names=("唯我独尊",))
                self.assertEqual("洗髓经", command.kungfu)
                self.assertEqual("桃桃白糖", command.name)

    def test_ambiguous_shortcuts_are_explicit_errors_with_both_choices(self):
        for value, choices in (("cy", ("紫霞功", "太虚剑意", "分山劲", "铁骨衣")), ("tl", ("铁牢律", "天罗诡道")),
                               ("tx", ("太虚剑意", "太玄经")), ("yl", ("隐龙诀", "幽罗引")),
                               (" CY ", ("紫霞功", "太虚剑意", "分山劲", "铁骨衣")), ("ｔｌ", ("铁牢律", "天罗诡道"))):
            with self.subTest(value=value):
                with self.assertRaises(self.module.KungfuAliasError) as caught:
                    self.module.resolve_kungfu_alias(value)
                for choice in choices:
                    self.assertIn(choice, str(caught.exception))

    def test_multiple_specialization_school_names_require_disambiguation(self):
        for school in ("七秀", "万花", "纯阳", "天策", "少林", "五毒", "唐门", "明教", "苍云", "长歌", "药宗", "藏剑"):
            with self.subTest(school=school):
                with self.assertRaises(self.module.KungfuAliasError) as caught:
                    self.module.resolve_kungfu_alias(school)
                self.assertTrue(str(caught.exception))

    def test_unknown_empty_and_non_string_values_return_none(self):
        for value in ("", "  ", "不存在心法", None, 123, True, [], {}):
            with self.subTest(value=value):
                self.assertIsNone(self.module.resolve_kungfu_alias(value))

    def test_aliases_match_whole_tokens_without_prefix_or_substring_guessing(self):
        for value in ("bxx", "xbx", "冰心PVP", "冰心诀abc", "我想玩奶秀", "奶秀配装", "bx pvp"):
            with self.subTest(value=value):
                self.assertIsNone(self.module.resolve_kungfu_alias(value))

    def test_ambiguous_shortcuts_are_not_stored_as_unambiguous_aliases(self):
        entries = {normalized(alias) for aliases in self.module.KUNGFU_ALIASES.values() for alias in aliases}
        self.assertNotIn("cy", entries)
        self.assertNotIn("tl", entries)
        self.assertNotIn("tx", entries)
        self.assertNotIn("yl", entries)


class TestEquipmentKungfuAliasParsing(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("src.services.jx3.equipment_query")

    def parse(self, raw):
        return self.module.parse_equipment_command(raw, server_names=("唯我独尊", "长安城"))

    def test_bare_aliases_are_canonicalized_with_optional_type(self):
        for alias, expected in (("冰心", "冰心诀"), ("bx", "冰心诀"), ("BX", "冰心诀"), ("ｂｘ", "冰心诀"),
                                ("奶秀", "云裳心经"), ("秀奶", "云裳心经"), ("nx", "云裳心经"), ("xz", "相知"), ("xc", "笑尘诀")):
            for suffix in (alias, alias + " PVP", "PVP " + alias):
                with self.subTest(alias=alias, suffix=suffix):
                    command = self.parse("桃桃白糖 " + suffix)
                    self.assertEqual("桃桃白糖", command.name)
                    self.assertIsNone(command.server)
                    self.assertEqual(expected, command.kungfu)
                    self.assertEqual("竞技对抗" if "PVP" in suffix else None, command.equip_type)

    def test_explicit_aliases_resolve_to_canonical_names(self):
        for raw, expected in (("桃桃白糖 心法=bx 类型=PVP", "冰心诀"),
                              ("桃桃白糖 kungfu=ＢＸ type=pve", "冰心诀"),
                              ("唯我独尊 桃桃白糖 心法=奶秀", "云裳心经")):
            with self.subTest(raw=raw):
                command = self.parse(raw)
                self.assertEqual("桃桃白糖", command.name)
                self.assertEqual(expected, command.kungfu)

    def test_single_token_alias_or_school_name_stays_a_character_identity(self):
        for name in ("bx", "ｂｘ", "nx", "冰心", "奶秀", "xz", "tl", "七秀"):
            with self.subTest(name=name):
                command = self.parse(name)
                self.assertEqual(name, command.name)
                self.assertIsNone(command.kungfu)
                self.assertEqual((name, None, None), command.identity_groups())

    def test_known_server_character_named_like_an_alias_is_preserved(self):
        for name in ("bx", "ｂｘ", "奶秀", "xz", "tl", "七秀"):
            with self.subTest(name=name):
                command = self.parse("唯我独尊 " + name)
                self.assertEqual(("唯我独尊", name, None), (command.server, command.name, command.kungfu))
                command = self.parse("唯我独尊 " + name + " PVP")
                self.assertEqual(("唯我独尊", name, None, "竞技对抗"),
                                 (command.server, command.name, command.kungfu, command.equip_type))

    def test_canonical_and_alias_synonyms_are_still_duplicate_filters(self):
        for raw in ("桃桃白糖 bx 冰心诀", "桃桃白糖 冰心 bx", "桃桃白糖 BX 心法=冰心诀",
                    "桃桃白糖 奶秀 nx", "桃桃白糖 kungfu=nx 心法=云裳心经"):
            with self.subTest(raw=raw):
                with self.assertRaises(self.module.EquipmentQueryError) as caught:
                    self.parse(raw)
                self.assertIn("重复", str(caught.exception))

    def test_ambiguous_bare_and_explicit_filters_produce_user_facing_choice_errors(self):
        for value, choices in (("cy", ("紫霞功", "太虚剑意", "分山劲", "铁骨衣")), ("tl", ("铁牢律", "天罗诡道")),
                               ("tx", ("太虚剑意", "太玄经")), ("yl", ("隐龙诀", "幽罗引"))):
            for raw in ("桃桃白糖 " + value, "桃桃白糖 心法=" + value, "唯我独尊 桃桃白糖 " + value + " PVP"):
                with self.subTest(raw=raw):
                    with self.assertRaises(self.module.EquipmentQueryError) as caught:
                        self.parse(raw)
                    for choice in choices:
                        self.assertIn(choice, str(caught.exception))

    def test_unknown_explicit_kungfu_is_rejected_without_becoming_character_text(self):
        for raw in ("桃桃白糖 心法=不存在", "桃桃白糖 kungfu=bxx", "桃桃白糖 心法=冰心PVP"):
            with self.subTest(raw=raw):
                with self.assertRaises(self.module.EquipmentQueryError):
                    self.parse(raw)

    def test_full_canonical_names_keep_existing_equipment_parse_behavior(self):
        for row in get_jjc_kungfu_catalog():
            with self.subTest(kungfu=row["name"]):
                command = self.parse("桃桃白糖 " + row["name"] + " PVP")
                self.assertEqual(row["name"], command.kungfu)
                self.assertEqual("竞技对抗", command.equip_type)
                self.assertEqual("桃桃白糖", command.name)


if __name__ == "__main__":
    unittest.main()
