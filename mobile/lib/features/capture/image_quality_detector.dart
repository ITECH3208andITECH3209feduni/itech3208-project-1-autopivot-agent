/// A cheap, on-device check for two defects the pipeline has never caught
/// before this: a motion-blurred shot, and a shot blown out by glare on the
/// car's own paint. Neither `vehicle_frame_detector.dart`'s ML Kit check nor
/// the server's classifier (today) look at either — a photograph can be a
/// perfectly framed, perfectly centred car and still be useless because the
/// photographer's hand moved or the sun bounced straight off a door panel.
///
/// Runs on the same BGRA8888 camera frame `capture_screen.dart` already
/// decodes for ML Kit, at the same throttled cadence — no extra frame
/// capture, just extra arithmetic on bytes already in hand. Deliberately
/// samples a sparse grid (every [_stride]th pixel) rather than every pixel:
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

  double lumaAt(int x, int y) {
    final offset = y * bytesPerRow + x * 4;
    final b = bytes[offset];
    final g = bytes[offset + 1];
    final r = bytes[offset + 2];
    return 0.299 * r + 0.587 * g + 0.114 * b;
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

ImageQuality evaluateImageQuality(ImageQualityReading reading) {
  if (reading.overexposedFraction > _overexposedFractionThreshold) {
    return ImageQuality.overexposed;
  }
  if (reading.sharpness < _sharpnessThreshold) return ImageQuality.blurry;
  return ImageQuality.ok;
}
