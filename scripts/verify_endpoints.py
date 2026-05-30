import argparse
import os
import sys
import httpx
import psycopg2

GATEWAY_DEFAULT = "http://localhost:8000"
WORKER_PORTS = [8001, 8002, 8003, 8004]
SLOW_WORKERS = ["worker_3", "worker_4"]
FAST_WORKERS = ["worker_1", "worker_2"]

SAMPLE_PROCESS_BODY = {
    "page_id": 1,
    "title": "Endpoint Test",
    "raw_wikitext": "== Test == This is a [[test]] with {{Template}} and <ref>source</ref>."
}

def get_page_id_from_db():
    try:
        conn = psycopg2.connect(
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"]
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT wp.page_id
                FROM wiki_pages wp
                JOIN wiki_page_features wpf ON wp.page_id = wpf.page_id
                LIMIT 1;
            """)
            row = cur.fetchone()
            if row:
                return row[0]
    except Exception as e:
        print(f"[DB ERROR] {e}")
    finally:
        if 'conn' in locals():
            conn.close()
    print("[FAIL] Could not fetch a valid page_id from DB.")
    sys.exit(1)

def print_fail(msg, resp=None):
    print(f"[FAIL] {msg}")
    if resp is not None:
        print(f"Status: {resp.status_code}")
        try:
            print(f"Body: {resp.json()}")
        except Exception:
            print(f"Body: {resp.text}")
    sys.exit(1)

def print_pass(msg):
    print(f"[PASS] {msg}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-url", default=GATEWAY_DEFAULT)
    parser.add_argument("--page-id", type=int)
    args = parser.parse_args()

    gateway_url = args.gateway_url.rstrip("/")
    page_id = args.page_id

    if not page_id:
        page_id = get_page_id_from_db()
        print(f"Using page_id: {page_id}")

    # Test gateway health
    with httpx.Client(timeout=10) as client:
        r = client.get(f"{gateway_url}/health")
        if r.status_code == 200:
            print_pass("Gateway /health")
        else:
            print_fail("Gateway /health", r)

        # Test render endpoint
        r = client.get(f"{gateway_url}/render-page/{page_id}")
        if r.status_code == 200:
            j = r.json()
            if (
                j.get("page_id") == page_id and
                "rendered_html_length_bytes" in j and
                "html_tag_count" in j
            ):
                print_pass("Gateway /render-page/{page_id}")
            else:
                print_fail("Gateway /render-page/{page_id} response missing fields", r)
        else:
            print_fail("Gateway /render-page/{page_id}", r)

        # Test round robin
        r = client.post(f"{gateway_url}/route-round-robin/{page_id}")
        if r.status_code == 200:
            j = r.json()
            if (
                j.get("routing_mode") == "round_robin" and
                j.get("selected_worker") and
                j.get("worker_response") and
                j["worker_response"].get("status") == "processed"
            ):
                print_pass("Gateway /route-round-robin/{page_id}")
            else:
                print_fail("Gateway /route-round-robin/{page_id} response missing fields", r)
        else:
            print_fail("Gateway /route-round-robin/{page_id}", r)

        # Test neuroroute
        r = client.post(f"{gateway_url}/route-neuroroute/{page_id}")
        if r.status_code == 200:
            j = r.json()
            if (
                j.get("routing_mode") == "neuroroute" and
                "prediction" in j and
                "predicted_slow" in j and
                j.get("selected_worker") and
                j.get("worker_response") and
                j["worker_response"].get("status") == "processed"
            ):
                pred_slow = j["predicted_slow"]
                sel_worker = j["selected_worker"]
                # Extract worker name from URL if needed
                if sel_worker.startswith("http"):
                    sel_worker_name = sel_worker.rstrip("/").split(":")[-2].split("/")[-1]
                else:
                    sel_worker_name = sel_worker
                if pred_slow == 1 and sel_worker_name not in SLOW_WORKERS:
                    print_fail(f"NeuroRoute predicted_slow=1 but selected_worker={sel_worker} not in SLOW_WORKERS", r)
                if pred_slow == 0 and sel_worker_name not in FAST_WORKERS:
                    print_fail(f"NeuroRoute predicted_slow=0 but selected_worker={sel_worker} not in FAST_WORKERS", r)
                print_pass("Gateway /route-neuroroute/{page_id}")
            else:
                print_fail("Gateway /route-neuroroute/{page_id} response missing fields", r)
        else:
            print_fail("Gateway /route-neuroroute/{page_id}", r)

    # Test workers
    for i, port in enumerate(WORKER_PORTS, 1):
        worker_url = f"http://localhost:{port}"
        # Health
        try:
            r = httpx.get(f"{worker_url}/health", timeout=10)
            if r.status_code == 200:
                print_pass(f"Worker {i} /health")
            else:
                print_fail(f"Worker {i} /health", r)
        except Exception as e:
            print_fail(f"Worker {i} /health exception: {e}")
        # Process
        try:
            r = httpx.post(f"{worker_url}/process", json=SAMPLE_PROCESS_BODY, timeout=15)
            if r.status_code == 200:
                j = r.json()
                if (
                    "worker" in j and
                    "lane" in j and
                    j.get("status") == "processed" and
                    "rendered_html_length_bytes" in j and
                    "html_tag_count" in j and
                    "checksum" in j
                ):
                    print_pass(f"Worker {i} /process")
                else:
                    print_fail(f"Worker {i} /process response missing fields", r)
            else:
                print_fail(f"Worker {i} /process", r)
        except Exception as e:
            print_fail(f"Worker {i} /process exception: {e}")

    print("\nAll endpoint checks passed.")

if __name__ == "__main__":
    main()
