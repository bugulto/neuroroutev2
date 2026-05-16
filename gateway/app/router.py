import os
import itertools
import httpx

from app.model import predict_is_slow, extract_features
from app.db import get_pool


FAST_WORKERS = os.getenv("WORKER_FAST_URLS", "").split(",")
SLOW_WORKERS = os.getenv("WORKER_SLOW_URLS", "").split(",")

FAST_WORKERS = [w.strip() for w in FAST_WORKERS if w.strip()]
SLOW_WORKERS = [w.strip() for w in SLOW_WORKERS if w.strip()]

fast_cycle = itertools.cycle(FAST_WORKERS)
slow_cycle = itertools.cycle(SLOW_WORKERS)


def choose_worker(is_slow: int) -> str:
    if is_slow:
        return next(slow_cycle)

    return next(fast_cycle)


async def save_page_and_features(
    page_id: int,
    title: str,
    raw_wikitext: str,
    is_slow: int,
):
    features = extract_features(raw_wikitext)
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO wiki_pages (
                    page_id,
                    title,
                    raw_wikitext
                )
                VALUES ($1, $2, $3)
                ON CONFLICT (page_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    raw_wikitext = EXCLUDED.raw_wikitext
                """,
                page_id,
                title,
                raw_wikitext,
            )

            await conn.execute(
                """
                INSERT INTO wiki_page_features (
                    page_id,
                    wikitext_length_bytes,
                    template_count,
                    image_count,
                    reference_count,
                    heading_count,
                    internal_link_count,
                    external_link_count,
                    category_count
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (page_id)
                DO UPDATE SET
                    wikitext_length_bytes = EXCLUDED.wikitext_length_bytes,
                    template_count = EXCLUDED.template_count,
                    image_count = EXCLUDED.image_count,
                    reference_count = EXCLUDED.reference_count,
                    heading_count = EXCLUDED.heading_count,
                    internal_link_count = EXCLUDED.internal_link_count,
                    external_link_count = EXCLUDED.external_link_count,
                    category_count = EXCLUDED.category_count
                """,
                page_id,
                features["wikitext_length_bytes"],
                features["template_count"],
                features["image_count"],
                features["reference_count"],
                features["heading_count"],
                features["internal_link_count"],
                features["external_link_count"],
                features["category_count"],
            )

            await conn.execute(
                """
                INSERT INTO wiki_page_labels (
                    page_id,
                    is_slow
                )
                VALUES ($1, $2)
                ON CONFLICT (page_id)
                DO UPDATE SET
                    is_slow = EXCLUDED.is_slow
                """,
                page_id,
                is_slow,
            )


async def route_request(payload: dict) -> dict:
    raw_wikitext = payload.get("raw_wikitext", "")
    page_id = int(payload.get("page_id", 0))
    title = payload.get("title", "Untitled")

    is_slow = predict_is_slow(raw_wikitext)
    worker_url = choose_worker(is_slow)

    await save_page_and_features(
        page_id=page_id,
        title=title,
        raw_wikitext=raw_wikitext,
        is_slow=is_slow,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{worker_url}/process",
            json={
                "page_id": page_id,
                "title": title,
                "raw_wikitext": raw_wikitext,
                "predicted_slow": is_slow,
            },
        )

    return {
        "gateway_prediction": "slow" if is_slow else "fast",
        "selected_worker": worker_url,
        "worker_response": response.json(),
    }