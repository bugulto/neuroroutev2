import asyncio
import os

import asyncpg
import joblib


CHEAP_FEATURES = [
    "wikitext_length_bytes",
    "template_count",
    "image_count",
    "reference_count",
    "heading_count",
    "internal_link_count",
    "external_link_count",
    "category_count",
]


def load_model():
    model_path = os.getenv(
        "NEUROROUTE_MODEL_PATH",
        "models/cheap_neuroroute_random_forest10k.joblib",
    )

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    payload = joblib.load(model_path)

    if not isinstance(payload, dict) or "model" not in payload or "features" not in payload:
        raise ValueError("Invalid model payload: expected keys 'model' and 'features'.")

    feature_order = list(payload["features"])
    extra_features = [feature for feature in feature_order if feature not in CHEAP_FEATURES]

    if extra_features:
        raise ValueError(
            "Model expects non-cheap features: " + ", ".join(extra_features)
        )

    return payload["model"], feature_order


def get_db_config() -> dict:
    return {
        "database": os.getenv("POSTGRES_DB", "neuroroute"),
        "user": os.getenv("POSTGRES_USER", "neuroroute_user"),
        "password": os.getenv("POSTGRES_PASSWORD", "neuroroute_password"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
    }


def build_feature_vector(row: asyncpg.Record, feature_order: list[str]) -> list[float]:
    vector = []

    for feature_name in feature_order:
        value = row[feature_name]
        if value is None:
            vector.append(0.0)
        else:
            vector.append(float(value))

    return vector


async def cache_predictions() -> None:
    model, feature_order = load_model()
    db_config = get_db_config()

    pool = await asyncpg.create_pool(**db_config)

    predicted_fast = 0
    predicted_slow = 0
    cached = 0

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    page_id,
                    wikitext_length_bytes,
                    template_count,
                    image_count,
                    reference_count,
                    heading_count,
                    internal_link_count,
                    external_link_count,
                    category_count
                FROM wiki_page_features
                """
            )

            if not rows:
                print("total pages read: 0")
                print("predictions cached: 0")
                print("predicted fast count: 0")
                print("predicted slow count: 0")
                return

            values = []

            for row in rows:
                vector = [build_feature_vector(row, feature_order)]
                prediction = int(model.predict(vector)[0])

                if prediction == 1:
                    predicted_slow += 1
                else:
                    predicted_fast += 1

                values.append(
                    (
                        int(row["page_id"]),
                        prediction,
                        "cheap_random_forest10k",
                    )
                )

            await conn.executemany(
                """
                INSERT INTO wiki_page_predictions (
                    page_id,
                    predicted_slow,
                    model_name,
                    updated_at
                )
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (page_id)
                DO UPDATE SET
                    predicted_slow = EXCLUDED.predicted_slow,
                    model_name = EXCLUDED.model_name,
                    updated_at = NOW()
                """,
                values,
            )

            cached = len(values)

            print(f"total pages read: {len(rows)}")
            print(f"predictions cached: {cached}")
            print(f"predicted fast count: {predicted_fast}")
            print(f"predicted slow count: {predicted_slow}")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(cache_predictions())
