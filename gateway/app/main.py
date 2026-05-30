from fastapi import FastAPI

from app.db import close_pool
from app.render_api import router as render_router
from app.router import router as route_router


app = FastAPI(
    title="NeuroRoute Gateway",
    description="AI-driven predictive load balancer for Wikipedia-style workloads",
    version="0.1.0",
)

app.include_router(render_router)
app.include_router(route_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "gateway",
    }


@app.on_event("shutdown")
async def shutdown():
    await close_pool()