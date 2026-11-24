import copy
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from src.services.jx3.equipment_mobile import build_core_stats, compact_attribute_names, refinement_view
from src.services.jx3.role_queries import build_equipment_spec_or_text


def by_name(stats):
    return {row["name"]:row["value"] for row in stats}


class TestEquipmentMobile(unittest.TestCase):
    def test_healer_pvp_uses_actual_percent_and_twelve_cards(self):
        payload={"kungfuName":"云裳心经","kungfuType":"治疗","equipType":"竞技对抗","equipScore":20032,
                 "panelList":[{"name":"基础治疗量","value":12920},{"name":"面板治疗量","value":14925},
                              {"name":"会心等级","value":2369,"percent":24.9},
                              {"name":"会心效果等级","value":0,"percent":175},
                              {"name":"加速等级","value":1398,"percent":13.77},
                              {"name":"气血","value":59595},{"name":"根骨","value":2825},
                              {"name":"外功防御","value":1234,"percent":7.31},
                              {"name":"内功防御","value":2345,"percent":7.9},
                              {"name":"御劲等级","value":123,"percent":0.8},
                              {"name":"化劲等级","value":678,"percent":51.87}]}
        before=copy.deepcopy(payload)
        stats=build_core_stats(payload)
        self.assertEqual(12,len(stats))
        values=by_name(stats)
        self.assertEqual("24.9%",values["会心"])
        self.assertEqual("175%",values["会效"])
        self.assertEqual("1398",values["加速"])
        self.assertEqual("12920",values["基础治疗"])
        self.assertEqual("14925",values["面板治疗"])
        self.assertEqual("0.8%",values["御劲"])
        self.assertEqual("51.87%",values["化劲"])
        self.assertEqual("20032",values["装分"])
        self.assertEqual(before,payload)

    def test_attack_pve_selects_offensive_values_and_does_not_guess_percent(self):
        payload={"kungfuName":"冰心诀","kungfuType":"DPS","equipType":"秘境挑战",
                 "panelList":[{"name":"基础攻击","value":1000},{"name":"面板攻击","value":1200},
                              {"name":"会心等级","value":2369},{"name":"破防等级","value":912},
                              {"name":"破招","value":343},{"name":"无双等级","value":120,"percent":5.1}]}
        stats=build_core_stats(payload)
        self.assertEqual(12,len(stats))
        values=by_name(stats)
        self.assertEqual("2369",values["会心等级"])
        self.assertEqual("912",values["破防等级"])
        self.assertEqual("343",values["破招"])
        self.assertEqual("5.1%",values["无双"])
        self.assertNotIn("御劲",values)
        self.assertEqual("—",values["气血"])

    def test_unknown_values_are_not_synthesized_as_zero(self):
        stats=build_core_stats({"panelList":[{"name":"会心等级","value":None,"percent":None}]})
        self.assertEqual(12,len(stats))
        self.assertTrue(all(row["value"]=="—" for row in stats))
        stats=build_core_stats({"panelList":[{"name":"会心等级","value":99,"percent":0}]})
        self.assertEqual("0%",by_name(stats)["会心"])

    def test_compact_affixes_keep_names_and_remove_weapon_damage_noise(self):
        rows=[{"name":"会心等级","value":2369},{"name":"会心效果等级","value":175},
              {"name":"武器伤害（最小）","value":12345},{"name":"武器伤害（最大）","value":23456},
              {"name":"会心等级","value":1},{"name":"根骨","value":9999}]
        self.assertEqual(["根骨","会心","会效"],compact_attribute_names(rows))

    def test_real_weapon_names_are_limited_and_primary_attribute_is_first(self):
        rows=[{"name":name,"value":999} for name in
              ("体质","基础攻击","会心等级","内功治疗量","元气","根骨","无双等级","加速等级","破防等级","武器伤害最大")]
        self.assertEqual(["元气","根骨","会心","治疗","无双"],compact_attribute_names(rows))

    def test_internal_ascii_stat_codes_are_omitted_without_guessing_labels(self):
        rows=[{"name":"LIFE_ADDITIONAL","value":800},{"name":"atMagicAttackPowerBase","value":500},
              {"name":"_EXTRA_STAT_1","value":10},{"name":"会心等级","value":100},
              {"name":"根骨","value":50},{"name":"PVE增伤","value":1}]
        before=copy.deepcopy(rows)
        self.assertEqual(["根骨","会心","PVE增伤"],compact_attribute_names(rows))
        self.assertEqual(before,rows)

    def test_known_damage_roles_ignore_incidental_healing_values(self):
        panel=[{"name":"基础攻击","value":2000},{"name":"面板攻击","value":2400},
               {"name":"基础治疗量","value":1},{"name":"面板治疗量","value":2}]
        for extra in ({"kungfuType":"DPS"},{"kungfuName":"冰心诀"},
                      {"kungfuName":"未识别心法","kungfuType":"未知"}):
            with self.subTest(extra=extra):
                values=by_name(build_core_stats({**extra,"panelList":panel}))
                self.assertIn("基础攻击",values)
                self.assertNotIn("基础治疗",values)
        values=by_name(build_core_stats({"kungfuName":"云裳心经","kungfuType":"DPS","panelList":panel}))
        self.assertIn("基础治疗",values)
        values=by_name(build_core_stats({"kungfuName":"未识别心法","panelList":
                    [{"name":"基础攻击","value":10},{"name":"基础治疗量","value":2000}]}))
        self.assertIn("基础治疗",values)

    def test_refinement_never_invents_filled_stars(self):
        self.assertEqual("★★★★☆☆",refinement_view(4,6)["stars"])
        for strength,maximum in ((None,None),(6,None),(9,9),(7,6),(True,6)):
            with self.subTest(strength=strength,maximum=maximum):
                result=refinement_view(strength,maximum)
                self.assertEqual("",result["stars"])
                self.assertTrue(result["text"])

    def test_mobile_template_keeps_all_equipment_and_original_panel(self):
        payload={"kungfuName":"冰心诀","equipType":"秘境挑战","seasonName":"苍生铸世","cacheTime":1795438546,
                 "panelList":[{"name":"基础攻击","value":1159,"percent":0},{"name":"气血","value":59595}],
                 "equipList":[{"itemName":"测试武器"+str(i),"itemAttrib":[{"name":"会心等级","value":999999}],
                               "strengthLevel":4,"maxStrengthLevel":6,"itemSource":"测试来源"} for i in range(13)]}
        spec,error=build_equipment_spec_or_text(data={"data":payload},server="测试服",role_name="测试角色",random_text="")
        self.assertIsNone(error)
        self.assertEqual(760,spec.width)
        self.assertEqual(13,len(spec.context["equipment"]))
        self.assertEqual(2,len(spec.context["panel"]))
        self.assertEqual(0,spec.context["panel"][0]["percent"])
        self.assertEqual(12,len(spec.context["core_stats"]))
        env=Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1]/"templates")))
        html=env.get_template(spec.template_name).render(**spec.context)
        self.assertIn("测试武器12",html)
        self.assertNotIn("999999",html)
        self.assertIn("★★★★☆☆",html)
        self.assertIn("苍生铸世",html)
        self.assertIn("秘境挑战",html)
        self.assertIn("repeat(4",html)
        self.assertIn("font-size: 32px",html)
        self.assertIn("font-size: 34px",html)


if __name__=="__main__": unittest.main()
