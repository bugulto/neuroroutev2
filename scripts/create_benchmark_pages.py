import csv
import os
import random

import psycopg2


FAST_COUNT = 800
SLOW_COUNT = 200
RANDOM_SEED = 42


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required env var: {name}")
    return value


def main() -> None:
    db_name = _get_env("POSTGRES_DB")
    db_user = _get_env("POSTGRES_USER")
    db_password = _get_env("POSTGRES_PASSWORD")
    db_host = _get_env("POSTGRES_HOST")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    connection = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port,
    )

    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT page_id, is_slow
                FROM wiki_page_labels
                WHERE is_slow IN (0, 1)
                """
            )
            rows = cursor.fetchall()

    fast_rows = [row for row in rows if int(row[1]) == 0]
    slow_rows = [row for row in rows if int(row[1]) == 1]

    if len(fast_rows) < FAST_COUNT or len(slow_rows) < SLOW_COUNT:
        raise ValueError(
            "Insufficient labeled pages: "
            f"fast={len(fast_rows)}, slow={len(slow_rows)}"
        )

    rng = random.Random(RANDOM_SEED)
    selected_fast = rng.sample(fast_rows, FAST_COUNT)
    selected_slow = rng.sample(slow_rows, SLOW_COUNT)

    benchmark_rows = [
        {"page_id": int(page_id), "is_slow": int(is_slow)}
        for page_id, is_slow in (selected_fast + selected_slow)
    ]
    rng.shuffle(benchmark_rows)

    output_path = os.path.join("loadtests", "benchmark_pages.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["page_id", "is_slow"])
        writer.writeheader()
        writer.writerows(benchmark_rows)

    fast_count = sum(1 for row in benchmark_rows if row["is_slow"] == 0)
    slow_count = sum(1 for row in benchmark_rows if row["is_slow"] == 1)

    print(f"Total exported: {len(benchmark_rows)}")
    print(f"Fast count: {fast_count}")
    print(f"Slow count: {slow_count}")


if __name__ == "__main__":
    main()
