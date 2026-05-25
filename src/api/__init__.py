from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.routers import announcements, arena, jjc_ranking_stats, jjc_sync, mongo_health


def register_api(app: FastAPI) -> None:
    app.include_router(announcements.router)
    app.include_router(arena.router)
    app.include_router(jjc_ranking_stats.router)
    app.include_router(jjc_sync.router)
    app.include_router(mongo_health.router)

    public_dir = Path(__file__).resolve().parents[2] / "public"
    if public_dir.exists():
        app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")
