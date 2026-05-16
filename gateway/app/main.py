from fastapi import FastAPI
from pydantic import BaseModel

from app.router import route_request
from app.db import close_pool


app = FastAPI(
    title="NeuroRoute Gateway",
    description="AI-driven predictive load balancer for Wikipedia-style workloads",
    version="0.1.0",
)


class WikiRequest(BaseModel):
    page_id: int
    title: str
    raw_wikitext: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "gateway",
    }


@app.post("/route")
async def route(payload: WikiRequest):
    return await route_request(payload.model_dump())


@app.on_event("shutdown")
async def shutdown():
    await close_pool()