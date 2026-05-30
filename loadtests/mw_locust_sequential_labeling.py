import csv
import os
import time
from typing import List

from locust import HttpUser, task, events
from locust.exception import StopUser


PAGE_IDS_PATH = os.path.join("loadtests", "page_ids.csv")
RESULTS_PATH = os.path.join("loadtests", "results", "mw_sequential_response_times_50k.csv")
RUNS_PER_PAGE = 3

page_ids: List[int] = []
results_writer = None
results_handle = None


# Run with:
# locust -f loadtests/mw_locust_sequential_labeling.py \
#   --host=http://localhost:8000 \
#   --users=1 \
#   --spawn-rate=1 \
#   --headless


def load_page_ids() -> List[int]:
    if not os.path.exists(PAGE_IDS_PATH):
        raise FileNotFoundError(f"page_ids.csv not found at {PAGE_IDS_PATH}")

    with open(PAGE_IDS_PATH, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [int(row["page_id"]) for row in reader if row.get("page_id")]


def ensure_results_writer() -> None:
    global results_writer
    global results_handle

    if results_writer is not None:
        return

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    results_handle = open(RESULTS_PATH, "w", newline="", encoding="utf-8")

    results_writer = csv.writer(results_handle)
    results_writer.writerow(
        ["page_id", "run_number", "response_time_ms", "status_code", "success", "error"]
    )

    results_handle.flush()


def close_results_writer() -> None:
    global results_writer
    global results_handle

    if results_handle is not None:
        results_handle.flush()
        results_handle.close()

    results_writer = None
    results_handle = None


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global page_ids

    page_ids = load_page_ids()
    ensure_results_writer()

    print(f"Loaded {len(page_ids)} page IDs")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    close_results_writer()
    print("Locust test stopped. Results file closed.")


class SequentialRendererUser(HttpUser):
    wait_time = lambda self: 0

    def on_start(self):
        self.page_index = 0
        self.run_number = 0

    def stop_test(self):
        runner = self.environment.runner
        if runner is not None:
            runner.quit()
        raise StopUser()

    @task
    def render_page(self):
        global page_ids
        global results_writer
        global results_handle

        if not page_ids:
            print("No page IDs found. Stopping test.")
            self.stop_test()

        if self.page_index >= len(page_ids):
            self.stop_test()

        page_id = page_ids[self.page_index]
        self.run_number += 1

        start = time.perf_counter()

        try:
            response = self.client.get(f"/render-page/{page_id}")
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

            status_code = response.status_code
            success = status_code == 200
            error_text = "" if success else response.text

        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

            status_code = 0
            success = False
            error_text = str(exc)

        ensure_results_writer()

        results_writer.writerow(
            [
                page_id,
                self.run_number,
                elapsed_ms,
                status_code,
                int(success),
                error_text,
            ]
        )

        if results_handle is not None:
            results_handle.flush()

        if self.run_number >= RUNS_PER_PAGE:
            self.page_index += 1
            self.run_number = 0

        if self.page_index >= len(page_ids):
            print("Finished all page IDs. Stopping Locust run.")
            self.stop_test()