import os
from fastapi import FastAPI
from pydantic import BaseModel

from renderer.mwparser_renderer import process_with_mwparser


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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "worker": WORKER_NAME,
        "lane": WORKER_LANE,
    }


@app.post("/process")
async def process(payload: WorkRequest):
    processed = process_with_mwparser(payload.raw_wikitext)

    return {
        "worker": WORKER_NAME,
        "lane": WORKER_LANE,
        "page_id": payload.page_id,
        "title": payload.title,
        "rendered_html_length_bytes": int(processed["rendered_html_length_bytes"]),
        "html_tag_count": int(processed["html_tag_count"]),
        "checksum": processed["checksum"],
        "status": "processed",
    }