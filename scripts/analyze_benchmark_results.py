import argparse
import json
import os
from typing import Dict, List

import matplotlib.pyplot as plt
import pandas as pd


REQUIRED_COLUMNS = {
    "page_id",
    "is_slow",
    "routing_mode",
    "response_time_ms",
    "status_code",
    "success",
    "error",
}


def _load_results(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {path}: {sorted(missing)}")

    df = df.copy()
    df["response_time_ms"] = pd.to_numeric(df["response_time_ms"], errors="coerce")
    df["is_slow"] = pd.to_numeric(df["is_slow"], errors="coerce")
    df["success"] = df["success"].astype(str).str.lower().isin({"true", "1", "yes"})
    return df


def _safe_percentile(series: pd.Series, q: float) -> float:
    if series.empty:
        return float("nan")
    return float(series.quantile(q))


def _summarize_group(df: pd.DataFrame) -> Dict[str, float]:
    total = len(df)
    failures = int((~df["success"]).sum())
    failure_rate = (failures / total) if total else 0.0

    success_df = df[df["success"]].copy()
    latency = success_df["response_time_ms"].dropna()

    return {
        "count": int(total),
        "failures": int(failures),
        "failure_rate": float(failure_rate),
        "mean": float(latency.mean()) if not latency.empty else float("nan"),
        "p50": _safe_percentile(latency, 0.50),
        "p90": _safe_percentile(latency, 0.90),
        "p95": _safe_percentile(latency, 0.95),
        "p99": _safe_percentile(latency, 0.99),
        "max": float(latency.max()) if not latency.empty else float("nan"),
    }


def _build_summary(df: pd.DataFrame, mode: str) -> Dict[str, Dict[str, float]]:
    all_pages = _summarize_group(df)
    fast_pages = _summarize_group(df[df["is_slow"] == 0])
    slow_pages = _summarize_group(df[df["is_slow"] == 1])

    return {
        "routing_mode": mode,
        "all": all_pages,
        "fast": fast_pages,
        "slow": slow_pages,
    }


def _improvement_percent(rr_value: float, nr_value: float) -> float:
    if rr_value is None or pd.isna(rr_value) or rr_value == 0:
        return float("nan")
    return ((rr_value - nr_value) / rr_value) * 100.0


def _write_summary_csv(path: str, rr: Dict, nr: Dict) -> None:
    rows: List[Dict[str, object]] = []
    for group_key, group_label in [("all", "all"), ("fast", "fast"), ("slow", "slow")]:
        for mode_label, data in [("round_robin", rr[group_key]), ("neuroroute", nr[group_key])]:
            rows.append(
                {
                    "routing_mode": mode_label,
                    "group": group_label,
                    **data,
                }
            )

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def _write_improvement_txt(path: str, rr: Dict, nr: Dict) -> Dict[str, Dict[str, float]]:
    metrics = ["mean", "p50", "p90", "p95", "p99", "max"]
    improvements: Dict[str, Dict[str, float]] = {}

    lines = []
    for group_key in ["all", "fast", "slow"]:
        improvements[group_key] = {}
        lines.append(f"{group_key} pages:")
        for metric in metrics:
            value = _improvement_percent(rr[group_key][metric], nr[group_key][metric])
            improvements[group_key][metric] = value
            lines.append(f"  {metric}: {value:.2f}%")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")

    return improvements


def _plot_latency_distribution(
    output_path: str,
    rr_df: pd.DataFrame,
    nr_df: pd.DataFrame,
) -> None:
    rr_latency = rr_df[rr_df["success"]]["response_time_ms"].dropna()
    nr_latency = nr_df[nr_df["success"]]["response_time_ms"].dropna()

    plt.figure(figsize=(10, 6))
    plt.hist(rr_latency, bins=40, alpha=0.6, label="Round Robin")
    plt.hist(nr_latency, bins=40, alpha=0.6, label="NeuroRoute")
    plt.title("Latency Distribution (Successful Requests)")
    plt.xlabel("Response Time (ms)")
    plt.ylabel("Count")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def _plot_p95_p99(
    output_path: str,
    title: str,
    rr_summary: Dict[str, float],
    nr_summary: Dict[str, float],
) -> None:
    labels = ["p95", "p99"]
    rr_values = [rr_summary["p95"], rr_summary["p99"]]
    nr_values = [nr_summary["p95"], nr_summary["p99"]]

    x = range(len(labels))
    width = 0.35

    plt.figure(figsize=(8, 5))
    plt.bar([i - width / 2 for i in x], rr_values, width=width, label="Round Robin")
    plt.bar([i + width / 2 for i in x], nr_values, width=width, label="NeuroRoute")
    plt.title(title)
    plt.xlabel("Percentile")
    plt.ylabel("Response Time (ms)")
    plt.xticks(list(x), labels)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze NeuroRoute benchmark results")
    parser.add_argument("--round-robin", required=True, help="Round Robin results CSV")
    parser.add_argument("--neuroroute", required=True, help="NeuroRoute results CSV")
    parser.add_argument("--output-name", required=True, help="Output folder name")
    args = parser.parse_args()

    rr_df = _load_results(args.round_robin)
    nr_df = _load_results(args.neuroroute)

    output_dir = os.path.join("reports", args.output_name)
    os.makedirs(output_dir, exist_ok=True)

    rr_summary = _build_summary(rr_df, "round_robin")
    nr_summary = _build_summary(nr_df, "neuroroute")

    summary_csv_path = os.path.join(output_dir, "summary.csv")
    summary_json_path = os.path.join(output_dir, "summary.json")
    improvement_path = os.path.join(output_dir, "improvement_summary.txt")
    latency_plot_path = os.path.join(output_dir, "latency_distribution.png")
    fast_plot_path = os.path.join(output_dir, "fast_pages_p95_p99.png")
    all_plot_path = os.path.join(output_dir, "all_pages_p95_p99.png")
    slow_plot_path = os.path.join(output_dir, "slow_pages_p95_p99.png")

    _write_summary_csv(summary_csv_path, rr_summary, nr_summary)
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "round_robin": rr_summary,
                "neuroroute": nr_summary,
            },
            f,
            indent=2,
        )

    improvements = _write_improvement_txt(improvement_path, rr_summary, nr_summary)

    _plot_latency_distribution(latency_plot_path, rr_df, nr_df)
    _plot_p95_p99(
        fast_plot_path,
        "Fast Pages: p95/p99 Latency",
        rr_summary["fast"],
        nr_summary["fast"],
    )
    _plot_p95_p99(
        all_plot_path,
        "All Pages: p95/p99 Latency",
        rr_summary["all"],
        nr_summary["all"],
    )
    _plot_p95_p99(
        slow_plot_path,
        "Slow Pages: p95/p99 Latency",
        rr_summary["slow"],
        nr_summary["slow"],
    )

    def _fmt(values: Dict[str, float]) -> str:
        return f"p95={values['p95']:.2f}, p99={values['p99']:.2f}"

    print(f"Output folder: {output_dir}")
    print(f"All pages: {_fmt(rr_summary['all'])} vs {_fmt(nr_summary['all'])}")
    print(f"Fast pages: {_fmt(rr_summary['fast'])} vs {_fmt(nr_summary['fast'])}")
    print(f"Slow pages: {_fmt(rr_summary['slow'])} vs {_fmt(nr_summary['slow'])}")
    print("Improvement percentages (mean, p50, p90, p95, p99, max):")
    for group_key in ["all", "fast", "slow"]:
        metrics = improvements[group_key]
        metric_text = ", ".join(
            f"{name}={metrics[name]:.2f}%"
            for name in ["mean", "p50", "p90", "p95", "p99", "max"]
        )
        print(f"  {group_key}: {metric_text}")


if __name__ == "__main__":
    main()
