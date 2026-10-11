# PLATE_CONFIDENCE has to reach the plate detector, not only filter what it
# returns.
#
# The detector is a transformers object-detection pipeline, and that pipeline
# drops low scores itself before anything here sees a detection:
# ObjectDetectionPipeline.postprocess(model_outputs, threshold=0.5) uses 0.5
# unless the call passes a threshold of its own (transformers 4.45,
# pipelines/object_detection.py). _detect_plates called it without one, so a
# plate the model scored 0.42 was discarded inside the pipeline, the 0.30 filter
# after it never saw the plate, and it went out readable. Any PLATE_CONFIDENCE
# below 0.5 did nothing at all.
#
# These import autopivot_backend, which needs the ML environment
# (requirements-ml.txt). No model is loaded: the registry is handed a stand-in
# that filters scores the way the real pipeline does, default included.
#
#     pytest tests/test_plate_detection_threshold.py -v

import math

import pytest
import torch
from PIL import Image
from transformers import (
    ObjectDetectionPipeline,
    YolosConfig,
    YolosForObjectDetection,
    YolosImageProcessor,
)

import autopivot_backend as backend


# ObjectDetectionPipeline.postprocess's default when the call passes none.
PIPELINE_DEFAULT_THRESHOLD = 0.5

SHIPPED_PLATE_CONFIDENCE = 0.30


class ObjectDetectionPipelineStandIn:
    """
    Answers the way transformers' ObjectDetectionPipeline does: a list of
    {"score", "label", "box"} dicts, keeping only scores above the threshold —
    the call's own if it passes one, 0.5 if it does not.
    """

    def __init__(self, detections):
        self._detections = detections

    def __call__(self, image, **kwargs):
        threshold = kwargs.get("threshold", PIPELINE_DEFAULT_THRESHOLD)
        return [d for d in self._detections if d["score"] > threshold]


def yolos_pipeline(score, centre, size):
    """
    The real ObjectDetectionPipeline, around a YOLOS model small enough to build
    on the spot, so nothing is downloaded.

    Its weights are random except the last layer of each head, which is zeroed
    and given a bias, so the one detection token always reports the same box:
    `centre` and `size` as fractions of the image, with probability `score` of
    being a plate.
    """

    def logit(p):
        return math.log(p / (1 - p))

    config = YolosConfig(
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=37,
        image_size=[64, 64],
        patch_size=16,
        num_detection_tokens=1,
        num_labels=1,
        id2label={0: "license-plates"},
        label2id={"license-plates": 0},
    )
    model = YolosForObjectDetection(config).eval()
    with torch.no_grad():
        classes = model.class_labels_classifier.layers[-1]
        classes.weight.zero_()
        # A softmax over (plate, no object) at logits (logit(score), 0) is score.
        classes.bias.copy_(torch.tensor([logit(score), 0.0]))
        boxes = model.bbox_predictor.layers[-1]
        boxes.weight.zero_()
        # The box head is read through a sigmoid: centre x, centre y, width, height.
        boxes.bias.copy_(torch.tensor([logit(v) for v in (*centre, *size)]))

    return ObjectDetectionPipeline(
        model=model,
        image_processor=YolosImageProcessor(
            size={"shortest_edge": 64, "longest_edge": 64}
        ),
    )


def detection(score, box=(40, 120, 180, 170)):
    xmin, ymin, xmax, ymax = box
    return {
        "score": score,
        "label": "license-plates",
        "box": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
    }


def photograph():
    return Image.new("RGB", (400, 300), (90, 90, 90))


@pytest.fixture
def install_detector(monkeypatch):
    """Put a detector on the registry, so the real one is never loaded."""

    def install(detector):
        monkeypatch.setattr(backend.registry, "_plates", detector)
        monkeypatch.setattr(backend.registry, "_plates_ok", True)

    return install


@pytest.fixture(autouse=True)
def shipped_confidence(monkeypatch):
    # Pinned so a PLATE_CONFIDENCE in the developer's environment cannot
    # change what "the default setting" means here.
    monkeypatch.setattr(backend, "PLATE_CONFIDENCE", SHIPPED_PLATE_CONFIDENCE)


def test_a_plate_scored_between_the_setting_and_the_pipelines_default_is_found(
    install_detector,
):
    install_detector(ObjectDetectionPipelineStandIn([detection(0.42)]))

    found = backend._detect_plates(photograph())

    assert [d["score"] for d in found] == [0.42]


def test_the_real_pipeline_hands_back_a_plate_it_scores_below_its_own_default(
    install_detector,
):
    """
    The stand-in is only as right as its idea of the pipeline, so the same case
    runs through the library's own class: the keyword and the 0.5 default are
    transformers', and an upgrade that renamed or moved either fails here
    instead of quietly bringing the dead setting back.
    """
    install_detector(yolos_pipeline(score=0.42, centre=(0.5, 0.5), size=(0.35, 0.1)))

    found = backend._detect_plates(photograph())

    assert [round(d["score"], 4) for d in found] == [0.42]


def test_scores_at_or_below_the_setting_are_dropped_whatever_the_detector_returns(
    install_detector,
):
    """
    The explicit filter stays as a second line: a detector that applies no
    threshold of its own — built with threshold=0, or a pipeline whose keyword
    changes name — must not turn every faint guess into an obscured patch.
    """
    everything = [detection(0.2), detection(0.30), detection(0.42)]
    install_detector(lambda image, **kwargs: list(everything))

    found = backend._detect_plates(photograph())

    assert [d["score"] for d in found] == [0.42]
