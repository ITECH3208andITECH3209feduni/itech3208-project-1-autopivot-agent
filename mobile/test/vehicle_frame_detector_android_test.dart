// Android support for inputImageFromCameraImage() in
// lib/features/capture/vehicle_frame_detector.dart.
//
// dart:io's Platform.isIOS/isAndroid are hard-wired to whatever OS
// `flutter test` itself runs on (this machine, never actually iOS or
// Android), and nothing in dart:io lets a test override that -- so every
// test below drives the function through its debugIsIOS/debugIsAndroid
// parameters, which exist for exactly this (see that function's doc
// comment). Both are passed explicitly in every call, even the Android
// ones, so none of this depends on which OS happens to run the suite.
//
// A real CameraDescription and a real CameraImage are both plain data
// classes -- no camera hardware or platform channel involved in building
// one -- so they are constructed directly rather than faked. CameraImage's
// only non-deprecated constructor needs camera_platform_interface types
// this package does not declare a dependency on; the deprecated
// Map-based one is the path camera.dart's own public export surface still
// offers without that, and the package's own source marks it "kept to
// avoid breaking changes" (see the one call site below).
//
// Plain test(): nothing here draws a widget.

import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_mlkit_image_labeling/google_mlkit_image_labeling.dart';

import 'package:autopivot/features/capture/vehicle_frame_detector.dart';

/// android.graphics.ImageFormat.NV21 -- also InputImageFormat.nv21's raw
/// value, and what the camera plugin reports once nv21 streaming is on.
const _nv21Raw = 17;

/// kCVPixelFormatType_32BGRA -- InputImageFormat.bgra8888's raw value.
const _bgra8888Raw = 1111970369;

/// Builds a real [CameraImage] with a single plane, the shape both
/// formats this app uses actually have (see
/// inputImageFromCameraImage's doc comment for why).
CameraImage _singlePlaneImage({
  required int rawFormat,
  required int width,
  required int height,
  required Uint8List bytes,
  required int bytesPerRow,
}) {
  // ignore: deprecated_member_use
  return CameraImage.fromPlatformData({
    'format': rawFormat,
    'width': width,
    'height': height,
    'planes': [
      {'bytes': bytes, 'bytesPerRow': bytesPerRow},
    ],
  });
}

/// NV21 is 1.5 bytes/pixel: a full Y plane, then a half-resolution
/// interleaved VU plane.
Uint8List _nv21Bytes(int width, int height) =>
    Uint8List(width * height + (width * height) ~/ 2);

CameraImage _nv21Image({int width = 8, int height = 4}) => _singlePlaneImage(
  rawFormat: _nv21Raw,
  width: width,
  height: height,
  bytes: _nv21Bytes(width, height),
  bytesPerRow: width,
);

CameraImage _bgra8888Image({int width = 4, int height = 4}) =>
    _singlePlaneImage(
      rawFormat: _bgra8888Raw,
      width: width,
      height: height,
      bytes: Uint8List(width * height * 4),
      bytesPerRow: width * 4,
    );

CameraDescription _cameraWith({
  required CameraLensDirection lensDirection,
  required int sensorOrientation,
}) => CameraDescription(
  name: 'test-camera',
  lensDirection: lensDirection,
  sensorOrientation: sensorOrientation,
);

/// sensorOrientation -> expected ML Kit rotation when device orientation
/// is 0 -- true for both lens directions, since back's and front's
/// formulas collapse to the same thing at device orientation 0 (see the
/// sign-regression test below for why that is not a weaker check than it
/// looks).
const _sensorOrientationToRotation = {
  0: InputImageRotation.rotation0deg,
  90: InputImageRotation.rotation90deg,
  180: InputImageRotation.rotation180deg,
  270: InputImageRotation.rotation270deg,
};

void main() {
  group('Android, back camera: sensorOrientation alone (device orientation '
      'fixed at 0) maps straight through to the rotation enum', () {
    for (final MapEntry(key: sensorOrientation, value: expected)
        in _sensorOrientationToRotation.entries) {
      test('sensorOrientation $sensorOrientation -> $expected', () {
        final input = inputImageFromCameraImage(
          _nv21Image(),
          _cameraWith(
            lensDirection: CameraLensDirection.back,
            sensorOrientation: sensorOrientation,
          ),
          debugIsAndroid: true,
          debugIsIOS: false,
        );

        expect(input, isNotNull);
        expect(input!.metadata!.rotation, expected);
      });
    }
  });

  group('Android, front camera: same mapping as back at device '
      'orientation 0 -- expected, not a copy/paste slip (see the '
      'sign-regression test below)', () {
    for (final MapEntry(key: sensorOrientation, value: expected)
        in _sensorOrientationToRotation.entries) {
      test('sensorOrientation $sensorOrientation -> $expected', () {
        final input = inputImageFromCameraImage(
          _nv21Image(),
          _cameraWith(
            lensDirection: CameraLensDirection.front,
            sensorOrientation: sensorOrientation,
          ),
          debugIsAndroid: true,
          debugIsIOS: false,
        );

        expect(input, isNotNull);
        expect(input!.metadata!.rotation, expected);
      });
    }
  });

  test('front and back actually use opposite-signed formulas -- not provable '
      'through inputImageFromCameraImage itself while device orientation is '
      'fixed at 0, because 0 is its own negation: (s - 0 + 360) % 360 and '
      '(s + 0) % 360 are the same number for every sensorOrientation s, so '
      'no sensorOrientation choice could ever catch the signs being swapped '
      'there. androidRotationCompensationDegrees is exercised directly here '
      'at a non-zero device orientation -- the only place the sign is '
      'actually visible -- which is exactly why it is factored out rather '
      'than inlined', () {
    final back = androidRotationCompensationDegrees(
      sensorOrientation: 0,
      lensDirection: CameraLensDirection.back,
      deviceOrientationDegrees: 90,
    );
    final front = androidRotationCompensationDegrees(
      sensorOrientation: 0,
      lensDirection: CameraLensDirection.front,
      deviceOrientationDegrees: 90,
    );

    expect(back, 270); // (0 - 90 + 360) % 360
    expect(front, 90); // (0 + 90) % 360
    expect(back, isNot(front));
  });

  test('an Android frame reported in a format other than nv21 is rejected, '
      'the same defensive check iOS already has for bgra8888', () {
    final input = inputImageFromCameraImage(
      _bgra8888Image(),
      _cameraWith(
        lensDirection: CameraLensDirection.back,
        sensorOrientation: 90,
      ),
      debugIsAndroid: true,
      debugIsIOS: false,
    );

    expect(input, isNull);
  });

  test('a synthetic single-plane NV21 CameraImage on Android produces a '
      'non-null InputImage with InputImageFormat.nv21 and the expected byte '
      'count', () {
    const width = 8;
    const height = 4;

    final input = inputImageFromCameraImage(
      _nv21Image(width: width, height: height),
      _cameraWith(
        lensDirection: CameraLensDirection.back,
        sensorOrientation: 0,
      ),
      debugIsAndroid: true,
      debugIsIOS: false,
    );

    expect(input, isNotNull);
    expect(input!.metadata!.format, InputImageFormat.nv21);
    expect(input.bytes!.length, width * height + (width * height) ~/ 2);
  });

  group('iOS regression: unchanged by the Android branch existing', () {
    for (final MapEntry(key: sensorOrientation, value: expected)
        in _sensorOrientationToRotation.entries) {
      test('sensorOrientation $sensorOrientation -> $expected', () {
        final input = inputImageFromCameraImage(
          _bgra8888Image(),
          _cameraWith(
            lensDirection: CameraLensDirection.back,
            sensorOrientation: sensorOrientation,
          ),
          debugIsIOS: true,
          debugIsAndroid: false,
        );

        expect(input, isNotNull);
        expect(input!.metadata!.rotation, expected);
        expect(input.metadata!.format, InputImageFormat.bgra8888);
      });
    }
  });

  test('neither iOS nor Android: fails safe exactly as before', () {
    final input = inputImageFromCameraImage(
      _nv21Image(),
      _cameraWith(
        lensDirection: CameraLensDirection.back,
        sensorOrientation: 90,
      ),
      debugIsIOS: false,
      debugIsAndroid: false,
    );

    expect(input, isNull);
  });
}
