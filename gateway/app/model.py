import os
import pickle


_MODEL = None
_FEATURE_ORDER = None


def _load_model():
    global _MODEL, _FEATURE_ORDER

    if _MODEL is not None and _FEATURE_ORDER is not None:
        return _MODEL, _FEATURE_ORDER

    model_path = os.getenv(
        "NEUROROUTE_MODEL_PATH",
        "/app/models/cheap_neuroroute_random_forest10k.pkl",
    )

    with open(model_path, "rb") as handle:
        payload = pickle.load(handle)

    _MODEL = payload["model"]
    _FEATURE_ORDER = list(payload["features"])

    return _MODEL, _FEATURE_ORDER


def predict_is_slow_from_features(features: dict) -> int:
    model, feature_order = _load_model()

    vector = [
        [
            float(features.get(feature_name, 0))
            for feature_name in feature_order
        ]
    ]

    prediction = model.predict(vector)[0]

    return int(prediction)