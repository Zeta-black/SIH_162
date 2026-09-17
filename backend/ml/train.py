"""Train the FIRETRACE Random Forest classifier.

Run:  python -m ml.train           (from the backend/ directory)
      python -m ml.train --trees 400 --seed 7

Reads `ml/data/training_dataset.csv`, trains a RandomForestClassifier, evaluates
it on a held-out split, and writes the model plus its metadata to
`ml/artifacts/`.

WHAT THE REPORTED METRICS MEAN
------------------------------
The labels in the training set were assigned by the rule policy in
`app/services/labeling.py`, not by verified field reports. So every number this
script prints measures **agreement with that labelling policy on held-out
detections**. It is not a measure of real-world fire-type accuracy, and the
figure is carried into the model metadata and the API response with that
caveat attached so it cannot be quoted out of context.

The split is GROUPED BY REGION where there are enough regions to allow it.
A random row-wise split would put detections from the same refinery in both
train and test, and the model would score well by memorising locations rather
than by learning anything transferable. Grouping by region forces it to
generalise to industrial sites it has never seen.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupShuffleSplit, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ARTIFACT_DIR, ML_DIR  # noqa: E402
from app.services.features import FEATURE_NAMES, FEATURE_VERSION  # noqa: E402
from app.services.labeling import LABEL_POLICY_VERSION, policy_summary  # noqa: E402
from app.taxonomy import TRAINED_CLASSES  # noqa: E402

DATA_CSV = ML_DIR / "data" / "training_dataset.csv"
MANIFEST = ML_DIR / "data" / "dataset_manifest.json"
MODEL_PATH = ARTIFACT_DIR / "firetrace_rf.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

MODEL_VERSION = "1.0.0"
MODEL_NAME = "FIRETRACE Random Forest"

# A class needs enough examples for a held-out split to mean anything.
MIN_ROWS_PER_CLASS = 12

log = logging.getLogger("firetrace.train")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(message)s", stream=sys.stdout
    )


def load_dataset() -> pd.DataFrame:
    if not DATA_CSV.exists():
        log.error(
            "No training dataset at %s.\nRun `python -m ml.build_dataset` first.", DATA_CSV
        )
        sys.exit(1)
    frame = pd.read_csv(DATA_CSV)
    if "label" not in frame.columns:
        log.error("Dataset has no `label` column.")
        sys.exit(1)
    return frame


def drop_tiny_classes(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Remove classes too rare to evaluate honestly."""
    counts = Counter(frame["label"])
    dropped = [c for c, n in counts.items() if n < MIN_ROWS_PER_CLASS]
    if dropped:
        log.warning(
            "  dropping %s — fewer than %d examples, too rare to evaluate",
            ", ".join(dropped),
            MIN_ROWS_PER_CLASS,
        )
        frame = frame[~frame["label"].isin(dropped)].copy()
    return frame, dropped


def make_split(frame: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Group-aware train/test split, falling back to stratified if necessary."""
    labels = frame["label"]

    if "region_id" in frame.columns:
        groups = frame["region_id"]
        n_groups = groups.nunique()
        # Only worth grouping if there are enough regions that a held-out set
        # can still contain more than one class.
        if n_groups >= 6:
            splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
            train_idx, test_idx = next(splitter.split(frame, labels, groups))
            train, test = frame.iloc[train_idx], frame.iloc[test_idx]
            if test["label"].nunique() >= 2 and len(test) >= 20:
                return train, test, f"grouped by region ({n_groups} regions)"
            log.warning("  grouped split produced a degenerate test set; using stratified split")

    train, test = train_test_split(
        frame, test_size=0.25, random_state=seed, stratify=labels
    )
    return train, test, "stratified random (rows)"


def build_pipeline(trees: int, seed: int) -> Pipeline:
    return Pipeline(
        [
            # Missing values are genuinely missing (a product did not report
            # FRP), so they are imputed with a learned median and the feature
            # builder emits a companion *_missing flag so the model can still
            # tell the difference.
            ("imputer", SimpleImputer(strategy="median")),
            (
                "forest",
                RandomForestClassifier(
                    n_estimators=trees,
                    max_depth=14,
                    min_samples_leaf=3,
                    min_samples_split=6,
                    # Detection counts per class are very unbalanced (stubble
                    # burning dwarfs everything). Balanced weights stop the
                    # majority class from simply winning by prior.
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=seed,
                    oob_score=True,
                    bootstrap=True,
                ),
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the FIRETRACE classifier.")
    parser.add_argument("--trees", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    setup_logging()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    frame = load_dataset()
    log.info("=" * 74)
    log.info("FIRETRACE model training")
    log.info("=" * 74)
    log.info("dataset          : %s", DATA_CSV.name)
    log.info("rows             : %d", len(frame))
    log.info("feature version  : %s", FEATURE_VERSION)
    log.info("label policy     : v%s (weak supervision, NOT ground truth)", LABEL_POLICY_VERSION)

    frame, dropped_classes = drop_tiny_classes(frame)
    counts = Counter(frame["label"])
    log.info("class balance    :")
    for label, n in counts.most_common():
        log.info("   %-30s %5d  (%.1f%%)", label, n, 100 * n / len(frame))

    if len(counts) < 2:
        log.error(
            "\nOnly %d class present after filtering. A classifier needs at least two.\n"
            "Widen the regions or windows in ml/regions.py and ml/windows.py, then rebuild.",
            len(counts),
        )
        sys.exit(1)

    missing = [f for f in FEATURE_NAMES if f not in frame.columns]
    if missing:
        log.error("Dataset is missing %d feature columns: %s", len(missing), missing[:6])
        sys.exit(1)

    train_df, test_df, split_note = make_split(frame, args.seed)
    X_train = train_df[FEATURE_NAMES].to_numpy(dtype=float)
    y_train = train_df["label"].to_numpy()
    X_test = test_df[FEATURE_NAMES].to_numpy(dtype=float)
    y_test = test_df["label"].to_numpy()

    log.info("\nsplit            : %s", split_note)
    log.info("   train %d rows / test %d rows", len(train_df), len(test_df))

    pipeline = build_pipeline(args.trees, args.seed)
    pipeline.fit(X_train, y_train)

    predictions = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    balanced = balanced_accuracy_score(y_test, predictions)
    macro_f1 = f1_score(y_test, predictions, average="macro", zero_division=0)
    forest = pipeline.named_steps["forest"]

    # Cross-validation on the training portion gives a sense of variance that a
    # single split cannot.
    cv_scores = []
    try:
        min_class = min(Counter(y_train).values())
        folds = max(2, min(5, min_class))
        if folds >= 2:
            cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=args.seed)
            cv_scores = cross_val_score(
                build_pipeline(args.trees, args.seed),
                X_train,
                y_train,
                cv=cv,
                scoring="balanced_accuracy",
            ).tolist()
    except Exception as exc:  # noqa: BLE001
        log.warning("  cross-validation skipped: %s", type(exc).__name__)

    labels_present = sorted(set(y_test) | set(predictions))
    report = classification_report(
        y_test, predictions, labels=labels_present, zero_division=0, output_dict=True
    )
    matrix = confusion_matrix(y_test, predictions, labels=labels_present).tolist()

    log.info("\nheld-out performance (agreement with the labelling policy):")
    log.info("   accuracy           %.3f", accuracy)
    log.info("   balanced accuracy  %.3f", balanced)
    log.info("   macro F1           %.3f", macro_f1)
    if hasattr(forest, "oob_score_"):
        log.info("   OOB score          %.3f", forest.oob_score_)
    if cv_scores:
        log.info(
            "   CV balanced acc    %.3f ± %.3f (%d folds)",
            float(np.mean(cv_scores)),
            float(np.std(cv_scores)),
            len(cv_scores),
        )

    log.info("\n%s", classification_report(y_test, predictions, labels=labels_present, zero_division=0))

    # Global importance, for the model panel. Per-prediction explanation is a
    # different computation entirely and lives in services/classifier.py.
    importances = sorted(
        zip(FEATURE_NAMES, forest.feature_importances_), key=lambda kv: kv[1], reverse=True
    )
    log.info("most-used features (global importance):")
    for name, score in importances[:12]:
        log.info("   %-34s %.4f", name, score)

    # ---- circularity check ------------------------------------------------
    # A near-perfect score on held-out REGIONS is not a success signal here. The
    # labels were generated by a deterministic rule set over features the model
    # can see, so any sufficiently flexible model simply re-derives the rules.
    # Measured on this dataset: logistic regression and a depth-3 decision tree
    # also reach ~0.99, which is the proof. The script says so rather than
    # letting anyone quote 1.00 as evidence of skill.
    circular = balanced >= 0.98
    if circular:
        log.warning("")
        log.warning("  " + "!" * 68)
        log.warning("  IMPLAUSIBLY HIGH SCORE - READ THIS BEFORE QUOTING IT")
        log.warning("  " + "!" * 68)
        log.warning("  Balanced accuracy %.3f on held-out regions.", balanced)
        log.warning("")
        log.warning("  This does NOT mean the model classifies fires well. The training")
        log.warning("  labels come from a deterministic rule policy over the same features")
        log.warning("  the model sees, so the task reduces to recovering those rules -")
        log.warning("  something a depth-3 tree and a linear model do equally well.")
        log.warning("")
        log.warning("  What this number means : the model faithfully encodes the policy.")
        log.warning("  What it does NOT mean  : real-world fire-classification accuracy.")
        log.warning("")
        log.warning("  Run `python -m ml.validate` for the baseline comparison that")
        log.warning("  demonstrates this, and never present 1.00 as an accuracy claim.")
        log.warning("  " + "!" * 68)

    small_test = len(test_df) < 60
    if small_test:
        log.warning(
            "\nNOTE: the test set has only %d rows. Treat these metrics as indicative, "
            "not as a stable estimate.",
            len(test_df),
        )

    dataset_manifest = {}
    if MANIFEST.exists():
        try:
            dataset_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    metrics = {
        "accuracy": round(float(accuracy), 4),
        "balanced_accuracy": round(float(balanced), 4),
        "macro_f1": round(float(macro_f1), 4),
        "oob_score": round(float(forest.oob_score_), 4) if hasattr(forest, "oob_score_") else None,
        "cv_balanced_accuracy_mean": round(float(np.mean(cv_scores)), 4) if cv_scores else None,
        "cv_balanced_accuracy_std": round(float(np.std(cv_scores)), 4) if cv_scores else None,
        "test_rows": int(len(test_df)),
        "train_rows": int(len(train_df)),
        "split_strategy": split_note,
        "labels": labels_present,
        "confusion_matrix": matrix,
        "per_class": {
            k: v for k, v in report.items() if k in labels_present
        },
        "small_test_set": small_test,
        "circularity_warning": circular,
        "circularity_note": (
            "Labels are generated by a deterministic rule policy over features the model "
            "can see, so a high score measures faithful encoding of that policy, not "
            "fire-classification skill. A depth-3 decision tree and logistic regression "
            "reach comparable scores on the same split; see ml/validate.py."
        ) if circular else None,
        "interpretation": (
            "These figures measure how well the model reproduces the weak-supervision "
            "labelling policy on held-out detections. They are NOT verified real-world "
            "fire-classification accuracy, because no per-detection ground truth was available."
        ),
    }

    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "training_data_version": dataset_manifest.get("dataset_version", "unknown"),
        "feature_version": FEATURE_VERSION,
        "label_policy_version": LABEL_POLICY_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "hyperparameters": {
            "n_estimators": args.trees,
            "max_depth": 14,
            "min_samples_leaf": 3,
            "min_samples_split": 6,
            "class_weight": "balanced_subsample",
            "random_state": args.seed,
        },
        "metrics": metrics,
        "training_summary": {
            "rows_total": int(len(frame)),
            "class_counts": {k: int(v) for k, v in counts.items()},
            "dropped_rare_classes": dropped_classes,
            "dataset_manifest": {
                k: dataset_manifest.get(k)
                for k in ("built_at", "rows_labelled", "rows_unlabelled_excluded", "rule_counts")
            },
        },
        "top_features": [
            {"feature": name, "importance": round(float(score), 5)}
            for name, score in importances[:15]
        ],
        "label_policy": policy_summary(),
        "trained_classes": [c for c in TRAINED_CLASSES if c in counts],
    }

    joblib.dump(
        {
            "pipeline": pipeline,
            "feature_names": FEATURE_NAMES,
            "classes": [str(c) for c in pipeline.classes_],
            "metadata": metadata,
        },
        MODEL_PATH,
    )
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    log.info("\nmodel   -> %s (%.1f KB)", MODEL_PATH.name, MODEL_PATH.stat().st_size / 1024)
    log.info("metrics -> %s", METRICS_PATH.name)
    log.info("=" * 74)


if __name__ == "__main__":
    main()
