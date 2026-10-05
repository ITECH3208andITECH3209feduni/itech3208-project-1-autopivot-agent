/// The capture screen's last gate before the shutter: every on-device check
/// has to have agreed for a moment, not just on one lucky frame, before a
/// photograph can be taken — and agreed about the shot actually being taken.
///
/// Its own file, away from [CaptureScreen]'s camera and sensors, so the rule
/// can be tested with the time handed in.
library;

import 'capture_angles.dart';

class HoldSteady {
  HoldSteady(this.duration);

  /// How long the checks have to keep agreeing.
  final Duration duration;

  /// The angle the window is being timed for — whatever [update] was last
  /// told the screen is asking for.
  CaptureAngle? get target => _target;
  CaptureAngle? _target;

  DateTime? _readySince;

  /// Tells this what the checks say now: [ready] when none of them is
  /// blocking [target], the angle the screen is asking for (null once there
  /// is none left to shoot).
  ///
  /// A new [target] starts the window over, however long the checks have
  /// agreed. They are not evidence about it yet: taking a shot moves the
  /// screen straight on to the next angle, with the phone still where the
  /// last one was taken from, and nothing checked there tells the two apart
  /// (neighbouring angles' tilt windows overlap, and the vehicle check only
  /// asks whether a car is in frame). Carrying the old start over is what let
  /// a second tap, straight after the first, photograph the next angle from
  /// the last one's spot, and leave the set without that angle.
  void update({
    required CaptureAngle? target,
    required bool ready,
    required DateTime now,
  }) {
    if (target != _target) {
      _target = target;
      _readySince = null;
    }
    if (!ready || target == null) {
      _readySince = null;
    } else {
      _readySince ??= now;
    }
  }

  /// Starts the window over — a camera that has just opened has not been
  /// checked yet.
  void restart() => _readySince = null;

  /// Whether the checks have agreed about [target] for the whole of
  /// [duration] up to [now]. Never for an angle [update] has not been told
  /// about yet, so the shutter stays shut even when nothing has updated this
  /// since the screen moved on.
  bool isSettled({required CaptureAngle? target, required DateTime now}) {
    final since = _readySince;
    return target != null &&
        target == _target &&
        since != null &&
        now.difference(since) >= duration;
  }
}
