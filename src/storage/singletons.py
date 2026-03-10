from __future__ import annotations

from src.storage.factory import load_mongo_settings
from src.storage.mongo_adapter.base import MongoProvider
from src.storage.mongo_adapter.cache_entry_repo import MongoCacheEntryRepo
from src.storage.mongo_adapter.jjc_cache_repo import MongoJjcCacheRepo
from src.storage.mongo_adapter.jjc_ranking_stats_repo import MongoJjcRankingStatsRepo
from src.storage.mongo_adapter.reminder_repo import MongoReminderRepo
from src.storage.mongo_adapter.subscription_repo import MongoSubscriptionRepo

mongo_provider = MongoProvider(load_mongo_settings())

cache_entry_storage = MongoCacheEntryRepo(mongo_provider)
jjc_cache_storage = MongoJjcCacheRepo(mongo_provider)
reminder_storage = MongoReminderRepo(mongo_provider)
subscription_storage = MongoSubscriptionRepo(mongo_provider)
jjc_ranking_stats_storage = MongoJjcRankingStatsRepo(mongo_provider)
