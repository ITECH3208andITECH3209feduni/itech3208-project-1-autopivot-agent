/// The vehicle photo capture screen — a custom camera surface, not the
/// system camera picker, per the client's own description of this feature
/// (5 June): open the app, it tells you which angle to shoot, you shoot it,
/// it uploads as a set.
///
/// This file is deliberately scoped to the *camera* half of that story only:
/// a real, working live preview; a shutter that takes a real photograph;
/// a strip of what has been captured so far, with a way to drop a bad shot
/// before submitting. It does not know what angle it is on, what a good
/// angle-3 photograph looks like, whether a shot is too dark or blurred, or
/// how to hold a set offline and resume it later — those are a second
/// developer's story, built on top of this one. Two places mark exactly
/// where that work plugs in: [_ProgressPill] and [_GuidePlaceholder] below,
/// both commented `TODO(angle-sequence)`. Submitting a set is stubbed for
/// the same reason: a real upload needs an angle tag per photograph, which
/// does not exist yet on this screen.
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
  final List<XFile> _captured = [];
  bool _capturing = false;

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
    if (state is! _CameraReady || _capturing) return;

    setState(() => _capturing = true);
    try {
      final photo = await state.controller.takePicture();
      if (!mounted) return;
      setState(() => _captured.add(photo));
    } on CameraException {
      // Skeleton scope: a failed shutter press just leaves the set
      // unchanged rather than surfacing a dedicated error — see the doc
      // comment at the top of this file for what deliberately isn't here
      // yet (dark/blurred warnings among it).
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  void _removeCaptured(int index) => setState(() => _captured.removeAt(index));

  void _submit() {
    final count = _captured.length;
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Not wired up yet'),
        content: Text(
          'This will upload the $count photograph${count == 1 ? '' : 's'} '
          "captured here, each tagged with the angle it was shot from — "
          'once the angle sequence exists to tag them with. That part, and '
          'the upload itself, is the next piece of this story.',
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
                captured: _captured,
                capturing: _capturing,
                onCapture: null,
                onRemove: _removeCaptured,
                onSubmit: _captured.isEmpty ? null : _submit,
              ),
              _CameraReady(:final controller) => _CaptureBody(
                controller: controller,
                captured: _captured,
                capturing: _capturing,
                onCapture: _capture,
                onRemove: _removeCaptured,
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
    required this.captured,
    required this.capturing,
    required this.onCapture,
    required this.onRemove,
    required this.onSubmit,
  });

  /// Null on a device with no camera to preview — see [_NoCameraHardware].
  final CameraController? controller;
  final List<XFile> captured;
  final bool capturing;

  /// Null when there is no controller to capture from. The shutter renders
  /// disabled rather than disappearing, so the rest of the layout — where it
  /// sits, how big it is — can still be reviewed without a camera.
  final VoidCallback? onCapture;
  final ValueChanged<int> onRemove;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    final controller = this.controller;
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
                // TODO(angle-sequence): this counts photographs taken, which
                // is all this screen knows. Replace with the real angle name
                // and a progress indicator across the full sequence (e.g.
                // "3 of 10 — driver-side front quarter").
                _ProgressPill(count: captured.length),
                // Lives up here rather than sharing the centre with the
                // guide placeholder below — two explanations both trying to
                // occupy screen centre is how they end up printed on top of
                // one another instead of either being readable.
                if (controller == null) ...[
                  const SizedBox(height: Space.sm),
                  const _NoCameraNotice(),
                ],
              ],
            ),
          ),
        ),
        const Center(
          // TODO(angle-sequence): replace with a framing overlay specific to
          // the current angle — a silhouette, a grid, whatever the guidance
          // design turns out to need. This box only marks where it goes.
          child: _GuidePlaceholder(),
        ),
        SafeArea(
          child: Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: Space.md),
              child: _BottomControls(
                captured: captured,
                capturing: capturing,
                onCapture: onCapture,
                onRemove: onRemove,
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
  const _ProgressPill({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
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
        child: Text('Photo ${count + 1}', style: T.label.copyWith(color: C.white)),
      ),
    );
  }
}

/// TODO(angle-sequence): the intended replacement for this box is a
/// silhouette of the vehicle for the current angle, which the photographer
/// lines the real car up against. Framing becomes its own validation that
/// way — no separate "is this the right angle?" check is needed — and
/// because the app dictated the angle rather than guessing it afterwards,
/// every photo this screen produces arrives already tagged with exactly
/// what it is a photograph of. That is the whole realism argument for this
/// story: the estimation problem the web upload path still has to solve for
/// arbitrary imagery simply does not exist for a photograph shot this way.
class _GuidePlaceholder extends StatelessWidget {
  const _GuidePlaceholder();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Opacity(
        opacity: 0.7,
        child: Container(
          width: 220,
          height: 220,
          alignment: Alignment.center,
          padding: const EdgeInsets.all(Space.md),
          decoration: BoxDecoration(
            border: Border.all(color: C.white, width: 1.5),
            borderRadius: Radii.cardAll,
          ),
          child: Text(
            'Framing guide for this angle goes here',
            textAlign: TextAlign.center,
            style: T.bodySmall.copyWith(color: C.white),
          ),
        ),
      ),
    );
  }
}

// ── Bottom controls: thumbnails, shutter, submit ────────────────────────────

class _BottomControls extends StatelessWidget {
  const _BottomControls({
    required this.captured,
    required this.capturing,
    required this.onCapture,
    required this.onRemove,
    required this.onSubmit,
  });

  final List<XFile> captured;
  final bool capturing;
  final VoidCallback? onCapture;
  final ValueChanged<int> onRemove;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (captured.isNotEmpty) ...[
          SizedBox(
            height: 56,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: Space.lg),
              itemCount: captured.length,
              separatorBuilder: (context, index) =>
                  const SizedBox(width: Space.sm),
              itemBuilder: (context, index) => _Thumbnail(
                file: captured[index],
                onRemove: () => onRemove(index),
              ),
            ),
          ),
          const SizedBox(height: Space.md),
        ],
        _ShutterButton(busy: capturing, onPressed: onCapture),
        const SizedBox(height: Space.md),
        _SubmitButton(count: captured.length, onPressed: onSubmit),
      ],
    );
  }
}

class _Thumbnail extends StatelessWidget {
  const _Thumbnail({required this.file, required this.onRemove});

  final XFile file;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Captured photograph ${file.name}. Double tap to remove.',
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
