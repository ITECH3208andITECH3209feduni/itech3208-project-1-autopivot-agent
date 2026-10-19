// The on-device blur/glare check: lib/features/capture/image_quality_detector.dart.
//
// Written BGRA8888-only, back when it only ever ran on iOS — capture_screen
// never started an image stream on Android at all. A sibling change starts
// that stream on Android too, requesting ImageFormatGroup.nv21, a format
// this file's one luma formula was never written for: NV21's first plane is
// already luma, one byte per pixel, not four interleaved BGRA bytes, and
// reading it with the BGRA formula walks x*4 bytes into a buffer that is
// only ever x bytes wide per row — drifting into the wrong row, or past the
// end of the buffer entirely, well before the right edge of a real frame.
//
// The fakes below build the exact shape `CameraImage.fromPlatformInterface`
// produces for each format (a single plane, `format.group` set accordingly)
// rather than going through the camera plugin's platform channel, which
// `flutter test` has no camera behind anyway.
//
// The "edge" pattern used for the sharp case is a single flat/flat step, not
// a dense checkerboard: the sharpness figure is a *variance* of per-sample
// gradients (see that file's own doc comment), so a pattern that puts an
// edge at every single sample point produces a constant, not varying,
// gradient — which reads as low variance, i.e. blurry, exactly backwards
// from what it looks like it should prove. A mix of mostly-flat samples and
// one strong step is what actually drives the variance up.
//
// A BGRA8888 group runs the same three patterns through the pre-existing
// path, to pin down that adding the NV21 branch left its numbers alone —
// there was no existing test file for this detector to leave unmodified
// (checked: nothing under test/ or lib/ outside this feature referenced
// CameraImage), so this is that regression check, written fresh.
//
// Plain test(): no widget, nothing async — analyzeImageQuality is a pure
// function over bytes someone already captured.

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:camera/camera.dart';
// camera_platform_interface is only a transitive dependency (via camera)
// today, not a direct one in pubspec.yaml, but it's the only place
// CameraImageData/CameraImagePlane/CameraImageFormat live — camera.dart's
// own export of that package deliberately leaves them out (see its show
// list) — and CameraImage.fromPlatformInterface, the only non-deprecated
// way to build one, takes exactly a CameraImageData.
// ignore: depend_on_referenced_packages
import 'package:camera_platform_interface/camera_platform_interface.dart'
    show CameraImageData, CameraImageFormat, CameraImagePlane;

import 'package:autopivot/features/capture/image_quality_detector.dart';

/// Both fake builders below take their pixel content through this
/// signature, so the same pattern can be handed to either format and
/// produce the same logical image.
typedef _Luma = int Function(int x, int y);

// Comfortably more than twice image_quality_detector.dart's own sampling
// stride (12, read off that file) in both dimensions, so the sampled grid
// has several points to work with rather than just the one or two a
// borderline size would leave.
const _width = 96;
const _height = 96;

/// A single hard step at x=48: flat at [low] left of it, flat at [high] from
/// it on. See the file header for why a step, not a dense checkerboard, is
/// what the sharpness variance needs to read as sharp.
_Luma _edge({int low = 50, int high = 230}) =>
    (x, y) => x < 48 ? low : high;

/// The same value everywhere — no edges for the gradient variance to find.
_Luma _uniform(int value) =>
    (x, y) => value;

/// Builds the fake [CameraImage] the camera plugin hands `onCameraFrame`
/// for an NV21 stream: one plane, tightly packed (`bytesPerRow == width`,
/// no row padding), [luma] supplying each pixel's 0-255 Y byte directly.
CameraImage _nv21Image({
  required int width,
  required int height,
  required _Luma luma,
}) {
  final y = Uint8List(width * height);
  for (var row = 0; row < height; row++) {
    for (var col = 0; col < width; col++) {
      y[row * width + col] = luma(col, row);
    }
  }
  return CameraImage.fromPlatformInterface(
    CameraImageData(
      // android.graphics.ImageFormat.NV21 — analyzeImageQuality only ever
      // reads format.group, never .raw, but a real value costs nothing.
      format: const CameraImageFormat(ImageFormatGroup.nv21, raw: 17),
      width: width,
      height: height,
      planes: [
        // NV21's second, interleaved-VU plane is never built here:
        // analyzeImageQuality only reads planes.first, so a fake missing
        // plane 2 is exactly as valid an input as a real frame would be
        // for what this function actually looks at.
        CameraImagePlane(bytes: y, bytesPerRow: width),
      ],
    ),
  );
}

/// Builds the fake [CameraImage] the camera plugin hands `onCameraFrame`
/// for a BGRA8888 stream: one plane, 4 interleaved bytes per pixel, tightly
/// packed (`bytesPerRow == width * 4`). [luma] supplies one 0-255 value per
/// pixel, written into all three of B/G/R so the frame is grayscale — all
/// three channels equal is exactly what a real monochrome-ish patch of a
/// photograph looks like, and it's the only thing this detector's luma
/// formula cares about.
CameraImage _bgraImage({
  required int width,
  required int height,
  required _Luma luma,
}) {
  final bytes = Uint8List(width * height * 4);
  for (var row = 0; row < height; row++) {
    for (var col = 0; col < width; col++) {
      final v = luma(col, row);
      final offset = (row * width + col) * 4;
      bytes[offset] = v; // B
      bytes[offset + 1] = v; // G
      bytes[offset + 2] = v; // R
      bytes[offset + 3] = 255; // A — analyzeImageQuality never reads it.
    }
  }
  return CameraImage.fromPlatformInterface(
    CameraImageData(
      // kCVPixelFormatType_32BGRA — see the NV21 builder above re raw.
      format: const CameraImageFormat(
        ImageFormatGroup.bgra8888,
        raw: 1111970369,
      ),
      width: width,
      height: height,
      planes: [CameraImagePlane(bytes: bytes, bytesPerRow: width * 4)],
    ),
  );
}

void main() {
  group('NV21 (Android)', () {
    test('a uniform grey frame with no edges anywhere reads as blurry', () {
      final reading = analyzeImageQuality(
        _nv21Image(width: _width, height: _height, luma: _uniform(128)),
      );
      expect(evaluateImageQuality(reading), ImageQuality.blurry);
    });

    test('a frame with a real edge reads as ok, not blurry', () {
      final reading = analyzeImageQuality(
        _nv21Image(width: _width, height: _height, luma: _edge()),
      );
      expect(evaluateImageQuality(reading), ImageQuality.ok);
    });

    test('a frame blown out past the overexposed luma threshold reads as '
        'overexposed', () {
      final reading = analyzeImageQuality(
        _nv21Image(width: _width, height: _height, luma: _uniform(255)),
      );
      expect(evaluateImageQuality(reading), ImageQuality.overexposed);
    });
  });

  group('BGRA8888 (iOS) regression', () {
    // Same three patterns as above, same expected classifications: proving
    // the branch added for NV21 left this pre-existing path's own behaviour
    // alone.
    test('a uniform grey frame with no edges anywhere reads as blurry', () {
      final reading = analyzeImageQuality(
        _bgraImage(width: _width, height: _height, luma: _uniform(128)),
      );
      expect(evaluateImageQuality(reading), ImageQuality.blurry);
    });

    test('a frame with a real edge reads as ok, not blurry', () {
      final reading = analyzeImageQuality(
        _bgraImage(width: _width, height: _height, luma: _edge()),
      );
      expect(evaluateImageQuality(reading), ImageQuality.ok);
    });

    test('a frame blown out past the overexposed luma threshold reads as '
        'overexposed', () {
      final reading = analyzeImageQuality(
        _bgraImage(width: _width, height: _height, luma: _uniform(255)),
      );
      expect(evaluateImageQuality(reading), ImageQuality.overexposed);
    });

    test('the edge pattern\'s exact sharpness and overexposed fraction are '
        'untouched by the NV21 branch', () {
      final reading = analyzeImageQuality(
        _bgraImage(width: _width, height: _height, luma: _edge()),
      );
      // Hand-derived from _edge() above over a 96x96 frame: the sampled
      // grid is 6x6 (stride 12, from 12 to 72 in each axis) = 36 points.
      // Only the x=36 column's rightward gradient crosses the x=48 step
      // (36 -> 48), the other 5 columns and every downward gradient stay
      // on one flat side or the other. So 6 of the 36 samples (one full
      // column) see a gradient of |50-230|=180, the remaining 30 see 0:
      // mean 1080/36=30, mean-of-squares 194400/36=5400,
      // variance 5400 - 30*30 = 4500, no sampled pixel reaching the
      // overexposed threshold. closeTo, not exact equality: the BGRA
      // formula's 0.299/0.587/0.114 weights aren't exactly representable
      // in binary floating point, so even unchanged, untouched-by-this-
      // task BGRA arithmetic lands a couple of ULPs off whole numbers
      // (observed: 4499.999999999998) — the tolerance absorbs that, not
      // anything the NV21 branch could have perturbed.
      expect(reading.sharpness, closeTo(4500.0, 1e-6));
      expect(reading.overexposedFraction, closeTo(0.0, 1e-6));
    });
  });
}
