# NeuroRoute — AI-Driven Predictive Load Balancer

## 1. Overview
NeuroRoute is a Dockerized AI-driven predictive load balancer designed for Wikipedia-style rendering workloads. 

**The Problem:** Traditional load balancers, such as Round Robin, do not understand the computational cost of an incoming request. When expensive, heavy requests are routed to the same worker processing lightweight, fast requests, the fast requests get stuck waiting behind the slow ones. This phenomenon is known as **Head-of-Line (HoL) blocking**.

**The Solution:** NeuroRoute solves this by predicting whether a page request will be "fast" (lightweight) or "slow" (computationally heavy) *before* routing it to a worker. It uses a trained Random Forest model that evaluates cheap, pre-render wikitext features. 
- Fast pages are isolated into a dedicated "fast worker pool".
- Slow pages are isolated into a dedicated "slow worker pool".

**Success Metric:** By preventing Head-of-Line blocking for lightweight requests, the primary success metric of NeuroRoute is the **tail latency improvement (p95 / p99) for fast pages**.

## 2. Final Result
Using an AI prediction pipeline at 25 Locust users, a spawn rate of 5, and 40% slow requests, the system demonstrates massive improvements for fast-page rendering compared to baseline Round Robin:

**Fast Pages (Cached Prediction):**
- Mean improvement: **97.40%**
- p50 improvement: **96.66%**
- p80 improvement: **98.16%**
- p90 improvement: **98.02%**
- p95 improvement: **97.86%**
- p99 improvement: **97.22%**

**Fast Pages (Online Inference):**
- Mean improvement: **83.58%**
- p50 improvement: **77.25%**
- p80 improvement: **91.40%**
- p90 improvement: **90.34%**
- p95 improvement: **85.78%**
- p99 improvement: **64.25%**

In another experiment conducted with **20% slow requests**:

**Online Inference Mode:**
- Fast-page p95 improvement: **66.06%**
- Fast-page p99 improvement: **68.21%**

**Cached Prediction Mode:**
- Fast-page p95 improvement: **93.79%**
- Fast-page p99 improvement: **96.11%**. 

**The Tradeoff:**
Isolating slow pages means they no longer benefit from sharing resources with fast requests, so slow pages become slower. As a result, the overall global p95/p99 latency can worsen if slow-page processing dominates the workload. Therefore, NeuroRoute is best framed as a **fast-tail-latency protection mechanism**, not a universal latency reduction tool.

## 3. Architecture

```text
Locust / Client
    ↓
Gateway FastAPI :8000
    ↓
PostgreSQL lookup
    ↓
Routing decision
    ├── Round Robin → worker_1/2/3/4
    └── NeuroRoute → model/cache prediction
              ├── fast → worker_1/2/3
              └── slow → worker_4
    ↓
Worker /process
    ↓
mwparserfromhell processing
    ↓
Response
```

**Docker Containers:**
- `postgres`: The relational database containing Wiki data and predictions.
- `gateway`: The entrypoint FastAPI server handling load balancing logic.
- `worker_1`, `worker_2`, `worker_3`: Fast lane workers.
- `worker_4`: Slow lane worker.

**Worker Pools:**
- **Round Robin:** Uses all workers (`worker_1`, `worker_2`, `worker_3`, `worker_4`).
- **NeuroRoute Fast Lane:** Uses only `worker_1`, `worker_2`, `worker_3`.
- **NeuroRoute Slow Lane:** Uses only `worker_4`.

## 4. Tech Stack
- **Python 3.11**
- **FastAPI** (Gateway and Worker APIs)
- **PostgreSQL** (Database)
- **Docker Compose** (Container Orchestration)
- **Locust** (Load Testing)
- **scikit-learn** (RandomForestClassifier for prediction)
- **joblib** (Model serialization)
- **mwparserfromhell** (MediaWiki syntax processing)
- **pandas / matplotlib** (Benchmark analysis and visualization)

## 5. Project Structure

```text
neuroroute/
├── gateway/
│   ├── Dockerfile
│   └── app/
│       ├── main.py
│       ├── router.py
│       ├── render_api.py
│       ├── model.py
│       ├── benchmark_api.py
│       └── static/
├── worker/
│   ├── Dockerfile
│   └── app/
│       └── main.py
├── renderer/
│   └── mwparser_renderer.py
├── postgres/
│   └── init/
├── scripts/
│   ├── create_benchmark_pages.py
│   ├── cache_model_predictions.py
│   ├── analyze_benchmark_results.py
│   ├── run_benchmark_workflow.py
│   └── ...
├── loadtests/
│   ├── benchmark_pages.csv
│   ├── locust_round_robin_benchmark.py
│   ├── locust_neuroroute_benchmark.py
│   ├── locust_neuroroute_cache_benchmark.py
│   └── results/
├── dataset/
│   ├── dataset50k_p80.csv
│   ├── dataset50k_p85.csv
│   ├── dataset50k_p90.csv
│   ├── dataset50k_p93.csv
│   └── dataset50k_p94.csv
├── models/
│   ├── cheap_neuroroute_random_forest50k_p80.joblib
│   ├── cheap_neuroroute_random_forest50k_p85.joblib
│   ├── cheap_neuroroute_random_forest50k_p90.joblib
│   ├── cheap_neuroroute_random_forest50k_p93.joblib
│   └── cheap_neuroroute_random_forest50k_p94.joblib
├── reports/
├── docker-compose.yml
├── .env
└── README.md
```
*(Note: Some filenames may differ slightly depending on your branch.)*

## 6. Docker Setup

The system is fully containerized using `docker-compose.yml`.

Example `.env` configuration:
```env
POSTGRES_DB=neuroroute
POSTGRES_USER=neuroroute_user
POSTGRES_PASSWORD=neuroroute_password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
NEUROROUTE_MODEL_PATH=/app/models/cheap_neuroroute_random_forest50k_p93.joblib

WORKER_ALL_URLS=http://worker_1:8001,http://worker_2:8002,http://worker_3:8003,http://worker_4:8004
WORKER_FAST_URLS=http://worker_1:8001,http://worker_2:8002,http://worker_3:8003
WORKER_SLOW_URLS=http://worker_4:8004
```

**Resource Limits:**
To accurately simulate processing bottlenecks locally, strict resource limits are enforced:
- `gateway`: 0.5 CPU, 512MB RAM
- `worker_1/2/3`: 0.5 CPU, 256MB RAM
- `worker_4`: 1 CPU, 512MB RAM
- `postgres`: 0.5 CPU, 512MB RAM

## 7. Running the System

**Build and Start:**
```bash
docker compose up --build -d
```

**Check Containers:**
```bash
docker compose ps
```

**View Logs:**
```bash
docker compose logs -f gateway
docker compose logs -f worker_1
```

**Check Health:**
```bash
curl http://localhost:8000/health
```

**Test Round Robin Endpoint:**
```bash
curl -X POST http://localhost:8000/route-round-robin/218
```

**Test NeuroRoute Online Inference Endpoint:**
```bash
curl -X POST http://localhost:8000/route-neuroroute/218
```

**Test NeuroRoute Cached Prediction Endpoint:**
```bash
curl -X POST http://localhost:8000/route-neuroroute-cached/218
```

## 8. API Endpoints

### `GET /health`
Gateway health check.

### `GET /render-page/{page_id}`
Data collection endpoint. Loads page from DB, runs the renderer, and updates render-derived feature columns. *Not used for the final routing benchmark.*

### `POST /route-round-robin/{page_id}`
Baseline load balancing endpoint. Loads the page from the DB and routes it sequentially across all workers.

### `POST /route-neuroroute/{page_id}`
Online inference endpoint. Loads the page and its cheap features from the DB, runs Random Forest model inference on the gateway, and routes to fast/slow worker pools.

### `POST /route-neuroroute-cached/{page_id}`
Cached prediction endpoint. Loads the page and its pre-calculated `predicted_slow` status from the DB. Skips the model inference step entirely to optimize gateway latency.

### `POST /process` (Worker API)
The actual rendering endpoint running on each worker container. Receives `page_id`, `title`, and `raw_wikitext`. Runs `mwparserfromhell` processing and returns a summarized JSON.

## 9. Database Schema

### `wiki_pages`
Stores the core page data: `page_id`, `title`, `revision_id`, `revision_timestamp`, and `raw_wikitext`.

### `wiki_page_features`
Stores cheap and render-derived features.

**Cheap features (used by final model):**
- `wikitext_length_bytes`
- `template_count`
- `image_count`
- `reference_count`
- `heading_count`
- `internal_link_count`
- `external_link_count`
- `category_count`

**Render-derived features (for offline analysis only):**
- `table_tag_count`
- `paragraph_tag_count`
- `rendered_html_length_bytes`
- `render_expansion_ratio`
- `html_tag_count`

### `wiki_page_labels`
Ground-truth labels: `avg_response_time` and `is_slow`.
*Note: This table is used for training and evaluation only. Do not use it directly for routing.*

### `wiki_page_predictions`
Cached model predictions to bypass online inference.
```sql
CREATE TABLE IF NOT EXISTS wiki_page_predictions (
    page_id BIGINT PRIMARY KEY REFERENCES wiki_pages(page_id),
    predicted_slow SMALLINT CHECK (predicted_slow IN (0, 1)),
    model_name TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wiki_page_predictions_predicted_slow
ON wiki_page_predictions(predicted_slow);
```

## 10. Dataset Creation Pipeline

1. Parse the SimpleWiki XML dump.
2. Skip redirects, non-article namespaces, and empty/tiny pages.
3. Sample articles intelligently to create a representative dataset.

**Example distribution for a 50k dataset:**
- target_count: 50000
- random_count: 30000
- largest_count: 10000
- template_heavy_count: 5000
- complex_count: 5000

```bash
python scripts/parse_simplewiki.py \
  --xml-path /path/to/simplewiki.xml \
  --target-count 50000 \
  --random-count 30000 \
  --largest-count 10000 \
  --template-heavy-count 5000 \
  --complex-count 5000 \
  --batch-size 1000
```

## 11. Label Creation

Ground truth labels are generated by having Locust sequentially render pages through the gateway.
- Use the gateway only (`--host=http://localhost:8000`). Do not call workers directly.
- The mean response time across sequential runs (e.g., 2 or 3 runs per page) is saved as `avg_response_time`.
- `is_slow` is determined dynamically based on threshold experiments (e.g., p80, p85, p90, p93, p94). For the final 50k experiment, the p93 threshold proved highly effective.

**Export page IDs:**
```bash
python scripts/export_page_ids.py
```

**Run sequential labeling:**
```bash
locust -f loadtests/mw_locust_sequential_labeling.py \
  --host=http://localhost:8000 \
  --users=1 \
  --spawn-rate=1 \
  --headless
```

**Import timings and set threshold:**
```bash
python scripts/mw_import_locust_timings.py
```

## 12. Training Models

The final routing model **must only use cheap pre-render features**. Do not train the final model on `page_id`, `avg_response_time`, or any render-derived features.

```bash
# Example generic training command
python ml/cheap_train_random_forest50k.py \
  --dataset dataset/dataset50k_p93.csv \
  --model-output models/cheap_neuroroute_random_forest50k_p93.joblib
```

**Model configuration:**
- `RandomForestClassifier`
- `n_estimators=300`
- `class_weight=balanced`
- `random_state=42`
- `n_jobs=-1`

## 13. Cached Prediction

While online inference works, running the ML model on the gateway for every request adds overhead. Cached prediction solves this by shifting inference out of the critical request path.

**Populate prediction cache:**
```bash
NEUROROUTE_MODEL_PATH=models/cheap_neuroroute_random_forest50k_p93.joblib \
NEUROROUTE_MODEL_NAME=cheap_random_forest50k_p93 \
python scripts/cache_model_predictions.py
```

**Verify caching:**
```bash
docker exec -it neuroroute_postgres psql -U neuroroute_user -d neuroroute

SELECT COUNT(*) FROM wiki_page_predictions;

SELECT predicted_slow, COUNT(*)
FROM wiki_page_predictions
GROUP BY predicted_slow
ORDER BY predicted_slow;
```

## 14. Benchmarking

Benchmarks rely on a fixed `loadtests/benchmark_pages.csv`. The `is_slow` field in this file is strictly for offline analysis and grouping; it is never sent to the routing endpoints.

**Generate benchmark pages:**
```bash
python scripts/create_benchmark_pages.py \
  --dataset-path dataset/dataset50k_p93.csv \
  --total-count 1000 \
  --slow-ratio 0.20 \
  --output-path loadtests/benchmark_pages.csv
```

**Run Round Robin:**
```bash
BENCHMARK_USERS=10_p93 locust \
  -f loadtests/locust_round_robin_benchmark.py \
  --host=http://localhost:8000 \
  --users=10 \
  --spawn-rate=2 \
  --headless
```

**Run NeuroRoute (Cached):**
```bash
BENCHMARK_USERS=10_p93_cache locust \
  -f loadtests/locust_neuroroute_cache_benchmark.py \
  --host=http://localhost:8000 \
  --users=10 \
  --spawn-rate=2 \
  --headless
```

**Analyze Cache Benchmark Results:**
```bash
python scripts/analyze_benchmark_results.py \
  --round-robin loadtests/results/round_robin_u10_p93_cache_results.csv \
  --neuroroute loadtests/results/neuroroute_u10_p93_cache_results.csv \
  --output-name benchmark_u10_p93_cache
```

## 15. Benchmark UI

A local orchestration UI is available at `http://localhost:8000/benchmark-ui` (or `http://localhost:9090` depending on the port configuration). 

It allows you to graphically configure:
- Threshold selection
- Locust users & spawn rate
- Total request count & slow ratio
- **NeuroRoute mode:**
  - `Online inference` (uses `/route-neuroroute/{page_id}` and dynamic thresholds)
  - `Cached prediction` (locked to p93 threshold, uses `/route-neuroroute-cached/{page_id}`)

## 16. Analysis Output

The analyzer script generates three key outputs in `reports/{output_name}/`:
- `summary.csv`: Aggregated metrics (mean, p50, p80, p90, p95, p99) grouped by `all`, `fast`, and `slow` requests.
- `improvement_summary.txt`: A human-readable text file highlighting key percentiles.
- `latency_ranges_all_fast_slow.png`: A comprehensive boxplot/range chart comparing RR vs. NR.

**Improvement formula:**
```text
((round_robin_latency - neuroroute_latency) / round_robin_latency) * 100
```

## 17. Recommended Benchmark Settings

- **Smoke test:** `users=1`, `spawn-rate=1`
- **Main benchmark:** `users=10`, `spawn-rate=2`
- **Stress test:** `users=25`, `spawn-rate=5` up to `users=50`, `spawn-rate=10`

*Stop increasing concurrency if Locust starts reporting timeouts or connection failures.*

## 18. Viewing Database

You can inspect the database using DBeaver or PGAdmin with the following credentials:
- **Host:** localhost
- **Port:** 5432
- **Database:** neuroroute
- **Username:** neuroroute_user
- **Password:** neuroroute_password

## 19. Common Problems and Fixes

- **Gateway cannot load model:** Check if the joblib file exists inside the Docker container, ensure `NEUROROUTE_MODEL_PATH` is correct, and verify that `scikit-learn` versions match.
- **Route returns 404 features not found:** Ensure `wiki_page_features` is populated for the requested `page_id`.
- **Cached endpoint returns 404:** Ensure `wiki_page_predictions` is populated. Run the caching script.
- **Locust CSV has fewer than expected lines:** Locust may have shut down prematurely. Ensure `_BENCHMARK_TOTAL` logic is intact and rerun.
- **Workers timeout:** The slow lane may be overloaded, resource limits in `docker-compose.yml` might be too strict, or Locust concurrency is too high.
- **Results inconsistent:** Always ensure the same `benchmark_pages.csv` is used for both Round Robin and NeuroRoute. Do not run heavy applications on your host machine while benchmarking.

## 20. What Not To Do

- **DO NOT** use `wiki_page_labels.is_slow` for routing in the API.
- **DO NOT** send `is_slow` as a parameter to the gateway endpoints.
- **DO NOT** execute rendering in the gateway before routing the request.
- **DO NOT** train the final model on render-derived features.
- **DO NOT** compare Round Robin and NeuroRoute using different lists of pages.
- **DO NOT** call worker container ports directly during load tests.
- **DO NOT** mix p90 benchmark pages with a p94 model.

## 21. Future Work

- Adaptive fast/slow worker allocation based on real-time load.
- Testing a 2-fast / 2-slow worker pool distribution.
- Replacing binary classification with continuous latency regression.
- Implementing queue-depth-aware routing.
- Confidence-based routing (e.g., probability > 0.8 routes to slow lane).
- Moving the prediction cache to Redis.
- Adding Prometheus & Grafana for live observability.
- Kubernetes deployment.
- Testing on the full English Wikipedia dataset.
- Integrating a real MediaWiki/Parsoid renderer instead of `mwparserfromhell`.

## 22. Final Project Interpretation

NeuroRoute is considered successful if it significantly reduces fast-page tail latency under mixed workloads. It is not designed to reduce slow-page latency, and it may not reduce global overall latency if slow pages dominate the tail. The primary success indicator remains the protective **fast-page p95/p99 latency improvement**.
