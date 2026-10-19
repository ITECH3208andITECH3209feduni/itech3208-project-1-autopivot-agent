// Hero continuity and capture-screen micro-polish added for the trade-show
// booth demo: lib/features/capture/capture_screen.dart's filmstrip tile
// (_FilmstripTile) and progress dots (_ProgressDots). The matching
// grid-side Hero lives in review_screen_test.dart.
//
// Demo capture mode is the only way under `flutter test` to get a real
// captured photograph into this screen without a working camera plugin --
// see capture_demo_mode_test.dart's own header comment for why. These
// tests reuse exactly that mechanism (and its path_provider / ML Kit
// teardown stubs) purely as a vehicle for exercising the filmstrip tile
// once it actually holds a photograph; demo mode itself is already
// covered there, so this file stays scoped to the animation/Hero behaviour
// layered on top of it.
//
// Reduced motion is simulated the way Flutter's own framework tests do it
// (see widgets/media_query_test.dart in the SDK):
// tester.platformDispatcher.accessibilityFeaturesTestValue, which is what
// MediaQuery.of(context).disableAnimations actually reads underneath
// MaterialApp.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/design/tokens.dart';
import 'package:autopivot/features/capture/capture_screen.dart';
import 'package:autopivot/settings/app_preferences.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');
const _imageLabelerChannel = MethodChannel('google_mlkit_image_labeler');
const _objectDetectorChannel = MethodChannel('google_mlkit_object_detector');

/// Everything CaptureScreen's initState reads from AppPreferences -- the
/// same shape capture_demo_mode_test.dart's own fake uses, with demo mode
/// forced on since every test here needs a captured photo without a real
/// camera.
class _DemoPreferences extends AppPreferences {
  _DemoPreferences() : super(const FlutterSecureStorage());

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
  Future<bool> demoCaptureModeEnabled() async => true;
  @override
  Future<void> setDemoCaptureModeEnabled(bool value) async {}
}

/// See capture_demo_mode_test.dart's own doc comment on why both ML Kit
/// channels VehicleFrameDetector.dispose() closes need a quiet stub even
/// though demo mode never starts the analysis that would otherwise reach
/// them.
void _stubMlKitTeardownChannels() {
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  for (final channel in [_imageLabelerChannel, _objectDetectorChannel]) {
    messenger.setMockMethodCallHandler(channel, (call) async => null);
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
  }
}

Future<void> _pumpCaptureScreen(WidgetTester tester) async {
  final container = ProviderContainer(
    overrides: [
      appPreferencesStoreProvider.overrideWithValue(_DemoPreferences()),
    ],
  );
  addTearDown(container.dispose);
  await container.read(appPreferencesProvider.notifier).load();

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: CaptureScreen()),
    ),
  );
  await tester.pump();
}

/// Same convention as capture_demo_mode_test.dart's own _run: lets
/// loadDemoSamplePhoto's real asset-bundle read and file write interleave
/// with the pumps that pick up the setState they land in -- testWidgets'
/// FakeAsync zone does not let that real I/O complete on its own.
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

void _reduceMotion(WidgetTester tester) {
  tester.platformDispatcher.accessibilityFeaturesTestValue =
      const FakeAccessibilityFeatures(disableAnimations: true);
  addTearDown(tester.platformDispatcher.clearAllTestValues);
}

/// The filmstrip thumbnail for Front once it's captured -- not just any
/// Image, the one backed by exactly the file loadDemoSamplePhoto writes
/// (see that function's own doc comment for the `demo_<angle>_...` name),
/// the same predicate capture_demo_mode_test.dart already checks captures
/// with.
final _frontThumbnail = find.byWidgetPredicate((widget) {
  if (widget is! Image) return false;
  final image = widget.image;
  return image is FileImage && image.file.path.contains('demo_front_');
});

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory temporary;

  setUp(() {
    temporary = Directory.systemTemp.createTempSync('capture_polish_');
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
    'a captured filmstrip tile settles with its thumbnail wrapped in a '
    'Hero tagged for the review grid, when motion is allowed',
    (tester) async {
      await _pumpCaptureScreen(tester);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);
      await tester.pumpAndSettle();

      // Every one of the 8 tiles carries the fill-in switcher regardless
      // of its own state -- this is the implicit widget the brief asked
      // for, not just incidentally present on the one tile that got a
      // photo.
      expect(find.byType(AnimatedSwitcher), findsNWidgets(8));

      expect(find.byType(Hero), findsOneWidget);
      final hero = tester.widget<Hero>(
        find.ancestor(of: _frontThumbnail, matching: find.byType(Hero)),
      );
      expect(hero.tag, 'capture-photo-front');
    },
  );

  testWidgets(
    'with reduced motion, the same captured tile settles with a plain '
    'image and no Hero',
    (tester) async {
      await _pumpCaptureScreen(tester);
      _reduceMotion(tester);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);
      await tester.pumpAndSettle();

      expect(_frontThumbnail, findsOneWidget);
      expect(find.byType(Hero), findsNothing);
    },
  );

  testWidgets(
    "the progress dots settle on the new angle's colours once motion is "
    'allowed',
    (tester) async {
      await _pumpCaptureScreen(tester);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);
      await tester.pumpAndSettle();

      // Front is done and Front-right corner is now current -- see
      // _ProgressDots' own "i <= current" rule -- so dots 0 and 1 both
      // read as reached and dot 2 does not.
      final dots = tester
          .widgetList<AnimatedContainer>(find.byType(AnimatedContainer))
          .toList();
      expect(dots, hasLength(8));
      expect((dots[0].decoration as BoxDecoration).color, C.forestLift);
      expect((dots[1].decoration as BoxDecoration).color, C.forestLift);
      expect(
        (dots[2].decoration as BoxDecoration).color,
        Colors.white.withAlpha(70),
      );
    },
  );

  testWidgets(
    'with reduced motion, the progress dots still settle on the correct '
    'colours',
    (tester) async {
      await _pumpCaptureScreen(tester);
      _reduceMotion(tester);
      await _run(tester);

      await tester.tap(find.bySemanticsLabel('Take photograph'));
      await _run(tester);
      await tester.pumpAndSettle();

      final dots = tester
          .widgetList<AnimatedContainer>(find.byType(AnimatedContainer))
          .toList();
      expect((dots[0].decoration as BoxDecoration).color, C.forestLift);
      expect((dots[1].decoration as BoxDecoration).color, C.forestLift);
      expect(
        (dots[2].decoration as BoxDecoration).color,
        Colors.white.withAlpha(70),
      );
    },
  );
}
