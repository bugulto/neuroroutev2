"""Copy the selected threshold model to the active model path.

Usage:
    python scripts/set_active_model.py --threshold p90

This copies:
    models/neuroroute_random_forest50k_p90.joblib
to:
    models/active_neuroroute_model.joblib

The gateway container loads the active model on startup.
"""

import argparse
import shutil
import sys
from pathlib import Path


VALID_THRESHOLDS = ("p80", "p85", "p90", "p93", "p94")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

MODEL_TEMPLATE = "neuroroute_random_forest50k_{threshold}.joblib"
ACTIVE_MODEL_NAME = "active_neuroroute_model.joblib"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set the active NeuroRoute model for the gateway.",
    )
    parser.add_argument(
        "--threshold",
        required=True,
        choices=VALID_THRESHOLDS,
        help="Model threshold to activate (e.g. p90).",
    )
    args = parser.parse_args()

    source_name = MODEL_TEMPLATE.format(threshold=args.threshold)
    source_path = MODELS_DIR / source_name
    target_path = MODELS_DIR / ACTIVE_MODEL_NAME

    if not source_path.exists():
        print(f"ERROR: Model file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    shutil.copy2(source_path, target_path)

    print(f"Copied: {source_path.name}")
    print(f"    -> {target_path}")
    print(f"Active model set to: {args.threshold}")


if __name__ == "__main__":
    main()
