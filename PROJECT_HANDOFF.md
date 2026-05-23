# Project Handoff: NeuroRoute — AI-Driven Predictive Load Balancer

## 1. Executive Summary

NeuroRoute is a Dockerized AI-driven predictive load balancer for Wikipedia-style workloads. It predicts whether a page request is fast or slow using a trained Random Forest model based on cheap pre-render wikitext features, then routes predicted-fast pages to a fast worker pool and predicted-slow pages to a slow worker pool. The system exists to reduce Head-of-Line (HoL) blocking for lightweight requests by isolating heavy pages.

Main result and tradeoff (10 concurrent Locust users, cached AI predictions):
- Fast-page mean latency improved from 267.95 ms to 35.06 ms.
- Fast-page p95 improved from 1301.84 ms to 115.40 ms.
- Fast-page p99 improved from 2203.45 ms to 258.41 ms.
- Fast-page p95 improvement: 91.14%.
- Fast-page p99 improvement: 88.27%.
- Tradeoff: slow-page latency increases because heavy requests are concentrated in the slow lane.

## 2. Architecture Overview

Final architecture:

Client / Locust
→ Gateway FastAPI container
→ PostgreSQL lookup
→ cached AI prediction lookup
→ routing decision
→ worker container
→ mwparserfromhell processing
→ response

Containers:
- gateway
- worker_1
- worker_2
- worker_3
- worker_4
- postgres
- optional pgAdmin/DBeaver for viewing DB

Worker pools:
- Round Robin baseline uses all workers.
- NeuroRoute uses:
  - FAST_WORKERS = worker_1, worker_2, worker_3
  - SLOW_WORKERS = worker_4

Optional future experiment:
- 2 fast workers + 2 slow workers for better slow-page fairness.

## 3. Docker Setup

Purpose:
- docker-compose.yml defines the full stack: gateway, workers, and postgres.

Ports:
- Gateway: 8000
- Workers: 8001–8004
- Postgres: 5432

Resource limits:
- CPU/RAM limits are defined in docker-compose.yml for consistent, repeatable benchmarking.

Required environment variables:
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- POSTGRES_HOST
- POSTGRES_PORT
- WORKER_ALL_URLS
- WORKER_FAST_URLS
- WORKER_SLOW_URLS
- NEUROROUTE_MODEL_PATH

Example environment values:

POSTGRES_DB=neuroroute
POSTGRES_USER=neuroroute_user
POSTGRES_PASSWORD=neuroroute_password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

Gateway worker URL envs:

WORKER_ALL_URLS=http://worker_1:8001,http://worker_2:8002,http://worker_3:8003,http://worker_4:8004
WORKER_FAST_URLS=http://worker_1:8001,http://worker_2:8002,http://worker_3:8003
WORKER_SLOW_URLS=http://worker_4:8004

## 4. Database Schema

Tables:

wiki_pages:
- Stores raw page data.

wiki_page_features:
- Stores cheap raw wikitext features.
- Stores render-derived features from the renderer.

wiki_page_labels:
- Stores ground-truth timing labels.
- avg_response_time
- is_slow
- This is ground truth for analysis and training, not routing prediction.

wiki_page_predictions:
- Stores cached model prediction for routing.
- predicted_slow
- model_name
- created_at
- updated_at
- This is the AI model output used by NeuroRoute.

SQL for wiki_page_predictions:

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

## 5. Data Pipeline

A. Parse SimpleWiki XML
- Total pages in dump: 553,618
- Redirect pages skipped: 122,635
- Non-article skipped: 149,883
- Empty/tiny skipped: 27
- Valid candidates: 281,073
- Selected pages: 10,000 or 10,001 depending on final run
- Inserted/updated pages: 10,000/10,001

Sampling strategy:
- 6,000 random valid pages
- 2,000 largest pages
- 1,000 template-heavy pages
- 1,000 complex pages
- Redirects and non-article namespace pages skipped.

B. Render features
- Python renderer using mwparserfromhell or prior renderer fills:
  - table_tag_count
  - paragraph_tag_count
  - rendered_html_length_bytes
  - render_expansion_ratio
  - html_tag_count

C. Locust sequential labeling
- Locust calls /render-page/{page_id} or timing endpoint sequentially.
- 1 user, no wait time.
- Response time recorded per page.
- Top 20% slowest pages labeled is_slow = 1.
- Remaining 80% labeled is_slow = 0.

D. Train model
- dataset/dataset10k.csv created from database.
- Ground truth y = wiki_page_labels.is_slow.
- avg_response_time included only for analysis, not as feature.

## 6. Feature Engineering

Cheap pre-render features used by final routing model:
- wikitext_length_bytes
- template_count
- image_count
- reference_count
- heading_count
- internal_link_count
- external_link_count
- category_count

Render-derived features used for analysis / full model but NOT final gateway routing:
- table_tag_count
- paragraph_tag_count
- rendered_html_length_bytes
- render_expansion_ratio
- html_tag_count

Important note:
- Do not use render-derived features in the gateway routing model because rendering before routing defeats the purpose.

## 7. Models

A. Full analysis model
- Used all features including render-derived fields.
- Good for analysis but not correct for pre-routing.

B. Cheap routing model
- File: models/cheap_neuroroute_random_forest10k.joblib
- Uses only cheap pre-render features.
- Final model used by NeuroRoute.
- RandomForestClassifier
- n_estimators=300
- class_weight="balanced"
- random_state=42
- n_jobs=-1

Cheap model performance:

Class distribution:
- fast: 8000, about 79.99%
- slow: 2001, about 20.01%

Validation:
- accuracy: 0.9633
- precision: 0.9181
- recall: 0.8967
- f1: 0.9073
- roc_auc: 0.9773

Test:
- accuracy: 0.9547
- precision: 0.9000
- recall: 0.8700
- f1: 0.8847
- roc_auc: 0.9817

Feature importance:
- wikitext_length_bytes: 0.328996
- internal_link_count: 0.263375
- template_count: 0.202621
- heading_count: 0.088220
- external_link_count: 0.043954
- reference_count: 0.036505
- image_count: 0.019937
- category_count: 0.016392

## 8. Cached Prediction System

Why caching:
- Online model inference adds overhead on the hot path.
- Cached predictions keep NeuroRoute AI-driven while reducing request-time latency.

Batch script:
- scripts/cache_model_predictions.py
- Loads cheap model, reads cheap features, predicts predicted_slow, writes wiki_page_predictions.

Request-time flow (POST /route-neuroroute/{page_id}):
- Fetch page + cached prediction using LEFT JOIN.
- If cached, route directly.
- If missing, fetch features + model inference + cache.
- Choose worker by lane.
- POST to worker /process.

## 9. Gateway Endpoints

GET /health
- Gateway health check.

GET /render-page/{page_id}
- Data collection endpoint.
- Gateway-local renderer and feature update.
- Not used for final benchmark routing.

POST /route-round-robin/{page_id}
- Baseline endpoint.
- Fetches page from DB.
- Routes across ALL_WORKERS.
- Calls worker /process.

POST /route-neuroroute/{page_id}
- AI endpoint.
- Fetches page and cached prediction.
- Routes fast to FAST_WORKERS.
- Routes slow to SLOW_WORKERS.
- Calls worker /process.

## 10. Worker Endpoint

POST /process

Input:
```json
{
  "page_id": 123,
  "title": "Example",
  "raw_wikitext": "..."
}
```

Worker behavior:
- No DB calls.
- No labels.
- No prediction.
- Calls process_with_mwparser(raw_wikitext).
- Returns small JSON:
  - worker
  - lane
  - page_id
  - title
  - rendered_html_length_bytes
  - html_tag_count
  - checksum
  - status

Why workers do not fetch DB:
- Gateway centralizes DB and routing.
- Workers only process requests.
- Benchmark remains clean and consistent.

## 11. Renderer

File:
- renderer/mwparser_renderer.py

Functions:
- render_with_mwparser(raw_wikitext)
  - Detailed data-collection renderer.
- process_with_mwparser(raw_wikitext)
  - Benchmark renderer.
  - Same heavy mwparserfromhell work.
  - Returns smaller JSON payload.

Important:
- Do not use random sleeps.
- Workload is deterministic.
- Same input produces same output.
- Processing includes:
  - mwparserfromhell.parse
  - filter_templates
  - filter_wikilinks
  - filter_external_links
  - filter_headings
  - filter_tags
  - strip_code
  - checksum

## 12. Benchmarking

Benchmark page list:
- loadtests/benchmark_pages.csv
- 1000 rows
- 800 fast pages, 200 slow pages
- is_slow column is ONLY for analysis
- is_slow must NOT be sent to endpoints
- NeuroRoute must use model/cached prediction, not ground-truth label

Locust files:
- loadtests/locust_round_robin_benchmark.py
- loadtests/locust_neuroroute_benchmark.py

Result files:
- loadtests/results/round_robin_results.csv
- loadtests/results/neuroroute_results.csv
- per-user files:
  - round_robin_u10_results.csv
  - neuroroute_u10_results.csv

Analysis script:
- scripts/analyze_benchmark_results.py
- Takes two CSVs and output name.
- Saves reports/{output_name}/
- Calculates mean, p50, p90, p95, p99, max.
- Groups by:
  - all
  - fast where is_slow = 0
  - slow where is_slow = 1
- Computes improvement:
  - ((round_robin_latency - neuroroute_latency) / round_robin_latency) * 100

## 13. Final Benchmark Results

Key final benchmark with cached predictions at 10 users:

Round Robin vs NeuroRoute (All pages):

| Metric | Round Robin | NeuroRoute |
| --- | --- | --- |
| Mean | 344.96 ms | 354.75 ms |
| p50 | 106.48 ms | 16.73 ms |
| p95 | 1507.42 ms | 2099.02 ms |
| p99 | 2288.56 ms | 3003.57 ms |

Fast pages:

| Metric | Round Robin | NeuroRoute |
| --- | --- | --- |
| Mean | 267.95 ms | 35.06 ms |
| p50 | 38.33 ms | 12.95 ms |
| p90 | 857.38 ms | 68.43 ms |
| p95 | 1301.84 ms | 115.40 ms |
| p99 | 2203.45 ms | 258.41 ms |
| Mean improvement | - | 86.92% |
| p95 improvement | - | 91.14% |
| p99 improvement | - | 88.27% |

Slow pages:

| Metric | Round Robin | NeuroRoute |
| --- | --- | --- |
| Mean | 652.99 ms | 1633.51 ms |
| p95 | 2032.16 ms | 3004.11 ms |
| p99 | 2909.58 ms | 3716.26 ms |

Interpretation:
- NeuroRoute strongly improves fast-page latency.
- Slow pages become slower because they are intentionally isolated into worker_4.
- Overall p95/p99 can worsen because slow-page delays dominate the global tail.
- Main success metric is fast-page p95/p99 improvement.

## 14. Interpretation and Tradeoffs

- NeuroRoute succeeds at reducing HoL blocking for fast/light requests.
- It does not necessarily improve every metric.
- Median/overall/slow-page latency may worsen depending on worker allocation.
- Fast pages are protected because slow pages are isolated.
- Slow pages pay the cost because the slow lane can become congested.

## 15. Known Limitations

- Dataset is SimpleWiki, not full Wikipedia.
- Renderer approximates MediaWiki behavior using mwparserfromhell, not production Parsoid.
- Only 10k/10,001 pages used.
- Slow lane has one worker, so slow-page latency can increase.
- No adaptive queue-depth routing yet.
- No autoscaling.
- No health-based failover.
- No true production load balancer integration.
- Results depend on Docker resource limits and local hardware.

## 16. Future Work

- 2 fast / 2 slow worker split
- Adaptive lane sizing
- Queue-depth-aware routing
- Latency regression instead of binary classification
- Probability/confidence-based routing
- Worker health fallback
- Redis cache for predictions
- Model calibration
- Larger dataset, e.g. 25k/50k pages
- Real MediaWiki/Parsoid renderer
- Kubernetes deployment
- Prometheus/Grafana metrics

## 17. Commands

Start stack:
```bash
docker compose up --build
```

Enter Postgres:
```bash
docker exec -it neuroroute_postgres psql -U neuroroute_user -d neuroroute
```

Create predictions table:
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

Run cached prediction script:
```bash
python scripts/cache_model_predictions.py
```

Train cheap model:
```bash
python ml/cheap_train_random_forest10k.py
```

Run benchmark page creator:
```bash
python scripts/create_benchmark_pages.py
```

Run Round Robin Locust:
```bash
BENCHMARK_USERS=10 locust -f loadtests/locust_round_robin_benchmark.py --host=http://localhost:8000 --users=10 --spawn-rate=2 --headless
```

Run NeuroRoute Locust:
```bash
BENCHMARK_USERS=10 locust -f loadtests/locust_neuroroute_benchmark.py --host=http://localhost:8000 --users=10 --spawn-rate=2 --headless
```

Analyze results:
```bash
python scripts/analyze_benchmark_results.py \
  --round-robin loadtests/results/round_robin_u10_results.csv \
  --neuroroute loadtests/results/neuroroute_u10_results.csv \
  --output-name benchmark_u10
```

Test endpoints:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/route-round-robin/218
curl -X POST http://localhost:8000/route-neuroroute/218
```

## 18. How to Continue the Project

Practical next-step checklist:
- Verify Docker runs.
- Verify DB tables.
- Verify cached predictions count.
- Verify both endpoints.
- Run 1-user smoke benchmark.
- Run 10-user benchmark.
- Generate report.
- Try optional 2-fast/2-slow experiment.
- Update README.

## 19. What Not To Break

- Do not use wiki_page_labels.is_slow for routing.
- Do not use render-derived features for pre-routing model.
- Do not render in gateway before routing.
- Do not send is_slow from benchmark CSV to API endpoints.
- Do not make workers fetch from database.
- Do not remove cached prediction logic unless measuring online inference overhead.
- Do not compare Round Robin and NeuroRoute on different page lists.

## 20. Final Summary

- Project is successful.
- Main evidence: fast-page p95 and p99 improved by over 88–91%.
- Tradeoff: slow pages become slower due to slow-lane isolation.
- NeuroRoute is best framed as fast-tail-latency protection, not universal latency reduction.
