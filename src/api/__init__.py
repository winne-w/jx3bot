from fastapi import FastAPI

from src.api.routers import arena, jjc_ranking_stats


def register_api(app: FastAPI) -> None:
    app.include_router(arena.router)
    app.include_router(jjc_ranking_stats.router)
