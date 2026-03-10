from __future__ import annotations

import unittest

from src.storage.mongo_adapter.reminder_repo import MongoReminderRepo
from src.storage.mongo_adapter.subscription_repo import MongoSubscriptionRepo


class FakeResult:
    def __init__(self, modified_count: int = 0, deleted_count: int = 0) -> None:
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, spec):
        for key, direction in reversed(spec):
            reverse = direction == -1
            self._items.sort(key=lambda item: item.get(key), reverse=reverse)
        return self

    def __iter__(self):
        return iter(self._items)


class FakeCollection:
    def __init__(self) -> None:
        self.docs = {}

    def find(self, query=None, projection=None):
        query = query or {}
        return FakeCursor([doc.copy() for doc in self.docs.values() if self._match(doc, query)])

    def find_one(self, query):
        for doc in self.docs.values():
            if self._match(doc, query):
                return doc.copy()
        return None

    def replace_one(self, query, document, upsert=False):
        self.docs[document["_id"]] = document.copy()
        return FakeResult(modified_count=1)

    def update_one(self, query, update):
        for key, doc in self.docs.items():
            if self._match(doc, query):
                doc.update(update.get("$set", {}))
                self.docs[key] = doc
                return FakeResult(modified_count=1)
        return FakeResult(modified_count=0)

    def delete_one(self, query):
        for key, doc in list(self.docs.items()):
            if self._match(doc, query):
                del self.docs[key]
                return FakeResult(deleted_count=1)
        return FakeResult(deleted_count=0)

    def delete_many(self, query):
        if not query:
            count = len(self.docs)
            self.docs.clear()
            return FakeResult(deleted_count=count)
        deleted = 0
        for key, doc in list(self.docs.items()):
            if self._match(doc, query):
                del self.docs[key]
                deleted += 1
        return FakeResult(deleted_count=deleted)

    def insert_many(self, documents, ordered=False):
        for document in documents:
            self.docs[document["_id"]] = document.copy()

    @staticmethod
    def _match(doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict) and "$ne" in expected:
                if value == expected["$ne"]:
                    return False
                continue
            if value != expected:
                return False
        return True


class FakeProvider:
    def __init__(self) -> None:
        self.collections = {}

    def collection(self, name: str):
        return self.collections.setdefault(name, FakeCollection())


class MongoSubscriptionRepoTests(unittest.TestCase):
    def test_add_list_and_remove_by_index(self) -> None:
        repo = MongoSubscriptionRepo(FakeProvider())
        repo.add(
            "10001",
            {
                "item_name": "天选风不欺·无执",
                "price_threshold": 1,
                "group_id": 12345,
                "created_at": 10,
            },
        )
        repo.add(
            "10001",
            {
                "item_name": "龙隐·星月·标准",
                "price_threshold": 2,
                "group_id": 12345,
                "created_at": 20,
            },
        )

        items = repo.list_by_user("10001")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["item_name"], "天选风不欺·无执")

        removed = repo.remove_by_index("10001", 1)
        self.assertEqual(removed["item_name"], "天选风不欺·无执")
        self.assertEqual(len(repo.list_by_user("10001")), 1)


class MongoReminderRepoTests(unittest.TestCase):
    def test_list_pending_by_group_and_user(self) -> None:
        repo = MongoReminderRepo(FakeProvider())
        repo.create(
            {
                "id": "r1",
                "group_id": "20001",
                "creator_user_id": "30001",
                "message": "开团",
                "mention_type": "user",
                "remind_at": "20260310193000",
                "created_at": 1,
                "status": "pending",
            }
        )
        repo.create(
            {
                "id": "r2",
                "group_id": "20001",
                "creator_user_id": "30002",
                "message": "集合",
                "mention_type": "all",
                "remind_at": "20260310194000",
                "created_at": 2,
                "status": "done",
            }
        )

        self.assertEqual(len(repo.list_pending_by_group("20001")), 1)
        self.assertEqual(len(repo.list_pending_by_user("20001", "30001")), 1)
        self.assertEqual(len(repo.list_pending_by_user("20001", "30002")), 0)


if __name__ == "__main__":
    unittest.main()
