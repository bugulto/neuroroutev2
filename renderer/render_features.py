import argparse
import os
import sys
from typing import List, Tuple

import psycopg2
import psycopg2.extras

from wiki_renderer import render_wikitext


def connect_db() -> psycopg2.extensions.connection:
    try:
        return psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
        )
    except psycopg2.Error as exc:
        raise RuntimeError(f"Database connection failed: {exc}")


def fetch_pages(
    cursor: psycopg2.extensions.cursor,
    batch_size: int,
    limit: int | None,
    force: bool,
) -> List[Tuple[int, str, int]]:
    where_clause = "" if force else "WHERE f.rendered_html_length_bytes IS NULL"
    limit_clause = "" if limit is None else "LIMIT %s"

    query = f"""
        SELECT p.page_id, p.raw_wikitext, f.wikitext_length_bytes
        FROM wiki_pages p
        JOIN wiki_page_features f ON f.page_id = p.page_id
        {where_clause}
        ORDER BY p.page_id
        {limit_clause}
    """

    if limit is None:
        cursor.execute(query)
    else:
        cursor.execute(query, (limit,))

    return cursor.fetchmany(batch_size)


def update_features(
    cursor: psycopg2.extensions.cursor,
    rows: List[Tuple[int, int, int, float, int]],
) -> None:
    update_sql = """
        UPDATE wiki_page_features
        SET
            table_tag_count = data.table_tag_count,
            paragraph_tag_count = data.paragraph_tag_count,
            rendered_html_length_bytes = data.rendered_html_length_bytes,
            render_expansion_ratio = data.render_expansion_ratio,
            html_tag_count = data.html_tag_count
        FROM (VALUES %s) AS data(
            page_id,
            table_tag_count,
            paragraph_tag_count,
            rendered_html_length_bytes,
            render_expansion_ratio,
            html_tag_count
        )
        WHERE wiki_page_features.page_id = data.page_id
    """

    psycopg2.extras.execute_values(cursor, update_sql, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render wiki pages and fill render-derived feature columns."
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        conn = connect_db()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    processed = 0
    failed = 0
    batch_number = 0
    total_html_bytes = 0
    total_html_tags = 0
    total_expansion_ratio = 0.0

    try:
        with conn:
            with conn.cursor() as cursor:
                while True:
                    batch = fetch_pages(cursor, args.batch_size, args.limit, args.force)
                    if not batch:
                        break

                    batch_number += 1
                    updates: List[Tuple[int, int, int, int, float, int]] = []

                    for page_id, raw_wikitext, wikitext_length_bytes in batch:
                        try:
                            rendered = render_wikitext(raw_wikitext)
                            html_bytes = int(rendered["rendered_html_length_bytes"])
                            html_tags = int(rendered["html_tag_count"])
                            expansion_ratio = (
                                html_bytes / wikitext_length_bytes
                                if wikitext_length_bytes
                                else 0.0
                            )

                            updates.append(
                                (
                                    page_id,
                                    int(rendered["table_tag_count"]),
                                    int(rendered["paragraph_tag_count"]),
                                    html_bytes,
                                    expansion_ratio,
                                    html_tags,
                                )
                            )

                            processed += 1
                            total_html_bytes += html_bytes
                            total_html_tags += html_tags
                            total_expansion_ratio += expansion_ratio
                        except Exception as exc:
                            failed += 1
                            print(f"Render failed for page_id={page_id}: {exc}", file=sys.stderr)

                    if updates:
                        update_features(cursor, updates)

                    avg_html_bytes = total_html_bytes / processed if processed else 0.0
                    avg_html_tags = total_html_tags / processed if processed else 0.0

                    print(
                        "Progress:"
                        f" batch={batch_number}"
                        f" processed={processed}"
                        f" failed={failed}"
                        f" avg_html_bytes={avg_html_bytes:.2f}"
                        f" avg_html_tags={avg_html_tags:.2f}"
                    )

                    if args.limit is not None and processed >= args.limit:
                        break
    finally:
        conn.close()

    avg_html_bytes = total_html_bytes / processed if processed else 0.0
    avg_html_tags = total_html_tags / processed if processed else 0.0
    avg_expansion_ratio = total_expansion_ratio / processed if processed else 0.0

    print("Final summary:")
    print(f"  total pages processed: {processed}")
    print(f"  failed pages: {failed}")
    print(f"  average rendered HTML bytes: {avg_html_bytes:.2f}")
    print(f"  average expansion ratio: {avg_expansion_ratio:.4f}")
    print(f"  average HTML tag count: {avg_html_tags:.2f}")


if __name__ == "__main__":
    main()
