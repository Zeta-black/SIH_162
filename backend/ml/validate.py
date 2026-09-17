"""Hostile validation of the classifier.

Run:  python -m ml.validate

This script exists to attack our own model rather than to showcase it. It does
three things a sceptical reviewer would do first:

1. **Leakage audit.** Look for duplicate feature rows across the train/test
   boundary, identical coordinates on both sides, and temporal overlap.
2. **Baseline comparison.** A Random Forest is not automatically better than a
   trivial rule. Compare against a majority-class predictor, a one-feature
   decision stump, a depth-3 tree and logistic regression, all on the *same*
   region-grouped split.
3. **Inference latency.** Measure it rather than assert it.

Every number printed here comes from a computation in this file on the shipped
dataset. Results are written to `ml/artifacts/validation.json` so the dashboard
and the documents can read them instead of quoting figures by hand.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, f1_score, precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ARTIFACT_DIR, ML_DIR  # noqa: E402
from app.services.features import FEATURE_NAMES  # noqa: E402

DATA_CSV = ML_DIR / "data" / "training_dataset.csv"
OUT = ARTIFACT_DIR / "validation.json"
SEED = 42

log = logging.getLogger("firetrace.validate")


def setup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


def load() -> pd.DataFrame:
    if not DATA_CSV.exists():
        log.error("No dataset at %s. Run `python -m ml.build_dataset` first.", DATA_CSV)
        sys.exit(1)
    frame = pd.read_csv(DATA_CSV)
    counts = Counter(frame["label"])
    keep = [c for c, n in counts.items() if n >= 12]
    return frame[frame["label"].isin(keep)].copy()


def split(frame: pd.DataFrame):
    """The same region-grouped split the training script uses."""
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
    train_idx, test_idx = next(splitter.split(frame, frame["label"], frame["region_id"]))
    return frame.iloc[train_idx].copy(), frame.iloc[test_idx].copy()


# ---------------------------------------------------------------------------
# 1. Leakage
# ---------------------------------------------------------------------------
def leakage_audit(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Look for the ways a tabular model most often cheats."""
    findings: dict[str, object] = {}

    # Identical feature vectors on both sides of the split.
    tr = train[FEATURE_NAMES].round(6).astype(str).agg("|".join, axis=1)
    te = test[FEATURE_NAMES].round(6).astype(str).agg("|".join, axis=1)
    overlap = set(tr) & set(te)
    findings["duplicate_feature_rows_across_split"] = len(overlap)

    # The same physical pixel appearing on both sides.
    tr_pos = set(zip(train["latitude"].round(5), train["longitude"].round(5)))
    te_pos = set(zip(test["latitude"].round(5), test["longitude"].round(5)))
    findings["shared_coordinates"] = len(tr_pos & te_pos)

    # Region grouping should make this impossible by construction; assert it.
    findings["shared_regions"] = len(set(train["region_id"]) & set(test["region_id"]))
    findings["train_regions"] = sorted(set(train["region_id"]))
    findings["test_regions"] = sorted(set(test["region_id"]))

    # Duplicate detection ids anywhere in the dataset.
    all_ids = pd.concat([train["event_id"], test["event_id"]])
    findings["duplicate_detection_ids"] = int(all_ids.duplicated().sum())

    # Date overlap is EXPECTED here and is not leakage: the split is spatial, not
    # temporal, because the deployment question is "does this transfer to a
    # refinery we have never seen", not "does it transfer to next week".
    findings["date_overlap_days"] = len(
        set(train["acquisition_date"]) & set(test["acquisition_date"])
    )
    findings["split_axis"] = "region (spatial), not time"

    findings["verdict"] = (
        "CLEAN"
        if findings["duplicate_feature_rows_across_split"] == 0
        and findings["shared_regions"] == 0
        and findings["duplicate_detection_ids"] == 0
        else "LEAKAGE FOUND"
    )
    return findings


# ---------------------------------------------------------------------------
# 2. Baselines
# ---------------------------------------------------------------------------
def build_rf() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(
            n_estimators=300, max_depth=14, min_samples_leaf=3, min_samples_split=6,
            class_weight="balanced_subsample", n_jobs=-1, random_state=SEED,
        )),
    ])


def candidates() -> dict[str, tuple[Pipeline, str]]:
    """Every model is fitted on the identical split, so the comparison is fair."""
    return {
        "majority_class": (
            Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("clf", DummyClassifier(strategy="most_frequent"))]),
            "Always predicts the commonest class. The floor any model must beat.",
        ),
        "stratified_random": (
            Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("clf", DummyClassifier(strategy="stratified", random_state=SEED))]),
            "Guesses in proportion to the class distribution.",
        ),
        "one_rule_stump": (
            Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("clf", DecisionTreeClassifier(max_depth=1, random_state=SEED))]),
            "A single threshold on a single feature — the simplest non-trivial rule.",
        ),
        "shallow_tree_d3": (
            Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("clf", DecisionTreeClassifier(
                          max_depth=3, class_weight="balanced", random_state=SEED))]),
            "An interpretable tree a human could read out loud.",
        ),
        "logistic_regression": (
            Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("scale", StandardScaler()),
                      ("clf", LogisticRegression(
                          max_iter=2000, class_weight="balanced", random_state=SEED))]),
            "A linear model — tests whether the problem needs non-linearity at all.",
        ),
        "random_forest": (build_rf(), "The shipped model."),
    }


def evaluate(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    X_tr = train[FEATURE_NAMES].to_numpy(dtype=float)
    y_tr = train["label"].to_numpy()
    X_te = test[FEATURE_NAMES].to_numpy(dtype=float)
    y_te = test["label"].to_numpy()

    results = {}
    for name, (model, rationale) in candidates().items():
        model.fit(X_tr, y_tr)
        pred = model.predict(X_te)
        bal = balanced_accuracy_score(y_te, pred)
        macro_f1 = f1_score(y_te, pred, average="macro", zero_division=0)

        # Industrial fire is the class the problem statement is actually about,
        # so it gets reported separately rather than hidden inside a macro mean.
        p, r, f, _ = precision_recall_fscore_support(
            y_te, pred, labels=["INDUSTRIAL_FIRE"], average=None, zero_division=0
        )
        results[name] = {
            "rationale": rationale,
            "balanced_accuracy": round(float(bal), 4),
            "macro_f1": round(float(macro_f1), 4),
            "industrial_fire_precision": round(float(p[0]), 4),
            "industrial_fire_recall": round(float(r[0]), 4),
            "industrial_fire_f1": round(float(f[0]), 4),
        }
    return results


# ---------------------------------------------------------------------------
# 3. Inference latency
# ---------------------------------------------------------------------------
def latency(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    model = build_rf()
    model.fit(train[FEATURE_NAMES].to_numpy(dtype=float), train["label"].to_numpy())
    X = test[FEATURE_NAMES].to_numpy(dtype=float)

    single = X[:1]
    t0 = time.perf_counter()
    for _ in range(50):
        model.predict_proba(single)
    single_ms = (time.perf_counter() - t0) / 50 * 1000

    t0 = time.perf_counter()
    model.predict_proba(X)
    batch_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    model.fit(train[FEATURE_NAMES].to_numpy(dtype=float), train["label"].to_numpy())
    train_s = time.perf_counter() - t0

    return {
        "single_prediction_ms": round(single_ms, 3),
        "batch_rows": int(len(X)),
        "batch_total_ms": round(batch_ms, 2),
        "per_row_in_batch_ms": round(batch_ms / max(1, len(X)), 4),
        "full_training_seconds": round(train_s, 2),
    }


def repeated_splits(frame: pd.DataFrame, n: int = 12) -> dict:
    """The same comparison across many region splits.

    A single split gave 0.921 with one set of test regions and 1.000 with
    another. Reporting whichever number we happened to draw would be
    meaningless, so the spread is measured instead. With only ten regions the
    choice of test regions dominates the result, and that IS the finding.
    """
    rows: dict[str, list[float]] = {name: [] for name in candidates()}
    ind_recall: dict[str, list[float]] = {name: [] for name in candidates()}

    for seed in range(n):
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
        tr_idx, te_idx = next(splitter.split(frame, frame["label"], frame["region_id"]))
        tr, te = frame.iloc[tr_idx], frame.iloc[te_idx]
        if te["label"].nunique() < 2:
            continue
        X_tr = tr[FEATURE_NAMES].to_numpy(dtype=float)
        y_tr = tr["label"].to_numpy()
        X_te = te[FEATURE_NAMES].to_numpy(dtype=float)
        y_te = te["label"].to_numpy()
        for name, (model, _) in candidates().items():
            try:
                model.fit(X_tr, y_tr)
                pred = model.predict(X_te)
                rows[name].append(balanced_accuracy_score(y_te, pred))
                _, r, _, _ = precision_recall_fscore_support(
                    y_te, pred, labels=["INDUSTRIAL_FIRE"], average=None, zero_division=0
                )
                ind_recall[name].append(float(r[0]))
            except Exception:
                continue

    out = {}
    for name in rows:
        vals = rows[name]
        if not vals:
            continue
        out[name] = {
            "splits": len(vals),
            "balanced_accuracy_mean": round(float(np.mean(vals)), 4),
            "balanced_accuracy_std": round(float(np.std(vals)), 4),
            "balanced_accuracy_min": round(float(np.min(vals)), 4),
            "balanced_accuracy_max": round(float(np.max(vals)), 4),
            "industrial_recall_mean": round(float(np.mean(ind_recall[name])), 4)
            if ind_recall[name] else None,
        }
    return out


def behaviour_on_unlabelled(frame: pd.DataFrame) -> dict:
    """What the model does where the labelling policy refused to commit.

    This is the only place the classifier can add anything the rules do not
    already give, because on rule-labelled rows it simply recovers the rules.
    There is no ground truth here, so this measures BEHAVIOUR, not accuracy:
    does the model spread its predictions sensibly, and does the evidence gate
    abstain where the discriminating features are missing?
    """
    path = ML_DIR / "data" / "unlabelled_detections.csv"
    if not path.exists():
        return {"available": False}

    unl = pd.read_csv(path)
    missing = [f for f in FEATURE_NAMES if f not in unl.columns]
    if missing:
        return {"available": False, "reason": f"missing columns: {missing[:3]}"}

    model = build_rf()
    model.fit(frame[FEATURE_NAMES].to_numpy(dtype=float), frame["label"].to_numpy())
    X = unl[FEATURE_NAMES].to_numpy(dtype=float)
    proba = model.predict_proba(X)
    top = proba.max(axis=1)
    pred = model.classes_[proba.argmax(axis=1)]

    # The gate: no facility inside the search radius AND no land-use polygon.
    no_facility = unl["facility_found"].to_numpy() == 0
    no_landcover = unl["landcover__unknown"].to_numpy() == 1
    thin = no_facility & no_landcover

    return {
        "available": True,
        "rows": int(len(unl)),
        "predicted_distribution": {k: int(v) for k, v in Counter(pred).items()},
        "mean_top_probability": round(float(top.mean()), 4),
        "share_below_045": round(float((top < 0.45).mean()), 4),
        "share_below_072": round(float((top < 0.72).mean()), 4),
        "thin_evidence_rows": int(thin.sum()),
        "thin_evidence_share": round(float(thin.mean()), 4),
        "abstained_under_gate": int(((thin & (top < 0.72)) | (~thin & (top < 0.45))).sum()),
        "note": (
            "No ground truth exists for these rows — the policy refused to label them. "
            "This measures model behaviour and gate coverage, not correctness."
        ),
    }


def main() -> None:
    setup()
    frame = load()
    train, test = split(frame)

    log.info("=" * 74)
    log.info("FIRETRACE — hostile validation")
    log.info("=" * 74)
    log.info("rows %d  |  train %d  |  test %d", len(frame), len(train), len(test))
    log.info("class balance: %s", dict(Counter(frame["label"]).most_common()))

    log.info("\n--- 1. LEAKAGE AUDIT " + "-" * 53)
    leak = leakage_audit(train, test)
    for k in [
        "duplicate_feature_rows_across_split", "shared_coordinates",
        "shared_regions", "duplicate_detection_ids", "date_overlap_days",
    ]:
        log.info("   %-38s %s", k, leak[k])
    log.info("   train regions : %s", ", ".join(leak["train_regions"]))
    log.info("   test regions  : %s", ", ".join(leak["test_regions"]))
    log.info("   VERDICT       : %s", leak["verdict"])

    log.info("\n--- 2. BASELINE COMPARISON " + "-" * 47)
    log.info("   %-22s %8s %8s %10s %8s", "model", "bal-acc", "macroF1", "IND-recall", "IND-F1")
    results = evaluate(train, test)
    for name, r in results.items():
        log.info(
            "   %-22s %8.3f %8.3f %10.2f %8.2f",
            name, r["balanced_accuracy"], r["macro_f1"],
            r["industrial_fire_recall"], r["industrial_fire_f1"],
        )

    rf = results["random_forest"]
    best_baseline = max(
        (r for n, r in results.items() if n != "random_forest"),
        key=lambda r: r["balanced_accuracy"],
    )
    lift = rf["balanced_accuracy"] - best_baseline["balanced_accuracy"]
    log.info("\n   Random Forest lift over best baseline: %+.3f balanced accuracy", lift)
    if lift <= 0.02:
        log.info("   NOTE: the margin is small. A simpler model may be defensible.")

    log.info("")
    log.info("--- 2b. SPLIT STABILITY (12 region splits) " + "-" * 31)
    stability = repeated_splits(frame)
    log.info("   %-22s %12s %8s %8s", "model", "mean+-std", "min", "max")
    for name, r in stability.items():
        log.info(
            "   %-22s %6.3f+-%.3f %8.3f %8.3f",
            name, r["balanced_accuracy_mean"], r["balanced_accuracy_std"],
            r["balanced_accuracy_min"], r["balanced_accuracy_max"],
        )

    log.info("")
    log.info("--- 2c. BEHAVIOUR WHERE THE POLICY ABSTAINED " + "-" * 29)
    unl = behaviour_on_unlabelled(frame)
    if unl.get("available"):
        log.info("   unlabelled rows            %d", unl["rows"])
        log.info("   predicted distribution     %s", unl["predicted_distribution"])
        log.info("   mean top probability       %.3f", unl["mean_top_probability"])
        log.info("   thin-evidence rows         %d (%.0f%%)",
                 unl["thin_evidence_rows"], unl["thin_evidence_share"] * 100)
        log.info("   abstained under the gate   %d (%.0f%%)",
                 unl["abstained_under_gate"], unl["abstained_under_gate"] / max(1, unl["rows"]) * 100)
    else:
        log.info("   not available: %s", unl.get("reason", "no unlabelled file"))

    log.info("\n--- 3. INFERENCE LATENCY " + "-" * 49)
    lat = latency(train, test)
    for k, v in lat.items():
        log.info("   %-28s %s", k, v)

    payload = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset_rows": int(len(frame)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "class_distribution": {k: int(v) for k, v in Counter(frame["label"]).items()},
        "leakage": leak,
        "baselines": results,
        "split_stability": stability,
        "behaviour_on_unlabelled": unl,
        "random_forest_lift_over_best_baseline": round(float(lift), 4),
        "latency": lat,
        "split": "GroupShuffleSplit by region_id, test_size=0.25, seed 42",
        "caveat": (
            "Labels come from a documented weak-supervision policy, not verified "
            "incident reports. Every figure here measures agreement with that policy "
            "on held-out regions, not real-world correctness."
        ),
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("\nwritten -> %s", OUT.name)
    log.info("=" * 74)


if __name__ == "__main__":
    main()
