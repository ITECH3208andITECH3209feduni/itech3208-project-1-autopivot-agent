/// On-device "is there a car here, and is it framed well" check — a cheap
/// first filter so an obviously-wrong photograph (nothing in frame, a wall,
/// a person) never leaves the phone, rather than being rejected only after
/// a full round trip to the server. The server's own classifier
/// (`classification.py`) stays the real authority on whether a photograph
/// is usable — this is advisory-and-blocking on-device, not a replacement
/// for it: anything this misses, the server still catches, which is why
/// this can afford to be a cheap, approximate filter rather than a
/// perfectly accurate one.
///
/// Built from two off-the-shelf ML Kit models rather than a bundled custom
/// detector, on purpose. Ultralytics' YOLO weights — the obvious "best"
/// detector for this — are AGPL-3.0 even pretrained, confirmed directly
/// from Ultralytics' own licensing page: that licence applies "regardless
/// of whether you... use pretrained weights... or deploy internally", and
/// covers the weights themselves, not just training code. Shipping those
/// inside a compiled, distributed commercial app is exactly what their paid
/// Enterprise licence exists to gate — not usable here without buying it.
/// ML Kit's on-device SDKs need no bundled model file at all, which
/// sidesteps that question entirely:
///   - Image Labeling answers "is a car-like thing here" — its default
///     model's published label map includes Car/Vehicle/Van.
///   - Object Detection is used only for its bounding box; its own coarse
///     category output is NOT vehicle-aware (5 generic categories, no
///     "vehicle" among them), so that part is ignored. The box exists
///     purely to drive closer/further/centred guidance once labeling has
///     already said yes.
///
/// Box quality when a vehicle fills most of the frame — the normal case at
/// capture distance — was flagged as unverified from documentation alone;
/// Google's own demos are mostly smaller foreground objects. The thresholds
/// below are a reasonable starting point, not something measured on a real
/// device (this environment has no camera hardware to test detection
/// against at all — see capture_screen.dart's doc comment). Tune
/// [VehicleFrameDetector.minVehicleAreaRatio],
/// [VehicleFrameDetector.maxVehicleAreaRatio] and
/// [VehicleFrameDetector.centerTolerance] against how this actually behaves
/// once tried on a phone; nothing about the surrounding wiring needs to
/// change to retune them.
library;

import 'dart:io';
import 'dart:ui';

import 'package:camera/camera.dart';
import 'package:google_mlkit_image_labeling/google_mlkit_image_labeling.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';

/// What the last detection pass found, and what it means for the shutter.
enum FrameGuidance {
  /// Nothing car-like found — labeling never returned a confident match.
  noVehicle('No vehicle detected — point the camera at the car.'),

  /// A vehicle was found but its box is too small a share of the frame.
  tooFar('Move closer.'),

  /// A vehicle was found but its box is nearly the whole frame.
  tooClose('Move back a little.'),

  /// A vehicle was found, reasonably sized, but off to one side.
  notCentered('Centre the vehicle in the frame.'),

  /// Detected, well-sized, centred — nothing standing in the way of a shot.
  good('');

  const FrameGuidance(this.message);

  /// Shown to the photographer. Empty for [good] — there is nothing to say
  /// when nothing is wrong.
  final String message;

  /// Every state but [good] disables the shutter.
  bool get blocksCapture => this != FrameGuidance.good;
}

class VehicleFrameDetector {
  VehicleFrameDetector()
    : _labeler = ImageLabeler(
        options: ImageLabelerOptions(confidenceThreshold: 0.5),
      ),
      _detector = ObjectDetector(
        options: ObjectDetectorOptions(
          mode: DetectionMode.stream,
          classifyObjects: false,
          multipleObjects: false,
        ),
      );

  final ImageLabeler _labeler;
  final ObjectDetector _detector;

  /// Below this share of the frame's area, the vehicle reads as too far
  /// away to be a usable shot.
  static const double minVehicleAreaRatio = 0.15;

  /// Above this share, the vehicle is cropped too tight — back up a step.
  static const double maxVehicleAreaRatio = 0.95;

  /// How far the detected box's centre may drift from the frame's centre,
  /// as a fraction of frame width/height, before it reads as "off to one
  /// side" rather than centred.
  static const double centerTolerance = 0.20;

  /// Substrings matched case-insensitively against ML Kit's returned
  /// labels. Broader than just "car"/"vehicle" on purpose — Image
  /// Labeling's default model can return a more specific sub-class (e.g.
  /// "Pickup truck", "Convertible") instead of the generic term, and a
  /// narrow exact-match list would miss those.
  static const _vehicleLabelHints = [
    'car',
    'vehicle',
    'van',
    'truck',
    'bus',
    'sports car',
    'pickup truck',
    'convertible',
    'jeep',
    'minivan',
    'cab',
    'wheel',
  ];

  bool _busy = false;

  /// Runs one detection pass. Returns null if a pass is already in flight
  /// (the caller should just skip this frame rather than queue it up) or if
  /// ML Kit itself throws — a detection failure degrades to "say nothing"
  /// rather than blocking the shutter on an error that has nothing to do
  /// with whether a car is actually there.
  Future<FrameGuidance?> analyze(InputImage image) async {
    if (_busy) return null;
    _busy = true;
    try {
      final labels = await _labeler.processImage(image);
      final sawVehicle = labels.any(
        (l) => _vehicleLabelHints.any(
          (hint) => l.label.toLowerCase().contains(hint),
        ),
      );
      if (!sawVehicle) return FrameGuidance.noVehicle;

      final objects = await _detector.processImage(image);
      if (objects.isEmpty) return FrameGuidance.noVehicle;

      final size = image.metadata?.size;
      if (size == null || size.width <= 0 || size.height <= 0) {
        // No usable frame dimensions to size or centre a box against — a
        // vehicle-ish label was still seen, so let the shot through rather
        // than blocking on a measurement this frame cannot provide.
        return FrameGuidance.good;
      }

      final box = objects.first.boundingBox;
      final frameArea = size.width * size.height;
      final areaRatio = (box.width * box.height) / frameArea;
      if (areaRatio < minVehicleAreaRatio) return FrameGuidance.tooFar;
      if (areaRatio > maxVehicleAreaRatio) return FrameGuidance.tooClose;

      final dx = (box.center.dx - size.width / 2).abs() / size.width;
      final dy = (box.center.dy - size.height / 2).abs() / size.height;
      if (dx > centerTolerance || dy > centerTolerance) {
        return FrameGuidance.notCentered;
      }

      return FrameGuidance.good;
    } catch (_) {
      return null;
    } finally {
      _busy = false;
    }
  }

  Future<void> dispose() async {
    await _labeler.close();
    await _detector.close();
  }
}

/// Converts a live [CameraImage] from `controller.startImageStream` into
/// the [InputImage] ML Kit expects.
///
/// iOS-only for now — this app is iOS-first this session (see the doc
/// comment at the top of capture_screen.dart), and Android's rotation maths
/// (sensor orientation combined with device orientation) is genuinely
/// different from iOS's, not just a different enum value. Returns null on
/// Android rather than guessing at that maths and shipping it untested: on
/// Android this feature simply does not run yet, which fails safe — the
/// shutter behaves exactly as it did before this feature existed — rather
/// than failing by handing ML Kit an incorrectly-rotated image it would
/// silently misread.
InputImage? inputImageFromCameraImage(
  CameraImage image,
  CameraDescription camera,
) {
  if (!Platform.isIOS) return null;

  final rotation = InputImageRotationValue.fromRawValue(
    camera.sensorOrientation,
  );
  if (rotation == null) return null;

  final reportedFormat = InputImageFormatValue.fromRawValue(image.format.raw);
  if (reportedFormat != InputImageFormat.bgra8888) return null;
  const format = InputImageFormat.bgra8888;

  final plane = image.planes.first;
  return InputImage.fromBytes(
    bytes: plane.bytes,
    metadata: InputImageMetadata(
      size: Size(image.width.toDouble(), image.height.toDouble()),
      rotation: rotation,
      format: format,
      bytesPerRow: plane.bytesPerRow,
    ),
  );
}
