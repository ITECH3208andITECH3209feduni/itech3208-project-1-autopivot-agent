/// Reads the device's own tilt from the accelerometer and turns it into
/// guidance the capture screen can gate the shutter on, alongside the
/// on-device vehicle check (see `vehicle_frame_detector.dart`).
///
/// Two angles matter here, and they are not the same thing:
///  - Roll (side-to-side lean) should sit near zero — the classic "bubble
///    level" idea, a level horizon.
///  - Pitch (forward/back tilt — how far the camera looks down toward the
///    ground) should sit near [CaptureAngle.targetElevationDeg] for
///    whichever angle is currently being shot, NOT near zero. Those targets
///    already exist (see that field's own doc comment) precisely because a
///    car is photographed from above looking down at it, not dead level —
///    this detector's job is to confirm that target is actually hit, not
///    to flatten the phone.
///
/// The formulas below were derived from first principles against the axis
/// conventions [AccelerometerEvent] itself documents (device held upright
/// facing the user: +Y toward the sky, +Z toward the user), not copied from
/// an unverified source — a widely-circulated "pitch/roll from
/// accelerometer" formula pair turns out to assume the phone is held flat
/// like a tablet, which is a different rotation axis than tilting a camera
/// up/down while held upright. Still, no accelerometer reading from this
/// environment was available to confirm the sign against real hardware —
/// see [DeviceTiltDetector.invertPitch] / [invertRoll] if the on-screen
/// "tilt up"/"tilt down" message or the level indicator's rotation reads
/// backwards on a real device; flipping one constant is the whole fix.
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:sensors_plus/sensors_plus.dart';

/// A single smoothed tilt sample.
class TiltReading {
  const TiltReading({required this.pitchDeg, required this.rollDeg});

  /// Degrees the camera is currently tilted below horizontal. Compare
  /// against [CaptureAngle.targetElevationDeg], not zero.
  final double pitchDeg;

  /// Degrees the phone is leaning left/right off a level horizon. Always
  /// wants to be near zero regardless of which angle is being shot.
  final double rollDeg;
}

/// What the level check currently says for a specific target elevation.
/// Mirrors [FrameGuidance]'s shape deliberately — message plus a
/// [blocksCapture] getter — so `capture_screen.dart` can compose the two the
/// same way.
enum LevelGuidance {
  tiltDown('Tilt the phone down a little.'),
  tiltUp('Tilt the phone up a little.'),
  leaning('Level the phone — it\'s tilted to one side.'),
  good('');

  const LevelGuidance(this.message);

  final String message;

  bool get blocksCapture => this != LevelGuidance.good;
}

/// How far from target either angle is allowed to sit and still count as
/// "good". Untested against a real handheld device — a starting point in
/// the same spirit as [VehicleFrameDetector]'s own area-ratio thresholds,
/// tune once tried on a phone.
const double _pitchToleranceDeg = 4.0;
const double _rollToleranceDeg = 4.0;

LevelGuidance evaluateLevel(TiltReading reading, double targetElevationDeg) {
  if (reading.rollDeg.abs() > _rollToleranceDeg) return LevelGuidance.leaning;

  final pitchError = reading.pitchDeg - targetElevationDeg;
  if (pitchError.abs() <= _pitchToleranceDeg) return LevelGuidance.good;
  // Measured pitch bigger than the target means the camera is angled MORE
  // steeply down than wanted, so it needs to come back up, and vice versa.
  return pitchError > 0 ? LevelGuidance.tiltUp : LevelGuidance.tiltDown;
}

class DeviceTiltDetector {
  StreamSubscription<AccelerometerEvent>? _subscription;
  double? _smoothedPitch;
  double? _smoothedRoll;

  /// See the library doc comment — flip to -1.0 if a real device shows the
  /// tilt message or the level indicator's rotation backwards.
  static const double invertPitch = 1.0;
  static const double invertRoll = 1.0;

  /// Raw accelerometer samples are visibly jittery from hand tremor alone —
  /// an exponential moving average smooths that out with far less lag than
  /// a windowed average would add. This weight settles to within a couple
  /// of degrees of a step change in well under half a second.
  static const double _smoothingWeight = 0.15;

  void start(void Function(TiltReading reading) onReading) {
    _subscription =
        accelerometerEventStream(
          samplingPeriod: SensorInterval.uiInterval,
        ).listen((event) {
          final rawPitch = _degrees(math.atan2(event.z, event.y)) * invertPitch;
          final rawRoll = _degrees(math.atan2(event.x, event.y)) * invertRoll;

          _smoothedPitch = _ema(_smoothedPitch, rawPitch);
          _smoothedRoll = _ema(_smoothedRoll, rawRoll);

          onReading(
            TiltReading(pitchDeg: _smoothedPitch!, rollDeg: _smoothedRoll!),
          );
        });
  }

  double _ema(double? previous, double sample) {
    if (previous == null) return sample;
    return previous + _smoothingWeight * (sample - previous);
  }

  double _degrees(double radians) => radians * 180 / math.pi;

  void dispose() {
    _subscription?.cancel();
    _subscription = null;
  }
}
