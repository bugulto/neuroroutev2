import csv
import os
import statistics
import sys
from typing import Dict, List, Tuple

import psycopg2
import psycopg2.extras


INPUT_PATH = os.path.join("loadtests", "results", "mw_sequential_response_times_50k.csv")
SLOW_PERCENTILE = 0.90


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


def load_timings() -> Tuple[int, int, List[Tuple[int, float]]]:
    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(f"CSV not found at {INPUT_PATH}")

    total_rows = 0
    successful_rows = 0
    timings: Dict[int, List[float]] = {}

    with open(INPUT_PATH, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            total_rows += 1

            if not row.get("success"):
                continue

            if str(row["success"]).strip() != "1":
                continue

            page_id = int(row["page_id"])
            response_ms = float(row["response_time_ms"])

            timings.setdefault(page_id, []).append(response_ms)
            successful_rows += 1

    averages = [
        (page_id, statistics.mean(values))
        for page_id, values in timings.items()
    ]

    return total_rows, successful_rows, averages


def upsert_labels(
    cursor: psycopg2.extensions.cursor,
    rows: List[Tuple[int, float]],
) -> None:
    sql = """
        INSERT INTO wiki_page_labels (page_id, avg_response_time)
        VALUES %s
        ON CONFLICT (page_id)
        DO UPDATE SET avg_response_time = EXCLUDED.avg_response_time
    """

    psycopg2.extras.execute_values(cursor, sql, rows)


def update_is_slow(
    cursor: psycopg2.extensions.cursor,
    threshold: float,
) -> Tuple[int, int]:
    cursor.execute(
        """
        UPDATE wiki_page_labels
        SET is_slow = CASE
            WHEN avg_response_time >= %s THEN 1
            ELSE 0
        END
        WHERE avg_response_time IS NOT NULL
        """,
        (threshold,),
    )

    cursor.execute("SELECT COUNT(*) FROM wiki_page_labels WHERE is_slow = 1")
    slow_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM wiki_page_labels WHERE is_slow = 0")
    fast_count = cursor.fetchone()[0]

    return slow_count, fast_count


def percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return 0.0

    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)

    if f == c:
        return sorted_values[f]

    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)

    return d0 + d1


def main() -> None:
    try:
        total_rows, successful_rows, averages = load_timings()

    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    except Exception as exc:
        print(f"Failed to read CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    if not averages:
        print("No successful rows found. Nothing to import.", file=sys.stderr)
        sys.exit(1)

    avg_values = sorted(avg for _, avg in averages)
    slow_threshold = percentile(avg_values, SLOW_PERCENTILE)

    try:
        conn = connect_db()

    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cursor:
                upsert_labels(cursor, averages)
                slow_count, fast_count = update_is_slow(cursor, slow_threshold)

    finally:
        conn.close()

    print("Summary:")
    print(f"  total timing rows read: {total_rows}")
    print(f"  successful rows: {successful_rows}")
    print(f"  pages averaged: {len(averages)}")
    print(f"  p90 threshold: {slow_threshold:.2f}")
    print(f"  slow pages count: {slow_count}")
    print(f"  fast pages count: {fast_count}")


if __name__ == "__main__":
    main()