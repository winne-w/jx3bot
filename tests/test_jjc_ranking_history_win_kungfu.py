from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.jx3.jjc_cache_repo import (
    JjcCacheRepo,
    _build_match_detail_win_history_query,
    _match_player_in_detail,
)
from src.services.jx3.jjc_ranking import JjcRankingService


def _make_player(
    server: str = "蝶恋花",
    role_name: str = "测试角色",
    kungfu: str = "孤锋诀",
    role_id: Optional[str] = None,
    global_id: Optional[str] = None,
    kungfu_id: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    player: Dict[str, Any] = {
        "server": server,
        "role_name": role_name,
        "kungfu": kungfu,
    }
    if role_id is not None:
        player["role_id"] = role_id
    if global_id is not None:
        player["global_id"] = global_id
    if kungfu_id is not None:
        player["kungfu_id"] = kungfu_id
    player.update(kwargs)
    return player


def _make_detail(
    team1_players: List[Dict[str, Any]],
    team2_players: List[Dict[str, Any]],
    team1_won: bool = True,
    team2_won: bool = False,
    match_time: int = 1700000000,
    **kwargs: Any,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        "match_time": match_time,
        "team1": {
            "won": team1_won,
            "players_info": team1_players,
        },
        "team2": {
            "won": team2_won,
            "players_info": team2_players,
        },
    }
    detail.update(kwargs)
    return detail


def _make_doc(
    match_id: int,
    detail: Dict[str, Any],
    replay: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    doc_data: Dict[str, Any] = {"detail": detail}
    if replay is not None:
        doc_data["replay"] = replay
    return {
        "match_id": match_id,
        "data": doc_data,
    }


class MatchPlayerInDetailTests(unittest.TestCase):
    def test_server_and_name_match(self):
        player = _make_player(server="蝶恋花", role_name="测试角色")
        self.assertTrue(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )

    def test_name_with_server_suffix(self):
        player = _make_player(server="蝶恋花", role_name="测试角色·蝶恋花")
        self.assertTrue(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )

    def test_server_mismatch(self):
        player = _make_player(server="唯我独尊", role_name="测试角色")
        self.assertFalse(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )

    def test_name_mismatch(self):
        player = _make_player(server="蝶恋花", role_name="其他角色")
        self.assertFalse(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )

    def test_role_id_match(self):
        player = _make_player(server="蝶恋花", role_name="测试角色", role_id="rid_123")
        self.assertTrue(
            _match_player_in_detail(
                player, server="蝶恋花", name="测试角色", role_id="rid_123"
            )
        )

    def test_role_id_match_even_with_name_mismatch(self):
        player = _make_player(server="蝶恋花", role_name="其他角色", role_id="rid_123")
        self.assertTrue(
            _match_player_in_detail(
                player, server="蝶恋花", name="测试角色", role_id="rid_123"
            )
        )

    def test_global_id_match(self):
        player = _make_player(server="蝶恋花", role_name="测试角色", global_id="gid_456")
        self.assertTrue(
            _match_player_in_detail(
                player, server="蝶恋花", name="测试角色", global_id="gid_456"
            )
        )

    def test_no_match_when_ids_dont_match_and_name_server_dont_match(self):
        player = _make_player(server="唯我独尊", role_name="其他角色")
        self.assertFalse(
            _match_player_in_detail(
                player,
                server="蝶恋花",
                name="测试角色",
                role_id="rid_nonexistent",
            )
        )

    def test_missing_server_returns_false(self):
        player = _make_player(server="", role_name="测试角色")
        player.pop("server")
        self.assertFalse(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )

    def test_missing_name_returns_false(self):
        player = {"server": "蝶恋花"}
        self.assertFalse(
            _match_player_in_detail(player, server="蝶恋花", name="测试角色")
        )


class _AsyncCursorWrapper:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs
        self._index = 0

    def __aiter__(self) -> "_AsyncCursorWrapper":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._index]
        self._index += 1
        return doc


class HistoryWinKungfuFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = JjcCacheRepo(
            jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600,
        )

    def _mock_db(self, docs: List[Dict[str, Any]]) -> MagicMock:
        mock_db = MagicMock()
        mock_collection = MagicMock()

        def _find_side_effect(query: Dict[str, Any], *args: Any, **kwargs: Any) -> _AsyncCursorWrapper:
            filtered = list(docs)
            detail_filter = query.get("data.detail")
            if detail_filter == {"$ne": None}:
                filtered = [
                    d for d in filtered
                    if isinstance(d.get("data"), dict)
                    and d["data"].get("detail") is not None
                ]
            match_time_filter = query.get("data.detail.match_time")
            if isinstance(match_time_filter, dict) and "$gte" in match_time_filter:
                gte = match_time_filter["$gte"]
                filtered = [
                    d for d in filtered
                    if isinstance(d.get("data"), dict)
                    and isinstance(d["data"].get("detail"), dict)
                    and (d["data"]["detail"].get("match_time") or 0) >= gte
                ]
            return _AsyncCursorWrapper(filtered)

        mock_collection.find.side_effect = _find_side_effect
        mock_db.jjc_match_detail = mock_collection
        return mock_db

    @staticmethod
    def _set_repo_db(repo: JjcCacheRepo, db: MagicMock) -> JjcCacheRepo:
        return JjcCacheRepo(
            jjc_ranking_cache_duration=repo.jjc_ranking_cache_duration,
            kungfu_cache_duration=repo.kungfu_cache_duration,
            db=db,
        )

    def test_succeeds_with_3_wins(self):
        """角色在 3 场获胜对局中使用同一心法，应命中兜底。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["kungfu_selected_source"], "cached_match_detail_win_history")
        self.assertEqual(result["cached_match_detail_win_count"], 3)
        self.assertEqual(result["cached_match_detail_total_count"], 3)
        self.assertEqual(result["cached_match_detail_latest_win_match_id"], 3)
        self.assertEqual(result["cached_match_detail_latest_win_time"], 1700000300)
        self.assertEqual(len(result["cached_match_detail_win_samples"]), 3)

    def test_query_is_narrowed_by_name_and_stable_ids(self):
        query = _build_match_detail_win_history_query(
            server="蝶恋花",
            name="测试角色",
            season_start_ts=1700000000,
            role_id="rid_123",
            global_id="99999",
        )

        self.assertEqual(query["data.detail"], {"$ne": None})
        self.assertEqual(query["data.detail.match_time"], {"$gte": 1700000000})
        self.assertIn("$or", query)
        query_text = repr(query)
        self.assertIn("测试角色·蝶恋花", query_text)
        self.assertIn("rid_123", query_text)
        self.assertIn("99999", query_text)

    def test_rejects_less_than_3_wins(self):
        """角色同一心法只有 2 场获胜，不满足 >=3 阈值，不应命中。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNone(result)

    def test_does_not_mix_other_role_with_same_person_id(self):
        """同账号其他角色（不同 role_name）的对局不应计入目标角色的统计。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            # 同账号另一个角色，但不同名 → 不应匹配
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="其他角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        # 只有第1场属于目标角色，1场胜利 < 3，应返回 None
        self.assertIsNone(result)

    def test_season_filtering(self):
        """仅统计赛季开始后的对局。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1690000000,  # 赛季前
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000100,  # 赛季后
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000200,  # 赛季后
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        # 赛季开始于 2023-11-01 → timestamp 约 1698796800
        # 第1场 1690000000 < season_start，不应计入
        # 第2、3场 > season_start，应计入 → 2 胜 < 3，不命中
        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色", season_start="2023-11-01",
            )
        )

        self.assertIsNone(result)

    def test_season_filtering_allows_when_enough_post_season_wins(self):
        """赛季后的对局 >= 3 胜时应命中。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色", season_start="2023-01-01",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["cached_match_detail_win_count"], 3)

    def test_invalid_season_start_falls_back_to_no_filter(self):
        """无法解析 season_start 时不过滤时间，所有对局参与统计。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色", season_start="not-a-date",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["cached_match_detail_win_count"], 3)

    def test_picks_best_kungfu_with_most_wins(self):
        """多个心法达标时选胜场最多的。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
            _make_doc(4, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="花间游")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手D", kungfu="冰心诀")],
                team1_won=True, match_time=1700000400,
            )),
            _make_doc(5, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="花间游")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手E", kungfu="离经易道")],
                team1_won=True, match_time=1700000500,
            )),
            _make_doc(6, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="花间游")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手F", kungfu="冰心诀")],
                team1_won=True, match_time=1700000600,
            )),
            # 花间游 3 胜 vs 孤锋诀 3 胜，花间游胜场时间更新
            _make_doc(7, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="花间游")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手G", kungfu="离经易道")],
                team1_won=True, match_time=1700000700,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        # 花间游 4 胜 > 孤锋诀 3 胜，花间游胜场时间更新
        self.assertEqual(result["kungfu"], "花间游")
        self.assertEqual(result["cached_match_detail_win_count"], 4)

    def test_player_in_team2_can_win(self):
        """目标角色在 team2 且 team2 获胜时应正确统计。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team2_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team1_won=False, team2_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team2_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team1_won=False, team2_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team2_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team1_won=False, team2_won=True, match_time=1700000300,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["cached_match_detail_win_count"], 3)

    def test_lost_matches_not_counted_as_wins(self):
        """失败的对局不计入胜场。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=False, team2_won=True, match_time=1700000300,
            )),
            # 只有 2 胜，第3场输了
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNone(result)

    def test_unavailable_docs_skipped(self):
        """data.detail 为 null 的文档应跳过。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
            # 不可用的文档
            {
                "match_id": 999,
                "data": {
                    "match_id": 999,
                    "unavailable": True,
                    "detail": None,
                },
            },
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["cached_match_detail_win_count"], 3)

    def test_empty_collection_returns_none(self):
        """集合为空时返回 None。"""
        mock_db = self._mock_db([])
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNone(result)

    def test_role_name_with_server_suffix_in_detail(self):
        """role_name 包含 ·服务器 后缀时应正确匹配。"""
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色·蝶恋花", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            )),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色·蝶恋花", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            )),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="测试角色·蝶恋花", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            )),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="测试角色",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")


    def test_replay_stable_id_matching_renamed_player(self):
        """Player renamed; detail has no IDs but replay maps stable role_id to current name."""
        replay = {
            "data": {
                "players": [
                    {"role_id": "rid_stable", "role_name": "新名字", "global_role_id": "555"},
                    {"role_id": "rid_other1", "role_name": "队友A"},
                    {"role_id": "rid_other2", "role_name": "队友B"},
                ]
            }
        }
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="新名字", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            ), replay=replay),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="新名字", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            ), replay=replay),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="新名字", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            ), replay=replay),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="旧名字", role_id="rid_stable",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["cached_match_detail_win_count"], 3)

    def test_sk_like_global_role_id_ignored_in_replay(self):
        """Replay player with SK-prefixed global_role_id is ignored for stable matching."""
        replay = {
            "data": {
                "players": [
                    {"global_role_id": "SK01123456", "role_name": "被忽略的角色"},
                    {"global_role_id": "99999", "role_name": "正确角色", "role_id": "rid_ok"},
                ]
            }
        }
        docs = [
            _make_doc(1, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="正确角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手A", kungfu="花间游")],
                team1_won=True, match_time=1700000100,
            ), replay=replay),
            _make_doc(2, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="正确角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手B", kungfu="离经易道")],
                team1_won=True, match_time=1700000200,
            ), replay=replay),
            _make_doc(3, _make_detail(
                team1_players=[_make_player(server="蝶恋花", role_name="正确角色", kungfu="孤锋诀")],
                team2_players=[_make_player(server="唯我独尊", role_name="对手C", kungfu="冰心诀")],
                team1_won=True, match_time=1700000300,
            ), replay=replay),
        ]
        mock_db = self._mock_db(docs)
        repo = self._set_repo_db(self.repo, mock_db)

        result = asyncio_run(
            repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花", name="任何名字", global_id="99999",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")

    def test_normalize_role_name_respects_server_suffix(self):
        """Only strip ·server suffix when it matches the target or player server."""
        from src.services.jx3.jjc_cache_repo import _normalize_role_name

        self.assertEqual(
            _normalize_role_name("测试角色·蝶恋花", "蝶恋花", "蝶恋花"),
            "测试角色",
        )
        self.assertEqual(
            _normalize_role_name("测试角色·蝶恋花", "蝶恋花", "唯我独尊"),
            "测试角色",
        )
        self.assertEqual(
            _normalize_role_name("测试角色·蝶恋花", "唯我独尊", "唯我独尊"),
            "测试角色·蝶恋花",
        )
        self.assertEqual(
            _normalize_role_name("张三·李四", "蝶恋花", "蝶恋花"),
            "张三·李四",
        )
        self.assertEqual(
            _normalize_role_name("简单名字", "蝶恋花", "蝶恋花"),
            "简单名字",
        )


class SaveKungfuCacheDiagnosticFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = JjcCacheRepo(
            jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600,
            db=MagicMock(),
        )

    def test_persists_cached_match_detail_diagnostic_fields(self):
        mock_identity_repo = MagicMock()
        mock_identity_repo.upsert_from_indicator = AsyncMock(return_value={
            "identity_key": "global_id:12345",
            "server": "蝶恋花",
            "name": "测试角色",
        })
        mock_jjc_repo = MagicMock()
        mock_jjc_repo.save = AsyncMock()

        result = {
            "server": "蝶恋花",
            "name": "测试角色",
            "kungfu": "孤锋诀",
            "kungfu_selected_source": "cached_match_detail_win_history",
            "found": True,
            "cached_match_detail_win_count": 5,
            "cached_match_detail_total_count": 8,
            "cached_match_detail_latest_win_match_id": 42,
            "cached_match_detail_latest_win_time": 1700000300,
            "cached_match_detail_win_samples": [
                {"match_id": 42, "match_time": 1700000300, "kungfu": "孤锋诀"},
            ],
        }

        with patch(
            "src.storage.mongo_repos.role_identity_repo.RoleIdentityRepo",
            return_value=mock_identity_repo,
        ), patch(
            "src.storage.mongo_repos.role_jjc_cache_repo.RoleJjcCacheRepo",
            return_value=mock_jjc_repo,
        ):
            asyncio_run(self.repo.save_kungfu_cache("蝶恋花", "测试角色", result))

        mock_jjc_repo.save.assert_called_once()
        saved_data = mock_jjc_repo.save.call_args[0][1]

        self.assertEqual(saved_data.get("cached_match_detail_win_count"), 5)
        self.assertEqual(saved_data.get("cached_match_detail_total_count"), 8)
        self.assertEqual(saved_data.get("cached_match_detail_latest_win_match_id"), 42)
        self.assertEqual(saved_data.get("cached_match_detail_latest_win_time"), 1700000300)
        self.assertEqual(
            saved_data.get("cached_match_detail_win_samples"),
            [{"match_id": 42, "match_time": 1700000300, "kungfu": "孤锋诀"}],
        )
        self.assertEqual(saved_data.get("kungfu_selected_source"), "cached_match_detail_win_history")

    def test_omits_diagnostic_fields_when_not_in_result(self):
        mock_identity_repo = MagicMock()
        mock_identity_repo.upsert_from_indicator = AsyncMock(return_value={
            "identity_key": "global_id:12345",
        })
        mock_jjc_repo = MagicMock()
        mock_jjc_repo.save = AsyncMock()

        result = {
            "server": "蝶恋花",
            "name": "测试角色",
            "kungfu": "孤锋诀",
            "found": True,
        }

        with patch(
            "src.storage.mongo_repos.role_identity_repo.RoleIdentityRepo",
            return_value=mock_identity_repo,
        ), patch(
            "src.storage.mongo_repos.role_jjc_cache_repo.RoleJjcCacheRepo",
            return_value=mock_jjc_repo,
        ):
            asyncio_run(self.repo.save_kungfu_cache("蝶恋花", "测试角色", result))

        saved_data = mock_jjc_repo.save.call_args[0][1]
        self.assertNotIn("cached_match_detail_win_count", saved_data)
        self.assertNotIn("cached_match_detail_win_samples", saved_data)


def _build_ranking_service(defget_get: Any) -> JjcRankingService:
    return JjcRankingService(
        token="token",
        ticket="ticket",
        jjc_query_url="https://example.invalid/jjc",
        arena_time_tag_url="",
        arena_ranking_url="",
        match_detail_url="",
        jjc_ranking_cache_duration=3600,
        kungfu_cache_duration=3600,
        current_season="test",
        current_season_start="2023-01-01",
        kungfu_healer_list=[],
        kungfu_dps_list=[],
        kungfu_pinyin_to_chinese={},
        tuilan_request=lambda url, params: {},
        defget_get=defget_get,
    )


class GetUserKungfuDefgetFailureFallbackTests(unittest.TestCase):
    def test_defget_success_returns_refreshed_live_cache_result_when_found(self):
        defget_get = AsyncMock(return_value={
            "msg": "success",
            "data": {"history": [{"won": True, "kungfu": "旧历史心法"}]},
        })
        service = _build_ranking_service(defget_get)
        refreshed = {
            "server": "蝶恋花",
            "name": "测试角色",
            "kungfu": "孤锋诀",
            "found": True,
            "weapon": {"name": "钗蝶语双"},
            "teammates": [{"kungfu_id": 10015}],
        }
        update_kungfu_cache = AsyncMock(return_value=refreshed)

        with patch.object(
            JjcRankingService,
            "update_kungfu_cache",
            new=update_kungfu_cache,
        ), patch(
            "src.services.jx3.jjc_ranking.random_sleep",
            new=AsyncMock(),
        ):
            result = asyncio_run(service.get_user_kungfu(
                "蝶恋花",
                "测试角色",
                ranking_data={"code": 0, "data": []},
            ))

        self.assertIs(result, refreshed)
        update_kungfu_cache.assert_awaited_once()

    def test_defget_success_falls_back_to_history_when_live_refresh_not_found(self):
        defget_get = AsyncMock(return_value={
            "msg": "success",
            "data": {"history": [{"won": True, "kungfu": "旧历史心法"}]},
        })
        service = _build_ranking_service(defget_get)
        update_kungfu_cache = AsyncMock(return_value={
            "server": "蝶恋花",
            "name": "测试角色",
            "kungfu": None,
            "found": False,
        })
        cache = MagicMock()
        cache.get_kungfu_from_cached_match_detail_win_history = AsyncMock(return_value=None)
        cache.save_kungfu_cache = AsyncMock()

        with patch.object(
            JjcRankingService,
            "update_kungfu_cache",
            new=update_kungfu_cache,
        ), patch(
            "src.services.jx3.jjc_ranking.random_sleep",
            new=AsyncMock(),
        ), patch.object(JjcRankingService, "_cache", return_value=cache):
            result = asyncio_run(service.get_user_kungfu(
                "蝶恋花",
                "测试角色",
                ranking_data={"code": 0, "data": []},
            ))

        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "旧历史心法")
        update_kungfu_cache.assert_awaited_once()
        cache.get_kungfu_from_cached_match_detail_win_history.assert_not_awaited()
        cache.save_kungfu_cache.assert_awaited_once()

    def test_defget_success_falls_back_to_cached_match_detail_when_live_and_history_not_found(self):
        defget_get = AsyncMock(return_value={
            "msg": "success",
            "data": {"history": [{"won": False, "kungfu": "旧历史心法"}]},
        })
        service = _build_ranking_service(defget_get)
        update_kungfu_cache = AsyncMock(return_value={
            "server": "蝶恋花",
            "name": "测试角色",
            "kungfu": None,
            "found": False,
        })
        cache = MagicMock()
        cache.get_kungfu_from_cached_match_detail_win_history = AsyncMock(return_value={
            "found": True,
            "kungfu": "孤锋诀",
            "kungfu_id": 10015,
            "kungfu_selected_source": "cached_match_detail_win_history",
            "cached_match_detail_win_count": 3,
        })
        cache.save_kungfu_cache = AsyncMock()

        with patch.object(
            JjcRankingService,
            "update_kungfu_cache",
            new=update_kungfu_cache,
        ), patch(
            "src.services.jx3.jjc_ranking.random_sleep",
            new=AsyncMock(),
        ), patch.object(JjcRankingService, "_cache", return_value=cache):
            result = asyncio_run(service.get_user_kungfu(
                "蝶恋花",
                "测试角色",
                ranking_data={"code": 0, "data": []},
            ))

        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["kungfu_selected_source"], "cached_match_detail_win_history")
        cache.get_kungfu_from_cached_match_detail_win_history.assert_awaited_once_with(
            server="蝶恋花",
            name="测试角色",
            season_start="2023-01-01",
            role_id=None,
        )
        cache.save_kungfu_cache.assert_awaited_once()

    def test_defget_failure_uses_cached_match_detail_win_history_without_old_role_cache(self):
        defget_get = AsyncMock(return_value={
            "error": True,
            "message": "接口异常",
        })
        service = _build_ranking_service(defget_get)
        cache = MagicMock()
        cache.load_kungfu_cache = AsyncMock(return_value=None)
        cache.load_kungfu_cache_raw = AsyncMock(return_value={
            "weapon": "钗蝶语双",
            "weapon_quality": "5",
        })
        cache.get_kungfu_from_cached_match_detail_win_history = AsyncMock(return_value={
            "found": True,
            "kungfu": "孤锋诀",
            "kungfu_id": 10015,
            "kungfu_selected_source": "cached_match_detail_win_history",
            "cached_match_detail_win_count": 3,
            "cached_match_detail_total_count": 4,
            "cached_match_detail_latest_win_match_id": 42,
            "cached_match_detail_latest_win_time": 1700000300,
            "cached_match_detail_win_samples": [
                {"match_id": 42, "match_time": 1700000300, "kungfu": "孤锋诀"},
            ],
        })
        cache.save_kungfu_cache = AsyncMock()

        with patch(
            "src.services.jx3.jjc_ranking.random_sleep",
            new=AsyncMock(),
        ), patch.object(JjcRankingService, "_cache", return_value=cache):
            result = asyncio_run(service.get_user_kungfu(
                "蝶恋花",
                "测试角色",
                ranking_data={"code": 0, "data": []},
            ))

        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["kungfu_id"], 10015)
        self.assertEqual(result["kungfu_selected_source"], "cached_match_detail_win_history")
        self.assertEqual(result["cached_match_detail_win_count"], 3)
        self.assertEqual(result["cached_match_detail_total_count"], 4)
        self.assertEqual(result["cached_match_detail_latest_win_match_id"], 42)
        self.assertEqual(result["cached_match_detail_latest_win_time"], 1700000300)
        self.assertEqual(
            result["cached_match_detail_win_samples"],
            [{"match_id": 42, "match_time": 1700000300, "kungfu": "孤锋诀"}],
        )
        self.assertNotIn("weapon", result)
        self.assertNotIn("weapon_quality", result)

        cache.load_kungfu_cache.assert_not_awaited()
        cache.load_kungfu_cache_raw.assert_not_awaited()
        cache.get_kungfu_from_cached_match_detail_win_history.assert_awaited_once_with(
            server="蝶恋花",
            name="测试角色",
            season_start="2023-01-01",
            role_id=None,
        )
        cache.save_kungfu_cache.assert_awaited_once()
        saved_server, saved_name, saved_result = cache.save_kungfu_cache.call_args[0]
        self.assertEqual((saved_server, saved_name), ("蝶恋花", "测试角色"))
        self.assertTrue(saved_result["found"])
        self.assertEqual(saved_result["kungfu_selected_source"], "cached_match_detail_win_history")
        self.assertEqual(saved_result["cached_match_detail_latest_win_match_id"], 42)
        self.assertNotIn("weapon", saved_result)

    def test_defget_failure_fallback_miss_returns_original_error_shape(self):
        defget_get = AsyncMock(return_value={
            "error": True,
            "message": "接口异常",
        })
        service = _build_ranking_service(defget_get)
        cache = MagicMock()
        cache.load_kungfu_cache = AsyncMock(return_value=None)
        cache.get_kungfu_from_cached_match_detail_win_history = AsyncMock(return_value=None)
        cache.save_kungfu_cache = AsyncMock()

        with patch(
            "src.services.jx3.jjc_ranking.random_sleep",
            new=AsyncMock(),
        ), patch.object(JjcRankingService, "_cache", return_value=cache):
            result = asyncio_run(service.get_user_kungfu(
                "蝶恋花",
                "测试角色",
                ranking_data={"code": 0, "data": []},
            ))

        self.assertEqual(result, {
            "error": True,
            "message": "获取竞技场数据失败: 接口异常",
            "server": "蝶恋花",
            "name": "测试角色",
        })
        cache.load_kungfu_cache.assert_not_awaited()
        cache.save_kungfu_cache.assert_not_awaited()


def asyncio_run(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


if __name__ == "__main__":
    unittest.main()
