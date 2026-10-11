// The capture draft store: lib/features/capture/capture_draft.dart.
//
// path_provider is answered on its method channel. That is the implementation
// `flutter test` falls back to — plugin registration does not run under the
// test harness — so no platform code is involved, and every draft lands in a
// temporary directory this file creates and removes.
//
// Plain test() rather than testWidgets(): these do real file I/O, whose
// futures never resolve inside testWidgets' FakeAsync zone.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/capture_draft.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory documents;
  late Directory cameraTemp;

  setUp(() async {
    documents = await Directory.systemTemp.createTemp('draft_documents_');
    cameraTemp = await Directory.systemTemp.createTemp('draft_camera_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, (call) async => documents.path);
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, null);
    await documents.delete(recursive: true);
    await cameraTemp.delete(recursive: true);
  });

  /// A shot as the camera plugin leaves it: a file in the OS temp directory.
  Future<String> shot(String name, String contents) async {
    final file = File('${cameraTemp.path}/$name.jpg');
    await file.writeAsString(contents);
    return file.path;
  }

  test('saving again after resuming keeps the resumed photographs', () async {
    await saveCaptureDraft(
      capturedPaths: {
        CaptureAngle.front: await shot('CAP_1', 'front'),
        CaptureAngle.frontRightCorner: await shot('CAP_2', 'front-right'),
      },
      skipped: {},
    );

    // What CaptureScreen does on Resume: every restored shot now points at
    // the draft's own copy of it.
    final resumed = (await loadCaptureDraft())!;
    final captured = {
      for (final MapEntry(key: angle, value: file) in resumed.files.entries)
        angle: file.path,
    };

    // The next shot saves the draft again, resumed files included.
    captured[CaptureAngle.rightSide] = await shot('CAP_3', 'right');
    await saveCaptureDraft(capturedPaths: captured, skipped: {});

    final saved = (await loadCaptureDraft())!;
    expect(saved.shotCount, 3);
    expect(await saved.files[CaptureAngle.front]!.readAsString(), 'front');
    expect(
      await saved.files[CaptureAngle.frontRightCorner]!.readAsString(),
      'front-right',
    );
    expect(await saved.files[CaptureAngle.rightSide]!.readAsString(), 'right');

    // The screen keeps uploading from the paths it resumed with, so those
    // must still hold the same photographs.
    expect(await File(captured[CaptureAngle.front]!).readAsString(), 'front');
  });

  test('a save begun before the previous one finished still leaves the newer set', () async {
    final front = await shot('CAP_1', 'front');
    final side = await shot('CAP_2', 'right');

    // CaptureScreen does not wait for one shot's save before the next begins.
    final earlier = saveCaptureDraft(
      capturedPaths: {CaptureAngle.front: front},
      skipped: {},
    );
    final later = saveCaptureDraft(
      capturedPaths: {CaptureAngle.front: front, CaptureAngle.rightSide: side},
      skipped: {},
    );
    await Future.wait([earlier, later]);

    final saved = (await loadCaptureDraft())!;
    expect(
      saved.files.keys,
      unorderedEquals([CaptureAngle.front, CaptureAngle.rightSide]),
    );
  });

  test('discarding while a save is still running leaves no draft behind', () async {
    final pending = saveCaptureDraft(
      capturedPaths: {CaptureAngle.front: await shot('CAP_1', 'front')},
      skipped: {},
    );
    await clearCaptureDraft();
    await pending;

    expect(await loadCaptureDraft(), isNull);
  });

  /// Writes a draft by hand into the directory the store reads: one
  /// photograph, of the front, and whatever [manifest] adds to it.
  Future<void> writeDraft(Map<String, Object?> manifest) async {
    final dir = Directory('${documents.path}/capture_draft');
    await dir.create(recursive: true);
    final front = File('${dir.path}/front.jpg');
    await front.writeAsString('front');
    await File('${dir.path}/manifest.json').writeAsString(
      jsonEncode({
        'saved_at': '2026-09-24T17:30:00.000',
        'files': {'front': front.path},
        'skipped': ['rear'],
        ...manifest,
      }),
    );
  }

  test('a draft saved by the previous version still resumes', () async {
    // Exactly what it wrote: files named after their angles, and no record
    // of a submit.
    await writeDraft({});

    final draft = (await loadCaptureDraft())!;
    expect(draft.shotCount, 1);
    expect(await draft.files[CaptureAngle.front]!.readAsString(), 'front');
    expect(draft.skipped, {CaptureAngle.rear});
    expect(draft.unfinishedSubmission, isNull);
  });

  test('a damaged record of an unfinished submit still leaves the '
      'photographs to resume', () async {
    await writeDraft({
      'unfinished_submission': {'listing_id': 'seven', 'photos': 3},
    });

    final draft = (await loadCaptureDraft())!;
    expect(draft.shotCount, 1);
    expect(draft.unfinishedSubmission, isNull);
  });
}
