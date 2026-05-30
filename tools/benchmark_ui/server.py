"""NeuroRoute Benchmark UI Server.

A FastAPI application that orchestrates the full benchmark workflow:
generate pages → switch model → restart gateway → run Locust benchmarks → analyze results.

Start with:
    uvicorn tools.benchmark_ui.server:app --host 0.0.0.0 --port 9000
"""

import csv
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_THRESHOLDS = ("p80", "p85", "p90", "p93", "p94")

MODEL_TEMPLATE = "neuroroute_random_forest50k_{threshold}.joblib"
DATASET_TEMPLATE = "dataset50k_{threshold}.csv"

# ---------------------------------------------------------------------------
# In-memory run store
# ---------------------------------------------------------------------------

RUNS: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    threshold: str
    users: int = Field(default=10, gt=0)
    spawn_rate: int = Field(default=2, gt=0)
    total_count: int = Field(default=1000, gt=0)
    slow_ratio: float = Field(default=0.20, gt=0.0, lt=1.0)

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: str) -> str:
        if v not in VALID_THRESHOLDS:
            raise ValueError(f"threshold must be one of {VALID_THRESHOLDS}")
        return v


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NeuroRoute Benchmark UI",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_id(threshold: str, users: int) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"benchmark_u{users}_{threshold}_{ts}"


def _log(run_id: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"
    RUNS[run_id]["logs"].append(entry)


def _set_status(run_id: str, status: str) -> None:
    RUNS[run_id]["status"] = status
    _log(run_id, f"Status → {status}")


def _run_cmd(
    run_id: str,
    cmd: list[str],
    label: str,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Run a shell command, stream output into run logs."""
    import os

    full_env = {**os.environ, **(env or {})}

    _log(run_id, f"$ {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
    )

    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            _log(run_id, f"  {line}")

    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            _log(run_id, f"  [stderr] {line}")

    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {result.returncode})")

    return result


def _wait_for_gateway(run_id: str, retries: int = 15, delay: float = 2.0) -> None:
    """Poll gateway health endpoint until it responds."""
    import urllib.request
    import urllib.error

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request("http://localhost:8000/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    _log(run_id, f"  Gateway healthy (attempt {attempt})")
                    return
        except (urllib.error.URLError, OSError):
            pass
        _log(run_id, f"  Waiting for gateway... (attempt {attempt}/{retries})")
        time.sleep(delay)

    raise RuntimeError("Gateway did not become healthy after restart")


def _count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file (excludes header)."""
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)  # subtract header
    except OSError:
        return 0


def _run_locust(
    run_id: str,
    cmd: list[str],
    label: str,
    results_path: Path,
    expected_rows: int,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
    poll_interval: float = 3.0,
) -> None:
    """Run Locust via Popen and monitor the CSV for completion.

    Locust's runner.quit() in headless mode sometimes doesn't exit
    the process cleanly.  This monitors the results CSV and terminates
    the process once all expected rows have been written.
    """
    import os
    import signal

    full_env = {**os.environ, **(env or {})}
    _log(run_id, f"$ {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=full_env,
    )

    deadline = time.monotonic() + timeout
    last_logged_count = 0

    try:
        while time.monotonic() < deadline:
            # Check if process exited on its own
            retcode = proc.poll()
            if retcode is not None:
                break

            # Check CSV progress
            row_count = _count_csv_rows(results_path)
            if row_count != last_logged_count and row_count > 0:
                _log(run_id, f"  Progress: {row_count}/{expected_rows} requests")
                last_logged_count = row_count

            if row_count >= expected_rows:
                _log(run_id, f"  All {expected_rows} requests completed")
                # Give Locust a moment to flush and close
                time.sleep(2)
                # Terminate gracefully
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                break

            time.sleep(poll_interval)
        else:
            # Timeout reached
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"{label} timed out after {timeout}s")

    except Exception:
        # Ensure cleanup
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raise

    # Capture remaining output
    stdout, stderr = proc.communicate(timeout=5) if proc.poll() is not None else ("", "")
    if stdout and stdout.strip():
        for line in stdout.strip().splitlines()[-20:]:
            _log(run_id, f"  {line}")
    if stderr and stderr.strip():
        for line in stderr.strip().splitlines()[-10:]:
            _log(run_id, f"  [stderr] {line}")

    # A negative return code from terminate/kill is expected and OK
    final_rows = _count_csv_rows(results_path)
    if final_rows < expected_rows:
        raise RuntimeError(
            f"{label}: expected {expected_rows} rows but got {final_rows}"
        )


# ---------------------------------------------------------------------------
# Benchmark workflow (runs in background thread)
# ---------------------------------------------------------------------------


def _run_benchmark_workflow(run_id: str, req: BenchmarkRequest) -> None:
    try:
        threshold = req.threshold
        users = req.users
        spawn_rate = req.spawn_rate
        total_count = req.total_count
        slow_ratio = req.slow_ratio

        # Derive paths
        ts_suffix = run_id.split(f"benchmark_u{users}_{threshold}_")[1]
        benchmark_users_env = f"{users}_{threshold}_{ts_suffix}"

        dataset_path = DATASET_DIR / DATASET_TEMPLATE.format(threshold=threshold)
        model_path = MODELS_DIR / MODEL_TEMPLATE.format(threshold=threshold)
        benchmark_csv = LOADTESTS_DIR / "benchmark_pages.csv"

        rr_results = RESULTS_DIR / f"round_robin_u{benchmark_users_env}_results.csv"
        nr_results = RESULTS_DIR / f"neuroroute_u{benchmark_users_env}_results.csv"
        report_dir = REPORTS_DIR / run_id

        # Store paths in run for later retrieval
        RUNS[run_id]["report_dir"] = str(report_dir)
        RUNS[run_id]["rr_results"] = str(rr_results)
        RUNS[run_id]["nr_results"] = str(nr_results)

        # ── Pre-flight checks ────────────────────────────────────
        _set_status(run_id, "validating")

        # Kill any orphan locust benchmark processes from previous runs
        try:
            import os as _os
            result = subprocess.run(
                ["pkill", "-f", "locust.*locust_(round_robin|neuroroute)_benchmark"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                _log(run_id, "Killed orphan locust processes")
                time.sleep(1)
        except Exception:
            pass  # pkill not found or no matching processes

        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dataset_path}")
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        for script_name in [
            "create_benchmark_pages.py",
            "set_active_model.py",
            "analyze_benchmark_results.py",
        ]:
            if not (SCRIPTS_DIR / script_name).exists():
                raise FileNotFoundError(f"Script not found: scripts/{script_name}")

        for locust_file in [
            "locust_round_robin_benchmark.py",
            "locust_neuroroute_benchmark.py",
        ]:
            if not (LOADTESTS_DIR / locust_file).exists():
                raise FileNotFoundError(f"Locust file not found: loadtests/{locust_file}")

        _log(run_id, "Pre-flight checks passed")

        # ── Step 1: Generate benchmark pages ─────────────────────
        _set_status(run_id, "generating benchmark pages")

        _run_cmd(run_id, [
            sys.executable, "scripts/create_benchmark_pages.py",
            "--dataset-path", str(dataset_path),
            "--total-count", str(total_count),
            "--slow-ratio", str(slow_ratio),
            "--output-path", str(benchmark_csv),
        ], "Generate benchmark pages")

        # ── Step 2: Set active model ─────────────────────────────
        _set_status(run_id, "switching model")

        _run_cmd(run_id, [
            sys.executable, "scripts/set_active_model.py",
            "--threshold", threshold,
        ], "Set active model")

        # ── Step 3: Restart gateway ──────────────────────────────
        _set_status(run_id, "restarting gateway")

        _run_cmd(run_id, [
            "docker", "compose", "restart", "gateway",
        ], "Restart gateway", timeout=60)

        _log(run_id, "Waiting for gateway to become healthy...")
        time.sleep(5)
        _wait_for_gateway(run_id)

        # ── Step 4: Round Robin Locust ───────────────────────────
        _set_status(run_id, "running round robin")

        _run_locust(
            run_id,
            [
                LOCUST_BIN,
                "-f", "loadtests/locust_round_robin_benchmark.py",
                f"--host=http://localhost:8000",
                f"--users={users}",
                f"--spawn-rate={spawn_rate}",
                "--headless",
            ],
            "Round Robin benchmark",
            results_path=rr_results,
            expected_rows=total_count,
            env={"BENCHMARK_USERS": benchmark_users_env},
            timeout=1800,
        )

        if not rr_results.exists():
            raise FileNotFoundError(f"Round Robin results not created: {rr_results}")
        _log(run_id, f"Round Robin results: {rr_results.name}")

        # ── Step 5: NeuroRoute Locust ────────────────────────────
        _set_status(run_id, "running neuroroute")

        _run_locust(
            run_id,
            [
                LOCUST_BIN,
                "-f", "loadtests/locust_neuroroute_benchmark.py",
                f"--host=http://localhost:8000",
                f"--users={users}",
                f"--spawn-rate={spawn_rate}",
                "--headless",
            ],
            "NeuroRoute benchmark",
            results_path=nr_results,
            expected_rows=total_count,
            env={"BENCHMARK_USERS": benchmark_users_env},
            timeout=1800,
        )

        if not nr_results.exists():
            raise FileNotFoundError(f"NeuroRoute results not created: {nr_results}")
        _log(run_id, f"NeuroRoute results: {nr_results.name}")

        # ── Step 6: Analyze ──────────────────────────────────────
        _set_status(run_id, "analyzing")

        _run_cmd(run_id, [
            sys.executable, "scripts/analyze_benchmark_results.py",
            "--round-robin", str(rr_results),
            "--neuroroute", str(nr_results),
            "--output-name", run_id,
        ], "Analyze results")

        # ── Done ─────────────────────────────────────────────────
        _set_status(run_id, "completed")
        _log(run_id, f"Report saved to: {report_dir}")

    except Exception as exc:
        RUNS[run_id]["status"] = "failed"
        RUNS[run_id]["error"] = str(exc)
        _log(run_id, f"FAILED: {exc}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/api/thresholds")
async def get_thresholds():
    return {"thresholds": list(VALID_THRESHOLDS)}


@app.post("/api/run-benchmark")
async def run_benchmark(req: BenchmarkRequest):
    # Check if any benchmark is currently running
    for rid, run in RUNS.items():
        if run["status"] not in ("completed", "failed"):
            raise HTTPException(
                status_code=409,
                detail=f"Benchmark '{rid}' is already running. Wait for it to finish.",
            )

    run_id = _make_run_id(req.threshold, req.users)

    RUNS[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "logs": [],
        "error": None,
        "config": req.model_dump(),
        "report_dir": None,
        "rr_results": None,
        "nr_results": None,
        "created_at": datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=_run_benchmark_workflow,
        args=(run_id, req),
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

    report_dir = Path(run["report_dir"])
    image_path = report_dir / "latency_ranges_all_fast_slow.png"

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

    result: dict[str, Any] = {
        "summary_table": None,
        "improvement_text": None,
    }

    # Parse summary.csv
    if summary_csv_path.exists():
        rows = []
        with open(summary_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        result["summary_table"] = rows

    # Read improvement text
    if improvement_path.exists():
        result["improvement_text"] = improvement_path.read_text(encoding="utf-8")

    return result
