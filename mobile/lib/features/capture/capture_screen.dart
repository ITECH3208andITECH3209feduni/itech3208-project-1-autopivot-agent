/// The vehicle photo capture screen — a custom camera surface, not the
/// system camera picker, per the client's own description of this feature
/// (5 June): open the app, it tells you which angle to shoot, you shoot it,
/// it uploads as a set.
///
/// The 8-shot sequence in [CaptureAngle] and its guide silhouettes
/// ([VehicleGuideOverlay]) are real, not placeholders — this screen knows
/// exactly which angle it wants next and shows the photographer what to line
/// the car up against. What is still deliberately not here: reading the
/// phone's actual tilt at the moment of capture (the client brief's own
/// "layer that matters most" — see `CaptureAngle.targetElevationDeg`'s doc
/// comment for why), a warning on a dark or blurred shot, and holding a set
/// offline and resuming it after the app is closed. The tilt reading is
/// blocked on a package (`sensors_plus`) this environment could not fetch
/// over the network at the time this was written, not on any design
/// question — everything here is already shaped to take a measured pitch
/// per photograph the moment that package can be added. Submitting a set is
/// still stubbed: a real upload needs the backend's metadata column for
/// per-image angle/pitch, which is a small, already-scoped backend change
/// (see `docs/MOBILE_PLAN.md`'s "Backend changes" section) rather than
/// anything blocking on this screen.
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

import '../../design/tokens.dart';
import '../../design/typography.dart';
import 'capture_angles.dart';
import 'vehicle_silhouette_painter.dart';

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

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, this.onClose});

  /// Called instead of popping the route directly when set — [AppShell]
  /// passes the container-transform's own close callback here so leaving
  /// this screen shrinks back into the camera bubble rather than sliding
  /// away like an ordinary pushed route. Falls back to a plain
  /// `Navigator.pop` when this screen is reached some other way.
  final VoidCallback? onClose;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
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

  /// The next angle to shoot: the first in the fixed sequence that is
  /// neither captured nor skipped. Null once every angle has one or the
  /// other — the whole set is then either complete or deliberately partial,
  /// and either is a valid state to submit from (see the exception flows
  /// this story's brief calls out: skipping is permitted, not an error).
  CaptureAngle? get _currentAngle {
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initCamera();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    final state = _state;
    if (state is _CameraReady) state.controller.dispose();
    super.dispose();
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

      final chosen = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        chosen,
        ResolutionPreset.high,
        enableAudio: false,
      );
      await controller.initialize();

      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _state = _CameraReady(controller));
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

    setState(() => _capturing = true);
    try {
      final photo = await state.controller.takePicture();
      if (!mounted) return;
      // A reshoot of an angle that was previously skipped supersedes the
      // skip — it is no longer "left for later", it is done.
      setState(() {
        _captured[angle] = photo;
        _skipped.remove(angle);
      });
    } on CameraException {
      // Skeleton scope: a failed shutter press just leaves the set
      // unchanged rather than surfacing a dedicated error — see the doc
      // comment at the top of this file for what deliberately isn't here
      // yet (dark/blurred warnings among it).
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  void _removeCaptured(CaptureAngle angle) =>
      setState(() => _captured.remove(angle));

  /// Permitted, not an error — the brief is explicit that a photographer
  /// standing at a vehicle knows more about why an angle is awkward right
  /// now (parked against a wall, another car too close) than this screen
  /// does, and the set should move on rather than block.
  void _skip() {
    final angle = _currentAngle;
    if (angle == null) return;
    setState(() => _skipped.add(angle));
  }

  void _submit() {
    final captured = _captured.length;
    final total = CaptureAngle.values.length;
    final skipped = _skipped.length;
    final completeness = skipped == 0
        ? '$captured of $total angles'
        : '$captured of $total angles ($skipped skipped)';
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Not wired up yet'),
        content: Text(
          'This will upload the $completeness captured here, each tagged '
          'with the angle it was shot for. The upload itself, and the '
          "backend column that stores each photograph's angle, are the next "
          'piece of this story.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('OK'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
                orderedCaptures: _orderedCaptures,
                capturing: _capturing,
                onCapture: null,
                onRemove: _removeCaptured,
                onSkip: _currentAngle == null ? null : _skip,
                onSubmit: _captured.isEmpty ? null : _submit,
              ),
              _CameraReady(:final controller) => _CaptureBody(
                controller: controller,
                currentAngle: _currentAngle,
                orderedCaptures: _orderedCaptures,
                capturing: _capturing,
                onCapture: _currentAngle == null ? null : _capture,
                onRemove: _removeCaptured,
                onSkip: _currentAngle == null ? null : _skip,
                onSubmit: _captured.isEmpty ? null : _submit,
              ),
            },
          ),
          Positioned(
            top: Space.sm,
            left: Space.sm,
            child: SafeArea(
              child: _CloseButton(
                onPressed: widget.onClose ?? () => Navigator.of(context).pop(),
              ),
            ),
          ),
        ],
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
      child: Material(
        color: Colors.black45,
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
    );
  }
}

// ── Ready: preview, guidance seam, controls ─────────────────────────────────

class _CaptureBody extends StatelessWidget {
  const _CaptureBody({
    required this.controller,
    required this.currentAngle,
    required this.orderedCaptures,
    required this.capturing,
    required this.onCapture,
    required this.onRemove,
    required this.onSkip,
    required this.onSubmit,
  });

  /// Null on a device with no camera to preview — see [_NoCameraHardware].
  final CameraController? controller;

  /// The angle to shoot next, or null once every angle has been either
  /// captured or skipped.
  final CaptureAngle? currentAngle;
  final List<MapEntry<CaptureAngle, XFile>> orderedCaptures;
  final bool capturing;

  /// Null when there is no controller to capture from, or nothing left in
  /// the sequence to shoot. The shutter renders disabled rather than
  /// disappearing in either case, so the rest of the layout — where it sits,
  /// how big it is — can still be reviewed without a camera.
  final VoidCallback? onCapture;
  final ValueChanged<CaptureAngle> onRemove;
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
              : VehicleGuideOverlay(angle: angle),
        ),
        SafeArea(
          child: Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: Space.md),
              child: _BottomControls(
                orderedCaptures: orderedCaptures,
                capturing: capturing,
                onCapture: onCapture,
                onRemove: onRemove,
                onSkip: onSkip,
                onSubmit: onSubmit,
              ),
            ),
          ),
        ),
      ],
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
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: Colors.black45,
        borderRadius: Radii.controlAll,
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: Space.sm,
          vertical: 6,
        ),
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
    final label = angle == null
        ? 'All $total angles done'
        : '${CaptureAngle.values.indexOf(angle) + 1} of $total — ${angle.label}';

    return DecoratedBox(
      decoration: const BoxDecoration(
        color: Colors.black45,
        borderRadius: Radii.controlAll,
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: Space.md,
          vertical: Space.sm,
        ),
        child: Text(label, style: T.label.copyWith(color: C.white)),
      ),
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

class _BottomControls extends StatelessWidget {
  const _BottomControls({
    required this.orderedCaptures,
    required this.capturing,
    required this.onCapture,
    required this.onRemove,
    required this.onSkip,
    required this.onSubmit,
  });

  final List<MapEntry<CaptureAngle, XFile>> orderedCaptures;
  final bool capturing;
  final VoidCallback? onCapture;
  final ValueChanged<CaptureAngle> onRemove;
  final VoidCallback? onSkip;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (orderedCaptures.isNotEmpty) ...[
          SizedBox(
            height: 56,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: Space.lg),
              itemCount: orderedCaptures.length,
              separatorBuilder: (context, index) =>
                  const SizedBox(width: Space.sm),
              itemBuilder: (context, index) {
                final entry = orderedCaptures[index];
                return _Thumbnail(
                  angle: entry.key,
                  file: entry.value,
                  onRemove: () => onRemove(entry.key),
                );
              },
            ),
          ),
          const SizedBox(height: Space.md),
        ],
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
        _SubmitButton(count: orderedCaptures.length, onPressed: onSubmit),
      ],
    );
  }
}

class _Thumbnail extends StatelessWidget {
  const _Thumbnail({
    required this.angle,
    required this.file,
    required this.onRemove,
  });

  final CaptureAngle angle;
  final XFile file;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '${angle.label} photograph. Double tap to remove.',
      child: SizedBox(
        width: 56,
        height: 56,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            ClipRRect(
              borderRadius: Radii.controlAll,
              child: Image.file(
                File(file.path),
                width: 56,
                height: 56,
                fit: BoxFit.cover,
              ),
            ),
            Positioned(
              top: -6,
              right: -6,
              child: Material(
                color: C.ink,
                shape: const CircleBorder(),
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: onRemove,
                  child: const Padding(
                    padding: EdgeInsets.all(3),
                    child: Icon(Icons.close, size: 12, color: C.white),
                  ),
                ),
              ),
            ),
          ],
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
          width: 72,
          height: 72,
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.fromBorderSide(BorderSide(color: ringColor, width: 4)),
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
  const _SubmitButton({required this.count, required this.onPressed});

  final int count;
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
      child: Text(count == 0 ? 'Submit set' : 'Submit set ($count)'),
    );
  }
}
