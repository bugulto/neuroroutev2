import os


SLOW_THRESHOLD_BYTES = int(os.getenv("SLOW_THRESHOLD_BYTES", "50000"))


def extract_features(raw_wikitext: str) -> dict:
    return {
        "wikitext_length_bytes": len(raw_wikitext.encode("utf-8")),
        "template_count": raw_wikitext.count("{{"),
        "image_count": raw_wikitext.lower().count("[[file:") + raw_wikitext.lower().count("[[image:"),
        "reference_count": raw_wikitext.lower().count("<ref"),
        "heading_count": raw_wikitext.count("=="),
        "internal_link_count": raw_wikitext.count("[["),
        "external_link_count": raw_wikitext.count("http://") + raw_wikitext.count("https://"),
        "category_count": raw_wikitext.lower().count("[[category:"),
    }


def predict_is_slow(raw_wikitext: str) -> int:
    """
    Temporary rule-based model.

    Replace this later with:
    - scikit-learn model
    - XGBoost model
    - LightGBM model
    - ONNX model
    """

    features = extract_features(raw_wikitext)

    if features["wikitext_length_bytes"] >= SLOW_THRESHOLD_BYTES:
        return 1

    if features["template_count"] >= 40:
        return 1

    if features["reference_count"] >= 100:
        return 1

    return 0