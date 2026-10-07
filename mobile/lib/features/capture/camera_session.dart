/// Holds [CaptureScreen]'s one camera: opens it, closes it, and keeps it
/// released whenever the app is out of the foreground.
///
/// Its own file, and generic over what a "camera" is, so those rules can be
/// tested without camera hardware: the screen supplies how to open and close
/// a real `CameraController`, and tests supply stand-ins.
library;

import 'dart:async';

import 'package:flutter/widgets.dart' show AppLifecycleState;

class CameraSession<C extends Object> {
  CameraSession({
    required this._open,
    required this._close,
    required this._onChanged,
  });

  /// Opens a camera, or returns null when there is none to open: no
  /// hardware, or a failure it has already reported itself.
  final Future<C?> Function() _open;
  final Future<void> Function(C camera) _close;

  /// Told whenever [camera] changes.
  final void Function(C? camera) _onChanged;

  C? _camera;

  /// The open camera, or null while there is none: not opened yet, still
  /// opening, released while the app is away, or never available at all.
  C? get camera => _camera;

  bool _inForeground = true;
  bool _opening = false;
  bool _disposed = false;

  /// Set when leaving the foreground took a camera away — an open one, or
  /// one still opening — so that coming back knows to open another.
  bool _reopenOnReturn = false;

  bool get _mayHold => _inForeground && !_disposed;

  // Opens and closes run one at a time, in the order they were asked for.
  // An interruption can arrive while a camera is still opening (the iOS
  // permission prompt itself makes the app inactive during the very first
  // one), and without this a second open could start before the first had
  // finished, or a close land in the middle of one.
  Future<void> _pending = Future<void>.value();

  Future<void> _serialised(Future<void> Function() step) {
    final result = _pending.then((_) => step());
    // A failed step must not stall every one queued behind it.
    _pending = result.then<void>((_) {}, onError: (Object _) {});
    return result;
  }

  /// Opens a camera unless one is already open: the first start, and
  /// "Try again".
  Future<void> start() => _serialised(_openUnlessHeld);

  /// Closes the open camera and opens another in its place (a camera
  /// switch); [open] decides which one.
  Future<void> restart() => _serialised(() async {
    await _release();
    await _openUnlessHeld();
  });

  /// Every state but [AppLifecycleState.resumed] counts as away. `inactive`
  /// alone is Control Center, the notification shade, a call banner or the
  /// app switcher, and nothing may hold the camera through any of them: a
  /// controller left open behind a backgrounded app is a known source of
  /// crashes on both platforms. Only the first of the states the app passes
  /// through on its way out (inactive, hidden, paused) releases anything;
  /// the rest find nothing left to release.
  ///
  /// This used to release the camera on `inactive` and reopen it on
  /// `resumed` only if a camera was still open, which by then it never was,
  /// so every interruption left the screen on "Starting camera…" for good.
  void lifecycleChanged(AppLifecycleState state) {
    final inForeground = state == AppLifecycleState.resumed;
    if (inForeground == _inForeground) return;
    _inForeground = inForeground;

    if (!inForeground) {
      if (_camera != null || _opening) _reopenOnReturn = true;
      unawaited(_serialised(_releaseIfAway));
    } else if (_reopenOnReturn) {
      _reopenOnReturn = false;
      unawaited(_serialised(_openUnlessHeld));
    }
  }

  /// Closes the open camera, and one still opening once it has opened.
  void dispose() {
    _disposed = true;
    unawaited(_serialised(_release));
  }

  Future<void> _openUnlessHeld() async {
    if (_camera != null) return;
    if (!_mayHold) {
      // Asked for while the app is away (a switch that got its turn after
      // the app left): coming back opens it instead.
      if (!_disposed) _reopenOnReturn = true;
      return;
    }

    final C? camera;
    _opening = true;
    try {
      camera = await _open();
    } finally {
      _opening = false;
    }
    if (camera == null) return;

    if (!_mayHold) {
      // The app left, or the screen closed, while this was opening: closed
      // straight away rather than held in the background. Leaving has
      // already marked it for reopening on return.
      await _close(camera);
      return;
    }
    _camera = camera;
    _onChanged(camera);
  }

  Future<void> _releaseIfAway() async {
    // Back again before this got its turn: the camera is kept rather than
    // closed and immediately reopened.
    if (_mayHold) return;
    await _release();
  }

  Future<void> _release() async {
    final camera = _camera;
    if (camera == null) return;
    // Taken off screen first, so nothing is left showing a camera that is
    // being closed.
    _camera = null;
    _onChanged(null);
    await _close(camera);
  }
}

/// Brings up [camera] with [start] and hands back what [start] made of it —
/// or, when any step of [start] fails, closes it again with [close] before
/// passing the failure on.
///
/// For the steps between constructing a camera and handing it to a
/// [CameraSession]: a camera that initialised and then failed a later step
/// (the zoom query, the image stream) already holds the hardware, and the
/// session it was meant for never received it, so nothing else would ever
/// close it; the next open would find the camera still taken. A failure of
/// [close] itself is dropped in favour of the one that caused it, which is
/// the one worth reporting.
Future<R> startOrClose<C, R>(
  C camera, {
  required Future<R> Function(C camera) start,
  required Future<void> Function(C camera) close,
}) async {
  try {
    return await start(camera);
  } catch (_) {
    try {
      await close(camera);
    } catch (_) {
      // See above: the start's failure is the one passed on.
    }
    rethrow;
  }
}
