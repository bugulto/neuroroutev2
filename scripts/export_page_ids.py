import csv
import os
import sys

import psycopg2


OUTPUT_PATH = os.path.join("loadtests", "page_ids.csv")


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


def main() -> None:
    try:
        conn = connect_db()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.page_id
                    FROM wiki_pages p
                    JOIN wiki_page_features f ON f.page_id = p.page_id
                    WHERE f.rendered_html_length_bytes IS NOT NULL
                    ORDER BY p.page_id
                    """
                )
                rows = cursor.fetchall()
    finally:
        conn.close()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["page_id"])
        for (page_id,) in rows:
            writer.writerow([page_id])

    print(f"Exported {len(rows)} page_ids to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
