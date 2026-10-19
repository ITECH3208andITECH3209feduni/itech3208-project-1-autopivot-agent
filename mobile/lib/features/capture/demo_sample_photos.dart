/// Hands back a bundled sample photograph for a [CaptureAngle], standing in
/// for a shot the camera never took — the sample-photo side of "demo
/// capture mode": walking the usual 8-angle sequence at a trade-show booth
/// with no car in front of the phone at all. `CaptureScreen` is expected to
/// drive this exactly like the real camera — ask for the next angle, get
/// back something it can treat precisely as a shot just taken, down to the
/// same [XFile] shape a real capture already produces.
///
/// A different demo from `DemoScreen`'s
/// (lib/features/settings/demo_screen.dart), which uploads one bundled
/// photograph through the live pipeline to show what processing produces.
/// This one is about the capture walk itself, angle by angle, so a booth
/// visitor sees the actual guided flow — not just a finished result they
/// had no part in reaching.
///
/// All eight of [CaptureAngle]'s values have a sample behind them today
/// ([demoAvailableAngles]) — real photographs of the booth car, not
/// placeholders. [loadDemoSamplePhoto] still refuses any angle outside
/// [demoAvailableAngles] outright rather than quietly hand back some other
/// angle's photograph for it: coverage has already shrunk and grown more
/// than once as the booth car's photo set was reshot, and skipping an angle
/// this doesn't cover is left to the caller, the same way a real skipped
/// shot already is.
///
/// Nothing here depends on which file is real and which is a placeholder:
/// the contract is just "whatever JPEG sits at this angle's path", so
/// losing coverage for an angle again is a one-line change to
/// [demoAvailableAngles], nothing else.
library;

import 'dart:io';

import 'package:camera/camera.dart' show XFile;
import 'package:flutter/services.dart' show rootBundle;
import 'package:path_provider/path_provider.dart';

import 'capture_angles.dart';

/// The angles the booth has a real sample photograph for today — all eight
/// of [CaptureAngle]'s values. Spelled out explicitly rather than as
/// `CaptureAngle.values.toSet()`: this set tracks which photographs the
/// booth actually has, a physical fact, not a logical consequence of the
/// enum, so a future angle added to [CaptureAngle] with no photo behind it
/// yet must not silently read as covered.
const Set<CaptureAngle> demoAvailableAngles = {
  CaptureAngle.front,
  CaptureAngle.frontRightCorner,
  CaptureAngle.rightSide,
  CaptureAngle.rearRightCorner,
  CaptureAngle.rear,
  CaptureAngle.leftSide,
  CaptureAngle.frontLeftCorner,
  CaptureAngle.rearLeftCorner,
};

/// Bumped on every call so two samples loaded for the same angle inside one
/// demo session — a booth visitor "reshooting" the same angle after the
/// first look didn't land — never share a file name. The screen can still
/// have a thumbnail reading the first file by the time the second write
/// happens, so reusing a name would mean overwriting a file still in use,
/// not just a theoretical clash.
int _loadCount = 0;

/// Where [angle]'s sample is bundled. This exact shape — the capture
/// directory, then the angle's own [CaptureAngle.name], then ".jpg" — is a
/// fixed contract: whatever eventually replaces the placeholder files has
/// to land at exactly this path per angle, with nothing on this side to
/// update.
String _assetPathFor(CaptureAngle angle) =>
    'assets/demo/capture/${angle.name}.jpg';

/// Copies the bundled sample for [angle] out to a fresh file in the OS
/// temporary directory and hands it back as an [XFile] — the same type,
/// and the same kind of path (a real file on disk, not an in-memory
/// handle), that a real capture already produces. Nothing downstream has to
/// know this one came from an asset instead of the camera.
///
/// Throws [ArgumentError] for any angle outside [demoAvailableAngles]
/// rather than guessing: a caller asking for an angle nobody has a sample
/// for is a bug worth surfacing immediately, not a case worth quietly
/// degrading for.
Future<XFile> loadDemoSamplePhoto(CaptureAngle angle) async {
  if (!demoAvailableAngles.contains(angle)) {
    throw ArgumentError.value(
      angle,
      'angle',
      'No bundled demo sample exists for this angle.',
    );
  }

  final asset = await rootBundle.load(_assetPathFor(angle));
  final tempDir = await getTemporaryDirectory();
  // Timestamp plus a per-process counter: the counter alone is already
  // enough to keep every call in one run apart (see [_loadCount]), and the
  // timestamp just keeps this run's files from ever landing on a name an
  // earlier run of the app left behind in the same OS temp directory.
  final path =
      '${tempDir.path}/demo_${angle.name}_'
      '${DateTime.now().microsecondsSinceEpoch}_${_loadCount++}.jpg';
  await File(path).writeAsBytes(
    asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes),
    flush: true,
  );
  return XFile(path);
}
