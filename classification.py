"""Deciding what a photograph is of, before anything is done to it.

A URL import returns whatever the listing page published. On a 2cheapcars
listing that is around twenty images, and only some of them are the car: the
rest are interior shots, a close-up of a wheel, the dealership's own badges,
safety-rating graphics and finance advertisements.

The vehicle detector cannot separate those, and that is not a fault in it. The
"FINANCE MADE EASY" banner on one of those listings contains a real photograph
of a blue Mazda2, so YOLO finds a car in it — correctly. That Mazda was then
cut out, composited onto the studio turntable and published in a Nissan Note's
gallery. A close-up of a steering wheel went through the same path and came
back standing on the turntable. Both are what this module exists to stop.

"Is this a photograph of a whole car from outside?" is a question about what
the picture *is*, not about what objects appear in it, and that is the question
CLIP answers well: image and text are embedded in one space and compared, so a
written description of each kind of photograph is enough to sort them. The
descriptions live in KIND_PROMPTS below, several per kind, and the best-scoring
kind wins provided it wins clearly. Otherwise the answer is "unknown", which is
not processed.

The bar is deliberately set so that the likely failure is a whole-car
photograph being held back for the dealer to re-include, rather than a stranger's
car reaching their listing. The first costs a click; the second is published.

torch and transformers are imported inside the loader rather than at module
scope, so importing this module costs nothing and works where no vision stack
is installed — the light API and most of the test suite are both such places.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from PIL import Image

logger = logging.getLogger("autopivot.classification")

# These are the values images.image_kind accepts: the check constraint
# ck_images_image_kind_allowed lists them, so a fifth string invented here
# would fail at the database rather than anywhere useful.
KINDS: tuple[str, ...] = ("exterior", "interior", "detail", "advertisement", "unknown")

# Written to processing_jobs.detected_angle, which has no vocabulary
# constraint, so this tuple is the only definition of the terms.
ANGLES: tuple[str, ...] = ("front", "front_quarter", "side", "rear_quarter", "rear")

CLIP_MODEL: str = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")

# ── Thresholds ─────────────────────────────────────────────────────────────────
# A wrong exclusion costs the dealer one click to put the photograph back. A
# wrong inclusion puts somebody else's car in their listing, under their
# stock number, where a buyer sees it. These values are chosen to make the
# first failure the likely one.
#
# They are reasoned from the shape of the distribution below rather than
# measured against labelled photographs, because the machine they were written
# on has no vision stack. Run `python classification.py <images>` on a pod
# against a real listing and move them: that is what the environment overrides
# are for, and they are the only part of this module worth tuning.

# How much of the probability mass the winning kind must hold outright.
# Chance across the four described kinds is 0.25.
CLIP_KIND_CONFIDENCE: float = float(os.getenv("CLIP_KIND_CONFIDENCE", "0.55"))

# How far ahead of the runner-up it must be. This is the condition that catches
# the failure this module was written for: a finance banner built around a
# photograph of a car scores respectably as both "advertisement" and
# "exterior", and a threshold on the leader alone would let it through on the
# strength of the photograph inside it.
CLIP_KIND_MARGIN: float = float(os.getenv("CLIP_KIND_MARGIN", "0.15"))

# The angle is metadata beside a photograph, not a gate on processing, so it
# gets a lower bar and no margin requirement — see _decide_angle.
CLIP_ANGLE_CONFIDENCE: float = float(os.getenv("CLIP_ANGLE_CONFIDENCE", "0.35"))

# Cosine similarities from this checkpoint sit in a narrow band — a good match
# scores around 0.3 and a poor one around 0.2. CLIP was trained with a learned
# scale — exp(4.6052) ≈ 100 in the released weights — applied before the
# softmax, and without it every kind comes out near 0.25 and no threshold above
# means anything. Hard-coded rather than read from the model so that swapping
# the checkpoint cannot silently move the thresholds underneath us.
CLIP_LOGIT_SCALE: float = float(os.getenv("CLIP_LOGIT_SCALE", "100.0"))


# ── Prompts ────────────────────────────────────────────────────────────────────
# Where the accuracy lives. Three things are being bought by the wording:
#
#   * Several phrasings per kind, averaged. One phrasing carries whatever
#     incidental associations its particular words have — "a photo of a car"
#     matches an advertisement for a car about as well as a photograph of one —
#     and averaging over descriptions that differ in their incidentals leaves
#     what they have in common, which is the kind itself.
#   * Descriptions of the *photograph*, not of the object. "a whole car, the
#     entire vehicle in frame" separates from "a close-up of one car wheel"
#     in a way that "a car" and "a wheel" do not, because a wheel close-up
#     genuinely contains a car.
#   * Explicit mention of rendered text in the advertisement prompts. CLIP
#     reads text in images strongly, which is usually a nuisance and is exactly
#     what is wanted here: the banner that caused this is 40% headline.
#
# "unknown" has no prompts. It is not a kind of photograph, it is what is
# returned when none of these descriptions won clearly enough.

KIND_PROMPTS: dict[str, tuple[str, ...]] = {
    "exterior": (
        "a photograph of a whole car, the entire vehicle in frame",
        "an exterior photograph of a parked car, taken from outside it",
        "a used car for sale, the complete vehicle photographed in a car park",
        "a car listing photograph showing the body, wheels and windows of one car",
        # Dealer photographs routinely carry a watermark. Without this the
        # advertisement prompts claim them, because they also mention text.
        "a photograph of a whole car with a small dealership watermark in the corner",
        "a car standing outdoors, photographed from a few metres away",
    ),
    "interior": (
        "a photograph taken from inside a car, showing the steering wheel and dashboard",
        "the interior of a car, showing the seats and the door trim",
        "a car's dashboard and instrument cluster, photographed from the driver's seat",
        "the inside of a car's cabin, showing the gear lever and centre console",
        # The reversing-camera screen shows a view of the road behind, which
        # reads as an outdoor photograph unless it is described as a screen.
        "a car's infotainment touchscreen displaying the reversing camera view",
        "the rear seats and boot space of a car, photographed from inside",
    ),
    "detail": (
        "a close-up photograph of one car wheel and tyre",
        "a close-up of a small part of a car, filling the whole frame",
        "a close-up photograph of a car's headlight",
        "a close-up of a car's badge or bonnet emblem",
        "a photograph of a car's engine bay with the bonnet open",
        "a detail photograph of a scratch or a dent in a car's paintwork",
    ),
    "advertisement": (
        "an advertisement banner with large text written across it",
        "a car dealership advertisement offering finance, with a headline in big letters",
        "a promotional graphic with a slogan and a telephone number",
        # The specific defect: a banner whose artwork is a real photograph of a
        # car. It has to beat the exterior prompts on the strength of the text.
        "a marketing banner combining a photograph of a car with large advertising text",
        "a company logo on a plain background",
        "a safety rating graphic showing a row of stars",
        "a poster, a sign or a screenshot of a web page, mostly writing",
    ),
}

# Only asked once the kind is settled as exterior, so these need not compete
# with interiors or banners — only with each other. They describe which parts
# of the car face the camera, since that is what is actually visible in the
# pixels; naming the angle in degrees is not something CLIP has learnt.
ANGLE_PROMPTS: dict[str, tuple[str, ...]] = {
    "front": (
        "a car photographed head-on from the front, both headlights and the grille facing the camera",
        "the front of a car, straight on and symmetrical, no side of the car visible",
        "a car facing the camera directly, showing its front bumper and number plate",
    ),
    "front_quarter": (
        "a car photographed from the front three-quarter angle, showing the front and one side together",
        "a three-quarter front view of a car, the bonnet and the side doors both visible",
        "a car turned at an angle, showing its grille and the length of one side",
    ),
    "side": (
        "a car photographed from directly beside it, a full side profile",
        "the side profile of a car, both wheels in a line, neither the front nor the back visible",
        "a side-on photograph of a car showing the doors and the whole length of the body",
    ),
    "rear_quarter": (
        "a car photographed from the rear three-quarter angle, showing the back and one side together",
        "a three-quarter rear view of a car, the boot and the side doors both visible",
        "a car turned at an angle, showing its tail lights and the length of one side",
    ),
    "rear": (
        "a car photographed head-on from behind, both tail lights and the boot facing the camera",
        "the back of a car, straight on, showing the rear bumper and number plate",
        "a car facing away from the camera, showing its tailgate and rear window",
    ),
}


@dataclass(frozen=True)
class Classification:
    """
    What one photograph is, and how sure of it we are.

    kind_confidence is the probability of the leading description. Where kind
    is "unknown" that is the description the decision fell short on, kept
    rather than zeroed because it is the number worth looking at when deciding
    whether the thresholds are set right.

    angle and angle_confidence are None for anything that is not a confident
    exterior, and also for an exterior whose angle was too close to call.
    """

    kind: str
    kind_confidence: float
    angle: Optional[str]
    angle_confidence: Optional[float]


# ── Prompt bookkeeping ─────────────────────────────────────────────────────────

def _flatten(prompts: Mapping[str, Sequence[str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    One flat list of prompt texts, and the label each of them belongs to.

    The model is given the flat list and returns one similarity per prompt in
    the same order, so the labels are what puts the scores back together again.
    """
    texts: list[str] = []
    labels: list[str] = []
    for label, phrasings in prompts.items():
        for phrasing in phrasings:
            texts.append(phrasing)
            labels.append(label)
    return tuple(texts), tuple(labels)


_KIND_TEXTS, _KIND_LABELS = _flatten(KIND_PROMPTS)
_ANGLE_TEXTS, _ANGLE_LABELS = _flatten(ANGLE_PROMPTS)


# ── Scoring ────────────────────────────────────────────────────────────────────
# Deliberately free of torch and of numpy. The model's only contribution is a
# list of similarities; everything that decides an outcome from them is here,
# where it can be exercised on a machine with no vision stack — which is where
# this was written, and where the thresholds have to be reasoned about.

def _label_scores(
    similarities: Sequence[float], labels: Sequence[str]
) -> dict[str, float]:
    """Mean similarity per label, over that label's phrasings."""
    if len(similarities) != len(labels):
        raise ValueError(
            f"{len(similarities)} similarities for {len(labels)} prompts — "
            "the prompt list and the model's output have gone out of step"
        )

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for value, label in zip(similarities, labels):
        totals[label] = totals.get(label, 0.0) + float(value)
        counts[label] = counts.get(label, 0) + 1
    return {label: totals[label] / counts[label] for label in totals}


def _probabilities(
    scores: Mapping[str, float], scale: Optional[float] = None
) -> dict[str, float]:
    """
    Softmax over label scores, at CLIP's own logit scale unless told otherwise.

    The scale is resolved at call time rather than bound as a default argument,
    so that changing CLIP_LOGIT_SCALE actually changes what this does.

    The maximum is subtracted before exponentiating. That is arithmetically a
    no-op and numerically the difference between a distribution and an
    overflow, which matters here because the scale is 100.
    """
    if not scores:
        return {}

    if scale is None:
        scale = CLIP_LOGIT_SCALE
    logits = {label: value * scale for label, value in scores.items()}
    highest = max(logits.values())
    weights = {label: math.exp(value - highest) for label, value in logits.items()}
    total = sum(weights.values())
    return {label: weight / total for label, weight in weights.items()}


def _ranked(probabilities: Mapping[str, float]) -> list[tuple[str, float]]:
    """Labels by descending probability, ties broken by name so runs repeat."""
    return sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))


def _decide_kind(probabilities: Mapping[str, float]) -> tuple[str, float]:
    """
    The winning kind, or "unknown" when the win is not clear enough.

    Both conditions have to hold: the leader clears CLIP_KIND_CONFIDENCE
    outright, and it is CLIP_KIND_MARGIN clear of whatever came second. A
    photograph that two descriptions fit almost equally well is a photograph we
    have not identified, whichever of them happens to lead.
    """
    ranked = _ranked(probabilities)
    if not ranked:
        return "unknown", 0.0

    kind, confidence = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if confidence < CLIP_KIND_CONFIDENCE:
        return "unknown", confidence
    if confidence - runner_up < CLIP_KIND_MARGIN:
        return "unknown", confidence
    if kind not in KINDS:
        # Only reachable if the prompt table gains a label the database will
        # not accept; failing to "unknown" is better than failing at the insert.
        logger.warning("Prompt label %r is not one of KINDS — recording unknown.", kind)
        return "unknown", confidence
    return kind, confidence


def _decide_angle(
    probabilities: Mapping[str, float]
) -> tuple[Optional[str], Optional[float]]:
    """
    Which way the car faces, or None when it is too close to call.

    No margin requirement, unlike the kind. Adjacent angles genuinely resemble
    each other — a car turned slightly is somewhere between "front" and "front
    quarter", and no wording separates them cleanly — so requiring a margin
    would empty the field for most photographs. The asymmetry is deliberate:
    a mislabelled angle is a wrong word beside a correct picture, whereas a
    mislabelled kind is a wrong picture.

    Below the threshold the answer is None rather than the leading guess. The
    value reaches the dealer's screen, and an angle nothing supports is worse
    than an empty field.
    """
    ranked = _ranked(probabilities)
    if not ranked:
        return None, None

    angle, confidence = ranked[0]
    if confidence < CLIP_ANGLE_CONFIDENCE or angle not in ANGLES:
        return None, None
    return angle, confidence


# ── Model ──────────────────────────────────────────────────────────────────────

def _available_device() -> str:
    """
    Where the model would run, for health() to report before anything is loaded.

    torch is imported here rather than at module scope for the reason given in
    the module docstring. "unavailable" is the honest answer where there is no
    torch at all; answering "cpu" would suggest the classifier could run.
    """
    try:
        import torch
    except ImportError:
        return "unavailable"
    return "cuda" if torch.cuda.is_available() else "cpu"


class _ClipRegistry:
    """
    Lazily-loaded CLIP, following ModelRegistry in autopivot_backend.py.

    The lock is there for the same reason as the ones on the detectors: sync
    FastAPI endpoints run in a thread pool and a listing is processed image by
    image, so two threads can reach an unloaded model at the same moment.
    Without the re-check inside the lock both would load it, and the second
    would replace the first mid-inference.

    Not shared with that registry, and not imported from it: autopivot_backend
    imports this module, so this module cannot import it back.
    """

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._torch = None
        # Text features for every prompt, unit length, in _KIND_TEXTS and
        # _ANGLE_TEXTS order. Computed once at load: the prompts never change,
        # so per-image work is one image encode and two small matrix products.
        self._kind_features = None
        self._angle_features = None
        self._device: str = ""
        self._ok = False
        self._lock = threading.RLock()

    @property
    def device(self) -> str:
        return self._device or _available_device()

    def _load(self) -> None:
        with self._lock:
            # Re-checked inside the lock: a thread that blocked here may have
            # been waiting on the very load it was about to start.
            if self._ok:
                return

            logger.info("Loading CLIP classifier — %s", CLIP_MODEL)
            try:
                import torch
                from transformers import CLIPModel, CLIPProcessor

                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = CLIPModel.from_pretrained(CLIP_MODEL).eval().to(device)
                processor = CLIPProcessor.from_pretrained(CLIP_MODEL)

                self._kind_features = _encode_text(
                    model, processor, _KIND_TEXTS, device, torch
                )
                self._angle_features = _encode_text(
                    model, processor, _ANGLE_TEXTS, device, torch
                )
            except Exception as exc:
                logger.critical("CLIP classifier failed to load: %s", exc, exc_info=True)
                raise RuntimeError(f"Image classifier unavailable: {exc}") from exc

            self._torch = torch
            self._model = model
            self._processor = processor
            self._device = device
            self._ok = True
            logger.info("CLIP classifier loaded on %s", device)

    def similarities(self, image: Image.Image) -> tuple[list[float], list[float]]:
        """Cosine similarity of one image against every kind and angle prompt."""
        if not self._ok:
            self._load()

        torch = self._torch
        # Converted here rather than assumed: banners arrive as PNGs with an
        # alpha channel, and what the processor does with a fourth channel is
        # not something to leave to the version installed on the day.
        inputs = self._processor(images=image.convert("RGB"), return_tensors="pt")
        inputs = {name: value.to(self._device) for name, value in inputs.items()}

        with torch.no_grad():
            features = self._model.get_image_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
            kind = (features @ self._kind_features.T).squeeze(0)
            angle = (features @ self._angle_features.T).squeeze(0)

        return kind.float().cpu().tolist(), angle.float().cpu().tolist()

    def health(self) -> dict:
        return {"loaded": self._ok, "device": self.device, "model": CLIP_MODEL}


def _encode_text(model, processor, prompts: Sequence[str], device: str, torch):
    """Unit-length text features for a list of prompts, in the order given."""
    inputs = processor(text=list(prompts), return_tensors="pt", padding=True)
    inputs = {name: value.to(device) for name, value in inputs.items()}
    with torch.no_grad():
        features = model.get_text_features(**inputs)
    return features / features.norm(dim=-1, keepdim=True)


_registry = _ClipRegistry()


# ── Entry points ───────────────────────────────────────────────────────────────

def classify(image: Image.Image) -> Classification:
    """
    Say what a photograph is of.

    Raises RuntimeError if the model cannot be loaded. That is left to the
    caller rather than answered with "unknown": a deployment where CLIP is
    missing should stop and say so, not quietly decide that every photograph a
    dealer imported is unidentifiable.
    """
    kind_similarities, angle_similarities = _registry.similarities(image)

    kind_probabilities = _probabilities(
        _label_scores(kind_similarities, _KIND_LABELS)
    )
    kind, kind_confidence = _decide_kind(kind_probabilities)

    if kind != "exterior":
        logger.debug(
            "Classified as %s (%.2f) — kinds: %s",
            kind, kind_confidence, kind_probabilities,
        )
        return Classification(kind, kind_confidence, None, None)

    angle_probabilities = _probabilities(
        _label_scores(angle_similarities, _ANGLE_LABELS)
    )
    angle, angle_confidence = _decide_angle(angle_probabilities)
    logger.debug(
        "Classified as exterior (%.2f), angle %s — kinds: %s, angles: %s",
        kind_confidence, angle, kind_probabilities, angle_probabilities,
    )
    return Classification(kind, kind_confidence, angle, angle_confidence)


def is_processable(result: Classification) -> bool:
    """
    Whether this photograph may be cut out and composited onto a backdrop.

    Confident exteriors only. The threshold is re-applied rather than the label
    trusted, because a Classification can also be rebuilt from a stored row —
    written, possibly, under a lower threshold than the one now in force.
    """
    return (
        result.kind == "exterior"
        and result.kind_confidence >= CLIP_KIND_CONFIDENCE
    )


def health() -> dict:
    """Whether the classifier is loaded, where it runs, and which checkpoint."""
    return _registry.health()


if __name__ == "__main__":
    # The prompts were written on a machine with no vision stack, so this is
    # how they get checked against real photographs on one that has it:
    #
    #     python classification.py storage/listings/*/original/*.jpg
    #
    # It prints the decision and the full distribution, which is what shows
    # whether a misclassification was close or not close at all.
    import sys

    for path in sys.argv[1:]:
        with Image.open(path) as opened:
            kind_similarities, angle_similarities = _registry.similarities(opened)

        kinds = _probabilities(_label_scores(kind_similarities, _KIND_LABELS))
        angles = _probabilities(_label_scores(angle_similarities, _ANGLE_LABELS))
        kind, confidence = _decide_kind(kinds)
        verdict = Classification(kind, confidence, *_decide_angle(angles))

        print(f"{path}\n  {kind} {confidence:.3f} processable={is_processable(verdict)}")
        for label, probability in _ranked(kinds):
            print(f"    {label:<14} {probability:.3f}")
        if kind == "exterior":
            print(f"    angle: {verdict.angle}")
            for label, probability in _ranked(angles):
                print(f"    {label:<14} {probability:.3f}")
