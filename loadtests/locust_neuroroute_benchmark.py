import csv
import os
from typing import Dict, List, Optional

from gevent.lock import Semaphore
from locust import HttpUser, constant, events, task


_BENCHMARK_ROWS: Optional[List[Dict[str, str]]] = None
_BENCHMARK_INDEX = 0
_BENCHMARK_TOTAL = 0
_BENCHMARK_COMPLETED = 0
_BENCHMARK_LOCK = Semaphore()

_RESULTS_FILE = None
_RESULTS_WRITER = None
_RESULTS_INITIALIZED = False
_RESULTS_LOCK = Semaphore()

USERS = os.getenv("BENCHMARK_USERS", "unknown")

RESULTS_PATH = os.path.join(
    "loadtests",
    "results",
    f"neuroroute_u{USERS}_results.csv",
)


def _load_benchmark_rows() -> List[Dict[str, str]]:
    global _BENCHMARK_ROWS, _BENCHMARK_TOTAL

    if _BENCHMARK_ROWS is not None:
        return _BENCHMARK_ROWS

    input_path = os.path.join("loadtests", "benchmark_pages.csv")
    with open(input_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        _BENCHMARK_ROWS = list(reader)
        _BENCHMARK_TOTAL = len(_BENCHMARK_ROWS)

    return _BENCHMARK_ROWS


def _get_next_row() -> Optional[Dict[str, str]]:
    global _BENCHMARK_INDEX

    with _BENCHMARK_LOCK:
        rows = _load_benchmark_rows()
        if _BENCHMARK_INDEX >= len(rows):
            return None
        row = rows[_BENCHMARK_INDEX]
        _BENCHMARK_INDEX += 1
        return row


def _mark_completed_and_maybe_quit(environment) -> None:
    global _BENCHMARK_COMPLETED

    with _BENCHMARK_LOCK:
        _BENCHMARK_COMPLETED += 1
        if _BENCHMARK_TOTAL and _BENCHMARK_COMPLETED >= _BENCHMARK_TOTAL:
            if environment.runner:
                environment.runner.quit()


def _ensure_results_writer() -> None:
    global _RESULTS_FILE, _RESULTS_WRITER, _RESULTS_INITIALIZED

    with _RESULTS_LOCK:
        if _RESULTS_INITIALIZED:
            return

        os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
        _RESULTS_FILE = open(RESULTS_PATH, "w", newline="", encoding="utf-8")
        _RESULTS_WRITER = csv.DictWriter(
            _RESULTS_FILE,
            fieldnames=[
                "page_id",
                "is_slow",
                "routing_mode",
                "response_time_ms",
                "status_code",
                "success",
                "error",
            ],
        )
        _RESULTS_WRITER.writeheader()
        _RESULTS_INITIALIZED = True


def _write_result(result: Dict[str, object]) -> None:
    _ensure_results_writer()

    with _RESULTS_LOCK:
        _RESULTS_WRITER.writerow(result)
        _RESULTS_FILE.flush()


def _get_response_time_ms(response) -> float:
    meta = getattr(response, "request_meta", None) or {}
    if "response_time" in meta:
        return float(meta["response_time"])
    if getattr(response, "elapsed", None):
        return float(response.elapsed.total_seconds() * 1000)
    return 0.0


@events.test_stop.add_listener
def _close_results_file(environment, **kwargs) -> None:
    if _RESULTS_FILE is not None:
        _RESULTS_FILE.close()


class NeuroRouteBenchmarkUser(HttpUser):
    wait_time = constant(0)

    @task
    def run_benchmark(self) -> None:
        row = _get_next_row()
        if row is None:
            return

        page_id = int(row["page_id"])
        is_slow = int(row["is_slow"])

        response = self.client.post(f"/route-neuroroute/{page_id}")
        response_time_ms = _get_response_time_ms(response)

        success = response.ok
        error = "" if success else response.text

        _write_result(
            {
                "page_id": page_id,
                "is_slow": is_slow,
                "routing_mode": "neuroroute",
                "response_time_ms": f"{response_time_ms:.2f}",
                "status_code": response.status_code,
                "success": "true" if success else "false",
                "error": error,
            }
        )
        _mark_completed_and_maybe_quit(self.environment)