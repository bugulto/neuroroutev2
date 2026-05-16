from fastapi import APIRouter, HTTPException

from app.db import get_pool
from renderer.mwparser_renderer import render_with_mwparser


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

        rendered = render_with_mwparser(row["raw_wikitext"])
        html_bytes = int(rendered["rendered_html_length_bytes"])
        wikitext_bytes = int(row["wikitext_length_bytes"] or 0)
        expansion_ratio = html_bytes / wikitext_bytes if wikitext_bytes else 0.0

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wiki_page_features
                SET
                    rendered_html_length_bytes = $1,
                    render_expansion_ratio = $2,
                    html_tag_count = $3
                WHERE page_id = $4
                """,
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
            "template_count_mw": int(rendered["template_count_mw"]),
            "wikilink_count_mw": int(rendered["wikilink_count_mw"]),
            "external_link_count_mw": int(rendered["external_link_count_mw"]),
            "heading_count_mw": int(rendered["heading_count_mw"]),
            "tag_count_mw": int(rendered["tag_count_mw"]),
            "processed_text_length_bytes": int(rendered["processed_text_length_bytes"]),
            "checksum": rendered["checksum"],
            "status": "rendered",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"render failed: {exc}")
