/// The capture guide overlay: one of 5 base vehicle outlines a photographer
/// lines the real car up against, shown as a translucent case-mould shape
/// over the live camera preview.
///
/// These are pre-rendered PNGs, not drawn at runtime. Each is traced
/// straight from a real reference — a CC BY 4.0 LiDAR scan ("Car - Lidar
/// scan" by Moshe Caine, Sketchfab — commercial use permitted with
/// attribution, credited wherever this app's licences are listed) — rather
/// than approximated with hand-placed curves the way an earlier version of
/// this file drew them. The pipeline: splat the scan's ~805k real points
/// into a solid silhouette from each of this screen's own 5 target camera
/// angles (matching `CaptureAngle.targetElevationDeg`), blur and threshold
/// that solid shape to erode it by a few pixels, then subtract the eroded
/// copy from the original — what survives is a fixed-width ring sitting
/// exactly on the true projected boundary of the real scan, the same way a
/// case is moulded to a phone's exact shape rather than sketched free-hand.
/// Wheel arches are added the same way: found from the solid shape's own
/// column-density profile (a wheel arch reaches distinctly higher up the
/// frame than the flat rocker panel beside it), not placed at a guessed
/// screen position — only which of the 5 shapes gets a wheel circle at all,
/// and how many, still mirrors the original hand-drawn version (side: both
/// ends; the two quarter views: the near corner only; front/rear: none).
library;

import 'package:flutter/material.dart';

import '../../design/tokens.dart';
import 'capture_angles.dart';

/// Maps each base shape to its traced PNG in `assets/silhouettes/`.
extension on VehicleGuideShape {
  String get _assetPath {
    switch (this) {
      case VehicleGuideShape.front:
        return 'assets/silhouettes/front.png';
      case VehicleGuideShape.frontQuarter:
        return 'assets/silhouettes/front_quarter.png';
      case VehicleGuideShape.side:
        return 'assets/silhouettes/side.png';
      case VehicleGuideShape.rearQuarter:
        return 'assets/silhouettes/rear_quarter.png';
      case VehicleGuideShape.rear:
        return 'assets/silhouettes/rear.png';
    }
  }
}

/// The guide overlay itself: one of the 5 base shapes, mirrored for the
/// slots that need the opposite side, with a translucent finish so the live
/// preview (or, on a device with none, the flat placeholder fill) still
/// shows through it.
///
/// [aligned] tints the outline green instead of white — the on-device
/// vehicle check (see `vehicle_frame_detector.dart`) already knows when the
/// shot is well-framed, since that's exactly what currently disables or
/// enables the shutter; this just gives that same signal a visible home on
/// the guide itself; a photographer glancing at the outline sees the same
/// verdict the shutter is already acting on, rather than having to read the
/// text banner separately.
class VehicleGuideOverlay extends StatelessWidget {
  const VehicleGuideOverlay({super.key, required this.angle, this.aligned = false});

  final CaptureAngle angle;
  final bool aligned;

  // Was 0xFF34D058, a bright success-green with no source in
  // design/tokens.dart. That file's own comment is explicit that there is
  // "deliberately no success colour" and to "resist adding a second
  // accent" — forestLift (a lifted version of the brand's one real accent,
  // legible against a dark camera feed the way the base `forest` tone
  // isn't) is what "aligned" should actually look like.
  static const _alignedColor = C.forestLift;

  /// 240x168 (10:7) read as small on an iPad screen in practice — a
  /// photographer matching a tiny on-screen outline has no strong cue to
  /// physically step closer, so shots came out too far back for a usable
  /// listing photo. Sized off the actual screen instead of a fixed guess:
  /// most of the width, capped so it doesn't balloon on a tablet.
  static const double _aspect = 168 / 240;

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final guideWidth = (screenWidth * 0.86).clamp(240.0, 560.0);
    final guideHeight = guideWidth * _aspect;

    return IgnorePointer(
      child: Opacity(
        opacity: 0.75,
        child: Transform(
          alignment: Alignment.center,
          transform: Matrix4.identity()
            ..scaleByDouble(angle.mirrored ? -1.0 : 1.0, 1.0, 1.0, 1.0),
          child: SizedBox(
            width: guideWidth,
            height: guideHeight,
            child: ColorFiltered(
              colorFilter: ColorFilter.mode(
                aligned ? _alignedColor : Colors.white,
                BlendMode.srcIn,
              ),
              child: Image.asset(angle.shape._assetPath, fit: BoxFit.contain),
            ),
          ),
        ),
      ),
    );
  }
}
