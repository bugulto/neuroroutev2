import argparse
import csv
import os
import random


DEFAULT_TOTAL_COUNT = 1000
DEFAULT_SLOW_RATIO = 0.20
RANDOM_SEED = 42
DEFAULT_DATASET_PATH = os.path.join("dataset", "dataset50k_p80.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create benchmark_pages.csv from dataset CSV using page_id and is_slow."
    )
    parser.add_argument("--dataset-path", default=DEFAULT_DATASET_PATH)
    parser.add_argument("--total-count", type=int, default=DEFAULT_TOTAL_COUNT)
    parser.add_argument("--slow-ratio", type=float, default=DEFAULT_SLOW_RATIO)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument(
        "--output-path",
        default=os.path.join("loadtests", "benchmark_pages.csv"),
    )

    args = parser.parse_args()

    if not 0 < args.slow_ratio < 1:
        raise ValueError("--slow-ratio must be between 0 and 1")

    if not os.path.exists(args.dataset_path):
        raise FileNotFoundError(f"Dataset not found: {args.dataset_path}")

    slow_count_target = int(args.total_count * args.slow_ratio)
    fast_count_target = args.total_count - slow_count_target

    fast_rows = []
    slow_rows = []

    with open(args.dataset_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)

        required_columns = {"page_id", "is_slow"}
        missing_columns = required_columns - set(reader.fieldnames or [])

        if missing_columns:
            raise ValueError(
                f"Dataset missing required columns: {sorted(missing_columns)}"
            )

        for row in reader:
            page_id_raw = row.get("page_id")
            is_slow_raw = row.get("is_slow")

            if page_id_raw is None or is_slow_raw is None:
                continue

            page_id = int(page_id_raw)
            is_slow = int(float(is_slow_raw))

            if is_slow == 0:
                fast_rows.append((page_id, is_slow))
            elif is_slow == 1:
                slow_rows.append((page_id, is_slow))

    if len(fast_rows) < fast_count_target or len(slow_rows) < slow_count_target:
        raise ValueError(
            "Insufficient labeled pages in dataset: "
            f"available fast={len(fast_rows)}, available slow={len(slow_rows)}, "
            f"needed fast={fast_count_target}, needed slow={slow_count_target}"
        )

    rng = random.Random(args.seed)

    selected_fast = rng.sample(fast_rows, fast_count_target)
    selected_slow = rng.sample(slow_rows, slow_count_target)

    benchmark_rows = [
        {
            "page_id": int(page_id),
            "is_slow": int(is_slow),
        }
        for page_id, is_slow in selected_fast + selected_slow
    ]

    rng.shuffle(benchmark_rows)

    os.makedirs(os.path.dirname(args.output_path), exist_ok=True)

    with open(args.output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["page_id", "is_slow"])
        writer.writeheader()
        writer.writerows(benchmark_rows)

    fast_count = sum(1 for row in benchmark_rows if row["is_slow"] == 0)
    slow_count = sum(1 for row in benchmark_rows if row["is_slow"] == 1)

    print(f"Dataset: {args.dataset_path}")
    print(f"Total exported: {len(benchmark_rows)}")
    print(f"Fast count: {fast_count}")
    print(f"Slow count: {slow_count}")
    print(f"Slow ratio: {slow_count / len(benchmark_rows):.2%}")
    print(f"Seed: {args.seed}")
    print(f"Output: {args.output_path}")


if __name__ == "__main__":
    main()