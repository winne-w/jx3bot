from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class JjcApiClient:
    arena_time_tag_url: str
    arena_ranking_url: str
    tuilan_request: Callable[[str, dict[str, Any]], Any]

    def get_arena_time_tag(self, type_param: str = "role") -> dict[str, Any]:
        url = self.arena_time_tag_url
        params = {"type": type_param}

        print("正在请求竞技场时间标签...")
        print(f"请求地址: {url}")
        print(f"请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                print("❌ 竞技场时间标签请求失败: 返回None")
                return {"error": "请求返回None"}

            if "error" in result:
                print(f"❌ 竞技场时间标签请求失败: {result['error']}")
                return result

            print("✅ 竞技场时间标签请求成功")
            return result
        except Exception as exc:
            print(f"❌ 竞技场时间标签请求异常: {exc}")
            import traceback

            traceback.print_exc()
            return {"error": f"请求异常: {exc}"}

    def get_arena_ranking(self, tag: int) -> dict[str, Any]:
        url = self.arena_ranking_url
        params = {"typeName": "week", "heiMaBang": False, "tag": tag}

        print("正在请求竞技场排行榜...")
        print(f"请求地址: {url}")
        print(f"请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                print("❌ 竞技场排行榜请求失败: 返回None")
                return {"error": "请求返回None"}

            if "error" in result:
                print(f"❌ 竞技场排行榜请求失败: {result['error']}")
                return result

            print("✅ 竞技场排行榜请求成功")
            return result
        except Exception as exc:
            print(f"❌ 竞技场排行榜请求异常: {exc}")
            import traceback

            traceback.print_exc()
            return {"error": f"请求异常: {exc}"}

