// Holding the capture screen's camera across interruptions:
// lib/features/capture/camera_session.dart.
//
// A real CameraController needs camera hardware, which `flutter test` does not
// have, so the session is generic over what a camera is. _Hardware hands out
// numbered stand-ins and logs every open and close in the order they happen,
// and that log is the contract under test: no camera is ever closed twice, two
// are never open at once, none is held while the app is out of the
// foreground, and one the app gave up for an interruption comes back.
//
// Plain test(): nothing here draws a widget.

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/camera_session.dart';

class _Camera {
  _Camera(this.number);

  final int number;

  @override
  String toString() => 'camera $number';
}

/// Stands in for the camera hardware.
class _Hardware {
  /// Every open and close, in the order they finished.
  final log = <String>[];

  var _opened = 0;
  Completer<void>? _held;

  /// Makes every open from here on wait for [finishOpening]: a camera still
  /// starting up when something else happens.
  void holdOpening() => _held = Completer<void>();

  void finishOpening() {
    _held?.complete();
    _held = null;
  }

  Future<_Camera?> open() async {
    await _held?.future;
    final camera = _Camera(++_opened);
    log.add('open ${camera.number}');
    return camera;
  }

  Future<void> close(_Camera camera) async => log.add('close ${camera.number}');
}

void main() {
  late _Hardware hardware;
  late CameraSession<_Camera> session;

  /// Every camera the screen was told to show, and null for each time it was
  /// told there is none.
  late List<int?> shown;

  setUp(() {
    hardware = _Hardware();
    shown = [];
    session = CameraSession<_Camera>(
      open: hardware.open,
      close: hardware.close,
      onChanged: (camera) => shown.add(camera?.number),
    );
  });

  test('a camera released for an interruption is reopened when the app '
      'comes back', () async {
    await session.start();

    session.lifecycleChanged(AppLifecycleState.inactive);
    await pumpEventQueue();
    session.lifecycleChanged(AppLifecycleState.resumed);
    await pumpEventQueue();

    expect(hardware.log, ['open 1', 'close 1', 'open 2']);
    expect(session.camera?.number, 2);
    expect(shown, [1, null, 2]);
  });

  for (final state in [
    AppLifecycleState.hidden,
    AppLifecycleState.paused,
    AppLifecycleState.detached,
  ]) {
    test('$state releases the camera even with no inactive before it', () async {
      await session.start();

      session.lifecycleChanged(state);
      await pumpEventQueue();

      expect(hardware.log, ['open 1', 'close 1']);
      expect(session.camera, isNull);
    });
  }

  test('leaving through inactive, hidden and paused closes the camera once', () async {
    await session.start();

    session.lifecycleChanged(AppLifecycleState.inactive);
    session.lifecycleChanged(AppLifecycleState.hidden);
    session.lifecycleChanged(AppLifecycleState.paused);
    await pumpEventQueue();

    expect(hardware.log, ['open 1', 'close 1']);
    expect(session.camera, isNull);
  });

  test('a return while the camera is still opening keeps that camera rather '
      'than opening another', () async {
    hardware.holdOpening();
    final starting = session.start();
    await pumpEventQueue();

    session.lifecycleChanged(AppLifecycleState.inactive);
    session.lifecycleChanged(AppLifecycleState.resumed);
    hardware.finishOpening();
    await starting;
    await pumpEventQueue();

    expect(hardware.log, ['open 1']);
    expect(session.camera?.number, 1);
  });

  test('a camera that finishes opening after the app has left is closed, '
      'then replaced when the app comes back', () async {
    hardware.holdOpening();
    final starting = session.start();
    await pumpEventQueue();

    session.lifecycleChanged(AppLifecycleState.inactive);
    hardware.finishOpening();
    await starting;
    await pumpEventQueue();

    expect(hardware.log, ['open 1', 'close 1']);
    expect(session.camera, isNull);

    session.lifecycleChanged(AppLifecycleState.resumed);
    await pumpEventQueue();

    expect(hardware.log, ['open 1', 'close 1', 'open 2']);
    expect(session.camera?.number, 2);
  });

  test('closing the screen closes its camera, even one still opening', () async {
    hardware.holdOpening();
    final starting = session.start();
    await pumpEventQueue();

    session.dispose();
    hardware.finishOpening();
    await starting;
    await pumpEventQueue();

    expect(hardware.log, ['open 1', 'close 1']);
    expect(session.camera, isNull);
  });

  test('switching cameras closes the open one before opening the next', () async {
    await session.start();

    await session.restart();

    expect(hardware.log, ['open 1', 'close 1', 'open 2']);
    expect(session.camera?.number, 2);
  });
}
