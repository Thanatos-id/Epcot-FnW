from fastapi import FastAPI

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

app = FastAPI(title="Epcot Food & Wine Festival API", version="0.1.0")

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
