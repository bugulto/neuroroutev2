import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split


DATASET_PATH = os.path.join("dataset", "dataset50k_p85.csv")
MODEL_PATH = os.path.join("models", "neuroroute_random_forest50k_p85.joblib")

TARGET_COLUMN = "is_slow"

FEATURE_COLUMNS = [
    "wikitext_length_bytes",
    "template_count",
    "image_count",
    "reference_count",
    "heading_count",
    "internal_link_count",
    "external_link_count",
    "category_count",
]


def print_class_distribution(y: pd.Series) -> None:
    counts = y.value_counts().sort_index()
    total = len(y)

    print("Class distribution:")
    for label, count in counts.items():
        ratio = count / total if total else 0
        print(f"  {label}: {count} ({ratio:.2%})")


def evaluate(y_true, y_pred, y_prob, label: str) -> None:
    print(f"{label} metrics:")
    print(f"  accuracy: {accuracy_score(y_true, y_pred):.4f}")
    print(f"  precision: {precision_score(y_true, y_pred, zero_division=0):.4f}")
    print(f"  recall: {recall_score(y_true, y_pred, zero_division=0):.4f}")
    print(f"  f1: {f1_score(y_true, y_pred, zero_division=0):.4f}")
    print(f"  roc_auc: {roc_auc_score(y_true, y_prob):.4f}")
    print("  confusion matrix:")
    print(confusion_matrix(y_true, y_pred))


def main() -> None:
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    df = pd.read_csv(DATASET_PATH)
    df = df.dropna()

    print(f"Dataset rows after dropna: {len(df)}")

    if TARGET_COLUMN not in df.columns:
        raise ValueError(f"Missing target column: {TARGET_COLUMN}")

    missing_features = [col for col in FEATURE_COLUMNS if col not in df.columns]
    if missing_features:
        raise ValueError(f"Missing required features: {missing_features}")

    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN].astype(int)

    print_class_distribution(y)

    X_train, X_temp, y_train, y_temp = train_test_split(
        X,
        y,
        test_size=0.30,
        random_state=42,
        stratify=y,
    )

    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=0.50,
        random_state=42,
        stratify=y_temp,
    )

    print("Split sizes:")
    print(f"  train: {len(X_train)}")
    print(f"  validation: {len(X_val)}")
    print(f"  test: {len(X_test)}")

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    model.fit(X_train, y_train)

    val_pred = model.predict(X_val)
    val_prob = model.predict_proba(X_val)[:, 1]
    evaluate(y_val, val_pred, val_prob, "Validation")

    test_pred = model.predict(X_test)
    test_prob = model.predict_proba(X_test)[:, 1]
    evaluate(y_test, test_pred, test_prob, "Test")

    importances = list(zip(FEATURE_COLUMNS, model.feature_importances_))
    importances.sort(key=lambda x: x[1], reverse=True)

    print("Feature importance:")
    for name, score in importances:
        print(f"  {name}: {score:.6f}")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "features": FEATURE_COLUMNS,
        },
        MODEL_PATH,
    )

    print(f"Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    main()