/// Draws the 5 base vehicle guide outlines a photographer lines the real car
/// up against.
///
/// Plain stroked line art, not an illustration — the point is a fast
/// alignment cue on a translucent camera overlay, and every shape carries a
/// text label alongside it (see `capture_screen.dart`), so the drawing only
/// has to read as "roughly this kind of view", not stand alone. Built from
/// straight lines and a handful of quadratic curves rather than freehand
/// bezier art, deliberately, so the shape stays predictable at any size.
library;

import 'package:flutter/material.dart';

import 'capture_angles.dart';

class VehicleSilhouettePainter extends CustomPainter {
  const VehicleSilhouettePainter({required this.shape, required this.color});

  final VehicleGuideShape shape;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final bodyPaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round;
    final markPaint = Paint()..color = color;

    switch (shape) {
      case VehicleGuideShape.front:
        _paintNose(canvas, size, bodyPaint, markPaint, upright: true);
      case VehicleGuideShape.rear:
        _paintNose(canvas, size, bodyPaint, markPaint, upright: false);
      case VehicleGuideShape.side:
        canvas.drawPath(_sideBody(size), bodyPaint);
        _wheel(canvas, size, markPaint, cx: 0.26);
        _wheel(canvas, size, markPaint, cx: 0.76);
      case VehicleGuideShape.frontQuarter:
        canvas.drawPath(_quarterLowerBody(size), bodyPaint);
        canvas.drawPath(_quarterGreenhouse(size, noseNear: true), bodyPaint);
        _wheel(canvas, size, markPaint, cx: 0.20);
      case VehicleGuideShape.rearQuarter:
        canvas.drawPath(_quarterLowerBody(size), bodyPaint);
        canvas.drawPath(_quarterGreenhouse(size, noseNear: false), bodyPaint);
        _wheel(canvas, size, markPaint, cx: 0.20);
    }
  }

  /// Front and rear share one head-on silhouette — a low body with a
  /// windshield trapezoid above it — since a stroked outline of either end
  /// of a car reads as near-identical without colour or grille/badge detail
  /// to tell them apart. What actually distinguishes them here is
  /// [upright] (the rear's greenhouse sits a little taller and squarer,
  /// suggesting a boxier trunk line rather than a sloped bonnet) plus the
  /// two marks along the bumper: headlamps (circles) for the front, a
  /// numberplate strip (a single bar) for the rear. Reasonable, not exact —
  /// the on-screen label carries the rest.
  void _paintNose(
    Canvas canvas,
    Size size,
    Paint bodyPaint,
    Paint markPaint, {
    required bool upright,
  }) {
    final w = size.width, h = size.height;
    final bodyTop = h * 0.46;

    final body = Path()
      ..addRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTRB(w * 0.14, bodyTop, w * 0.86, h * 0.82),
          Radius.circular(h * 0.07),
        ),
      );

    final greenhouseTop = upright ? h * 0.18 : h * 0.24;
    final greenhouse = Path()
      ..moveTo(w * 0.30, bodyTop)
      ..lineTo(w * 0.36, greenhouseTop)
      ..lineTo(w * 0.64, greenhouseTop)
      ..lineTo(w * 0.70, bodyTop);

    canvas.drawPath(body, bodyPaint);
    canvas.drawPath(greenhouse, bodyPaint);

    if (upright) {
      _dot(canvas, markPaint, Offset(w * 0.22, h * 0.68), h * 0.035);
      _dot(canvas, markPaint, Offset(w * 0.78, h * 0.68), h * 0.035);
    } else {
      canvas.drawLine(
        Offset(w * 0.40, h * 0.68),
        Offset(w * 0.60, h * 0.68),
        bodyPaint,
      );
    }
  }

  /// A side profile: a two-tier outline (lower body, offset cabin) that
  /// reads as the classic "car icon" silhouette, plus two wheels.
  Path _sideBody(Size size) {
    final w = size.width, h = size.height;
    return Path()
      ..moveTo(w * 0.06, h * 0.78)
      ..lineTo(w * 0.06, h * 0.56)
      ..quadraticBezierTo(w * 0.06, h * 0.46, w * 0.16, h * 0.44)
      ..lineTo(w * 0.30, h * 0.26)
      ..quadraticBezierTo(w * 0.34, h * 0.18, w * 0.42, h * 0.18)
      ..lineTo(w * 0.68, h * 0.18)
      ..quadraticBezierTo(w * 0.76, h * 0.18, w * 0.81, h * 0.26)
      ..lineTo(w * 0.90, h * 0.44)
      ..quadraticBezierTo(w * 0.94, h * 0.46, w * 0.94, h * 0.56)
      ..lineTo(w * 0.94, h * 0.78)
      ..close();
  }

  /// A three-quarter view's lower body: the near corner (left, whichever end
  /// is nearest the camera) drawn tall, the far corner short and low,
  /// receding the way a car's far side genuinely foreshortens at an angle —
  /// two tiers, the same idea as [_sideBody], rather than one flat outline,
  /// which is what makes this read as a body with a roof rather than a
  /// wedge. Shared by both quarter angles; [_quarterGreenhouse] is what
  /// tells a front-quarter guide from a rear-quarter one.
  Path _quarterLowerBody(Size size) {
    final w = size.width, h = size.height;
    return Path()
      ..moveTo(w * 0.06, h * 0.78)
      ..lineTo(w * 0.06, h * 0.56)
      ..lineTo(w * 0.20, h * 0.48)
      ..lineTo(w * 0.90, h * 0.58)
      ..lineTo(w * 0.90, h * 0.72)
      ..close();
  }

  /// The cabin, sitting on the near (tall) end of [_quarterLowerBody] and
  /// tapering off before the far end — a roofline recedes faster than the
  /// body does at this angle, which is what keeps the far end reading as
  /// "further away" rather than just "shorter". [noseNear] pushes the
  /// window line's peak a little further from the near edge for a
  /// front-quarter guide (more bonnet in view ahead of the windscreen) than
  /// a rear-quarter one (more boot, less glass ahead of the rear window).
  Path _quarterGreenhouse(Size size, {required bool noseNear}) {
    final w = size.width, h = size.height;
    final peakStart = noseNear ? 0.30 : 0.20;
    return Path()
      ..moveTo(w * 0.14, h * 0.56)
      ..lineTo(w * peakStart, h * 0.30)
      ..lineTo(w * (peakStart + 0.34), h * 0.26)
      ..lineTo(w * 0.68, h * 0.42);
  }

  void _wheel(Canvas canvas, Size size, Paint paint, {required double cx}) {
    canvas.drawCircle(
      Offset(size.width * cx, size.height * 0.78),
      size.height * 0.12,
      paint..style = PaintingStyle.stroke..strokeWidth = 2.5,
    );
  }

  void _dot(Canvas canvas, Paint paint, Offset center, double radius) {
    canvas.drawCircle(center, radius, paint);
  }

  @override
  bool shouldRepaint(covariant VehicleSilhouettePainter oldDelegate) =>
      oldDelegate.shape != shape || oldDelegate.color != color;
}

/// The guide overlay itself: one of the 5 base shapes, mirrored for the
/// slots that need the opposite side, with a translucent finish so the live
/// preview (or, on a device with none, the flat placeholder fill) still
/// shows through it.
class VehicleGuideOverlay extends StatelessWidget {
  const VehicleGuideOverlay({super.key, required this.angle});

  final CaptureAngle angle;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Opacity(
        opacity: 0.75,
        child: Transform(
          alignment: Alignment.center,
          transform: Matrix4.identity()
            ..scaleByDouble(angle.mirrored ? -1.0 : 1.0, 1.0, 1.0, 1.0),
          child: SizedBox(
            width: 240,
            height: 168,
            child: CustomPaint(
              painter: VehicleSilhouettePainter(
                shape: angle.shape,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
