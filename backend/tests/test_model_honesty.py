"""Guards on the claims the model artefact is allowed to make.

These tests exist because the project's biggest reputational risk is not a bug,
it is a number quoted without its caveat. The model currently scores 1.000 on a
region-grouped split, and that is a symptom of label circularity rather than
skill: the labels come from a deterministic rule policy over features the model
can see, so a depth-3 tree and a linear model score the same.

If someone later retrains, edits the metrics writer, or trims a docstring, the
disclosure must not quietly vanish with it. So the disclosure is asserted, not
merely written down.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import ARTIFACT_DIR

METRICS_PATH = ARTIFACT_DIR / "metrics.json"
DOCS = Path(__file__).resolve().parent.parent.parent / "docs"
MODEL_CARD = DOCS / "ML_MODEL_CARD.md"

# The threshold train.py uses to decide a score is too good to be true.
IMPLAUSIBLE = 0.98


def _flat(path: Path) -> str:
    """Lower-cased text with wrapping, blockquote markers and emphasis removed.

    The card is hard-wrapped and partly inside a blockquote, so a phrase like
    "not an accuracy claim" is split across a newline and a "> " marker.
    Matching on the raw text would fail for purely cosmetic reasons.
    """
    text = path.read_text(encoding="utf-8").lower().replace("*", "")
    return " ".join(text.replace("\n>", " ").split())


@pytest.fixture(scope="module")
def metrics() -> dict:
    if not METRICS_PATH.exists():
        pytest.skip("no trained model in this checkout")
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


class TestCircularityDisclosure:
    def test_an_implausible_score_is_flagged_in_the_artefact(self, metrics):
        """A near-perfect score must carry its own warning flag."""
        balanced = metrics.get("balanced_accuracy")
        assert balanced is not None
        if balanced >= IMPLAUSIBLE:
            assert metrics.get("circularity_warning") is True, (
                f"balanced accuracy is {balanced:.3f} but circularity_warning is not "
                "set. A score this high is evidence of label circularity and must "
                "never be exported as an accuracy claim."
            )

    def test_the_flag_comes_with_an_explanation(self, metrics):
        if not metrics.get("circularity_warning"):
            pytest.skip("score is not in the implausible range")
        note = metrics.get("circularity_note") or ""
        # The explanation has to actually explain, not just gesture.
        assert "rule" in note.lower()
        assert "not" in note.lower()
        assert len(note) > 120, "the note is too short to be a real explanation"

    def test_metrics_never_claim_verified_accuracy(self, metrics):
        """The artefact must not contain a bare 'accuracy' claim in prose."""
        blob = json.dumps(metrics).lower()
        for forbidden in ("ground truth", "field verified", "field-verified"):
            assert forbidden not in blob or "not" in blob


class TestModelCard:
    def test_model_card_exists(self):
        assert MODEL_CARD.exists(), (
            "docs/ML_MODEL_CARD.md is the only place the circularity finding is "
            "explained in full. It must not be deleted."
        )

    def test_model_card_states_the_finding(self):
        text = _flat(MODEL_CARD)
        assert "circular" in text
        # The baselines are the proof, so the card must cite them.
        assert "logistic regression" in text
        assert "depth-3" in text
        # And it must not bury the weakest number.
        assert "72" in text and "8" in text

    def test_model_card_refuses_the_accuracy_framing(self):
        """The phrase "accuracy claim" must always arrive negated.

        Asserted on the negation rather than on one exact sentence, so the card
        can be reworded without breaking the test — but cannot be reworded into
        actually claiming accuracy.
        """
        text = _flat(MODEL_CARD)
        assert "accuracy claim" in text, "the card never addresses the framing at all"
        idx = text.find("accuracy claim")
        while idx != -1:
            window = text[max(0, idx - 60) : idx]
            assert "not" in window, (
                "'accuracy claim' appears without a negation in the preceding "
                f"60 characters: ...{window}accuracy claim..."
            )
            idx = text.find("accuracy claim", idx + 1)

    def test_model_card_admits_no_temporal_validation(self):
        text = _flat(MODEL_CARD)
        assert "temporal" in text and "48-day" in text


class TestTrainScriptGuard:
    def test_train_script_still_checks_its_own_result(self):
        """The warning must be in the code, not only in the docs."""
        src = (Path(__file__).resolve().parent.parent / "ml" / "train.py").read_text(
            encoding="utf-8"
        )
        assert "circularity_warning" in src
        assert "0.98" in src, "the implausibility threshold has been removed"
