// Demo capture mode on CaptureScreen: lib/features/capture/capture_screen.dart,
// backed by lib/settings/app_preferences.dart's demoCaptureModeEnabled and
// lib/features/capture/demo_sample_photos.dart's bundled samples.
//
// CaptureScreen itself has no existing widget test to follow the shape of —
// every capture_followup_*_test.dart file exercises one piece it depends on
// in isolation (camera_session.dart's startOrClose, hold_steady.dart,
// draft_resume_prompt.dart) rather than pumping the screen, because the real
// camera plugin has no implementation under `flutter test` to answer it.
// Demo mode is the one path through this screen that never asks the camera
// plugin for anything at all, which is what makes pumping CaptureScreen
// itself finally possible here. Preferences are faked the way
// app_settings_screen_demo_mode_test.dart fakes them for AppSettingsScreen;
// path_provider is answered on its method channel the way capture_draft_test
// .dart and medium_demo_test.dart both already do, over a fresh temp
// directory per test; the camera plugin's own channel is answered too (and
// logged), since CaptureScreen still reaches for it from initState whenever
// demo mode is off — real mode is not this file's concern, but a stray call
// to it must not crash a test, and the "never opened" assertion below is
// read straight off that log. Both ML Kit channels VehicleFrameDetector
// closes in dispose() are stubbed defensively for the same reason: nothing
// here should ever call them, but a previous test's teardown landing mid-way
// through this one must not throw an unhandled MissingPluginException into
// whichever test happens to be running when it resolves.
//
// Asset-bundle and file I/O: loadDemoSamplePhoto does both (reads the
// bundled JPEG, writes a copy to a temp file), and real I/O only completes
// while real time passes, which testWidgets' FakeAsync zone does not allow
// by itself — same problem, same fix (tester.runAsync inside a bounded pump
// loop) as medium_demo_test.dart's own _run uses for the sample car's
// asset-to-temp-file copy.
//
// bySemanticsLabel is how every control on this screen is found: none of
// _ShutterButton, _CloseButton or _FilmstripTile is a public type this file
// could reference even if it wanted to, and the accessible name is exactly
// what a real user (or the shutter's own _enabled check) would go by too.
// testWidgets' own semanticsEnabled parameter (true by default) is what
// makes that finder work at all, and already disposes its handle at the
// right point in the test lifecycle -- an extra manual
// tester.ensureSemantics() here would only leak a second handle, since
// addTearDown runs after Flutter's own end-of-test semantics check.
//
// There is deliberately no "retaking an unavailable angle from Review is
// refused" test here anymore: demoAvailableAngles covers all eight angles
// today, so there is no real angle left to provoke that guard in
// _selectAngle with. The guard itself stays in capture_screen.dart --
// coverage has already shrunk more than once this project -- it is just
// untested until it does.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/capture_draft.dart';
import 'package:autopivot/features/capture/capture_screen.dart';
import 'package:autopivot/features/capture/review_screen.dart';
import 'package:autopivot/settings/app_preferences.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');
const _cameraChannel = MethodChannel('plugins.flutter.io/camera');
const _imageLabelerChannel = MethodChannel('google_mlkit_image_labeler');
const _objectDetectorChannel = MethodChannel('google_mlkit_object_detector');

/// Everything CaptureScreen's own initState reads from AppPreferences,
/// trimmed to what it actually calls — the same shape
/// app_settings_screen_demo_mode_test.dart's own fake uses for
/// AppSettingsScreen.
class _FakePreferences extends AppPreferences {
  _FakePreferences({required this.demoCaptureMode})
    : super(const FlutterSecureStorage());

  final bool demoCaptureMode;

  @override
  Future<bool> biometricLockEnabled() async => false;
  @override
  Future<void> setBiometricLockEnabled(bool value) async {}
  @override
  Future<bool> hapticsEnabled() async => true;
  @override
  Future<void> setHapticsEnabled(bool value) async {}
  @override
  Future<bool> welcomeTourSeen() async => true;
  @override
  Future<void> setWelcomeTourSeen(bool value) async {}
  @override
  Future<bool> demoCaptureModeEnabled() async => demoCaptureMode;
  @override
  Future<void> setDemoCaptureModeEnabled(bool value) async {}
}

/// Records every method the camera plugin's own channel is asked for.
/// Demo mode's whole point is that this stays empty — see _openCamera in
/// capture_screen.dart, whose first step on a real open is exactly
/// 'availableCameras' — so this doubles as the "never opened" assertion's
/// evidence and as a safety net against a stray real call throwing
/// MissingPluginException into the test instead.
class _CameraLog {
  _CameraLog() {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_cameraChannel, _handle);
    addTearDown(() => messenger.setMockMethodCallHandler(_cameraChannel, null));
  }

  final calls = <String>[];

  Future<Object?> _handle(MethodCall call) async {
    calls.add(call.method);
    if (call.method == 'availableCameras') return <Map<Object?, Object?>>[];
    return null;
  }
}

/// Answers both ML Kit channels VehicleFrameDetector.dispose() closes
/// unconditionally when this screen itself closes, regardless of demo mode
/// — see that method in vehicle_frame_detector.dart. Neither should ever be
/// asked anything in a demo-mode test (the image stream feeding
/// VehicleFrameDetector.analyze() is never started here), but the close()
/// calls happen whether or not anything was ever analysed, so both are
/// stubbed to resolve quietly rather than left to throw into whichever
/// test's turn it is when that teardown actually runs.
void _stubMlKitTeardownChannels() {
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  for (final channel in [_imageLabelerChannel, _objectDetectorChannel]) {
    messenger.setMockMethodCallHandler(channel, (call) async => null);
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
  }
}

/// Pumps CaptureScreen directly over fake preferences loaded the way
/// AppBootstrap loads them for real (see that provider's own doc comment
/// for why a later synchronous ref.read in initState is then safe).
/// Returns a flag this test can read after tapping Close, since onClose is
/// the only hook CaptureScreen itself offers for "did it actually close".
Future<_ClosedFlag> _pumpCaptureScreen(
  WidgetTester tester, {
  required bool demoMode,
}) async {
  final container = ProviderContainer(
    overrides: [
      appPreferencesStoreProvider.overrideWithValue(
        _FakePreferences(demoCaptureMode: demoMode),
      ),
    ],
  );
  addTearDown(container.dispose);
  await container.read(appPreferencesProvider.notifier).load();

  final closed = _ClosedFlag();
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(home: CaptureScreen(onClose: closed._markClosed)),
    ),
  );
  await tester.pump();
  return closed;
}

class _ClosedFlag {
  bool value = false;
  void _markClosed() => value = true;
}

/// Lets loadDemoSamplePhoto's real asset-bundle read and file write
/// interleave with the pumps that pick up the setState they land in —
/// testWidgets' FakeAsync zone does not let real I/O complete on its own.
/// Same convention medium_demo_test.dart's own _run uses for the sample
/// car's asset-to-temp-file copy.
Future<void> _run(WidgetTester tester) async {
  for (var i = 0; i < 25; i++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    for (var j = 0; j < 4; j++) {
      await tester.pump(Duration.zero);
    }
  }
}

/// Settles an ordinary, finite UI animation (a dialog opening or closing) —
/// deliberately not pumpAndSettle, which would hang forever against the
/// indeterminate CircularProgressIndicator a capture in flight shows (its
/// ticker never stops on its own). Never used while a capture might still
/// be running; _run already waits one out fully before this is reached.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory temporary;

  setUp(() {
    temporary = Directory.systemTemp.createTempSync('capture_demo_mode_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          _pathProvider,
          (call) async => temporary.path,
        );
    _stubMlKitTeardownChannels();
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, null);
    temporary.deleteSync(recursive: true);
  });

  testWidgets(
    'demo mode never opens the camera, and never offers to resume a draft '
    'that genuinely exists on disk',
    (tester) async {
      final cameraLog = _CameraLog();

      // A draft genuinely on disk: without initState's demo-mode guard
      // around the post-frame _offerDraftResume call, this is exactly what
      // would surface as the "Resume your last capture?" dialog. Real file
      // I/O, so it runs through runAsync -- this testWidgets body is
      // inside a FakeAsync zone from the very start, well before the first
      // pump, and real I/O never completes on its own in there.
      await tester.runAsync(() async {
        final seedPhoto = File('${temporary.path}/seed.jpg');
        await seedPhoto.writeAsString('seed');
        await saveCaptureDraft(
          capturedPaths: {CaptureAngle.front: seedPhoto.path},
          skipped: {},
        );
      });

      await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      expect(cameraLog.calls, isEmpty);
      expect(find.text('Resume your last capture?'), findsNothing);
    },
  );

  testWidgets(
    'the shutter is enabled for the current angle immediately, with no '
    'camera-starting message in the way',
    (tester) async {
      await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      expect(find.text('1 of 8 — Front'), findsOneWidget);
      expect(find.text('Starting camera…'), findsNothing);
      // _ShutterButton's own accessible name only ever reads "Take
      // photograph" when onPressed is non-null and it is not mid-capture —
      // see its _enabled getter — so finding it here is finding "enabled",
      // not just "present".
      expect(find.bySemanticsLabel('Take photograph'), findsOneWidget);
    },
  );

  testWidgets(
    'with a real sample for all eight angles, nothing starts pre-skipped',
    (tester) async {
      await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      // demoAvailableAngles now covers every CaptureAngle, so initState's
      // skip-seeding (CaptureAngle.values.toSet().difference(
      // demoAvailableAngles)) has nothing left to add -- unlike when
      // rearLeftCorner was the one angle still missing a real sample.
      expect(find.bySemanticsLabel(RegExp('skipped')), findsNothing);
      expect(find.text('1 of 8 — Front'), findsOneWidget);
    },
  );

  testWidgets(
    'capturing writes the bundled sample for the current angle into the '
    'captured map and moves on to the next angle',
    (tester) async {
      await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);

      expect(find.text('2 of 8 — Front-right corner'), findsOneWidget);
      expect(
        find.bySemanticsLabel('Front, captured. Double tap to reshoot.'),
        findsOneWidget,
      );
      // Not just any file landed in the captured map — the filmstrip
      // thumbnail is backed by exactly the kind of file loadDemoSamplePhoto
      // produces for this angle (see that function's own doc comment for
      // the "demo_<angle>_<timestamp>_<counter>.jpg" name it writes).
      expect(
        find.byWidgetPredicate((widget) {
          if (widget is! Image) return false;
          final image = widget.image;
          return image is FileImage && image.file.path.contains('demo_front_');
        }),
        findsOneWidget,
      );
    },
  );

  testWidgets('no draft is written after a capture in demo mode', (
    tester,
  ) async {
    await _pumpCaptureScreen(tester, demoMode: true);
    await _run(tester);

    await tester.tap(find.bySemanticsLabel('Take photograph'));
    await _run(tester);

    // Real file I/O again -- see the first test's own comment on this.
    expect(await tester.runAsync(loadCaptureDraft), isNull);
  });

  testWidgets(
    'closing the screen in demo mode writes no draft, even choosing Save '
    'Draft',
    (tester) async {
      final closed = await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Close camera'));
      await _settle(tester);
      expect(find.text('Quit the camera?'), findsOneWidget);

      await tester.tap(find.text('Save Draft'));
      await _settle(tester);

      expect(closed.value, isTrue);
      expect(await tester.runAsync(loadCaptureDraft), isNull);
    },
  );

  testWidgets(
    'closing via Discard in demo mode does not delete an unrelated real '
    'draft that exists on disk',
    (tester) async {
      // A real draft from an earlier, non-demo session — demo mode never
      // wrote this one (see _saveDraft's own guard) and must not be what
      // erases it.
      await tester.runAsync(() async {
        final seedPhoto = File('${temporary.path}/seed.jpg');
        await seedPhoto.writeAsString('seed');
        await saveCaptureDraft(
          capturedPaths: {CaptureAngle.front: seedPhoto.path},
          skipped: {},
        );
      });

      final closed = await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Close camera'));
      await _settle(tester);
      expect(find.text('Quit the camera?'), findsOneWidget);

      await tester.tap(find.text('Discard'));
      await _settle(tester);

      expect(closed.value, isTrue);
      expect(await tester.runAsync(loadCaptureDraft), isNotNull);
    },
  );

  testWidgets(
    'closing immediately in demo mode, before anything is captured or '
    'skipped by choice, skips the quit-confirmation dialog entirely',
    (tester) async {
      final closed = await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Close camera'));
      await _settle(tester);

      expect(find.text('Quit the camera?'), findsNothing);
      expect(closed.value, isTrue);
    },
  );

  testWidgets(
    'retaking a photo from Review re-syncs the demo preview to the angle '
    'being retaken',
    (tester) async {
      await _pumpCaptureScreen(tester, demoMode: true);
      await _run(tester);

      // Capture Front — the demo preview advances on to Front-right corner.
      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);
      expect(find.text('2 of 8 — Front-right corner'), findsOneWidget);

      await tester.tap(find.text('Submit set (1)'));
      await tester.pumpAndSettle();
      expect(find.byType(ReviewScreen), findsOneWidget);

      // The same result tapping Front's own empty tile in the real Review
      // grid would produce — simulated directly on the pushed route rather
      // than driving that screen's own UI, since this is testing how
      // CaptureScreen reacts to the result, not Review itself.
      Navigator.of(tester.element(find.byType(ReviewScreen))).pop(
        const ReviewRetake(
          angle: CaptureAngle.front,
          photos: {},
          draft: ReviewDraft(),
        ),
      );
      await tester.pumpAndSettle();
      await _run(tester);

      expect(find.text('1 of 8 — Front'), findsOneWidget);
      // Not just the angle label — the background photo has to have caught
      // up too, not still be showing the front-right-corner sample
      // _syncDemoPreview loaded two steps ago.
      expect(
        find.byWidgetPredicate((widget) {
          if (widget is! Image) return false;
          final image = widget.image;
          return image is FileImage && image.file.path.contains('demo_front_');
        }),
        findsOneWidget,
      );
    },
  );

}
