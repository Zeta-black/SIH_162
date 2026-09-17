"""Random Forest inference, confidence handling and explanation.

Explanation strategy
--------------------
Global feature importance answers "what does this model rely on in general?",
which is not the same question as "why did it say that about THIS hotspot?".
So the per-event explanation here is genuinely local: each tree's decision path
for the sample is walked, and the change in class probability at every split is
attributed to the feature that produced the split. Averaging over the forest
gives per-feature contributions that sum, with the forest's bias term, to the
predicted probability. This is the standard tree-interpreter decomposition,
implemented directly so no extra dependency is needed.

Even so the wording stays careful: these are the factors that moved the
model's output, not a causal account of the fire.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.config import ARTIFACT_DIR, settings
from app.schemas import (
    Classification,
    Evidence,
    Factor,
    HotspotEvent,
    LandCoverResult,
    ModelInfo,
    NearestFacility,
    RecurrenceResult,
)
from app.services.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    build_feature_row,
    display_name,
    row_to_vector,
)
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    CLASS_DESCRIPTIONS,
    CLASS_LABELS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    TRAINED_CLASSES,
    UNKNOWN,
)

log = logging.getLogger("firetrace.ml")

MODEL_PATH = ARTIFACT_DIR / "firetrace_rf.joblib"

DISCLAIMER = (
    "FIRETRACE provides an AI-assisted likelihood classification derived from satellite "
    "thermal detections and open geographic data. It is not a confirmed ground-truth fire "
    "diagnosis and requires human verification before any operational decision."
)

INDUSTRIAL_RELATED = {INDUSTRIAL_FIRE, GAS_FLARE_OR_INDUSTRIAL_HEAT}

# One-hot columns are collapsed back into the logical feature a person thinks
# in, so the explanation says "Land cover" once instead of eight near-zero rows.
def _group_key(feature: str) -> str:
    if feature.startswith("landcover__"):
        return "land_cover"
    if feature.startswith("facility_cat__"):
        return "facility_category"
    if feature in {"season_sin", "season_cos"}:
        return "season"
    if feature in {"frp_mw", "log_frp", "frp_missing"}:
        return "frp_mw"
    if feature in {"brightness_k", "brightness_secondary_k", "brightness_missing"}:
        return "brightness_k"
    if feature in {"scan", "track", "pixel_area_proxy"}:
        return "pixel_footprint"
    if feature in {"latitude", "longitude"}:
        return "location"
    # These four all describe one thing — how close the detection is to mapped
    # industry — and all render the same sentence. Grouping them stops the
    # panel printing "0.26 km from the refinery" three times over.
    if feature in {
        "distance_to_facility_km",
        "facility_proximity_score",
        "facility_onsite",
        "facility_found",
    }:
        return "facility_distance"
    # Likewise, the recurrence counters are one idea to a reader.
    if feature in {
        "recurrence_count",
        "distinct_days",
        "is_persistent",
        "persistence_ratio",
        "history_available",
    }:
        return "recurrence"
    return feature


GROUP_DISPLAY = {
    "land_cover": "Land cover",
    "facility_category": "Nearby facility type",
    "season": "Season / time of year",
    "pixel_footprint": "Detection pixel footprint",
    "location": "Geographic location",
}



def evidence_sufficiency(
    facility: NearestFacility | None,
    land_cover: LandCoverResult,
    recurrence: RecurrenceResult,
) -> tuple[bool, str]:
    """Was the evidence that actually discriminates these classes present?

    Returns (sufficient, reason). The two features that carry most of the
    model's signal are proximity to a mapped industrial facility and the land
    cover under the detection. With neither available the forest is left voting
    on position and radiative power, which is not enough to separate a crop
    fire from a forest fire — and it will still produce a confident-looking
    number, so the caller raises the abstention bar instead of trusting it.
    """
    has_facility = facility is not None
    has_land_cover = land_cover is not None and land_cover.category != "unknown"

    if has_facility or has_land_cover:
        return True, ""

    # Recurrence deliberately does NOT satisfy this test. It separates a
    # persistent source from a one-off, which is what distinguishes a flare
    # from an incident — but it says nothing about whether the ground below is
    # a wheat field or a forest. Letting history stand in for spatial context
    # was the first version of this check, and it passed almost every one of
    # the detections the check exists to catch.
    return False, (
        "No industrial facility is mapped within the search radius and no land-use "
        "polygon covers this point. The two features that separate these classes "
        "were both unavailable, so no class is asserted."
    )


class ClassifierService:
    """Loads the model artifact once and serves predictions from it."""

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or MODEL_PATH
        self.pipeline = None
        self.forest = None
        self.imputer = None
        self.feature_names: list[str] = list(FEATURE_NAMES)
        self.classes: list[str] = list(TRAINED_CLASSES)
        self.metadata: dict[str, Any] = {}
        self.loaded = False
        self.status_note = "Model not loaded."
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        if not self.model_path.exists():
            self.status_note = (
                "No trained model artifact found. Run `python -m ml.train` to train one. "
                "All events are reported as Unclassified until then."
            )
            log.warning("[ML] model artifact missing at %s", self.model_path)
            return
        try:
            bundle = joblib.load(self.model_path)
            self.pipeline = bundle["pipeline"]
            self.feature_names = list(bundle["feature_names"])
            self.classes = list(bundle["classes"])
            self.metadata = dict(bundle.get("metadata", {}))

            artifact_feature_version = self.metadata.get("feature_version")
            if artifact_feature_version != FEATURE_VERSION:
                self.status_note = (
                    f"Model was trained on feature version {artifact_feature_version} but the "
                    f"code is on {FEATURE_VERSION}. Retrain before trusting predictions."
                )
                log.error("[ML] feature version mismatch; refusing to load model")
                self.pipeline = None
                return

            self.imputer = self.pipeline.named_steps.get("imputer")
            self.forest = self.pipeline.named_steps.get("forest")
            self.loaded = True
            self.status_note = "Model loaded."
            log.info(
                "[ML] model loaded version=%s trees=%s features=%d",
                self.metadata.get("model_version"),
                getattr(self.forest, "n_estimators", "?"),
                len(self.feature_names),
            )
        except Exception as exc:  # noqa: BLE001
            self.status_note = f"Model artifact could not be loaded ({type(exc).__name__})."
            log.exception("[ML] failed to load model artifact")
            self.pipeline = None
            self.loaded = False

    # ------------------------------------------------------------------ info
    def info(self) -> ModelInfo:
        return ModelInfo(
            name=self.metadata.get("model_name", "FIRETRACE Random Forest"),
            algorithm="RandomForestClassifier (scikit-learn)",
            model_version=self.metadata.get("model_version", "unavailable"),
            training_data_version=self.metadata.get("training_data_version", "unavailable"),
            feature_version=self.metadata.get("feature_version", FEATURE_VERSION),
            trained_at=self.metadata.get("trained_at"),
            n_features=len(self.feature_names),
            classes=list(self.classes),
            loaded=self.loaded,
            status_note=self.status_note,
        )

    # ------------------------------------------------------------- inference
    def predict(
        self,
        event: HotspotEvent,
        nearest_facility: NearestFacility | None,
        land_cover: LandCoverResult,
        recurrence: RecurrenceResult,
    ) -> tuple[Classification, dict[str, float], list[Factor]]:
        row = build_feature_row(event, nearest_facility, land_cover, recurrence)

        if not self.loaded or self.pipeline is None:
            return self._unclassified(), {c: 0.0 for c in TRAINED_CLASSES}, [
                Factor(
                    direction="neutral",
                    text="No trained model is loaded, so no classification was attempted.",
                    feature="model",
                )
            ]

        vector = np.asarray([row_to_vector(row, self.feature_names)], dtype=float)
        try:
            proba = self.pipeline.predict_proba(vector)[0]
        except Exception as exc:  # noqa: BLE001
            log.exception("[ML] prediction failed")
            return self._unclassified(f"Prediction failed ({type(exc).__name__})."), {
                c: 0.0 for c in TRAINED_CLASSES
            }, []

        probabilities = {
            str(cls): round(float(p), 4) for cls, p in zip(self.pipeline.classes_, proba)
        }
        # Present every trained class, including ones this sample scored at 0.
        for cls in TRAINED_CLASSES:
            probabilities.setdefault(cls, 0.0)

        top_index = int(np.argmax(proba))
        top_label = str(self.pipeline.classes_[top_index])
        top_prob = float(proba[top_index])

        sufficient, reason = evidence_sufficiency(nearest_facility, land_cover, recurrence)
        threshold = (
            settings.unknown_abstention_threshold
            if sufficient
            else settings.low_evidence_abstention_threshold
        )
        abstained = top_prob < threshold
        final_label = UNKNOWN if abstained else top_label

        description = CLASS_DESCRIPTIONS.get(final_label, "")
        if abstained and not sufficient:
            description = reason

        classification = Classification(
            label=final_label,
            label_display=CLASS_LABELS.get(final_label, final_label),
            description=description,
            confidence=round(top_prob, 4),
            confidence_level=confidence_level(top_prob),
            abstained=abstained,
            top_trained_label=top_label,
        )

        factors = self._explain(
            vector, row, top_index, event, nearest_facility, land_cover, recurrence, abstained
        )
        log.debug("[ML] prediction completed %s -> %s (%.2f)", event.event_id, final_label, top_prob)
        return classification, probabilities, factors

    def predict_batch(
        self,
        items: list[tuple[HotspotEvent, NearestFacility | None, LandCoverResult, RecurrenceResult]],
        explain: bool = True,
    ) -> list[tuple[Classification, dict[str, float], list[Factor]]]:
        """Classify many events with one vectorised `predict_proba` call.

        Scoring is cheap in bulk; the local explanation is not, because it
        walks every tree's decision path per sample. So `explain=False` skips
        that work for events the caller is only going to count, and the detail
        endpoint asks for it on the one event actually being inspected.
        """
        if not items:
            return []
        if not self.loaded or self.pipeline is None:
            fallback = (
                self._unclassified(),
                {c: 0.0 for c in TRAINED_CLASSES},
                [
                    Factor(
                        direction="neutral",
                        text="No trained model is loaded, so no classification was attempted.",
                        feature="model",
                    )
                ],
            )
            return [fallback for _ in items]

        rows = [build_feature_row(ev, fac, lc, rec) for ev, fac, lc, rec in items]
        matrix = np.asarray(
            [row_to_vector(r, self.feature_names) for r in rows], dtype=float
        )
        try:
            probabilities_matrix = self.pipeline.predict_proba(matrix)
        except Exception as exc:  # noqa: BLE001
            log.exception("[ML] batch prediction failed")
            note = f"Prediction failed ({type(exc).__name__})."
            return [
                (self._unclassified(note), {c: 0.0 for c in TRAINED_CLASSES}, [])
                for _ in items
            ]

        classes = [str(c) for c in self.pipeline.classes_]
        results: list[tuple[Classification, dict[str, float], list[Factor]]] = []

        for i, (event, facility, land_cover, recurrence) in enumerate(items):
            proba = probabilities_matrix[i]
            probabilities = {cls: round(float(p), 4) for cls, p in zip(classes, proba)}
            for cls in TRAINED_CLASSES:
                probabilities.setdefault(cls, 0.0)

            top_index = int(np.argmax(proba))
            top_label = classes[top_index]
            top_prob = float(proba[top_index])

            sufficient, reason = evidence_sufficiency(facility, land_cover, recurrence)
            threshold = (
                settings.unknown_abstention_threshold
                if sufficient
                else settings.low_evidence_abstention_threshold
            )
            abstained = top_prob < threshold
            final_label = UNKNOWN if abstained else top_label

            description = CLASS_DESCRIPTIONS.get(final_label, "")
            if abstained and not sufficient:
                description = reason

            classification = Classification(
                label=final_label,
                label_display=CLASS_LABELS.get(final_label, final_label),
                description=description,
                confidence=round(top_prob, 4),
                confidence_level=confidence_level(top_prob),
                abstained=abstained,
                top_trained_label=top_label,
            )

            if explain:
                factors = self._explain(
                    matrix[i : i + 1],
                    rows[i],
                    top_index,
                    event,
                    facility,
                    land_cover,
                    recurrence,
                    abstained,
                )
            else:
                factors = []
            results.append((classification, probabilities, factors))

        return results

    def explain_one(
        self,
        event: HotspotEvent,
        facility: NearestFacility | None,
        land_cover: LandCoverResult,
        recurrence: RecurrenceResult,
        class_label: str,
        abstained: bool,
    ) -> list[Factor]:
        """Compute the local explanation for a single already-scored event."""
        if not self.loaded or self.pipeline is None:
            return []
        row = build_feature_row(event, facility, land_cover, recurrence)
        vector = np.asarray([row_to_vector(row, self.feature_names)], dtype=float)
        classes = [str(c) for c in self.pipeline.classes_]
        class_index = classes.index(class_label) if class_label in classes else 0
        return self._explain(
            vector, row, class_index, event, facility, land_cover, recurrence, abstained
        )

    def _unclassified(self, note: str | None = None) -> Classification:
        return Classification(
            label=UNKNOWN,
            label_display=CLASS_LABELS[UNKNOWN],
            description=note or CLASS_DESCRIPTIONS[UNKNOWN],
            confidence=0.0,
            confidence_level=CONFIDENCE_LOW,  # type: ignore[arg-type]
            abstained=True,
            top_trained_label=UNKNOWN,
        )

    # ----------------------------------------------------------- explanation
    def local_contributions(self, vector: np.ndarray, class_index: int) -> dict[str, float]:
        """Per-feature contribution to one class probability for one sample.

        Walks each tree's decision path and attributes the probability change
        at every split to the splitting feature, then averages over the forest.
        contributions.sum() + bias == predict_proba for that class.
        """
        if self.forest is None:
            return {}
        x = vector
        if self.imputer is not None:
            x = self.imputer.transform(vector)
        x = np.asarray(x, dtype=np.float32)

        totals = np.zeros(len(self.feature_names), dtype=float)
        n_trees = len(self.forest.estimators_)
        if n_trees == 0:
            return {}

        for estimator in self.forest.estimators_:
            tree = estimator.tree_
            values = tree.value  # (n_nodes, n_outputs, n_classes)
            path = estimator.decision_path(x).indices
            # Node values are class counts in some sklearn versions and already
            # normalised in others, so normalise defensively either way.
            for depth in range(len(path) - 1):
                node, child = int(path[depth]), int(path[depth + 1])
                p_node = _node_probability(values, node, class_index)
                p_child = _node_probability(values, child, class_index)
                feature_index = int(tree.feature[node])
                if 0 <= feature_index < len(totals):
                    totals[feature_index] += p_child - p_node

        totals /= n_trees
        return {name: float(totals[i]) for i, name in enumerate(self.feature_names)}

    def _explain(
        self,
        vector: np.ndarray,
        row: dict[str, float],
        class_index: int,
        event: HotspotEvent,
        facility: NearestFacility | None,
        land_cover: LandCoverResult,
        recurrence: RecurrenceResult,
        abstained: bool,
    ) -> list[Factor]:
        try:
            contributions = self.local_contributions(vector, class_index)
        except Exception as exc:  # noqa: BLE001 - explanation must never break a prediction
            log.warning("[ML] local explanation failed: %s", type(exc).__name__)
            contributions = {}

        # Collapse one-hot groups into the logical feature a reader thinks in.
        grouped: dict[str, float] = {}
        for feature, value in contributions.items():
            grouped[_group_key(feature)] = grouped.get(_group_key(feature), 0.0) + value

        ranked = sorted(grouped.items(), key=lambda kv: abs(kv[1]), reverse=True)
        max_abs = max((abs(v) for _, v in ranked), default=0.0)

        factors: list[Factor] = []
        seen_text: set[str] = set()
        for feature, contribution in ranked:
            if len(factors) >= 5:
                break
            if max_abs > 0 and abs(contribution) < max_abs * 0.08:
                continue
            text, value_text = _describe(feature, row, event, facility, land_cover, recurrence)
            if text is None or text in seen_text:
                continue
            seen_text.add(text)
            factors.append(
                Factor(
                    direction="supports" if contribution >= 0 else "counters",
                    text=text,
                    feature=feature,
                    value=value_text,
                    importance=round(abs(contribution) / max_abs, 3) if max_abs > 0 else None,
                )
            )

        if abstained:
            sufficient, _ = evidence_sufficiency(facility, land_cover, recurrence)
            bar = (
                settings.unknown_abstention_threshold
                if sufficient
                else settings.low_evidence_abstention_threshold
            )
            text = (
                f"Evidence was mixed: the strongest class stayed below the {bar:.0%} "
                "threshold, so FIRETRACE reports this as unclassified rather than guessing."
                if sufficient
                else (
                    "No facility within the search radius and no land-use polygon here, so "
                    f"the bar was raised to {bar:.0%}. The model's leading class did not "
                    "clear it on this much evidence."
                )
            )
            factors.insert(
                0,
                Factor(direction="neutral", text=text, feature="abstention"),
            )
        if not factors:
            factors.append(
                Factor(
                    direction="neutral",
                    text="No single factor dominated this prediction.",
                    feature="none",
                )
            )
        return factors


def _node_probability(values: np.ndarray, node: int, class_index: int) -> float:
    node_values = values[node][0]
    total = float(node_values.sum())
    if total <= 0:
        return 0.0
    return float(node_values[class_index]) / total


def _describe(
    feature: str,
    row: dict[str, float],
    event: HotspotEvent,
    facility: NearestFacility | None,
    land_cover: LandCoverResult,
    recurrence: RecurrenceResult,
) -> tuple[str | None, str | None]:
    """Turn a feature group into a sentence backed by the real measured value."""
    if feature == "facility_distance":
        if facility is None:
            return (
                f"No industrial facility mapped within {settings.facility_search_radius_km:.0f} km",
                "none in radius",
            )
        d = facility.distance_km
        where = "on the facility footprint" if d <= settings.facility_onsite_km else "from"
        name = facility.name or facility.category_label
        return (
            f"{d:.2f} km {where} {name}" if where == "from" else f"{d:.2f} km — {where} of {name}",
            f"{d:.2f} km",
        )

    if feature == "facility_category":
        if facility is None:
            return None, None
        return (f"Nearest facility is a {facility.category_label.lower()}", facility.category_label)

    if feature == "facility_is_high_heat":
        if facility is None:
            return None, None
        return (
            f"{facility.category_label} is a process that normally runs hot",
            facility.category_label,
        )

    if feature == "land_cover":
        return (f"Land cover here is {land_cover.label.lower()}", land_cover.label)

    if feature == "recurrence":
        if not recurrence.history_available:
            return ("No detection history is loaded for this area", "no history")
        if recurrence.distinct_days == 0:
            return ("No earlier detection at this location in the history window", "first seen")
        return (
            f"Detected on {recurrence.distinct_days} separate days in the last "
            f"{recurrence.window_days} days",
            f"{recurrence.distinct_days} days",
        )

    if feature == "recent_count_7d":
        if not recurrence.history_available:
            return None, None
        return (
            f"{recurrence.recent_count_7d} detection(s) at this spot in the past week",
            str(recurrence.recent_count_7d),
        )

    if feature == "nearby_density":
        return (
            f"{recurrence.nearby_density} other hotspot(s) detected nearby on the same pass",
            str(recurrence.nearby_density),
        )

    if feature == "frp_mw":
        if event.frp_mw is None:
            return ("Fire radiative power was not reported for this detection", "not reported")
        return (f"Fire radiative power is {event.frp_mw:.1f} MW", f"{event.frp_mw:.1f} MW")

    if feature == "brightness_k":
        if event.brightness_k is None:
            return ("Brightness temperature was not reported", "not reported")
        return (
            f"Brightness temperature is {event.brightness_k:.0f} K",
            f"{event.brightness_k:.0f} K",
        )

    if feature == "brightness_delta_k":
        delta = row.get("brightness_delta_k")
        if delta is None or (isinstance(delta, float) and math.isnan(delta)):
            return None, None
        return (
            f"Thermal channels separate by {delta:.0f} K, indicating a "
            f"{'small, very hot' if delta > 40 else 'broader, cooler'} source",
            f"{delta:.0f} K",
        )

    if feature == "is_night":
        return (
            "Detected at night" if event.day_night == "N" else "Detected during the day",
            "night" if event.day_night == "N" else "day",
        )

    if feature == "season":
        return (
            f"Time of year: {event.acquisition_date.strftime('%B')}",
            event.acquisition_date.strftime("%B"),
        )

    if feature == "pixel_footprint":
        return None, None

    if feature == "location":
        return (
            f"Geographic position ({event.latitude:.3f}, {event.longitude:.3f})",
            f"{event.latitude:.3f}, {event.longitude:.3f}",
        )

    if feature == "firms_confidence_ordinal":
        if event.firms_confidence_level is None:
            return None, None
        return (
            f"NASA FIRMS rates this detection {event.firms_confidence_level} confidence",
            event.firms_confidence_level,
        )

    label = GROUP_DISPLAY.get(feature) or display_name(feature)
    return (label, None)


def confidence_level(probability: float) -> str:
    if probability >= settings.confidence_high_threshold:
        return CONFIDENCE_HIGH
    if probability >= settings.confidence_medium_threshold:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


_service: ClassifierService | None = None


def get_classifier() -> ClassifierService:
    """Process-wide singleton so the artifact is read from disk exactly once."""
    global _service
    if _service is None:
        _service = ClassifierService()
    return _service


def reset_classifier() -> None:
    global _service
    _service = None
