import atexit
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from posthog import Posthog

from epcot_fw.api.routers import (
    booths,
    events,
    festivals,
    menu_items,
    meta,
    search,
    seminars,
    snapshot,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from epcot_fw.config import get_settings

    settings = get_settings()
    app.state.posthog_client = None

    if settings.posthog_project_token and settings.posthog_host:
        posthog_client = Posthog(
            settings.posthog_project_token,
            host=settings.posthog_host,
            enable_exception_autocapture=True,
        )
        app.state.posthog_client = posthog_client
        atexit.register(posthog_client.shutdown)
    elif settings.debug:
        missing_variable = (
            "POSTHOG_PROJECT_TOKEN"
            if not settings.posthog_project_token
            else "POSTHOG_HOST"
        )
        raise RuntimeError(
            f"{missing_variable} variable required by PostHog is missing or un-configured, "
            f"this causes events to be silently missed. This error stops appearing once "
            f"{missing_variable} is configured"
        )

    yield

    if app.state.posthog_client:
        app.state.posthog_client.flush()


app = FastAPI(
    title="Epcot Food & Wine Festival API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def posthog_exception_handler(request: Request, exc: Exception) -> PlainTextResponse:
    posthog_client = getattr(request.app.state, "posthog_client", None)
    if posthog_client:
        posthog_client.capture_exception(exc)

    return PlainTextResponse("Internal Server Error", status_code=500)


API_PREFIX = "/api/v1"

for router in (
    festivals.router,
    booths.router,
    menu_items.router,
    events.router,
    seminars.router,
    search.router,
    snapshot.router,
    meta.router,
):
    app.include_router(router, prefix=API_PREFIX)
