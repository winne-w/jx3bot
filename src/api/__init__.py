from fastapi import FastAPI

from src.api.routers import arena, jjc_ranking_stats, mongo_health


def register_api(app: FastAPI) -> None:
    app.include_router(arena.router)
    app.include_router(jjc_ranking_stats.router)
    app.include_router(mongo_health.router)
