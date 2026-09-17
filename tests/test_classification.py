# Tests for image classification and the import-time size filter.
#
# classification.py keeps torch and transformers inside its loader, so the
# scoring maths, the thresholds and the decisions can be exercised with nothing
# installed. That is what most of this file does — the model contributes a list
# of similarities and nothing else, so a list of similarities is what the tests
# supply.
#
# The handful of tests that do need the model are skipped where it is absent,
# so this suite runs clean on a laptop and in full on the GPU pod:
#
#     pytest tests/test_classification.py -v

import ast
import importlib.util
import io
import re
from pathlib import Path

import pytest
from PIL import Image

import classification
from classification import (
    ANGLES,
    ANGLE_PROMPTS,
    KINDS,
    KIND_PROMPTS,
    Classification,
    _decide_angle,
    _decide_kind,
    _flatten,
    _label_scores,
    _probabilities,
    is_processable,
)

ROOT = Path(__file__).resolve().parent.parent

HAS_MODEL = all(
    importlib.util.find_spec(name) is not None for name in ("torch", "transformers")
)
requires_model = pytest.mark.skipif(
    not HAS_MODEL, reason="torch and transformers are not installed here"
)

try:
    from api import url_import
except ImportError:  # httpx and beautifulsoup4 are not in the light test env
    url_import = None

requires_url_import = pytest.mark.skipif(
    url_import is None, reason="httpx and beautifulsoup4 are not installed here"
)


def uniform(labels, value=0.0):
    """A probability-shaped mapping to start from, before nudging one label."""
    return {label: value for label in labels}


# ── The vocabulary ─────────────────────────────────────────────────────────────

def test_kinds_match_the_database_constraint():
    """
    KINDS and ck_images_image_kind_allowed have to agree exactly. If they drift,
    nothing fails until an insert is attempted with the new value, by which
    point a listing has been processed and the result cannot be recorded.

    Parsed rather than imported, so this needs no database and no SQLAlchemy.
    """
    sources = [
        ROOT / "database" / "models.py",
        ROOT / "migrations" / "versions" / "d7e2c9a13f84_add_image_kind.py",
    ]

    for path in sources:
        # Adjacent string literals are folded into one constant by the parser,
        # so the clause arrives here in one piece however it was wrapped.
        clauses = [
            node.value
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "image_kind IN" in node.value
        ]
        assert clauses, f"no image_kind constraint found in {path.name}"
        allowed = tuple(re.findall(r"'([a-z_]+)'", clauses[0].split("IN", 1)[1]))
        assert allowed == KINDS, f"{path.name} allows {allowed}, KINDS is {KINDS}"


def test_every_described_kind_is_a_real_kind():
    assert set(KIND_PROMPTS) == set(KINDS) - {"unknown"}


def test_unknown_has_no_prompts():
    """It is the absence of an answer, not a kind of photograph."""
    assert "unknown" not in KIND_PROMPTS


def test_every_angle_is_described():
    assert set(ANGLE_PROMPTS) == set(ANGLES)


@pytest.mark.parametrize("prompts", [KIND_PROMPTS, ANGLE_PROMPTS])
def test_averaging_has_something_to_average(prompts):
    assert all(len(phrasings) >= 3 for phrasings in prompts.values())


# ── Flattening ─────────────────────────────────────────────────────────────────

def test_flatten_keeps_prompts_and_labels_in_step():
    texts, labels = _flatten({"a": ("one", "two"), "b": ("three",)})
    assert texts == ("one", "two", "three")
    assert labels == ("a", "a", "b")


# ── Scoring ────────────────────────────────────────────────────────────────────

def test_similarities_are_averaged_within_a_label():
    scores = _label_scores([0.2, 0.4, 0.9], ["a", "a", "b"])
    assert scores == {"a": pytest.approx(0.3), "b": pytest.approx(0.9)}


def test_a_mismatched_similarity_vector_is_an_error():
    """
    Silently truncating would misattribute every score after the first missing
    one, which is a wrong answer rather than a failure.
    """
    with pytest.raises(ValueError):
        _label_scores([0.1, 0.2], ["a", "a", "b"])


def test_probabilities_are_a_distribution():
    probabilities = _probabilities({"a": 0.30, "b": 0.25, "c": 0.20})
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for value in probabilities.values())
    assert probabilities["a"] > probabilities["b"] > probabilities["c"]


def test_probabilities_survive_the_logit_scale():
    """
    exp(0.3 * 100) overflows a float. The maximum has to come off first, and
    this is the arrangement where forgetting it raises rather than passes.
    """
    probabilities = _probabilities({"a": 8.0, "b": 7.5}, scale=1000.0)
    assert probabilities["a"] == pytest.approx(1.0)
    assert probabilities["b"] == pytest.approx(0.0)


def test_the_scale_is_what_spreads_them_out():
    scores = {"a": 0.30, "b": 0.28, "c": 0.20, "d": 0.19}
    flat = _probabilities(scores, scale=1.0)
    scaled = _probabilities(scores, scale=100.0)
    # Unscaled, a 0.02 lead is indistinguishable from chance.
    assert flat["a"] < 0.30
    assert scaled["a"] > flat["a"]


def test_an_empty_score_set_is_not_an_error():
    assert _probabilities({}) == {}


# ── The kind decision ──────────────────────────────────────────────────────────

def test_a_clear_exterior_is_accepted():
    probabilities = {
        "exterior": 0.90, "interior": 0.05, "detail": 0.03, "advertisement": 0.02
    }
    assert _decide_kind(probabilities) == ("exterior", 0.90)


def test_a_leader_below_the_threshold_is_unknown():
    probabilities = {
        "exterior": 0.40, "interior": 0.24, "detail": 0.20, "advertisement": 0.16
    }
    kind, confidence = _decide_kind(probabilities)
    assert kind == "unknown"
    assert confidence == 0.40, "the leader's probability is kept for tuning"


def test_a_leader_without_a_margin_is_unknown():
    """
    The failure this was built for. The finance banner is a photograph of a
    blue Mazda2 with a headline across it, so it fits "advertisement" and
    "exterior" almost equally. Whichever leads, it is not identified, and an
    unidentified photograph is not composited onto a turntable.
    """
    probabilities = {
        "exterior": 0.56, "advertisement": 0.44, "interior": 0.00, "detail": 0.00
    }
    assert _decide_kind(probabilities)[0] == "unknown"


def test_the_margin_is_measured_against_the_runner_up_only():
    # 0.60 against a 0.14 field: clear of everything, and accepted.
    probabilities = {
        "exterior": 0.60, "interior": 0.14, "detail": 0.13, "advertisement": 0.13
    }
    assert _decide_kind(probabilities)[0] == "exterior"


def test_nothing_at_all_is_unknown():
    assert _decide_kind({}) == ("unknown", 0.0)


def test_every_decidable_kind_can_actually_be_returned():
    for kind in set(KINDS) - {"unknown"}:
        probabilities = uniform(set(KINDS) - {"unknown"}, 0.05)
        probabilities[kind] = 0.85
        assert _decide_kind(probabilities)[0] == kind


def test_raising_the_threshold_holds_more_back(monkeypatch):
    """The environment override has to reach the decision, not just the module."""
    probabilities = {
        "exterior": 0.70, "interior": 0.15, "detail": 0.10, "advertisement": 0.05
    }
    assert _decide_kind(probabilities)[0] == "exterior"

    monkeypatch.setattr(classification, "CLIP_KIND_CONFIDENCE", 0.80)
    assert _decide_kind(probabilities)[0] == "unknown"


def test_widening_the_margin_holds_more_back(monkeypatch):
    probabilities = {
        "exterior": 0.60, "interior": 0.40, "detail": 0.00, "advertisement": 0.00
    }
    monkeypatch.setattr(classification, "CLIP_KIND_MARGIN", 0.05)
    assert _decide_kind(probabilities)[0] == "exterior"

    monkeypatch.setattr(classification, "CLIP_KIND_MARGIN", 0.30)
    assert _decide_kind(probabilities)[0] == "unknown"


def test_a_label_the_database_would_reject_is_not_returned():
    assert _decide_kind({"showroom": 0.99, "exterior": 0.01})[0] == "unknown"


# ── The angle decision ─────────────────────────────────────────────────────────

def test_a_confident_angle_is_reported():
    probabilities = uniform(ANGLES, 0.05)
    probabilities["front_quarter"] = 0.80
    assert _decide_angle(probabilities) == ("front_quarter", 0.80)


def test_adjacent_angles_do_not_need_a_margin():
    """
    Unlike the kind. A car turned slightly is genuinely between two of these,
    and requiring a margin would empty the field for most photographs while
    protecting against nothing worse than a wrong word.
    """
    probabilities = {
        "front": 0.36, "front_quarter": 0.34, "side": 0.15, "rear_quarter": 0.10,
        "rear": 0.05,
    }
    assert _decide_angle(probabilities) == ("front", 0.36)


def test_an_angle_too_close_to_call_is_left_empty():
    probabilities = uniform(ANGLES, 0.20)
    assert _decide_angle(probabilities) == (None, None)


def test_nothing_at_all_leaves_the_angle_empty():
    assert _decide_angle({}) == (None, None)


def test_an_unrecognised_angle_is_left_empty():
    assert _decide_angle({"overhead": 0.99}) == (None, None)


# ── Processability ─────────────────────────────────────────────────────────────

def test_a_confident_exterior_is_processable():
    assert is_processable(Classification("exterior", 0.90, "side", 0.60))


@pytest.mark.parametrize("kind", ["interior", "detail", "advertisement", "unknown"])
def test_nothing_else_is_processable(kind):
    assert not is_processable(Classification(kind, 0.99, None, None))


def test_an_exterior_below_the_threshold_is_not_processable():
    """
    Reachable through a stored row: the label was written when the threshold
    was lower than it is now.
    """
    assert not is_processable(Classification("exterior", 0.20, None, None))


def test_an_exterior_needs_no_angle_to_be_processable():
    """The angle is metadata. A car facing an unclear direction is still a car."""
    assert is_processable(Classification("exterior", 0.90, None, None))


# ── Health ─────────────────────────────────────────────────────────────────────

def test_health_reports_the_three_things_the_caller_wires_to():
    state = classification.health()
    assert set(state) == {"loaded", "device", "model"}
    assert isinstance(state["loaded"], bool)
    assert state["model"] == classification.CLIP_MODEL
    assert state["device"]


@pytest.mark.skipif(HAS_MODEL, reason="torch is installed, so it is available")
def test_health_does_not_claim_a_device_it_has_not_got():
    """
    Importing this module must work without torch — the light API and this
    suite both do it — and health() has to say so rather than answering "cpu".
    """
    assert classification.health()["device"] == "unavailable"


# ── classify(), with the model stood in for ────────────────────────────────────
# The model's whole contribution is one similarity per prompt, so a list of
# similarities stands in for it and the rest of classify() can be tested
# anywhere. What this is really checking is that the flat vector is still
# matched to the right labels — an ordering mistake there would be invisible in
# the arithmetic and would misclassify everything.

class StubRegistry:
    """Scores one kind and one angle above the rest by `lead`."""

    def __init__(self, kind: str, angle: str = "side", lead: float = 0.10) -> None:
        self.kind = kind
        self.angle = angle
        self.lead = lead

    def similarities(self, image):
        return (
            [0.20 + (self.lead if label == self.kind else 0.0)
             for label in classification._KIND_LABELS],
            [0.20 + (self.lead if label == self.angle else 0.0)
             for label in classification._ANGLE_LABELS],
        )


@pytest.fixture
def photograph():
    return Image.new("RGB", (64, 64), (90, 90, 90))


@pytest.mark.parametrize("kind", ["exterior", "interior", "detail", "advertisement"])
def test_classify_reports_the_kind_the_prompts_scored(monkeypatch, photograph, kind):
    monkeypatch.setattr(classification, "_registry", StubRegistry(kind))
    result = classification.classify(photograph)
    assert result.kind == kind
    assert result.kind_confidence > classification.CLIP_KIND_CONFIDENCE


def test_classify_finds_the_angle_of_an_exterior(monkeypatch, photograph):
    monkeypatch.setattr(
        classification, "_registry", StubRegistry("exterior", angle="rear_quarter")
    )
    result = classification.classify(photograph)
    assert (result.angle, result.kind) == ("rear_quarter", "exterior")
    assert result.angle_confidence > classification.CLIP_ANGLE_CONFIDENCE
    assert is_processable(result)


@pytest.mark.parametrize("kind", ["interior", "detail", "advertisement"])
def test_classify_does_not_give_a_non_exterior_an_angle(monkeypatch, photograph, kind):
    """
    The angle would be meaningless, and the field is shown to the dealer. It is
    also the contract the caller writes to the database against.
    """
    monkeypatch.setattr(classification, "_registry", StubRegistry(kind))
    result = classification.classify(photograph)
    assert result.angle is None and result.angle_confidence is None
    assert not is_processable(result)


def test_classify_falls_back_to_unknown_when_nothing_stands_out(monkeypatch, photograph):
    """A photograph no description fits is not guessed at."""
    monkeypatch.setattr(
        classification, "_registry", StubRegistry("exterior", lead=0.001)
    )
    result = classification.classify(photograph)
    assert result.kind == "unknown"
    assert not is_processable(result)


# ── With the model ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def loaded():
    try:
        classification._registry._load()
    except RuntimeError as exc:  # weights absent, or no network to fetch them
        pytest.skip(f"CLIP weights are not available here: {exc}")
    return classification._registry


@requires_model
def test_the_model_scores_every_prompt(loaded):
    kinds, angles = loaded.similarities(Image.new("RGB", (640, 480), (140, 140, 145)))
    assert len(kinds) == len(classification._KIND_LABELS)
    assert len(angles) == len(classification._ANGLE_LABELS)
    assert all(-1.0 <= value <= 1.0 for value in kinds + angles)


@requires_model
def test_a_blank_rectangle_is_not_composited(loaded):
    """
    A flat grey field is not a photograph of a car by any reading. Whatever it
    scores as, the one thing that must not happen is that it is processed.
    """
    result = classification.classify(Image.new("RGB", (640, 480), (140, 140, 145)))
    assert result.kind in KINDS
    assert 0.0 <= result.kind_confidence <= 1.0
    assert not is_processable(result)


@requires_model
def test_an_image_with_transparency_is_accepted(loaded):
    """
    Banners and badges arrive as RGBA PNGs. The fourth channel has to be dealt
    with here rather than in whatever version of the processor is installed.
    """
    result = classification.classify(Image.new("RGBA", (300, 300), (10, 20, 30, 0)))
    assert result.kind in KINDS


@requires_model
def test_the_angle_is_only_asked_about_exteriors(loaded):
    result = classification.classify(Image.new("RGB", (640, 480), (140, 140, 145)))
    if result.kind != "exterior":
        assert result.angle is None and result.angle_confidence is None


# ── The import-time size filter ────────────────────────────────────────────────
# api/url_import.py, tested here because it is the first half of the same
# defence: the badges and rating graphics it drops never reach the classifier.

def encoded(width: int, height: int, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


@requires_url_import
@pytest.mark.parametrize("size", [(105, 81), (210, 71)])
def test_the_images_that_caused_this_are_rejected(size):
    """bluecorner.png and star-4.png, both imported from a 2cheapcars listing."""
    assert not url_import.is_large_enough(encoded(*size))


@requires_url_import
def test_a_photograph_is_kept():
    assert url_import.is_large_enough(encoded(800, 600))
    assert url_import.is_large_enough(encoded(800, 600, fmt="JPEG"))


@requires_url_import
def test_the_shorter_side_is_what_counts():
    """A banner is wide. Measuring the longer side would let every one through."""
    assert not url_import.is_large_enough(encoded(1200, 90))


@requires_url_import
def test_the_floor_is_inclusive():
    floor = url_import.MIN_IMAGE_PIXELS
    assert url_import.is_large_enough(encoded(floor, floor))
    assert not url_import.is_large_enough(encoded(floor, floor - 1))


@requires_url_import
@pytest.mark.parametrize("content", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\n"])
def test_anything_unreadable_is_rejected(content):
    """Including a truncated PNG header, which is a fetch that went wrong."""
    assert not url_import.is_large_enough(content)
