import csv
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
LOADTESTS_DIR = PROJECT_ROOT / "loadtests"
RESULTS_DIR = LOADTESTS_DIR / "results"
REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR = PROJECT_ROOT / "models"
DATASET_DIR = PROJECT_ROOT / "dataset"

VENV_BIN_DIR = Path(sys.executable).parent
LOCUST_BIN = str(VENV_BIN_DIR / "locust")

VALID_THRESHOLDS = ("p80", "p85", "p90", "p93", "p94")

MODEL_TEMPLATE = "neuroroute_random_forest50k_{threshold}.joblib"
DATASET_TEMPLATE = "dataset50k_{threshold}.csv"

RUNS: dict[str, dict[str, Any]] = {}


class BenchmarkRequest(BaseModel):
    threshold: str
    neuroroute_mode: Literal["online", "cache"] = "online"
    users: int = Field(default=10, gt=0)
    spawn_rate: int = Field(default=2, gt=0)
    total_count: int = Field(default=1000, gt=0)
    slow_ratio: float = Field(default=0.20, gt=0.0, lt=1.0)

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, value: str) -> str:
        if value not in VALID_THRESHOLDS:
            raise ValueError(f"threshold must be one of {VALID_THRESHOLDS}")
        return value


app = FastAPI(
    title="NeuroRoute Benchmark UI",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def make_run_id(threshold: str, users: int, mode: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if mode == "cache":
        return f"benchmark_u{users}_{threshold}_cache_{timestamp}"
    return f"benchmark_u{users}_{threshold}_{timestamp}"


def log(run_id: str, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    RUNS[run_id]["logs"].append(f"[{timestamp}] {message}")


def set_status(run_id: str, status: str) -> None:
    RUNS[run_id]["status"] = status
    log(run_id, f"Status → {status}")


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        return 0


def run_cmd(
    run_id: str,
    cmd: list[str],
    label: str,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    import os

    full_env = {**os.environ, **(env or {})}

    log(run_id, f"$ {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
    )

    for line in result.stdout.strip().splitlines():
        log(run_id, f"  {line}")

    for line in result.stderr.strip().splitlines():
        log(run_id, f"  [stderr] {line}")

    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")

    return result


def wait_for_gateway(run_id: str, retries: int = 15, delay: float = 2.0) -> None:
    import urllib.error
    import urllib.request

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request("http://localhost:8000/health")
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    log(run_id, f"Gateway healthy on attempt {attempt}")
                    return
        except (urllib.error.URLError, OSError):
            pass

        log(run_id, f"Waiting for gateway... {attempt}/{retries}")
        time.sleep(delay)

    raise RuntimeError("Gateway did not become healthy")


def kill_orphan_locust_processes(run_id: str) -> None:
    result = subprocess.run(
        ["pkill", "-f", "locust.*locust_.*_benchmark"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        log(run_id, "Killed orphan Locust processes")
        time.sleep(1)


def run_locust(
    run_id: str,
    cmd: list[str],
    label: str,
    results_path: Path,
    expected_rows: int,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
    poll_interval: float = 3.0,
    stall_timeout: int = 60,
) -> None:
    import os

    full_env = {**os.environ, **(env or {})}

    if results_path.exists():
        results_path.unlink()

    log(run_id, f"$ {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=full_env,
    )

    deadline = time.monotonic() + timeout
    last_count = -1
    last_progress_time = time.monotonic()

    try:
        while time.monotonic() < deadline:
            row_count = count_csv_rows(results_path)

            if row_count != last_count:
                log(run_id, f"Progress: {row_count}/{expected_rows} requests")
                last_count = row_count
                last_progress_time = time.monotonic()

            if row_count >= expected_rows:
                log(run_id, f"All {expected_rows} requests completed")
                time.sleep(2)
                break

            return_code = process.poll()
            if return_code is not None:
                if row_count == 0:
                    raise RuntimeError(f"{label} exited with no results")
                break

            if row_count > 0 and time.monotonic() - last_progress_time > stall_timeout:
                raise RuntimeError(
                    f"{label} stalled at {row_count}/{expected_rows} for {stall_timeout}s"
                )

            time.sleep(poll_interval)

        else:
            raise RuntimeError(f"{label} timed out after {timeout}s")

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    final_rows = count_csv_rows(results_path)
    log(run_id, f"Final: {final_rows}/{expected_rows} rows collected")

    if final_rows == 0:
        raise RuntimeError(f"{label}: no results collected")

    if final_rows < expected_rows:
        raise RuntimeError(f"{label}: incomplete results, got {final_rows}/{expected_rows}")


def validate_required_files_online(threshold: str) -> tuple[Path, Path]:
    dataset_path = DATASET_DIR / DATASET_TEMPLATE.format(threshold=threshold)
    model_path = MODELS_DIR / MODEL_TEMPLATE.format(threshold=threshold)

    required_paths = [
        dataset_path,
        model_path,
        SCRIPTS_DIR / "create_benchmark_pages.py",
        SCRIPTS_DIR / "set_active_model.py",
        SCRIPTS_DIR / "analyze_benchmark_results.py",
        LOADTESTS_DIR / "locust_round_robin_benchmark.py",
        LOADTESTS_DIR / "locust_neuroroute_benchmark.py",
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {path}")

    return dataset_path, model_path


def validate_required_files_cache() -> Path:
    dataset_path = DATASET_DIR / DATASET_TEMPLATE.format(threshold="p93")

    required_paths = [
        dataset_path,
        SCRIPTS_DIR / "create_benchmark_pages.py",
        SCRIPTS_DIR / "analyze_benchmark_results.py",
        LOADTESTS_DIR / "locust_round_robin_benchmark.py",
        LOADTESTS_DIR / "locust_neuroroute_cache_benchmark.py",
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {path}")

    return dataset_path


def locust_cmd(locust_file: str, users: int, spawn_rate: int) -> list[str]:
    return [
        LOCUST_BIN,
        "-f",
        f"loadtests/{locust_file}",
        "--host=http://localhost:8000",
        f"--users={users}",
        f"--spawn-rate={spawn_rate}",
        "--headless",
        "--loglevel=ERROR",
    ]


def run_benchmark_workflow(run_id: str, request: BenchmarkRequest) -> None:
    try:
        threshold = request.threshold
        users = request.users
        spawn_rate = request.spawn_rate
        total_count = request.total_count
        slow_ratio = request.slow_ratio
        mode = request.neuroroute_mode

        # Force p93 for cache mode
        if mode == "cache":
            threshold = "p93"

        # Derive naming suffix
        if mode == "cache":
            timestamp = run_id.split(f"benchmark_u{users}_{threshold}_cache_", 1)[1]
            benchmark_users = f"{users}_{threshold}_cache_{timestamp}"
        else:
            timestamp = run_id.split(f"benchmark_u{users}_{threshold}_", 1)[1]
            benchmark_users = f"{users}_{threshold}_{timestamp}"

        log(run_id, f"Mode: {mode} | Threshold: {threshold}")

        # Validate files
        set_status(run_id, "validating")
        kill_orphan_locust_processes(run_id)

        if mode == "cache":
            dataset_path = validate_required_files_cache()
        else:
            dataset_path, _ = validate_required_files_online(threshold)

        benchmark_csv = LOADTESTS_DIR / "benchmark_pages.csv"
        rr_results = RESULTS_DIR / f"round_robin_u{benchmark_users}_results.csv"
        nr_results = RESULTS_DIR / f"neuroroute_u{benchmark_users}_results.csv"
        report_dir = REPORTS_DIR / run_id

        RUNS[run_id]["report_dir"] = str(report_dir)
        RUNS[run_id]["rr_results"] = str(rr_results)
        RUNS[run_id]["nr_results"] = str(nr_results)

        log(run_id, "Pre-flight checks passed")

        # Generate benchmark pages
        set_status(run_id, "generating benchmark pages")
        run_cmd(
            run_id,
            [
                sys.executable,
                "scripts/create_benchmark_pages.py",
                "--dataset-path",
                str(dataset_path),
                "--total-count",
                str(total_count),
                "--slow-ratio",
                str(slow_ratio),
                "--output-path",
                str(benchmark_csv),
            ],
            "Generate benchmark pages",
        )

        expected_rows = count_csv_rows(benchmark_csv)
        if expected_rows <= 0:
            raise RuntimeError("No benchmark pages were generated")

        log(run_id, f"Benchmark pages generated: {expected_rows}")

        # Model switching (online mode only)
        if mode == "online":
            set_status(run_id, "switching model")
            run_cmd(
                run_id,
                [
                    sys.executable,
                    "scripts/set_active_model.py",
                    "--threshold",
                    threshold,
                ],
                "Set active model",
            )

            set_status(run_id, "restarting gateway")
            run_cmd(
                run_id,
                ["docker", "compose", "restart", "gateway"],
                "Restart gateway",
                timeout=60,
            )

            time.sleep(5)
            wait_for_gateway(run_id)
        else:
            set_status(run_id, "switching model")
            log(run_id, "Cache mode — skipping model switch")
            set_status(run_id, "restarting gateway")
            log(run_id, "Cache mode — skipping gateway restart")

            # Still verify gateway is up
            wait_for_gateway(run_id)

        # Round Robin benchmark
        set_status(run_id, "running round robin")
        run_locust(
            run_id,
            locust_cmd("locust_round_robin_benchmark.py", users, spawn_rate),
            "Round Robin benchmark",
            rr_results,
            expected_rows,
            env={"BENCHMARK_USERS": benchmark_users},
        )

        # NeuroRoute benchmark
        set_status(run_id, "running neuroroute")

        if mode == "cache":
            nr_locust_file = "locust_neuroroute_cache_benchmark.py"
        else:
            nr_locust_file = "locust_neuroroute_benchmark.py"

        run_locust(
            run_id,
            locust_cmd(nr_locust_file, users, spawn_rate),
            "NeuroRoute benchmark",
            nr_results,
            expected_rows,
            env={"BENCHMARK_USERS": benchmark_users},
        )

        # Analyze
        set_status(run_id, "analyzing")
        run_cmd(
            run_id,
            [
                sys.executable,
                "scripts/analyze_benchmark_results.py",
                "--round-robin",
                str(rr_results),
                "--neuroroute",
                str(nr_results),
                "--output-name",
                run_id,
            ],
            "Analyze results",
        )

        set_status(run_id, "completed")
        log(run_id, f"Report saved to: {report_dir}")

    except Exception as exc:
        RUNS[run_id]["status"] = "failed"
        RUNS[run_id]["error"] = str(exc)
        log(run_id, f"FAILED: {exc}")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/thresholds")
async def get_thresholds():
    return {"thresholds": list(VALID_THRESHOLDS)}


@app.post("/api/run-benchmark")
async def run_benchmark(request: BenchmarkRequest):
    for run_id, run in RUNS.items():
        if run["status"] not in ("completed", "failed"):
            raise HTTPException(
                status_code=409,
                detail=f"Benchmark '{run_id}' is already running",
            )

    # Force p93 for cache mode
    if request.neuroroute_mode == "cache":
        request.threshold = "p93"

    run_id = make_run_id(request.threshold, request.users, request.neuroroute_mode)

    RUNS[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "logs": [],
        "error": None,
        "config": request.model_dump(),
        "report_dir": None,
        "rr_results": None,
        "nr_results": None,
        "created_at": datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=run_benchmark_workflow,
        args=(run_id, request),
        daemon=True,
    )
    thread.start()

    return {"run_id": run_id, "status": "queued"}


@app.get("/api/benchmark-status/{run_id}")
async def benchmark_status(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    run = RUNS[run_id]

    return {
        "run_id": run_id,
        "status": run["status"],
        "logs": run["logs"],
        "error": run["error"],
        "config": run["config"],
    }


@app.get("/api/report-image/{run_id}")
async def report_image(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    run = RUNS[run_id]

    if run["status"] != "completed":
        raise HTTPException(status_code=404, detail="Benchmark not completed yet")

    image_path = Path(run["report_dir"]) / "latency_ranges_all_fast_slow.png"

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Chart image not found")

    return FileResponse(str(image_path), media_type="image/png")


@app.get("/api/report-summary/{run_id}")
async def report_summary(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    run = RUNS[run_id]

    if run["status"] != "completed":
        raise HTTPException(status_code=404, detail="Benchmark not completed yet")

    report_dir = Path(run["report_dir"])
    summary_csv_path = report_dir / "summary.csv"
    improvement_path = report_dir / "improvement_summary.txt"

    summary_table = None
    improvement_text = None

    if summary_csv_path.exists():
        with open(summary_csv_path, "r", encoding="utf-8") as handle:
            summary_table = list(csv.DictReader(handle))

    if improvement_path.exists():
        improvement_text = improvement_path.read_text(encoding="utf-8")

    return {
        "summary_table": summary_table,
        "improvement_text": improvement_text,
    }