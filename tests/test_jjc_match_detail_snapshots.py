import copy
import unittest

from src.services.jx3.match_detail_snapshots import (
    build_equipment_snapshot,
    build_talent_snapshot,
    calculate_snapshot_hash,
    normalize_equipment_snapshot,
    normalize_talent_snapshot,
)


class TestEquipmentSnapshotNormalization(unittest.TestCase):
    def test_different_key_order_produces_same_hash(self):
        armors1 = [{"pos": 1, "ui_id": "abc", "name": "破军"}]
        armors2 = [{"name": "破军", "pos": 1, "ui_id": "abc"}]
        h1 = calculate_snapshot_hash(normalize_equipment_snapshot(armors1))
        h2 = calculate_snapshot_hash(normalize_equipment_snapshot(armors2))
        self.assertEqual(h1, h2)

    def test_different_array_order_produces_same_hash(self):
        armors1 = [
            {"pos": 1, "ui_id": "a", "name": "破军"},
            {"pos": 2, "ui_id": "b", "name": "破虏"},
        ]
        armors2 = [
            {"pos": 2, "ui_id": "b", "name": "破虏"},
            {"pos": 1, "ui_id": "a", "name": "破军"},
        ]
        h1 = calculate_snapshot_hash(normalize_equipment_snapshot(armors1))
        h2 = calculate_snapshot_hash(normalize_equipment_snapshot(armors2))
        self.assertEqual(h1, h2)

    def test_empty_array_produces_stable_hash(self):
        h1 = calculate_snapshot_hash(normalize_equipment_snapshot([]))
        h2 = calculate_snapshot_hash(normalize_equipment_snapshot([]))
        self.assertEqual(h1, h2)
        self.assertIsInstance(h1, str)
        self.assertEqual(len(h1), 64)

    def test_input_not_modified(self):
        armors = [
            {"pos": 2, "name": "破虏", "ui_id": "b"},
            {"pos": 1, "name": "破军", "ui_id": "a"},
        ]
        original = copy.deepcopy(armors)
        normalize_equipment_snapshot(armors)
        self.assertEqual(armors, original)

    def test_normalize_sorts_by_pos_ui_id_name(self):
        armors = [
            {"pos": 3, "ui_id": "c", "name": "丙"},
            {"pos": 1, "ui_id": "b", "name": "乙"},
            {"pos": 1, "ui_id": "a", "name": "甲"},
        ]
        result = normalize_equipment_snapshot(armors)
        self.assertEqual(result[0]["name"], "甲")
        self.assertEqual(result[1]["name"], "乙")
        self.assertEqual(result[2]["name"], "丙")


class TestTalentSnapshotNormalization(unittest.TestCase):
    def test_different_array_order_produces_same_hash(self):
        talents1 = [
            {"level": 1, "id": "a", "name": "奇穴一"},
            {"level": 2, "id": "b", "name": "奇穴二"},
        ]
        talents2 = [
            {"level": 2, "id": "b", "name": "奇穴二"},
            {"level": 1, "id": "a", "name": "奇穴一"},
        ]
        h1 = calculate_snapshot_hash(normalize_talent_snapshot(talents1))
        h2 = calculate_snapshot_hash(normalize_talent_snapshot(talents2))
        self.assertEqual(h1, h2)

    def test_uses_talent_id_as_fallback(self):
        talents1 = [
            {"level": 1, "id": "a", "name": "奇穴一"},
            {"level": 2, "talent_id": "b", "name": "奇穴二"},
        ]
        talents2 = [
            {"level": 2, "talent_id": "b", "name": "奇穴二"},
            {"level": 1, "id": "a", "name": "奇穴一"},
        ]
        h1 = calculate_snapshot_hash(normalize_talent_snapshot(talents1))
        h2 = calculate_snapshot_hash(normalize_talent_snapshot(talents2))
        self.assertEqual(h1, h2)

    def test_empty_array_produces_stable_hash(self):
        h1 = calculate_snapshot_hash(normalize_talent_snapshot([]))
        h2 = calculate_snapshot_hash(normalize_talent_snapshot([]))
        self.assertEqual(h1, h2)
        self.assertIsInstance(h1, str)
        self.assertEqual(len(h1), 64)

    def test_input_not_modified(self):
        talents = [
            {"level": 2, "name": "奇穴二", "id": "b"},
            {"level": 1, "name": "奇穴一", "id": "a"},
        ]
        original = copy.deepcopy(talents)
        normalize_talent_snapshot(talents)
        self.assertEqual(talents, original)

    def test_normalize_sorts_by_level_id_name(self):
        talents = [
            {"level": 3, "id": "c", "name": "丙"},
            {"level": 1, "id": "b", "name": "乙"},
            {"level": 1, "id": "a", "name": "甲"},
        ]
        result = normalize_talent_snapshot(talents)
        self.assertEqual(result[0]["name"], "甲")
        self.assertEqual(result[1]["name"], "乙")
        self.assertEqual(result[2]["name"], "丙")


class TestBuildSnapshot(unittest.TestCase):
    def test_build_equipment_snapshot(self):
        armors = [{"pos": 1, "ui_id": "a", "name": "破军"}]
        snapshot = build_equipment_snapshot(armors)
        self.assertIn("snapshot_hash", snapshot)
        self.assertIn("armors", snapshot)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(len(snapshot["snapshot_hash"]), 64)
        self.assertEqual(snapshot["armors"], normalize_equipment_snapshot(armors))

    def test_build_talent_snapshot(self):
        talents = [{"level": 1, "id": "a", "name": "奇穴一"}]
        snapshot = build_talent_snapshot(talents)
        self.assertIn("snapshot_hash", snapshot)
        self.assertIn("talents", snapshot)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(len(snapshot["snapshot_hash"]), 64)
        self.assertEqual(snapshot["talents"], normalize_talent_snapshot(talents))


class TestHashStability(unittest.TestCase):
    def test_hash_is_deterministic(self):
        items = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        h1 = calculate_snapshot_hash(items)
        h2 = calculate_snapshot_hash(items)
        self.assertEqual(h1, h2)

    def test_different_data_produces_different_hash(self):
        h1 = calculate_snapshot_hash([{"pos": 1}])
        h2 = calculate_snapshot_hash([{"pos": 2}])
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
