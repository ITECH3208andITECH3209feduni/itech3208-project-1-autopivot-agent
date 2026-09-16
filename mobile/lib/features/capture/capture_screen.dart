/// The vehicle photo capture screen — a custom camera surface, not the
/// system camera picker, per the client's own description of this feature
/// (5 June): open the app, it tells you which angle to shoot, you shoot it,
/// it uploads as a set.
///
/// The 8-shot sequence in [CaptureAngle] and its guide silhouettes
/// ([VehicleGuideOverlay]) are real, not placeholders — this screen knows
/// exactly which angle it wants next and shows the photographer what to line
/// the car up against. Submitting a set is real too: it creates the listing
/// and uploads every captured photograph (see [_submit]).
///
/// Four independent checks all have to agree before the shutter enables,
/// composed in [_blockingMessage]'s priority order and shown as a single
/// banner (only the most fundamental active problem is ever shown at once,
/// never a stack of four):
///  1. [VehicleFrameDetector] — is a car actually in frame, reasonably
///     sized, centred (ML Kit, iOS only for now).
///  2. [DeviceTiltDetector] — is the phone tilted to the angle this shot's
///     [CaptureAngle.targetElevationDeg] actually wants, and level
///     side-to-side (the accelerometer; see that file's own doc comment for
///     why the pitch/roll formulas are original derivations, not copied
///     from an unverified source, and for the one thing about them that
///     still needs confirming on real hardware).
///  3. [ImageQualityReading]/[evaluateImageQuality] — is the frame sharp,
///     not blown out by glare (a cheap sampled-gradient/overexposure check,
///     also new).
///  4. A short "hold steady" window — all three above have to stay good for
///     [_holdSteadyDuration], not just be true on one lucky frame, before
///     the shutter actually enables (see [_updateHoldSteady]).
///
/// Exposure and focus lock to whatever the first successful shot of a set
/// metered ([_lockExposureAndFocus]), rather than each of the 8 shots
/// re-metering independently — otherwise a perfectly good set can still
/// read as inconsistent (photo 3 warmer than photo 7) purely from the
/// camera re-adjusting between shots of the same car under the same light.
/// Tappable to release (see [_unlockExposure]) for the real case where the
/// light actually does change mid-shoot. True white-balance lock isn't
/// something the `camera` plugin exposes at all — checked directly against
/// its API — so exposure and focus are the two levers actually available,
/// not a deliberately partial choice.
///
/// Still deliberately not here: holding a set offline and resuming it after
/// the app is closed; matching the guide's virtual FOV to a specific
/// device's real camera intrinsics (the `camera` plugin exposes zoom level
/// but no focal length or field of view at all — this would need native
/// platform-channel code reading AVFoundation directly, unverifiable
/// without a physical device, and a real addition of scope rather than a
/// tweak); and per-photograph angle/pitch/exposure metadata riding along
/// with the upload (checked `routes_listings.py` directly — its
/// `upload_images` endpoint and the `Image` model it writes have no column
/// for either today; sending it from this screen anyway would either be
/// silently dropped or need that backend change made first — see
/// `docs/MOBILE_PLAN.md`'s "Backend changes" section).
///
/// The chrome — the progress pill, the exposure-lock badge, the close and
/// camera-switch buttons — shares one translucent style ([_Glass]) so a
/// control still reads as floating over the video rather than as a grey box
/// stuck on top of it. This was real frosted glass (`BackdropFilter` blur)
/// for one round; see that class's own doc comment for why it came back
/// out — measured on-device at 130%+ CPU and a red energy gauge, from
/// blurring live camera video continuously on every frame across six
/// regions at once, not a cost that tuning the blur radius down would have
/// fixed. The pill's dot row underneath the angle
/// name is position only ("2 of 8"); which angles are actually captured,
/// skipped or still open is the filmstrip's job ([_Filmstrip], the right
/// edge) — one tile per angle rather than a growing thumbnail list, tap any
/// tile to shoot or reshoot that angle next regardless of its own state
/// (see [_selectAngle]). The old bottom thumbnail row and "Next: …" text
/// strip are both gone, absorbed into the dots and the filmstrip
/// respectively, which is also what let the shutter itself grow and move
/// to dead centre.
///
/// The "aligned" green is `design/tokens.dart`'s real `forestLift` accent,
/// not the `0xFF34D058` this screen used until it was caught mid-review as
/// off-brand — that file's own comment says there is "deliberately no
/// success colour" and to "resist adding a second accent".
///
/// Not reachable from a listing — there is no "start a new listing" flow in
/// this app yet either, so this screen is opened standalone from the camera
/// bubble in `AppShell` and holds its captures only in its own state.
///
/// Reached via a Material container transform (`OpenContainer`, wired in
/// `app_shell.dart`) rather than a pushed route: the bubble itself grows
/// into this screen and shrinks back on close, which is why this screen has
/// no route of its own and instead takes [onClose] to trigger that reverse
/// animation.
library;

import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../settings/app_preferences.dart';
import 'capture_angles.dart';
import 'capture_draft.dart';
import 'device_tilt_detector.dart';
import 'image_quality_detector.dart';
import 'review_screen.dart';
import 'vehicle_frame_detector.dart';
import 'vehicle_silhouette_painter.dart';

/// What the exit-confirmation dialog in [_CaptureScreenState._handleCloseRequest]
/// was answered with.
enum _QuitAction { discard, saveDraft }

// ── Camera lifecycle state ──────────────────────────────────────────────────

/// What the screen can currently show for the camera itself.
///
/// A sealed hierarchy for the same reason `_Load` exists on the listings and
/// listing detail screens: "starting up", "ready with a live controller" and
/// "not available" are mutually exclusive, and only [_CameraReady] carries a
/// controller — nothing here can accidentally call a method on a controller
/// that was never initialised.
sealed class _CameraState {
  const _CameraState();
}

final class _CameraInitializing extends _CameraState {
  const _CameraInitializing();
}

final class _CameraReady extends _CameraState {
  const _CameraReady(this.controller);
  final CameraController controller;
}

/// A real, actionable problem: permission was refused, or the hardware
/// reported a genuine fault. Blocks the interface with a message and a
/// retry, because there is nothing useful to show behind it — a shutter with
/// no chance of ever taking a photograph is worse than no shutter at all.
final class _CameraUnavailable extends _CameraState {
  const _CameraUnavailable(this.message);
  final String message;
}

/// There is simply no camera to ask — the iOS Simulator, mainly, which
/// reports zero cameras rather than denying permission for one. Unlike
/// [_CameraUnavailable] this is not an error to retry: the rest of the
/// capture interface still renders behind a placeholder in place of the live
/// feed, so the screen can be reviewed and its non-camera controls exercised
/// without a physical device.
final class _NoCameraHardware extends _CameraState {
  const _NoCameraHardware();
}

// ── Screen ───────────────────────────────────────────────────────────────────

class CaptureScreen extends ConsumerStatefulWidget {
  const CaptureScreen({super.key, this.onClose});

  /// Called instead of popping the route directly when set — [AppShell]
  /// passes the container-transform's own close callback here so leaving
  /// this screen shrinks back into the camera bubble rather than sliding
  /// away like an ordinary pushed route. Falls back to a plain
  /// `Navigator.pop` when this screen is reached some other way.
  final VoidCallback? onClose;

  @override
  ConsumerState<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends ConsumerState<CaptureScreen>
    with WidgetsBindingObserver {
  _CameraState _state = const _CameraInitializing();

  /// One photograph per angle it was shot for. Deliberately a map keyed by
  /// [CaptureAngle] rather than a plain list: an angle can be recaptured (a
  /// delete just removes its entry, making it "next" again), and the fixed
  /// sequence — not capture order — is what the rest of this screen displays
  /// things in, via [_orderedCaptures].
  final Map<CaptureAngle, XFile> _captured = {};

  /// Angles the photographer chose to skip rather than shoot — see
  /// [_skip]. Kept separate from [_captured] because a skipped angle is not
  /// "done", it is "deliberately left for later", and the two must not be
  /// conflated when deciding what is next.
  final Set<CaptureAngle> _skipped = {};

  bool _capturing = false;
  bool _submitting = false;

  /// Every camera the device offers — front, back, and (where the plugin
  /// exposes them) any extra back lenses — so [_switchCamera] has something
  /// to cycle through. Populated once, the first time [_initCamera] runs;
  /// switching cameras reuses it rather than re-querying the hardware.
  List<CameraDescription> _availableCameras = [];
  int _cameraIndex = 0;

  /// On-device "is a car actually in frame, and is it framed well" check —
  /// see vehicle_frame_detector.dart for why this exists and what it does
  /// and doesn't do. Created once and reused across camera switches; only
  /// disposed when this screen itself closes.
  final VehicleFrameDetector _frameDetector = VehicleFrameDetector();

  /// The most recent read from [_frameDetector]. Null means "no opinion
  /// yet" — either analysis hasn't produced a result since the camera last
  /// (re)started, or (on Android, for now — see
  /// inputImageFromCameraImage's doc comment) the feature simply is not
  /// running at all. Null never blocks the shutter; only a concrete
  /// [FrameGuidance] with [FrameGuidance.blocksCapture] true does — a brief
  /// window with no opinion is preferable to guessing, and preferable to
  /// permanently blocking a platform this has not been wired up for yet.
  FrameGuidance? _frameGuidance;
  DateTime? _lastFrameAnalysisAt;

  /// IMU-based pitch/roll — see device_tilt_detector.dart. Independent of
  /// the camera lifecycle (it reads the accelerometer, not a camera frame),
  /// so it starts once in [initState] and runs for as long as this screen
  /// is open, camera switches and all.
  final DeviceTiltDetector _tiltDetector = DeviceTiltDetector();
  TiltReading? _tiltReading;

  /// Blur/glare check on the same camera frame [_frameDetector] already
  /// analyses — see image_quality_detector.dart. Same "no opinion yet"
  /// convention as [_frameGuidance]: null never blocks.
  ImageQuality? _imageQuality;

  /// When the current shot first became fully unblocked (every check
  /// passing at once), or null while something is still wrong. Read by
  /// [build] to require that state to have held for [_holdSteadyDuration]
  /// before the shutter actually enables — see [_updateHoldSteady].
  DateTime? _allGoodSince;

  static const _holdSteadyDuration = Duration(milliseconds: 600);

  /// True once exposure and focus have been locked at whatever the first
  /// successful shot of this camera session metered — see [_capture] and
  /// [_unlockExposure]. Consistency, not correctness: nothing here checks
  /// whether that first shot happened to be well-lit, only that every shot
  /// after it stops drifting independently, which is what actually causes a
  /// listing where photo 3 reads warmer than photo 7. True white-balance
  /// lock isn't something the `camera` plugin exposes at all (checked —
  /// only exposure and focus mode/point exist in its API); exposure and
  /// focus are the two levers actually available.
  bool _exposureLocked = false;

  /// Set by tapping a tile in the filmstrip — see [_selectAngle]. Overrides
  /// the normal "first missing angle" sequencing so a photographer can shoot
  /// out of order, then reverts on its own once that angle is captured
  /// (checked in [_currentAngle] itself, so nothing else has to remember to
  /// clear it) or is explicitly skipped (cleared in [_skip]).
  CaptureAngle? _jumpTarget;

  /// The angle to shoot next: [_jumpTarget] if one is set and still open,
  /// otherwise the first in the fixed sequence that is neither captured nor
  /// skipped. Null once every angle has one or the other — the whole set is
  /// then either complete or deliberately partial, and either is a valid
  /// state to submit from (see the exception flows this story's brief calls
  /// out: skipping is permitted, not an error).
  CaptureAngle? get _currentAngle {
    final jump = _jumpTarget;
    if (jump != null && !_captured.containsKey(jump)) return jump;
    for (final angle in CaptureAngle.values) {
      if (!_captured.containsKey(angle) && !_skipped.contains(angle)) {
        return angle;
      }
    }
    return null;
  }

  /// Captured photographs in sequence order — the order they are shot in by
  /// default, but not necessarily the order they end up in [_captured] once
  /// a middle angle has been deleted and reshot later.
  List<MapEntry<CaptureAngle, XFile>> get _orderedCaptures => [
    for (final angle in CaptureAngle.values)
      if (_captured[angle] case final file?) MapEntry(angle, file),
  ];

  /// The current tilt reading against the current angle's own target — null
  /// only when either input is missing (no reading yet, or nothing left to
  /// shoot), never a "bad" value on its own.
  LevelGuidance? get _levelGuidance {
    final angle = _currentAngle;
    final tilt = _tiltReading;
    if (angle == null || tilt == null) return null;
    return evaluateLevel(tilt, angle.targetElevationDeg);
  }

  /// The single most fundamental reason the shutter can't fire right now,
  /// in priority order — vehicle framing first (there is no point telling
  /// someone to level the phone at an empty wall), then tilt, then image
  /// quality. Null means nothing is currently blocking (the hold-steady
  /// window in [_updateHoldSteady] is a separate, additional gate on top of
  /// this being null).
  String? get _blockingMessage {
    final frame = _frameGuidance;
    if (frame != null && frame.blocksCapture) return frame.message;

    final level = _levelGuidance;
    if (level != null && level.blocksCapture) return level.message;

    final quality = _imageQuality;
    if (quality != null && quality.blocksCapture) return quality.message;

    return null;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Locked to portrait for the whole time this screen is open: the live
    // preview's fill math (see _CameraPreviewFilled) assumes a portrait UI,
    // and on an iPad — which the app otherwise supports in any orientation —
    // an unlocked landscape rotation here is what made the feed look
    // squashed rather than simply rotated.
    SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
    _initCamera();
    _tiltDetector.start((reading) {
      if (!mounted) return;
      setState(() {
        _tiltReading = reading;
        _updateHoldSteady();
      });
    });
    // After the first frame, not inline here: offering to resume a draft
    // means showing a dialog, which needs a BuildContext already attached to
    // the tree.
    WidgetsBinding.instance.addPostFrameCallback((_) => _offerDraftResume());
  }

  /// Checks for a draft saved by a previous "Save Draft" (see
  /// [_handleCloseRequest]) and, if one exists, asks whether to pick up where
  /// it left off. Declining discards it outright rather than leaving it to be
  /// silently overwritten by whatever gets saved next — an abandoned draft
  /// sitting around unseen is worse than none at all.
  Future<void> _offerDraftResume() async {
    final draft = await loadCaptureDraft();
    if (draft == null || !mounted) return;

    final resume = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Resume your last capture?'),
        content: Text(
          '${draft.shotCount} of ${CaptureAngle.values.length} photographs '
          'were saved before you left the camera.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Discard'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Resume'),
          ),
        ],
      ),
    );
    if (!mounted) return;

    if (resume == true) {
      setState(() {
        for (final MapEntry(key: angle, value: file) in draft.files.entries) {
          _captured[angle] = XFile(file.path);
        }
        _skipped.addAll(draft.skipped);
      });
    } else {
      await clearCaptureDraft();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    SystemChrome.setPreferredOrientations(const []);
    final state = _state;
    if (state is _CameraReady) state.controller.dispose();
    _frameDetector.dispose();
    _tiltDetector.dispose();
    super.dispose();
  }

  /// Tracks how long the shot has been fully unblocked — [_blockingMessage]
  /// turning null is necessary but not sufficient for the shutter to
  /// enable; it also has to have STAYED null for [_holdSteadyDuration],
  /// so a shot isn't taken on the one frame where every check happened to
  /// line up for an instant. Called from inside every setState that can
  /// change [_blockingMessage]'s inputs (frame guidance, tilt, image
  /// quality) — mutating a field inside those closures, not in [build],
  /// which only reads the result.
  void _updateHoldSteady() {
    if (_blockingMessage != null || _currentAngle == null) {
      _allGoodSince = null;
    } else {
      _allGoodSince ??= DateTime.now();
    }
  }

  /// The camera hardware is released while the app is backgrounded and
  /// re-acquired on return — a controller left open behind a backgrounded
  /// app is a known source of crashes on both platforms, not a theoretical
  /// one, which is why this is here even though nothing else on this screen
  /// needs lifecycle awareness.
  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycleState) {
    final state = _state;
    if (state is! _CameraReady) return;

    if (lifecycleState == AppLifecycleState.inactive) {
      state.controller.dispose();
      setState(() => _state = const _CameraInitializing());
    } else if (lifecycleState == AppLifecycleState.resumed) {
      _initCamera();
    }
  }

  Future<void> _initCamera() async {
    setState(() => _state = const _CameraInitializing());
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        if (!mounted) return;
        setState(() => _state = const _NoCameraHardware());
        return;
      }

      _availableCameras = cameras;
      _cameraIndex = cameras.indexWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
      );
      if (_cameraIndex < 0) _cameraIndex = 0;
      await _openCamera(cameras[_cameraIndex]);
    } on CameraException catch (e) {
      if (!mounted) return;
      setState(() => _state = _CameraUnavailable(_messageFor(e)));
    }
  }

  Future<void> _openCamera(CameraDescription description) async {
    final controller = CameraController(
      description,
      ResolutionPreset.high,
      enableAudio: false,
      // bgra8888 is what inputImageFromCameraImage expects and is the one
      // format group ML Kit documents support on iOS; left unset on other
      // platforms since on-device detection does not run there yet (see
      // that function's doc comment) and there is no reason to force an
      // unusual format group for a feature that will not use it.
      imageFormatGroup: Platform.isIOS ? ImageFormatGroup.bgra8888 : null,
    );
    await controller.initialize();

    if (!mounted) {
      await controller.dispose();
      return;
    }
    setState(() {
      _state = _CameraReady(controller);
      _frameGuidance = null;
      _imageQuality = null;
      _allGoodSince = null;
      // A fresh CameraController always starts back on auto exposure/focus
      // regardless of what the previous one was set to — nothing carries
      // over across a camera switch, so neither should this flag.
      _exposureLocked = false;
    });

    if (Platform.isIOS) {
      await controller.startImageStream(
        (image) => _onCameraFrame(image, description),
      );
    }
  }

  /// Runs at most one detection pass every [_frameAnalysisInterval] — ML
  /// Kit's own SDKs are fast enough to run far more often than that, but
  /// there is no benefit to analysing faster than a photographer can
  /// actually react to the guidance text changing, and continuous
  /// full-rate inference is a real, avoidable battery cost for a screen
  /// meant to stay open for a whole walk around a vehicle.
  static const _frameAnalysisInterval = Duration(milliseconds: 400);

  void _onCameraFrame(CameraImage image, CameraDescription description) {
    final now = DateTime.now();
    final last = _lastFrameAnalysisAt;
    if (last != null && now.difference(last) < _frameAnalysisInterval) return;
    _lastFrameAnalysisAt = now;

    // Synchronous and cheap (a sparse sampled grid, not a full-resolution
    // pass — see image_quality_detector.dart) so it runs inline here rather
    // than needing the async dance ML Kit's analyze() below does.
    final quality = evaluateImageQuality(analyzeImageQuality(image));
    if (mounted) {
      setState(() {
        _imageQuality = quality;
        _updateHoldSteady();
      });
    }

    final input = inputImageFromCameraImage(image, description);
    if (input == null) return;

    _frameDetector.analyze(input).then((guidance) {
      if (!mounted || guidance == null) return;
      setState(() {
        _frameGuidance = guidance;
        _updateHoldSteady();
      });
    });
  }

  /// Cycles to the next camera the device offers — front/back at minimum,
  /// and any further back lenses the `camera` plugin exposes. Does nothing
  /// when there is only one, so the switch control simply does not appear
  /// in that case rather than doing something pointless.
  Future<void> _switchCamera() async {
    if (_availableCameras.length < 2) return;

    final state = _state;
    if (state is _CameraReady) await state.controller.dispose();
    if (!mounted) return;
    setState(() => _state = const _CameraInitializing());

    _cameraIndex = (_cameraIndex + 1) % _availableCameras.length;
    try {
      await _openCamera(_availableCameras[_cameraIndex]);
    } on CameraException catch (e) {
      if (!mounted) return;
      setState(() => _state = _CameraUnavailable(_messageFor(e)));
    }
  }

  String _messageFor(CameraException e) => switch (e.code) {
    'CameraAccessDenied' ||
    'CameraAccessDeniedWithoutPrompt' ||
    'CameraAccessRestricted' =>
      'AutoPivot needs camera access to take photographs. '
          'Enable it for AutoPivot in Settings.',
    _ => e.description ?? 'The camera could not be started.',
  };

  Future<void> _capture() async {
    final state = _state;
    final angle = _currentAngle;
    if (state is! _CameraReady || _capturing || angle == null) return;
    if (_blockingMessage != null) return;
    final goodSince = _allGoodSince;
    if (goodSince == null ||
        DateTime.now().difference(goodSince) < _holdSteadyDuration) {
      return;
    }

    setState(() => _capturing = true);
    try {
      final photo = await state.controller.takePicture();
      if (!mounted) return;
      // A reshoot of an angle that was previously skipped supersedes the
      // skip — it is no longer "left for later", it is done. Clearing a
      // matching jump target here (rather than leaving it to just stop
      // matching once _captured contains the angle) avoids a stale target
      // silently reactivating if this exact angle is ever removed again.
      setState(() {
        _captured[angle] = photo;
        _skipped.remove(angle);
        if (_jumpTarget == angle) _jumpTarget = null;
      });
      // A firmer tap than the alignment one above — this is the shot
      // actually being taken, the moment worth the most feedback in the
      // whole capture loop.
      haptic(ref, HapticFeedbackType.medium);
      // Locks in whatever auto exposure/focus metered for THIS shot — the
      // first one, specifically, since it's the first moment there was
      // actually a well-framed car to meter against. Every shot after it
      // reuses that same reading instead of re-metering independently,
      // which is what keeps a full 8-photo set looking like one
      // continuous shoot instead of eight separately-exposed photographs.
      if (!_exposureLocked) await _lockExposureAndFocus(state.controller);
    } on CameraException {
      // Skeleton scope: a failed shutter press just leaves the set
      // unchanged rather than surfacing a dedicated error — see the doc
      // comment at the top of this file for what deliberately isn't here
      // yet (dark/blurred warnings among it).
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  /// Best-effort — not every camera on every device actually supports a
  /// lock (older or unusual hardware can reject the mode change), and
  /// leaving the rest of the set on auto exposure in that case is a far
  /// smaller problem than crashing the screen or blocking the shutter over
  /// it, so a failure here is silently absorbed rather than surfaced.
  Future<void> _lockExposureAndFocus(CameraController controller) async {
    try {
      await controller.setExposureMode(ExposureMode.locked);
      await controller.setFocusMode(FocusMode.locked);
      if (mounted) setState(() => _exposureLocked = true);
    } on CameraException {
      // Stays unlocked; every future shot will just try again on its own
      // capture (the `if (!_exposureLocked)` guard above), which costs
      // nothing if it keeps failing.
    }
  }

  /// Lets the photographer deliberately re-meter — real lighting does
  /// change mid-shoot (a car rolled from shade into direct sun, say), and a
  /// lock with no way back would make that worse, not better. Returns to
  /// auto rather than re-locking immediately: the very next successful
  /// shot re-locks on whatever auto settles on for the new conditions, the
  /// same as the first shot of the set did.
  Future<void> _unlockExposure() async {
    final state = _state;
    if (state is! _CameraReady) return;
    try {
      await state.controller.setExposureMode(ExposureMode.auto);
      await state.controller.setFocusMode(FocusMode.auto);
    } on CameraException {
      // Nothing useful to do differently here — see _lockExposureAndFocus.
    } finally {
      if (mounted) setState(() => _exposureLocked = false);
    }
  }

  /// The filmstrip's one interaction, for a tile in any state: an untouched
  /// angle becomes the new target out of sequence, a skipped one is
  /// un-skipped and becomes the target, and a captured one is cleared and
  /// becomes the target — "tap this tile to shoot (or reshoot) this angle
  /// next", regardless of what it currently shows. One method rather than
  /// three, since all three are really the same intent.
  void _selectAngle(CaptureAngle angle) {
    setState(() {
      _captured.remove(angle);
      _skipped.remove(angle);
      _jumpTarget = angle;
    });
  }

  /// Permitted, not an error — the brief is explicit that a photographer
  /// standing at a vehicle knows more about why an angle is awkward right
  /// now (parked against a wall, another car too close) than this screen
  /// does, and the set should move on rather than block.
  void _skip() {
    final angle = _currentAngle;
    if (angle == null) return;
    setState(() {
      _skipped.add(angle);
      // Otherwise _currentAngle would keep returning this same angle
      // forever — skip only clears from the normal sequence, and the jump
      // target bypasses that check on purpose.
      if (_jumpTarget == angle) _jumpTarget = null;
    });
  }

  /// Creates the listing these photographs belong to, then uploads them.
  ///
  /// A listing cannot exist without make/model/year — they are `NOT NULL`
  /// columns on the server (see [ApiClient.createListing]) — so this asks
  /// for them here rather than pretending a bare set of photographs is
  /// enough. Per-photograph angle tagging is not part of this call: the
  /// upload endpoint takes plain files today, so every photograph reaches
  /// the pipeline as an ordinary original — the angle/pitch metadata column
  /// this story eventually wants (see the doc comment at the top of this
  /// file) is a separate, additive backend change, not a blocker for
  /// getting real photographs into a real listing now.
  /// Opens the review screen (grid → vehicle details) and acts on whatever
  /// it closes with — see [ReviewResult]'s own doc comment for why every
  /// branch carries the current photo map: a photo deleted mid-review is
  /// never lost, whether the review ends in a retake or a submit.
  Future<void> _submit() async {
    final result = await Navigator.of(context).push<ReviewResult>(
      MaterialPageRoute(
        builder: (_) => ReviewScreen(initialCaptured: Map.of(_captured)),
      ),
    );
    if (result == null || !mounted) return;

    setState(() {
      _captured
        ..clear()
        ..addAll(result.photos);
    });

    switch (result) {
      case ReviewClosed():
        return;
      case ReviewRetake(:final angle):
        _selectAngle(angle);
      case ReviewSubmit(:final details, :final backdropId):
        await _submitListing(details, backdropId);
    }
  }

  /// Creates the listing, uploads every captured photograph and queues it
  /// for processing — the pipeline used to only start once someone opened
  /// the listing on the platform and asked for it there; this is the whole
  /// reason the review screen asks for a backdrop up front rather than
  /// leaving it for later.
  Future<void> _submitListing(VehicleDetails details, int? backdropId) async {
    setState(() => _submitting = true);
    final api = ref.read(apiClientProvider);
    try {
      final listing = await api.createListing(
        make: details.make,
        model: details.model,
        year: details.year,
        variant: details.variant,
      );
      final paths = _orderedCaptures.map((e) => e.value.path).toList();
      await api.uploadImages(listing.id, paths);

      // A processing failure here does not undo the upload above — the
      // photographs and the listing both exist either way, which is why
      // this is its own try block with its own message rather than folding
      // into the outer catch and implying the whole submit failed.
      String? processingWarning;
      try {
        await api.processListing(listing.id, backdropId: backdropId);
      } on ApiException catch (e) {
        processingWarning = e.message;
      }
      await clearCaptureDraft();
      if (!mounted) return;
      haptic(ref, HapticFeedbackType.medium);

      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Uploaded'),
          content: Text(
            processingWarning == null
                ? '${paths.length} photograph${paths.length == 1 ? '' : 's'} '
                      'added to "${listing.title}" and sent for processing.'
                : '${paths.length} photograph${paths.length == 1 ? '' : 's'} '
                      'added to "${listing.title}", but processing could not '
                      'be started: $processingWarning',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('OK'),
            ),
          ],
        ),
      );
      if (!mounted) return;
      (widget.onClose ?? () => Navigator.of(context).pop()).call();
    } on ApiException catch (e) {
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Could not submit'),
          content: Text(e.message),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('OK'),
            ),
          ],
        ),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  /// The close button and the system back gesture both land here — a
  /// half-shot set is real work a photographer can lose by backing out
  /// without meaning to, so neither is allowed to close this screen
  /// silently once anything has been captured or skipped.
  Future<void> _handleCloseRequest() async {
    if (_captured.isEmpty && _skipped.isEmpty) {
      (widget.onClose ?? () => Navigator.of(context).pop()).call();
      return;
    }

    final action = await showDialog<_QuitAction>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Quit the camera?'),
        content: Text(
          '${_captured.length} of ${CaptureAngle.values.length} photographs '
          'have been taken. Save a draft to pick this back up later, or '
          'discard everything.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: C.rust),
            onPressed: () =>
                Navigator.of(dialogContext).pop(_QuitAction.discard),
            child: const Text('Discard'),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(_QuitAction.saveDraft),
            child: const Text('Save Draft'),
          ),
        ],
      ),
    );
    if (action == null || !mounted) return;

    if (action == _QuitAction.saveDraft) {
      await saveCaptureDraft(
        capturedPaths: _captured.map(
          (angle, file) => MapEntry(angle, file.path),
        ),
        skipped: _skipped,
      );
    } else {
      await clearCaptureDraft();
    }
    if (!mounted) return;
    (widget.onClose ?? () => Navigator.of(context).pop()).call();
  }

  @override
  Widget build(BuildContext context) {
    final canAct = !_submitting;
    final blockingMessage = _blockingMessage;
    // Green tint fires as soon as every check agrees — a moment before the
    // shutter itself unlocks (see settled below) — so the photographer sees
    // "you've got it" and knows to hold rather than only finding out once
    // the shutter silently becomes tappable.
    final instantaneouslyGood =
        blockingMessage == null && _currentAngle != null;
    final goodSince = _allGoodSince;
    final settled =
        goodSince != null &&
        DateTime.now().difference(goodSince) >= _holdSteadyDuration;
    final canCapture = canAct && instantaneouslyGood && settled;

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _handleCloseRequest();
      },
      child: Scaffold(
        backgroundColor: Colors.black,
        body: Stack(
          children: [
            Positioned.fill(
              child: switch (_state) {
                _CameraInitializing() => const _CenteredMessage(
                  message: 'Starting camera…',
                  showSpinner: true,
                ),
                _CameraUnavailable(:final message) => _CenteredMessage(
                  message: message,
                  onRetry: _initCamera,
                ),
                _NoCameraHardware() => _CaptureBody(
                  controller: null,
                  currentAngle: _currentAngle,
                  captured: _captured,
                  skipped: _skipped,
                  capturing: _capturing,
                  submitting: _submitting,
                  blockingMessage: null,
                  aligned: false,
                  tiltReading: null,
                  exposureLocked: false,
                  onUnlockExposure: null,
                  onCapture: null,
                  onSelectAngle: canAct ? _selectAngle : null,
                  onSkip: (canAct && _currentAngle != null) ? _skip : null,
                  onSubmit: (canAct && _captured.isNotEmpty) ? _submit : null,
                ),
                _CameraReady(:final controller) => _CaptureBody(
                  controller: controller,
                  currentAngle: _currentAngle,
                  captured: _captured,
                  skipped: _skipped,
                  capturing: _capturing,
                  submitting: _submitting,
                  blockingMessage: blockingMessage,
                  aligned: instantaneouslyGood,
                  tiltReading: _tiltReading,
                  exposureLocked: _exposureLocked,
                  onUnlockExposure: canAct ? _unlockExposure : null,
                  onCapture: canCapture ? _capture : null,
                  onSelectAngle: canAct ? _selectAngle : null,
                  onSkip: (canAct && _currentAngle != null) ? _skip : null,
                  onSubmit: (canAct && _captured.isNotEmpty) ? _submit : null,
                ),
              },
            ),
            Positioned(
              top: Space.sm,
              left: Space.sm,
              child: SafeArea(
                child: _CloseButton(onPressed: _handleCloseRequest),
              ),
            ),
            if (_availableCameras.length > 1 && _state is _CameraReady)
              Positioned(
                top: Space.sm,
                right: Space.sm,
                child: SafeArea(
                  child: _SwitchCameraButton(
                    onPressed: canAct ? _switchCamera : null,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ── Initialising / unavailable ──────────────────────────────────────────────

class _CenteredMessage extends StatelessWidget {
  const _CenteredMessage({
    required this.message,
    this.showSpinner = false,
    this.onRetry,
  });

  final String message;
  final bool showSpinner;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (showSpinner) ...[
              const CircularProgressIndicator(color: C.white),
              const SizedBox(height: Space.lg),
            ],
            Text(
              message,
              style: T.body.copyWith(color: C.white),
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: Space.lg),
              FilledButton(
                onPressed: onRetry,
                style: FilledButton.styleFrom(minimumSize: const Size(0, 48)),
                child: const Text('Try again'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CloseButton extends StatelessWidget {
  const _CloseButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Close camera',
      excludeSemantics: true,
      child: _Glass(
        circular: true,
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onPressed,
            child: const Padding(
              padding: EdgeInsets.all(Space.sm),
              child: Icon(Icons.close, color: C.white, size: 22),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Ready: preview, guidance seam, controls ─────────────────────────────────

class _CaptureBody extends StatelessWidget {
  const _CaptureBody({
    required this.controller,
    required this.currentAngle,
    required this.captured,
    required this.skipped,
    required this.capturing,
    required this.submitting,
    required this.blockingMessage,
    required this.aligned,
    required this.tiltReading,
    required this.exposureLocked,
    required this.onUnlockExposure,
    required this.onCapture,
    required this.onSelectAngle,
    required this.onSkip,
    required this.onSubmit,
  });

  /// Null on a device with no camera to preview — see [_NoCameraHardware].
  final CameraController? controller;

  /// The angle to shoot next, or null once every angle has been either
  /// captured or skipped.
  final CaptureAngle? currentAngle;

  /// What the filmstrip renders — every angle's own capture, or lack of
  /// one, rather than just the ones already shot, since the whole point of
  /// the filmstrip is showing all 8 slots at once, not a growing list.
  final Map<CaptureAngle, XFile> captured;
  final Set<CaptureAngle> skipped;
  final bool capturing;

  /// True while the submitted set is being created and uploaded — every
  /// other control on this screen disables during that window rather than
  /// letting a shot happen mid-upload.
  final bool submitting;

  /// The single most relevant reason the shutter can't fire yet — see
  /// [_CaptureScreenState._blockingMessage]. Null means every check
  /// currently agrees (though the shutter may still be disabled a moment
  /// longer for the hold-steady window — see [onCapture]).
  final String? blockingMessage;

  /// True the instant every check agrees, tinting the guide green — this
  /// fires slightly before [onCapture] actually becomes non-null, so the
  /// photographer sees "you've got it" and knows to hold still rather than
  /// only finding out once the shutter is already tappable.
  final bool aligned;

  /// Current device tilt for the level indicator — see
  /// device_tilt_detector.dart. Null before the first accelerometer sample
  /// arrives.
  final TiltReading? tiltReading;

  /// Whether exposure/focus are currently locked to the first shot's
  /// reading — see [_CaptureScreenState._exposureLocked]. Drives the small
  /// lock badge; [onUnlockExposure] is what a tap on it calls.
  final bool exposureLocked;

  /// Null while there is nothing locked to release (no camera, or already
  /// unlocked) — see [_CaptureScreenState._unlockExposure].
  final VoidCallback? onUnlockExposure;

  /// Null when there is no controller to capture from, nothing left in the
  /// sequence to shoot, [blockingMessage] is non-null, or the hold-steady
  /// window hasn't elapsed yet. The shutter renders disabled rather than
  /// disappearing in every case, so the rest of the layout — where it sits,
  /// how big it is — can still be reviewed without a camera.
  final VoidCallback? onCapture;
  final ValueChanged<CaptureAngle>? onSelectAngle;
  final VoidCallback? onSkip;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    final controller = this.controller;
    final angle = currentAngle;
    return Stack(
      fit: StackFit.expand,
      children: [
        controller == null
            ? const _NoPreviewPlaceholder()
            : _CameraPreviewFilled(controller: controller),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.only(top: Space.sm),
            child: Column(
              children: [
                _ProgressPill(currentAngle: angle),
                if (angle != null) ...[
                  const SizedBox(height: Space.sm),
                  _LevelIndicator(
                    tiltReading: tiltReading,
                    targetElevationDeg: angle.targetElevationDeg,
                  ),
                ],
                if (exposureLocked) ...[
                  const SizedBox(height: Space.sm),
                  _ExposureLockBadge(onTap: onUnlockExposure),
                ],
                // Lives up here rather than sharing the centre with the
                // guide overlay below — two things both reaching for screen
                // centre is how they end up printed on top of one another
                // instead of either being readable.
                if (controller == null) ...[
                  const SizedBox(height: Space.sm),
                  const _NoCameraNotice(),
                ],
              ],
            ),
          ),
        ),
        Center(
          child: angle == null
              ? const _AllAnglesDone()
              : VehicleGuideOverlay(angle: angle, aligned: aligned),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: SafeArea(
            child: Padding(
              padding: const EdgeInsets.only(right: Space.sm),
              child: _Filmstrip(
                currentAngle: angle,
                captured: captured,
                skipped: skipped,
                onSelect: onSelectAngle,
              ),
            ),
          ),
        ),
        SafeArea(
          child: Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: Space.md),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (blockingMessage case final message?) ...[
                    _BlockerBanner(message: message),
                    const SizedBox(height: Space.sm),
                  ],
                  _BottomControls(
                    capturedCount: captured.length,
                    capturing: capturing,
                    submitting: submitting,
                    onCapture: onCapture,
                    onSkip: onSkip,
                    onSubmit: onSubmit,
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// Explains why the shutter is disabled — whichever of vehicle framing
/// ([VehicleFrameDetector]), tilt ([DeviceTiltDetector]) or image quality
/// ([ImageQuality]) is currently the most fundamental problem; see
/// [_CaptureScreenState._blockingMessage] for the priority order. Only ever
/// shown for a concrete blocking message, so its text is always something
/// actionable ("Move closer", "Tilt the phone down a little"), never blank.
class _BlockerBanner extends StatelessWidget {
  const _BlockerBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: C.rust.withAlpha(217),
        borderRadius: Radii.controlAll,
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: Space.md,
          vertical: Space.sm,
        ),
        child: Text(
          message,
          style: T.label.copyWith(color: C.white),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

/// Shared translucent chrome for the small pills and circular buttons
/// scattered around this screen's edges, so a control still reads as
/// floating over the video against a bright, cluttered background (a car
/// lot, not a studio) rather than as a grey box stuck on top of it.
/// [circular] switches the shape from a rounded rectangle to a true circle
/// for the icon buttons.
///
/// This used to be real frosted glass — a `BackdropFilter` Gaussian blur —
/// which was measured on-device to push sustained CPU past 130% and the
/// energy gauge into the red, running visibly laggy, whereas the same
/// screen with only ML Kit's own (throttled, 400ms-interval) analysis
/// running was fine. That comparison is the tell: `BackdropFilter` has to
/// re-blur whatever is behind it on every displayed frame for as long as
/// it's on screen, not on a throttle — over a live camera preview updating
/// at 30-60fps, six of them at once (one per pill/button, all this
/// screen's chrome) meant six full-screen-region blurs recomputed every
/// single frame, continuously, the entire time this screen is open. ML
/// Kit's cost was bounded and occasional by comparison. iOS's own
/// UIVisualEffectView blur is cheap because it's a dedicated native
/// compositor path with no real equivalent in Flutter's Skia-based
/// BackdropFilter — this is a case where the literal iOS visual effect
/// genuinely isn't reproducible at acceptable cost over live video in
/// Flutter today, not a tuning problem to solve by lowering the blur
/// radius. A plain translucent fill is what real camera apps' own
/// "floating over video" chrome mostly is anyway once you look closely.
class _Glass extends StatelessWidget {
  const _Glass({required this.child, this.circular = false});

  final Widget child;
  final bool circular;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.black.withAlpha(130),
        shape: circular ? BoxShape.circle : BoxShape.rectangle,
        borderRadius: circular ? null : Radii.controlAll,
        border: Border.all(color: Colors.white.withAlpha(28)),
      ),
      child: child,
    );
  }
}

/// The iPhone Camera app's own level tool, not a carpenter's bubble level:
/// a dim, fixed crosshair marks true target, a brighter one drifts toward
/// it as the phone approaches level (pitch against
/// [targetElevationDeg] — see device_tilt_detector.dart for why that's the
/// target and not zero — and roll against zero), and the two snap into one
/// enlarged green mark with a light haptic tick the instant they agree —
/// the same confirmation iOS gives, not a text message or a number anyone
/// has to read. No pitch/roll figures shown here on purpose — that's
/// exactly the "for devs" framing this replaces; those numbers did real
/// work confirming the tilt formula's sign was correct against real
/// hardware, and having done that job, don't belong in front of a
/// photographer who just needs to know which way to move the phone.
class _LevelIndicator extends ConsumerStatefulWidget {
  const _LevelIndicator({
    required this.tiltReading,
    required this.targetElevationDeg,
  });

  final TiltReading? tiltReading;
  final double targetElevationDeg;

  @override
  ConsumerState<_LevelIndicator> createState() => _LevelIndicatorState();
}

class _LevelIndicatorState extends ConsumerState<_LevelIndicator> {
  bool _wasGood = false;

  @override
  Widget build(BuildContext context) {
    final reading = widget.tiltReading;
    final good =
        reading != null &&
        evaluateLevel(reading, widget.targetElevationDeg) == LevelGuidance.good;

    if (good && !_wasGood) {
      // Fires once, on the moment level is reached — not every frame it
      // stays that way. Routed through haptic() rather than calling
      // HapticFeedback directly, so the Settings toggle actually governs it.
      haptic(ref);
    }
    _wasGood = good;

    return SizedBox(
      width: 60,
      height: 60,
      child: AnimatedScale(
        scale: good ? 1.1 : 1.0,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
        child: CustomPaint(
          painter: _CrosshairPainter(
            // Pitch error maps straight onto the vertical axis (tilt the
            // phone up, the live mark rises toward the fixed one) and roll
            // onto the horizontal one — both clamped so a large tilt just
            // pins the mark near the edge rather than flying off it.
            offset: reading == null
                ? Offset.zero
                : Offset(
                    reading.rollDeg.clamp(-12.0, 12.0),
                    (reading.pitchDeg - widget.targetElevationDeg).clamp(
                      -12.0,
                      12.0,
                    ),
                  ),
            good: good,
            hasReading: reading != null,
          ),
        ),
      ),
    );
  }
}

class _CrosshairPainter extends CustomPainter {
  const _CrosshairPainter({
    required this.offset,
    required this.good,
    required this.hasReading,
  });

  final Offset offset;
  final bool good;
  final bool hasReading;

  // See the matching note in vehicle_silhouette_painter.dart — was
  // 0xFF34D058, off-brand; forestLift is design/tokens.dart's real accent.
  static const _alignedColor = C.forestLift;
  static const _armLength = 7.0;
  static const _maxPixelOffset = 18.0;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final liveColor = hasReading
        ? (good ? _alignedColor : Colors.white)
        : Colors.white38;

    void drawCrosshair(Offset at, Color color, double strokeWidth) {
      final paint = Paint()
        ..color = color
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(
        at.translate(-_armLength, 0),
        at.translate(_armLength, 0),
        paint,
      );
      canvas.drawLine(
        at.translate(0, -_armLength),
        at.translate(0, _armLength),
        paint,
      );
    }

    if (good) {
      // Merged into one enlarged mark rather than two overlapping ones —
      // the "locked in" moment, not just a coincidence of two marks
      // passing over each other.
      drawCrosshair(center, liveColor, 3);
      return;
    }

    // The dim, fixed target — always centred, deliberately understated so
    // it doesn't compete with the live mark for attention.
    drawCrosshair(center, Colors.white24, 2);

    final live = center + (offset / 12.0 * _maxPixelOffset);
    drawCrosshair(live, liveColor, 2.5);
  }

  @override
  bool shouldRepaint(covariant _CrosshairPainter oldDelegate) =>
      oldDelegate.offset != offset ||
      oldDelegate.good != good ||
      oldDelegate.hasReading != hasReading;
}

/// Tells the photographer exposure/focus are locked for the rest of this
/// set — the same small callout the iPhone Camera app itself shows after
/// an AE/AF lock (its own yellow "AE/AF LOCK" banner), so it reads as
/// familiar rather than needing an explanation. Tappable: a lock with no
/// way back would be worse than no lock at all if the light genuinely
/// changes mid-shoot — see [_CaptureScreenState._unlockExposure].
class _ExposureLockBadge extends StatelessWidget {
  const _ExposureLockBadge({required this.onTap});

  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Exposure locked. Double tap to unlock.',
      excludeSemantics: true,
      child: _Glass(
        child: Material(
          color: Colors.transparent,
          borderRadius: Radii.controlAll,
          child: InkWell(
            borderRadius: Radii.controlAll,
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: Space.sm,
                vertical: 6,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.lock_outline, size: 14, color: Colors.amber),
                  const SizedBox(width: Space.xs),
                  Text(
                    'Exposure locked — tap to reset',
                    style: T.caption.copyWith(color: Colors.amber),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SwitchCameraButton extends StatelessWidget {
  const _SwitchCameraButton({required this.onPressed});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Switch camera',
      excludeSemantics: true,
      child: _Glass(
        circular: true,
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onPressed,
            child: const Padding(
              padding: EdgeInsets.all(Space.sm),
              child: Icon(
                Icons.cameraswitch_outlined,
                color: C.white,
                size: 22,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Fills the screen with the live preview, cropping rather than letterboxing
/// or stretching it.
///
/// [CameraController.value.previewSize] is reported in the sensor's own
/// landscape orientation regardless of how the phone is held — the opposite
/// of what a portrait screen needs — so width and height are swapped before
/// handing the box to [FittedBox]. Getting this backwards is what makes a
/// camera preview look squashed; this is the standard fix for it.
class _CameraPreviewFilled extends StatelessWidget {
  const _CameraPreviewFilled({required this.controller});

  final CameraController controller;

  @override
  Widget build(BuildContext context) {
    final previewSize = controller.value.previewSize;
    if (previewSize == null) return const ColoredBox(color: Colors.black);

    return ClipRect(
      child: OverflowBox(
        alignment: Alignment.center,
        child: FittedBox(
          fit: BoxFit.cover,
          child: SizedBox(
            width: previewSize.height,
            height: previewSize.width,
            child: CameraPreview(controller),
          ),
        ),
      ),
    );
  }
}

/// Stands in for the live feed on a device with no camera to show one — the
/// iOS Simulator, today. Deliberately just a flat fill with no message of
/// its own: the centre of the screen already belongs to [_GuidePlaceholder],
/// and [_NoCameraNotice] carries the explanation instead, up near the
/// progress pill — two captions both reaching for screen centre is how they
/// end up printed on top of one another rather than either being readable.
class _NoPreviewPlaceholder extends StatelessWidget {
  const _NoPreviewPlaceholder();

  @override
  Widget build(BuildContext context) {
    return const ColoredBox(color: Color(0xFF1C1C1A));
  }
}

/// The small "no camera" caption itself — see [_NoPreviewPlaceholder] for
/// why it lives up here rather than centred on screen.
class _NoCameraNotice extends StatelessWidget {
  const _NoCameraNotice();

  @override
  Widget build(BuildContext context) {
    return _Glass(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Space.sm, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.videocam_off_outlined,
              size: 14,
              color: Colors.white70,
            ),
            const SizedBox(width: Space.xs),
            Text(
              'No camera on this device',
              style: T.caption.copyWith(color: Colors.white70),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProgressPill extends StatelessWidget {
  const _ProgressPill({required this.currentAngle});

  /// Null once every angle is captured or skipped.
  final CaptureAngle? currentAngle;

  @override
  Widget build(BuildContext context) {
    final angle = currentAngle;
    final total = CaptureAngle.values.length;
    final index = angle == null ? total : CaptureAngle.values.indexOf(angle);
    final label = angle == null
        ? 'All $total angles done'
        : '${index + 1} of $total — ${angle.label}';

    return _Glass(
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: Space.md,
          vertical: Space.sm,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: T.label.copyWith(color: C.white)),
            const SizedBox(height: 5),
            _ProgressDots(current: index, total: total),
          ],
        ),
      ),
    );
  }
}

/// The pill's "how far along the walking order" read at a glance, the way a
/// paginated iOS screen shows position with dots rather than spelling out a
/// fraction every time. Position only — which angle is captured, skipped or
/// still open in more detail is what the filmstrip is for; this and that
/// are deliberately not the same information rendered twice.
class _ProgressDots extends StatelessWidget {
  const _ProgressDots({required this.current, required this.total});

  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < total; i++) ...[
          if (i > 0) const SizedBox(width: 3.5),
          Container(
            width: 4,
            height: 4,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: i <= current ? C.forestLift : Colors.white.withAlpha(70),
            ),
          ),
        ],
      ],
    );
  }
}

/// Shown centre-screen once nothing is left to shoot — the guide overlay's
/// spot, repurposed, rather than an empty gap where it used to be.
class _AllAnglesDone extends StatelessWidget {
  const _AllAnglesDone();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Opacity(
        opacity: 0.85,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.check_circle_outline, color: C.white, size: 40),
            const SizedBox(height: Space.sm),
            Text(
              'Every angle is accounted for — submit the set below.',
              textAlign: TextAlign.center,
              style: T.bodySmall.copyWith(color: C.white),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Bottom controls: thumbnails, shutter, submit ────────────────────────────

/// Just Skip, the shutter and Submit now — reviewing and reshooting moved
/// into the filmstrip (see [_Filmstrip]), which is what leaves room for the
/// shutter itself to grow and sit dead centre instead of sharing this row
/// with a thumbnail strip.
class _BottomControls extends StatelessWidget {
  const _BottomControls({
    required this.capturedCount,
    required this.capturing,
    required this.submitting,
    required this.onCapture,
    required this.onSkip,
    required this.onSubmit,
  });

  final int capturedCount;
  final bool capturing;
  final bool submitting;
  final VoidCallback? onCapture;
  final VoidCallback? onSkip;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            SizedBox(
              width: 72,
              child: onSkip == null
                  ? null
                  : TextButton(
                      onPressed: onSkip,
                      style: TextButton.styleFrom(foregroundColor: C.white),
                      child: const Text('Skip'),
                    ),
            ),
            const SizedBox(width: Space.md),
            _ShutterButton(busy: capturing, onPressed: onCapture),
            const SizedBox(width: Space.md),
            const SizedBox(width: 72),
          ],
        ),
        const SizedBox(height: Space.md),
        _SubmitButton(
          count: capturedCount,
          submitting: submitting,
          onPressed: onSubmit,
        ),
      ],
    );
  }
}

/// All 8 angles at once, in walking order, along the right edge — the
/// "filmstrip view of pictures" the bottom thumbnail row and the old
/// "Next: …" text strip both merged into: one tile per angle rather than a
/// growing list of only what's captured so far, so the whole shoot's status
/// reads at a glance instead of needing the top pill and this row read
/// together. Every tile shares one interaction regardless of its own state
/// — see [_CaptureScreenState._selectAngle] — tap any of them to shoot (or
/// reshoot) that angle next.
class _Filmstrip extends StatelessWidget {
  const _Filmstrip({
    required this.currentAngle,
    required this.captured,
    required this.skipped,
    required this.onSelect,
  });

  final CaptureAngle? currentAngle;
  final Map<CaptureAngle, XFile> captured;
  final Set<CaptureAngle> skipped;
  final ValueChanged<CaptureAngle>? onSelect;

  @override
  Widget build(BuildContext context) {
    return _Glass(
      child: Padding(
        padding: const EdgeInsets.all(5),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final angle in CaptureAngle.values) ...[
              if (angle != CaptureAngle.values.first) const SizedBox(height: 5),
              _FilmstripTile(
                angle: angle,
                file: captured[angle],
                isCurrent: angle == currentAngle,
                isSkipped: skipped.contains(angle),
                onTap: onSelect == null ? null : () => onSelect!(angle),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _FilmstripTile extends StatelessWidget {
  const _FilmstripTile({
    required this.angle,
    required this.file,
    required this.isCurrent,
    required this.isSkipped,
    required this.onTap,
  });

  final CaptureAngle angle;
  final XFile? file;
  final bool isCurrent;
  final bool isSkipped;
  final VoidCallback? onTap;

  static const _size = 34.0;

  @override
  Widget build(BuildContext context) {
    final photo = file;
    final label = photo != null
        ? '${angle.label}, captured. Double tap to reshoot.'
        : isSkipped
        ? '${angle.label}, skipped. Double tap to shoot next.'
        : '${angle.label}. Double tap to shoot this next.';

    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: Material(
        color: Colors.transparent,
        borderRadius: Radii.controlAll,
        child: InkWell(
          borderRadius: Radii.controlAll,
          onTap: onTap,
          child: Container(
            width: _size,
            height: _size,
            decoration: BoxDecoration(
              borderRadius: Radii.controlAll,
              color: photo == null ? Colors.white.withAlpha(18) : null,
              border: Border.all(
                color: isCurrent ? C.forestLift : Colors.white.withAlpha(46),
                width: isCurrent ? 2 : 1,
              ),
            ),
            child: Stack(
              children: [
                if (photo != null)
                  ClipRRect(
                    borderRadius: Radii.controlAll,
                    child: Image.file(
                      File(photo.path),
                      width: _size,
                      height: _size,
                      fit: BoxFit.cover,
                    ),
                  )
                else if (isSkipped)
                  const Center(
                    child: Icon(
                      Icons.remove_rounded,
                      size: 14,
                      color: Colors.white38,
                    ),
                  ),
                if (photo != null)
                  Positioned(
                    right: 1,
                    bottom: 1,
                    child: Container(
                      width: 12,
                      height: 12,
                      decoration: const BoxDecoration(
                        shape: BoxShape.circle,
                        color: C.forestLift,
                      ),
                      child: const Icon(
                        Icons.check_rounded,
                        size: 9,
                        color: C.white,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ShutterButton extends StatelessWidget {
  const _ShutterButton({required this.busy, required this.onPressed});

  final bool busy;

  /// Null when there is no camera to capture from — the shutter still shows,
  /// dimmed, rather than vanishing. See [_CaptureBody.onCapture].
  final VoidCallback? onPressed;

  bool get _enabled => onPressed != null && !busy;

  @override
  Widget build(BuildContext context) {
    final ringColor = _enabled ? C.white : Colors.white38;

    return Semantics(
      button: true,
      label: _enabled ? 'Take photograph' : 'No camera to capture from',
      excludeSemantics: true,
      child: GestureDetector(
        onTap: _enabled ? onPressed : null,
        child: Container(
          // Bigger than before (was 72) — freed up by the filmstrip taking
          // over review/reshoot, this row no longer shares space with a
          // thumbnail strip, so the shutter itself can be the one thing
          // that's obviously the main action.
          width: 80,
          height: 80,
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.fromBorderSide(
              BorderSide(color: ringColor, width: 4),
            ),
          ),
          child: DecoratedBox(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: busy ? Colors.white38 : ringColor,
            ),
            child: busy
                ? const Padding(
                    padding: EdgeInsets.all(20),
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: C.ink,
                    ),
                  )
                : null,
          ),
        ),
      ),
    );
  }
}

class _SubmitButton extends StatelessWidget {
  const _SubmitButton({
    required this.count,
    required this.submitting,
    required this.onPressed,
  });

  final int count;
  final bool submitting;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return FilledButton(
      onPressed: onPressed,
      // minimumSize overrides the house-wide full-width default (see the
      // equivalent note in listing_detail_screen.dart's delete dialog) —
      // this button sits centred over a black preview, not stretched across
      // it.
      style: FilledButton.styleFrom(
        backgroundColor: C.forest,
        minimumSize: const Size(0, 44),
      ),
      child: submitting
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2, color: C.white),
            )
          : Text(count == 0 ? 'Submit set' : 'Submit set ($count)'),
    );
  }
}
