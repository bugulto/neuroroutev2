import csv
import statistics
from pathlib import Path

RESULTS_PATH = Path("loadtests/results/mw_sequential_response_times_50k.csv")
SUMMARY_PATH = Path("loadtests/results/mw_response_time_summary.csv")


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


def load_response_times(path):
    response_times = []
    failures = 0

    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            success = row.get("success") == "1"

            if not success:
                failures += 1
                continue

            response_time = row.get("response_time_ms")
            if response_time:
                response_times.append(float(response_time))

    return response_times, failures


def main():
    response_times, failures = load_response_times(RESULTS_PATH)

    if not response_times:
        print("No successful response times found.")
        return

    percentiles = [50, 75, 80, 85, 90, 95, 97, 98, 99, 99.5, 99.9, 100]

    summary = {
        "count": len(response_times),
        "failures": failures,
        "failure_rate": failures / (len(response_times) + failures),
        "mean_ms": statistics.mean(response_times),
        "median_ms": statistics.median(response_times),
        "min_ms": min(response_times),
        "max_ms": max(response_times),
    }

    for p in percentiles:
        key = f"p{str(p).replace('.', '_')}_ms"
        summary[key] = percentile(response_times, p)

    print("\nResponse Time Summary")
    print("=" * 40)

    for key, value in summary.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2f}")
        else:
            print(f"{key}: {value}")

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(SUMMARY_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print(f"\nSaved summary to: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()