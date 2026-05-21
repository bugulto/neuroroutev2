# NeuroRoute

AI-driven predictive load balancer for Wikipedia-style workloads. The system uses FastAPI services (gateway + workers), Postgres for page data and features, and a lightweight ML model to route pages to fast/slow worker lanes.

## Requirements

- Docker + Docker Compose
- Python 3.11+ (for data prep, training, and analysis scripts)

## Quick Start (Docker)

1. Copy env file (already present in this repo):
   - `.env` contains defaults for Postgres and the gateway port.

2. Start all services:

   ```bash
   docker compose up --build
   ```

3. Verify health:

   ```bash
   curl http://localhost:8000/health
   ```

## Data Preparation (Run on Host)

These scripts connect to Postgres via environment variables. When running locally (outside Docker), set `POSTGRES_HOST=localhost`.

1. Create a Python environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-ml.txt psycopg2-binary
   ```

2. Load SimpleWiki pages into Postgres:

   ```bash
   export POSTGRES_DB=neuroroute
   export POSTGRES_USER=neuroroute_user
   export POSTGRES_PASSWORD=neuroroute_password
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432

   python wikiparser/parse_simplewiki_10k.py \
     --xml-path simplewiki-latest-pages-articles.xml
   ```

## Generate Labels (Slow vs Fast)

1. Run the sequential labeling load test to record response times:

   ```bash
   locust -f loadtests/locust_sequential_labeling.py \
     --host=http://localhost:8000 --users=1 --spawn-rate=1 --headless
   ```

   Output: `loadtests/results/sequential_response_times.csv`

2. Import timings into Postgres and compute slow/fast labels (p80 threshold):

   ```bash
   export POSTGRES_DB=neuroroute
   export POSTGRES_USER=neuroroute_user
   export POSTGRES_PASSWORD=neuroroute_password
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432

   python scripts/import_locust_timings.py
   ```

## Create Benchmark Page Set

```bash
export POSTGRES_DB=neuroroute
export POSTGRES_USER=neuroroute_user
export POSTGRES_PASSWORD=neuroroute_password
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

python scripts/create_benchmark_pages.py
```

Output: `loadtests/benchmark_pages.csv`

## Train / Update the Model (Optional)

The gateway expects a model file at `models/cheap_neuroroute_random_forest10k.joblib`.

```bash
python ml/cheap_train_random_forest10k.py
```

This writes the model to `models/cheap_neuroroute_random_forest10k.joblib`, which is copied into the gateway container on build.

## Run Benchmarks

Round-robin:

```bash
BENCHMARK_USERS=10 locust -f loadtests/locust_round_robin_benchmark.py \
  --host=http://localhost:8000 --headless --users=10 --spawn-rate=2
```

NeuroRoute:

```bash
BENCHMARK_USERS=10 locust -f loadtests/locust_neuroroute_benchmark.py \
  --host=http://localhost:8000 --headless --users=10 --spawn-rate=2
```

## Analyze Results

```bash
python scripts/analyze_benchmark_results.py \
  --round-robin loadtests/results/round_robin_u10_results.csv \
  --neuroroute loadtests/results/neuroroute_u10_results.csv \
  --output-name benchmark_u10
```

Outputs are written under `reports/<output-name>`.

## Common Environment Variables

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`
- `NEUROROUTE_MODEL_PATH` (gateway, default: `/app/models/cheap_neuroroute_random_forest10k.joblib`)
- `WORKER_ALL_URLS`, `WORKER_FAST_URLS`, `WORKER_SLOW_URLS` (gateway)

## Notes

- When running scripts locally, use `POSTGRES_HOST=localhost`.
- When running inside Docker, the gateway uses `POSTGRES_HOST=postgres` from `.env`.
