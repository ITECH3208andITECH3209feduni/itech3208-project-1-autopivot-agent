// Which way the capture guide faces in each left/right slot:
// CaptureAngle.mirrored (lib/features/capture/capture_angles.dart), applied to
// the traced outlines in assets/silhouettes/ the way VehicleGuideOverlay
// applies it, a horizontal flip about the guide's centre.
//
// From anywhere along a car's right-hand side (its front-right corner, its
// right side, its rear-right corner) the car's front points to the
// photographer's right; from anywhere along its left-hand side, to their left.
// So every right-hand slot's guide needs its bonnet on the right, and every
// left-hand slot's on the left. That holds for the two quarter views as much as
// for the side: the front-right corner is shot with the front end near and on
// the right, the rear-right corner with the rear end near and on the left.
//
// Which end of an outline is the bonnet is read off the outline itself. The
// scanned vehicle is a hatchback: at one end the roof runs almost all the way
// to a tall, near-vertical tailgate, at the other it drops down the windscreen
// to a bonnet well below it. So across the outer third of the outline's width
// at each end, the end whose top edge sits lower in the frame is the bonnet
// end. The quarter views show it too: the front quarter's near bonnet still
// sits far below its far roofline, and the rear quarter's bonnet is the far,
// low end behind a near tailgate.
//
// Robust rather than exact: columns only count where the outline itself
// crosses them (at least 10 opaque pixels, roof and sill, where a speck of the
// scan's noise is a pixel or two), each end's height is the median over
// hundreds of columns, and a difference under 5% of the image height is no
// answer at all, so an outline that stopped showing the difference clearly
// fails this rather than passing by chance. On the current tracings the two
// ends are 114 px apart for the side, 129 px for the front quarter and 55 px
// for the rear quarter, of 672.
//
// Plain test(): the PNGs are decoded for real, and those futures never resolve
// inside testWidgets' FakeAsync zone.

import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/capture_angles.dart';

enum _End { left, right }

/// The traced outline each shape's guide draws, as bundled with the app.
const _assets = {
  VehicleGuideShape.side: 'assets/silhouettes/side.png',
  VehicleGuideShape.frontQuarter: 'assets/silhouettes/front_quarter.png',
  VehicleGuideShape.rearQuarter: 'assets/silhouettes/rear_quarter.png',
};

/// Which way each left/right slot's car points: true for its front to the
/// photographer's right. See the note at the top of this file.
const _frontPointsRight = {
  CaptureAngle.frontRightCorner: true,
  CaptureAngle.rightSide: true,
  CaptureAngle.rearRightCorner: true,
  CaptureAngle.rearLeftCorner: false,
  CaptureAngle.leftSide: false,
  CaptureAngle.frontLeftCorner: false,
};

/// A guide's outline as the photographer is shown it.
class _Outline {
  _Outline(this.width, this.height, this._rgba, {required this.mirrored});

  final int width;
  final int height;
  final Uint8List _rgba;
  final bool mirrored;

  bool _opaque(int x, int y) {
    final column = mirrored ? width - 1 - x : x;
    return _rgba[(y * width + column) * 4 + 3] >= 128;
  }

  int _ink(int x) {
    var count = 0;
    for (var y = 0; y < height; y++) {
      if (_opaque(x, y)) count++;
    }
    return count;
  }

  int _topEdge(int x) {
    for (var y = 0; y < height; y++) {
      if (_opaque(x, y)) return y;
    }
    return height;
  }

  /// The bonnet end, or null when the two ends are too close to call, with
  /// the median top edge found at each end (pixels down from the top).
  ({_End? end, int left, int right}) bonnet() {
    final ink = [for (var x = 0; x < width; x++) _ink(x)];
    final crossed = [
      for (var x = 0; x < width; x++)
        if (ink[x] >= 10) x,
    ];
    final first = crossed.first;
    final last = crossed.last;
    final third = (last - first + 1) ~/ 3;

    int medianTop(int from, int to) {
      final tops = [
        for (var x = from; x <= to; x++)
          if (ink[x] >= 10) _topEdge(x),
      ]..sort();
      return tops[tops.length ~/ 2];
    }

    final left = medianTop(first, first + third - 1);
    final right = medianTop(last - third + 1, last);
    final end = (right - left).abs() < height * 0.05
        ? null
        : right > left
        ? _End.right
        : _End.left;
    return (end: end, left: left, right: right);
  }
}

Future<_Outline> _guideShownFor(CaptureAngle angle) async {
  final asset = await rootBundle.load(_assets[angle.shape]!);
  final codec = await ui.instantiateImageCodec(
    asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes),
  );
  final image = (await codec.getNextFrame()).image;
  final pixels = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
  return _Outline(
    image.width,
    image.height,
    pixels!.buffer.asUint8List(pixels.offsetInBytes, pixels.lengthInBytes),
    mirrored: angle.mirrored,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final MapEntry(key: angle, value: pointsRight)
      in _frontPointsRight.entries) {
    final side = pointsRight ? 'right' : 'left';
    test("the ${angle.label} guide has its bonnet on the photographer's "
        '$side', () async {
      final outline = await _guideShownFor(angle);
      final bonnet = outline.bonnet();

      expect(
        bonnet.end,
        pointsRight ? _End.right : _End.left,
        reason:
            'top edge ${bonnet.left} px down at the left end and '
            '${bonnet.right} px at the right, of ${outline.height} '
            '(mirrored: ${angle.mirrored})',
      );
    });
  }
}
