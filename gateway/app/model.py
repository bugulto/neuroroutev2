import os
import joblib


_MODEL = None
_FEATURE_ORDER = None
_PREDICTION_CACHE = {}


async def warmup_cache():
    global _PREDICTION_CACHE
    from app.db import get_pool

    model, feature_order = _load_model()
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM wiki_page_features")
        
    vectors = []
    page_ids = []
    for row in rows:
        d = dict(row)
        vectors.append([_coerce_feature(d.get(f, 0)) for f in feature_order])
        page_ids.append(d["page_id"])
        
    if vectors:
        predictions = model.predict(vectors)
        for pid, pred in zip(page_ids, predictions):
            _PREDICTION_CACHE[pid] = int(pred)



def _load_model():
    global _MODEL, _FEATURE_ORDER

    if _MODEL is not None and _FEATURE_ORDER is not None:
        return _MODEL, _FEATURE_ORDER

    model_path = os.getenv(
        "NEUROROUTE_MODEL_PATH",
        "/app/models/active_neuroroute_model.joblib",
    )

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    payload = joblib.load(model_path)

    if not isinstance(payload, dict) or "model" not in payload or "features" not in payload:
        raise ValueError("Invalid model payload: expected keys 'model' and 'features'.")

    _MODEL = payload["model"]
    _FEATURE_ORDER = list(payload["features"])

    return _MODEL, _FEATURE_ORDER


def _coerce_feature(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def predict_is_slow_from_features(page_id: int, features: dict) -> int:
    if page_id in _PREDICTION_CACHE:
        return _PREDICTION_CACHE[page_id]

    model, feature_order = _load_model()

    vector = [[
        _coerce_feature(features.get(feature_name, 0))
        for feature_name in feature_order
    ]]

    prediction = model.predict(vector)[0]

    return int(prediction)