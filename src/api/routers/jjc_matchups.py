"""HTTP routes for JJC kungfu matchup metadata and searches."""

from fastapi import APIRouter, Request
from nonebot import logger

from src.api.response import error_response, success_response
from src.services.jx3.singletons import jjc_matchup_service


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


def _log_router_exception(message: str) -> None:
    """Log a fixed diagnostic message without changing the HTTP response path."""
    try:
        logger.exception(message)
    except Exception:
        pass


@router.get("/matchups/meta")
async def get_matchups_meta():
    """Return the service-owned matchup metadata."""
    try:
        return success_response(jjc_matchup_service.get_meta())
    except Exception:
        _log_router_exception("JJC matchup metadata service failed")
        return error_response("matchup_service_unavailable")


@router.post("/matchups/search")
async def search_matchups(request: Request):
    """Validate a JSON object request and delegate the matchup query."""
    try:
        payload = await request.json()
    except Exception:
        _log_router_exception("JJC matchup search request JSON parsing failed")
        return error_response("invalid_request")

    if not isinstance(payload, dict):
        return error_response("invalid_request")

    try:
        return success_response(await jjc_matchup_service.search(payload))
    except ValueError:
        _log_router_exception("JJC matchup search request validation failed")
        return error_response("invalid_request")
    except Exception:
        _log_router_exception("JJC matchup search service failed")
        return error_response("matchup_service_unavailable")
