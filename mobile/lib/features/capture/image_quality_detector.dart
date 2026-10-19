/// A cheap, on-device check for two defects the pipeline has never caught
/// before this: a motion-blurred shot, and a shot blown out by glare on the
/// car's own paint. Neither `vehicle_frame_detector.dart`'s ML Kit check nor
/// the server's classifier (today) look at either — a photograph can be a
/// perfectly framed, perfectly centred car and still be useless because the
/// photographer's hand moved or the sun bounced straight off a door panel.
///
/// Runs on the same camera frame `capture_screen.dart`'s stream is already
/// decoding, at the same throttled cadence — no extra frame capture, just
/// extra arithmetic on bytes already in hand. Which bytes those are depends
/// on platform: iOS hands over BGRA8888 (the format ML Kit's own frame also
/// arrives in), Android NV21 — see [_lumaReader], the one place in this
/// file that has to know the difference. Everything below works in plain
/// 0-255 luma, oblivious to which format produced it. Deliberately samples
/// a sparse grid (every [_stride]th pixel) rather than every pixel:
/// a full-resolution double loop in Dart on a live camera frame would cost
/// far more than the 400ms analysis budget this shares with ML Kit allows,
/// and a sparse grid is entirely sufficient for a coarse "is this obviously
/// blurred or blown out" signal — this was never trying to be a precise
/// image-quality metric, just a cheap filter for the worst cases.
///
/// The sharpness figure is a proxy for Laplacian variance, not the real
/// thing: instead of a proper 3x3 convolution kernel, it sums the absolute
/// pixel-to-neighbour luma differences across the sampled grid and takes
/// their variance. A blurred image has small, uniform differences
/// everywhere (low variance); a sharp one has a mix of near-zero
/// differences (flat areas) and large ones (real edges), which reads as
/// high variance — the same underlying idea Laplacian variance captures,
/// computed far more cheaply.
library;

import 'dart:math' as math;

import 'package:camera/camera.dart';

/// What the live image-quality pass currently says.
enum ImageQuality {
  blurry('Hold steady — the image looks blurred.'),
  overexposed('Too bright here — try a different angle to avoid glare.'),
  ok('');

  const ImageQuality(this.message);

  final String message;

  bool get blocksCapture => this != ImageQuality.ok;
}

class ImageQualityReading {
  const ImageQualityReading({
    required this.sharpness,
    required this.overexposedFraction,
  });

  /// Higher means sharper. Not a physical unit — only meaningful relative
  /// to [_sharpnessThreshold] below.
  final double sharpness;

  /// Share of sampled pixels at or near full brightness (0-1).
  final double overexposedFraction;
}

/// Below this, a frame reads as blurred. A starting point, not something
/// measured on a real device — same honest caveat as
/// [VehicleFrameDetector]'s own area-ratio thresholds; tune once tried on a
/// phone against genuinely sharp and genuinely blurred reference shots.
const double _sharpnessThreshold = 12.0;

/// Above this share of sampled pixels reading near-white, a frame counts as
/// glare rather than just "bright outdoors". Same caveat as above.
const double _overexposedFractionThreshold = 0.35;

const int _stride = 12;
const double _overexposedLuma = 250;

ImageQualityReading analyzeImageQuality(CameraImage image) {
  final plane = image.planes.first;
  final bytes = plane.bytes;
  final bytesPerRow = plane.bytesPerRow;
  final width = image.width;
  final height = image.height;

  final lumaAt = _lumaReader(image.format.group, bytes, bytesPerRow);
  // A format this check has no byte layout for (yuv420, jpeg, unknown):
  // capture_screen.dart only ever requests bgra8888 (iOS) or nv21 (Android)
  // for the stream this runs on, so in practice this never fires. It's a
  // safety net against misreading bytes under a layout assumption that
  // doesn't hold, not a path either platform actually takes today.
  if (lumaAt == null) {
    return const ImageQualityReading(sharpness: 0, overexposedFraction: 0);
  }

  var sampleCount = 0;
  var overexposedCount = 0;
  var gradientSum = 0.0;
  var gradientSumSquares = 0.0;
  var gradientCount = 0;

  for (var y = _stride; y < height - _stride; y += _stride) {
    for (var x = _stride; x < width - _stride; x += _stride) {
      final luma = lumaAt(x, y);
      sampleCount++;
      if (luma >= _overexposedLuma) overexposedCount++;

      final diff =
          (luma - lumaAt(x + _stride, y)).abs() +
          (luma - lumaAt(x, y + _stride)).abs();
      gradientSum += diff;
      gradientSumSquares += diff * diff;
      gradientCount++;
    }
  }

  if (sampleCount == 0 || gradientCount == 0) {
    return const ImageQualityReading(sharpness: 0, overexposedFraction: 0);
  }

  final meanGradient = gradientSum / gradientCount;
  final variance =
      (gradientSumSquares / gradientCount) - (meanGradient * meanGradient);

  return ImageQualityReading(
    sharpness: math.max(0, variance),
    overexposedFraction: overexposedCount / sampleCount,
  );
}

/// A reader for the 0-255 luma value at pixel ([x], [y]) out of [bytes], one
/// plane laid out with row stride [bytesPerRow] — or null when [group] is a
/// format this check doesn't have a byte layout for.
///
/// Looked up once per frame rather than branched on per pixel, and keyed on
/// [group] rather than on `Platform.isIOS`/`isAndroid`: this does the right
/// thing for whatever bytes a frame actually carries, not whatever a given
/// platform is merely expected to send — the two happen to line up today
/// (see capture_screen.dart's `imageFormatGroup`), but the format a camera
/// stream delivers is a configuration choice, not a law of the platform. A
/// function keyed on the real thing is also the one a test can drive
/// directly, with made-up bytes and a format label, without pretending to
/// be a platform at all.
double Function(int x, int y)? _lumaReader(
  ImageFormatGroup group,
  List<int> bytes,
  int bytesPerRow,
) => switch (group) {
  ImageFormatGroup.bgra8888 => (x, y) {
    // iOS's single plane interleaves 4 bytes per pixel as B-G-R-A
    // (kCVPixelFormatType_32BGRA) — the standard luma weights applied to
    // the red/green/blue bytes sitting at offsets 2/1/0 within each.
    final offset = y * bytesPerRow + x * 4;
    final b = bytes[offset];
    final g = bytes[offset + 1];
    final r = bytes[offset + 2];
    return 0.299 * r + 0.587 * g + 0.114 * b;
  },
  ImageFormatGroup.nv21 => (x, y) {
    // NV21's first plane *is* luma already: one byte per pixel, the
    // 0-255 value directly, no RGB math to do. The interleaved VU bytes
    // that follow belong to a second plane this function never reads —
    // planes.first stops at the end of Y, and this check has no use for
    // colour.
    return bytes[y * bytesPerRow + x].toDouble();
  },
  ImageFormatGroup.yuv420 ||
  ImageFormatGroup.jpeg ||
  ImageFormatGroup.unknown => null,
};

ImageQuality evaluateImageQuality(ImageQualityReading reading) {
  if (reading.overexposedFraction > _overexposedFractionThreshold) {
    return ImageQuality.overexposed;
  }
  if (reading.sharpness < _sharpnessThreshold) return ImageQuality.blurry;
  return ImageQuality.ok;
}
