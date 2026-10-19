// The demo-capture-mode sample-photo loader:
// lib/features/capture/demo_sample_photos.dart.
//
// path_provider is answered on its method channel exactly as in
// capture_draft_test.dart: `flutter test` never registers real plugins, so
// without this every getTemporaryDirectory() call throws
// MissingPluginException. rootBundle needs no fake of its own — `flutter
// test` bundles whatever assets/ pubspec.yaml declares into a real
// temporary asset directory before the suite runs, so loading one of the
// eight files below exercises the real pubspec.yaml entry, not a stand-in
// for it.
//
// Plain test() rather than testWidgets(): these do real file I/O (and real
// asset loading), whose futures never resolve inside testWidgets' FakeAsync
// zone — see capture_draft_test.dart for the same reasoning.
//
// There is deliberately no "throws for an angle the booth never shot" test
// here anymore: demoAvailableAngles covers all eight CaptureAngle values
// today, so there is no real angle left to exercise that branch with. The
// ArgumentError guard in loadDemoSamplePhoto stays — coverage has already
// shrunk more than once this project — it is just untested until it does.

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/demo_sample_photos.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('demo_sample_photos_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, (call) async => tempDir.path);
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, null);
    await tempDir.delete(recursive: true);
  });

  test('demoAvailableAngles is exactly all eight CaptureAngle values', () {
    expect(demoAvailableAngles, unorderedEquals(CaptureAngle.values));
  });

  test(
    'loadDemoSamplePhoto writes a real, non-empty file for every sampled '
    'angle',
    () async {
      for (final angle in demoAvailableAngles) {
        final xfile = await loadDemoSamplePhoto(angle);
        final file = File(xfile.path);
        expect(
          await file.exists(),
          isTrue,
          reason: '${angle.name} should have landed on disk',
        );
        expect(await file.length(), greaterThan(0));
      }
    },
  );

  test(
    'two loads of the same angle in one session get two different paths',
    () async {
      final first = await loadDemoSamplePhoto(CaptureAngle.front);
      final second = await loadDemoSamplePhoto(CaptureAngle.front);
      expect(first.path, isNot(equals(second.path)));
    },
  );
}
