// Opening one camera without leaving it half-open:
// startOrClose in lib/features/capture/camera_session.dart.
//
// A CameraController that initialised and then failed a later step (the zoom
// query, the image stream) already holds the camera, and the screen used to
// drop it without closing it. A real controller needs camera hardware, which
// `flutter test` does not have, so the steps are stand-ins that log what
// happened to the camera, in order.
//
// Plain test(): nothing here draws a widget.

import 'package:camera/camera.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/camera_session.dart';

class _Camera {
  /// What was done to this camera, in order.
  final log = <String>[];
}

void main() {
  // What getMaxZoomLevel() lets through untouched when the platform call
  // fails: the platform's own exception, not a CameraException.
  final zoomQueryFailed = PlatformException(
    code: 'ZoomError',
    message: 'The zoom range could not be read.',
  );

  test('a camera that fails after it initialised is closed again, and the '
      'failure still reported', () async {
    final camera = _Camera();

    await expectLater(
      startOrClose<_Camera, double>(
        camera,
        start: (camera) async {
          camera.log.add('initialize');
          throw zoomQueryFailed;
        },
        close: (camera) async => camera.log.add('close'),
      ),
      throwsA(same(zoomQueryFailed)),
    );
    expect(camera.log, ['initialize', 'close']);
  });

  test('a close that fails as well does not hide why the camera did not '
      'open', () async {
    final camera = _Camera();

    await expectLater(
      startOrClose<_Camera, double>(
        camera,
        start: (camera) async {
          camera.log.add('initialize');
          throw zoomQueryFailed;
        },
        close: (camera) async {
          camera.log.add('close');
          throw CameraException('Disposed CameraController', 'Already gone.');
        },
      ),
      throwsA(same(zoomQueryFailed)),
    );
    expect(camera.log, ['initialize', 'close']);
  });

  test('a camera that starts is handed back open', () async {
    final camera = _Camera();

    final maxZoom = await startOrClose<_Camera, double>(
      camera,
      start: (camera) async {
        camera.log.add('initialize');
        return 2.0;
      },
      close: (camera) async => camera.log.add('close'),
    );

    expect(maxZoom, 2.0);
    expect(camera.log, ['initialize']);
  });
}
