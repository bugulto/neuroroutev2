import itertools
import os

import httpx
from fastapi import APIRouter, HTTPException

from app.db import get_pool
from app.model import predict_is_slow_from_features


router = APIRouter()

_WORKER_CLIENT: httpx.AsyncClient | None = None


def parse_worker_urls(env_name: str, default_urls: list[str]) -> list[str]:
    raw_value = os.getenv(env_name)

    if raw_value is None:
        return default_urls

    parsed = [w.strip() for w in raw_value.split(",") if w.strip()]

    return parsed or default_urls


ALL_WORKERS = parse_worker_urls(
    "WORKER_ALL_URLS",
    [
        "http://worker_1:8001",
        "http://worker_2:8002",
        "http://worker_3:8003",
        "http://worker_4:8004",
    ],
)

FAST_WORKERS = parse_worker_urls(
    "WORKER_FAST_URLS",
    [
        "http://worker_1:8001",
        "http://worker_2:8002",
        "http://worker_3:8003",
    ],
)

SLOW_WORKERS = parse_worker_urls(
    "WORKER_SLOW_URLS",
    [
        "http://worker_4:8004",
    ],
)

round_robin_cycle = itertools.cycle(ALL_WORKERS)
fast_cycle = itertools.cycle(FAST_WORKERS)
slow_cycle = itertools.cycle(SLOW_WORKERS)


async def get_worker_client() -> httpx.AsyncClient:
    global _WORKER_CLIENT

    if _WORKER_CLIENT is None:
        _WORKER_CLIENT = httpx.AsyncClient(timeout=120.0)

    return _WORKER_CLIENT


async def close_worker_client() -> None:
    global _WORKER_CLIENT

    if _WORKER_CLIENT is not None:
        await _WORKER_CLIENT.aclose()
        _WORKER_CLIENT = None


async def get_page_by_id(page_id: int):
    pool = await get_pool()

    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT page_id, title, raw_wikitext
            FROM wiki_pages
            WHERE page_id = $1
            """,
            page_id,
        )


async def get_cheap_features_by_page_id(page_id: int):
    pool = await get_pool()

    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT
                wikitext_length_bytes,
                template_count,
                image_count,
                reference_count,
                heading_count,
                internal_link_count,
                external_link_count,
                category_count
            FROM wiki_page_features
            WHERE page_id = $1
            """,
            page_id,
        )
    
async def get_page_with_cached_prediction(page_id: int):
    pool = await get_pool()

    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT
                p.page_id,
                p.title,
                p.raw_wikitext,
                pred.predicted_slow
            FROM wiki_pages p
            JOIN wiki_page_predictions pred
            ON pred.page_id = p.page_id
            WHERE p.page_id = $1
            """,
            page_id,
        )


async def call_worker(worker_url: str, page_row) -> dict:
    payload = {
        "page_id": int(page_row["page_id"]),
        "title": page_row["title"],
        "raw_wikitext": page_row["raw_wikitext"],
    }

    try:
        client = await get_worker_client()
        response = await client.post(f"{worker_url}/process", json=payload)
        response.raise_for_status()
        return response.json()

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"worker request failed: {exc}",
        )


@router.post("/route-round-robin/{page_id}")
async def route_round_robin(page_id: int):
    if not ALL_WORKERS:
        raise HTTPException(status_code=500, detail="no workers configured")

    try:
        page_row = await get_page_by_id(page_id)

        if page_row is None:
            raise HTTPException(status_code=404, detail="page_id not found")

        selected_worker = next(round_robin_cycle)
        worker_response = await call_worker(selected_worker, page_row)

        return {
            "page_id": int(page_row["page_id"]),
            "title": page_row["title"],
            "routing_mode": "round_robin",
            "selected_worker": selected_worker,
            "worker_response": worker_response,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"route failed: {exc}")


@router.post("/route-neuroroute/{page_id}")
async def route_neuroroute(page_id: int):
    if not FAST_WORKERS or not SLOW_WORKERS:
        raise HTTPException(status_code=500, detail="no workers configured")

    try:
        page_row = await get_page_by_id(page_id)

        if page_row is None:
            raise HTTPException(status_code=404, detail="page_id not found")

        feature_row = await get_cheap_features_by_page_id(page_id)

        if feature_row is None:
            raise HTTPException(status_code=404, detail="features not found")

        features = dict(feature_row)
        predicted_slow = predict_is_slow_from_features(page_id, features)

        if predicted_slow == 1:
            selected_worker = next(slow_cycle)
            prediction_label = "slow"
        else:
            selected_worker = next(fast_cycle)
            prediction_label = "fast"

        worker_response = await call_worker(selected_worker, page_row)

        return {
            "page_id": int(page_row["page_id"]),
            "title": page_row["title"],
            "routing_mode": "neuroroute",
            "prediction": prediction_label,
            "predicted_slow": int(predicted_slow),
            "selected_worker": selected_worker,
            "worker_response": worker_response,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"route failed: {exc}")
    

@router.post("/route-neuroroute-cached/{page_id}")
async def route_neuroroute_cached(page_id: int):
    if not FAST_WORKERS or not SLOW_WORKERS:
        raise HTTPException(status_code=500, detail="no workers configured")

    try:
        page_row = await get_page_with_cached_prediction(page_id)

        if page_row is None:
            raise HTTPException(
                status_code=404,
                detail="page_id or cached prediction not found",
            )

        predicted_slow = int(page_row["predicted_slow"])

        if predicted_slow == 1:
            selected_worker = next(slow_cycle)
            prediction_label = "slow"
        else:
            selected_worker = next(fast_cycle)
            prediction_label = "fast"

        worker_response = await call_worker(selected_worker, page_row)

        return {
            "page_id": int(page_row["page_id"]),
            "title": page_row["title"],
            "routing_mode": "neuroroute_cached",
            "prediction_source": "cache",
            "prediction": prediction_label,
            "predicted_slow": predicted_slow,
            "selected_worker": selected_worker,
            "worker_response": worker_response,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"route failed: {exc}")
    
