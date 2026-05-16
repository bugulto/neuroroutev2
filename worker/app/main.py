import os
import time
from fastapi import FastAPI
from pydantic import BaseModel


WORKER_NAME = os.getenv("WORKER_NAME", "worker")
WORKER_LANE = os.getenv("WORKER_LANE", "unknown")


app = FastAPI(
    title=f"NeuroRoute Worker {WORKER_NAME}",
    version="0.1.0",
)


class WorkRequest(BaseModel):
    page_id: int
    title: str
    raw_wikitext: str
    predicted_slow: int


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "worker": WORKER_NAME,
        "lane": WORKER_LANE,
    }


@app.post("/process")
async def process(payload: WorkRequest):
    start = time.perf_counter()

    wikitext_size = len(payload.raw_wikitext.encode("utf-8"))

    if WORKER_LANE == "slow":
        simulated_ms = min(800, max(100, wikitext_size // 100))
    else:
        simulated_ms = min(100, max(20, wikitext_size // 1000))

    time.sleep(simulated_ms / 1000)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    return {
        "worker": WORKER_NAME,
        "lane": WORKER_LANE,
        "page_id": payload.page_id,
        "title": payload.title,
        "predicted_slow": payload.predicted_slow,
        "simulated_ms": simulated_ms,
        "actual_elapsed_ms": elapsed_ms,
    }