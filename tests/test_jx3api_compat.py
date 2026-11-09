import unittest

from src.infra.jx3api_compat import normalize_jx3api_response


class TestJx3apiCompat(unittest.TestCase):
    def test_normalizes_firework_fields_for_existing_template(self) -> None:
        response = {
            "code": 200,
            "data": [{"receiver": "乙", "mapName": "扬州", "firework": "真橙之心"}],
        }

        item = normalize_jx3api_response("https://www.jx3api.com/firework/records", response)["data"][0]

        self.assertEqual("乙", item["receive"])
        self.assertEqual("扬州", item["map_name"])
        self.assertEqual("真橙之心", item["name"])

    def test_normalizes_role_monster_fields_for_existing_parser(self) -> None:
        response = {
            "code": 200,
            "data": {
                "zone": "电信一区",
                "server": "唯我独尊",
                "globalId": "123",
                "skillEnergy": 20,
                "skillStamina": 30,
            },
        }

        data = normalize_jx3api_response("https://www.jx3api.com/monster/records", response)["data"]

        self.assertEqual("电信一区", data["zoneName"])
        self.assertEqual("唯我独尊", data["serverName"])
        self.assertEqual("123", data["globalRoleId"])
        self.assertEqual(20, data["gameEnergy"])
        self.assertEqual(30, data["gameStamina"])

    def test_normalizes_exam_index_to_legacy_id(self) -> None:
        response = {"code": 200, "data": [{"index": 8, "question": "题目"}]}

        item = normalize_jx3api_response("https://www.jx3api.com/exam/search", response)["data"][0]

        self.assertEqual(8, item["id"])

    def test_normalizes_flat_fraud_records_for_existing_formatter(self) -> None:
        response = {
            "code": 200,
            "data": [
                {"tieba": "剑网3", "title": "诈骗记录", "content": "内容", "created": 123, "pid": 456}
            ],
        }

        item = normalize_jx3api_response("https://www.jx3api.com/fraud/detail", response)["data"][0]

        self.assertEqual("剑网3", item["tieba"])
        self.assertEqual("诈骗记录", item["data"][0]["title"])
        self.assertEqual("内容", item["data"][0]["text"])
        self.assertEqual(123, item["data"][0]["time"])
        self.assertEqual("https://tieba.baidu.com/p/456", item["data"][0]["url"])

    def test_normalizes_calendar_and_status_fields(self) -> None:
        calendar = {
            "code": 200,
            "data": {"lucky": ["宠物"], "weekly": {"conn": ["公共", "秘境"], "raid": ["团队"]}},
        }
        status = {"code": 200, "data": [{"server": "唯我独尊", "status": "拥挤", "zone": "电信一区"}]}

        calendar_data = normalize_jx3api_response("https://www.jx3api.com/active/calendar", calendar)["data"]
        status_item = normalize_jx3api_response("https://www.jx3api.com/server/status/check", status)["data"][0]

        self.assertEqual(["宠物"], calendar_data["luck"])
        self.assertEqual(["公共", "秘境", "团队"], calendar_data["team"])
        self.assertEqual("拥挤", status_item["status"])
        self.assertEqual(1, status_item["legacyStatus"])
        self.assertIsInstance(status_item["time"], int)


if __name__ == "__main__":
    unittest.main()
