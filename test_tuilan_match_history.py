from __future__ import annotations

import argparse
import json

import config as cfg

from src.services.jx3.match_history import MatchHistoryClient
from src.utils.tuilan_request import tuilan_request


def main() -> None:
    parser = argparse.ArgumentParser(description="推栏：分页获取 3c 战局历史（match/history）")
    parser.add_argument("global_role_id", help="例如：SK01-J7Q5LL-MYKUPPGV6R32HDB7UZIYNTFGRQ")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--cursor", type=int, default=0)
    args = parser.parse_args()

    client = MatchHistoryClient(
        match_history_url=cfg.API_URLS["竞技场战局历史"],
        tuilan_request=tuilan_request,
    )

    result = client.get_mine_match_history(
        global_role_id=args.global_role_id,
        size=args.size,
        cursor=args.cursor,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
