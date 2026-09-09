/// The fixed 8-shot exterior capture sequence: which angle the photographer
/// is asked for, in what order, and what each maps back to for the parts of
/// the pipeline that only understand a coarser vocabulary.
///
/// The 8 slots are the 5-class vocabulary `classification.py` and
/// `compositing.py` already use (front, front_quarter, side, rear_quarter,
/// rear) split into a left and right shot for the two quarter angles and the
/// side — a complete, buyer-facing gallery showing every side of the car,
/// matching a recognisable auction/inspection shot list. Neither
/// `elevation.py` nor `compositing.py` branches on which side a shot was
/// taken from, only on the coarser class (confirmed by reading both: the
/// only "left"/"right" occurrences in either file are generic bounding-box
/// edges, never a vehicle-side distinction), so [pipelineAngle] maps each
/// pair straight back down to it — no backend vocabulary change required to
/// keep the tuned shadow/elevation handling for these shots.
///
/// [targetElevationDeg] is not invented for the app: it is
/// `elevation.py`'s own `ANGLE_ELEVATION_PRIOR_DEG` values (crouching 4.61°,
/// standing 11.16°, raised 17.43°, and the midpoint 14.30° the module derives
/// for `rear_quarter`), so the on-screen tilt target is provably the same
/// assumption the backend's population-prior fallback already makes for
/// each angle — the capture flow is aiming the photographer at the number
/// the pipeline already trusts, not a separately guessed one.
library;

enum CaptureAngle {
  front(
    label: 'Front',
    pipelineAngle: 'front',
    shape: VehicleGuideShape.front,
    mirrored: false,
    targetElevationDeg: 11.16,
  ),
  frontLeftCorner(
    label: 'Front-left corner',
    pipelineAngle: 'front_quarter',
    shape: VehicleGuideShape.frontQuarter,
    mirrored: false,
    targetElevationDeg: 4.61,
  ),
  frontRightCorner(
    label: 'Front-right corner',
    pipelineAngle: 'front_quarter',
    shape: VehicleGuideShape.frontQuarter,
    mirrored: true,
    targetElevationDeg: 4.61,
  ),
  leftSide(
    label: 'Left side',
    pipelineAngle: 'side',
    shape: VehicleGuideShape.side,
    mirrored: false,
    targetElevationDeg: 11.16,
  ),
  rightSide(
    label: 'Right side',
    pipelineAngle: 'side',
    shape: VehicleGuideShape.side,
    mirrored: true,
    targetElevationDeg: 11.16,
  ),
  rearLeftCorner(
    label: 'Rear-left corner',
    pipelineAngle: 'rear_quarter',
    shape: VehicleGuideShape.rearQuarter,
    mirrored: false,
    targetElevationDeg: 14.30,
  ),
  rearRightCorner(
    label: 'Rear-right corner',
    pipelineAngle: 'rear_quarter',
    shape: VehicleGuideShape.rearQuarter,
    mirrored: true,
    targetElevationDeg: 14.30,
  ),
  rear(
    label: 'Rear',
    pipelineAngle: 'rear',
    shape: VehicleGuideShape.rear,
    mirrored: false,
    targetElevationDeg: 17.43,
  );

  const CaptureAngle({
    required this.label,
    required this.pipelineAngle,
    required this.shape,
    required this.mirrored,
    required this.targetElevationDeg,
  });

  /// Shown to the photographer.
  final String label;

  /// What gets sent to the backend in place of this finer slot — see the
  /// library doc comment above for why this mapping is safe.
  final String pipelineAngle;

  /// Which of the 5 base silhouettes this slot's guide draws.
  final VehicleGuideShape shape;

  /// Whether that base silhouette should be flipped horizontally for this
  /// slot — every shape has one canonical (unmirrored) side and one
  /// mirrored side, so only 5 shapes need drawing for all 8 slots.
  final bool mirrored;

  /// Degrees below horizontal the camera is expected to be tilted for this
  /// shot — see the library doc comment for where this number comes from.
  final double targetElevationDeg;
}

/// The 5 distinct outlines a capture guide can show — see
/// [VehicleSilhouettePainter].
enum VehicleGuideShape { front, frontQuarter, side, rearQuarter, rear }
