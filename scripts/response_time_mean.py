import csv
import statistics
from collections import defaultdict
from pathlib import Path


RESULTS_PATH = Path("loadtests/results/mw_sequential_response_times_50k.csv")
SUMMARY_PATH = Path("loadtests/results/mw_page_response_time_summary_mean.csv")

AGGREGATION_METHOD = "mean"


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    lower = int(k)
    upper = min(lower + 1, len(values) - 1)

    if lower == upper:
        return values[lower]

    weight = k - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def load_page_timings(path):
    timings_by_page = defaultdict(list)
    failures = 0
    total_rows = 0

    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            total_rows += 1

            success = str(row.get("success", "")).strip() == "1"
            if not success:
                failures += 1
                continue

            page_id = row.get("page_id")
            response_time = row.get("response_time_ms")

            if not page_id or not response_time:
                failures += 1
                continue

            timings_by_page[int(page_id)].append(float(response_time))

    return timings_by_page, total_rows, failures


def aggregate_page_timings(timings_by_page, method):
    page_response_times = []

    for values in timings_by_page.values():
        if not values:
            continue

        if method == "mean":
            page_time = statistics.mean(values)
        elif method == "median":
            page_time = statistics.median(values)
        else:
            raise ValueError("AGGREGATION_METHOD must be 'mean' or 'median'")

        page_response_times.append(page_time)

    return page_response_times


def build_summary(page_response_times, total_rows, failures, page_count):
    percentiles = [
        50, 75, 80, 85, 90,
        91, 92, 93, 94, 95,
        97, 98, 99, 99.5, 99.9, 100,
    ]

    summary = {
        "aggregation_method": AGGREGATION_METHOD,
        "raw_timing_rows": total_rows,
        "successful_timing_rows": total_rows - failures,
        "failed_timing_rows": failures,
        "failure_rate": failures / total_rows if total_rows else 0,
        "pages_with_successful_timings": page_count,
        "mean_ms": statistics.mean(page_response_times),
        "median_ms": statistics.median(page_response_times),
        "min_ms": min(page_response_times),
        "max_ms": max(page_response_times),
    }

    for p in percentiles:
        key = f"p{str(p).replace('.', '_')}_ms"
        summary[key] = percentile(page_response_times, p)

    return summary


def save_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)


def main():
    timings_by_page, total_rows, failures = load_page_timings(RESULTS_PATH)

    page_response_times = aggregate_page_timings(
        timings_by_page,
        AGGREGATION_METHOD,
    )

    if not page_response_times:
        print("No successful page timings found.")
        return

    summary = build_summary(
        page_response_times=page_response_times,
        total_rows=total_rows,
        failures=failures,
        page_count=len(page_response_times),
    )

    save_summary(SUMMARY_PATH, summary)

    print("\nPer-Page Response Time Summary")
    print("=" * 45)
    print(f"Aggregation method: {AGGREGATION_METHOD}")
    print(f"Raw timing rows: {total_rows}")
    print(f"Pages with successful timings: {len(page_response_times)}")
    print(f"Failed timing rows: {failures}")

    print(f"\nPercentile ranges based on {AGGREGATION_METHOD} response time per page:")
    for key, value in summary.items():
        if key.startswith("p") and key.endswith("_ms"):
            print(f"{key}: {value:.2f} ms")

    print("\nCore summary:")
    print(f"mean_ms: {summary['mean_ms']:.2f}")
    print(f"median_ms: {summary['median_ms']:.2f}")
    print(f"min_ms: {summary['min_ms']:.2f}")
    print(f"max_ms: {summary['max_ms']:.2f}")

    print(f"\nSaved summary to: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()