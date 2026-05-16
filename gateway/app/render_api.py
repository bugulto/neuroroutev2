from fastapi import APIRouter, HTTPException

from app.db import get_pool
from renderer.wiki_renderer import render_wikitext


router = APIRouter()


@router.get("/render-page/{page_id}")
async def render_page(page_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.page_id, p.title, p.raw_wikitext, f.wikitext_length_bytes
                FROM wiki_pages p
                JOIN wiki_page_features f ON f.page_id = p.page_id
                WHERE p.page_id = $1
                """,
                page_id,
            )

        if row is None:
            raise HTTPException(status_code=404, detail="page_id not found")

        rendered = render_wikitext(row["raw_wikitext"])
        html_bytes = int(rendered["rendered_html_length_bytes"])
        wikitext_bytes = int(row["wikitext_length_bytes"] or 0)
        expansion_ratio = html_bytes / wikitext_bytes if wikitext_bytes else 0.0

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wiki_page_features
                SET
                    table_tag_count = $1,
                    paragraph_tag_count = $2,
                    rendered_html_length_bytes = $3,
                    render_expansion_ratio = $4,
                    html_tag_count = $5
                WHERE page_id = $6
                """,
                int(rendered["table_tag_count"]),
                int(rendered["paragraph_tag_count"]),
                html_bytes,
                expansion_ratio,
                int(rendered["html_tag_count"]),
                page_id,
            )

        return {
            "page_id": row["page_id"],
            "title": row["title"],
            "rendered_html_length_bytes": html_bytes,
            "render_expansion_ratio": round(expansion_ratio, 6),
            "html_tag_count": int(rendered["html_tag_count"]),
            "table_tag_count": int(rendered["table_tag_count"]),
            "paragraph_tag_count": int(rendered["paragraph_tag_count"]),
            "status": "rendered",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"render failed: {exc}")
