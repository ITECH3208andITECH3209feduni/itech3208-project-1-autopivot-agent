// The review screen: lib/features/capture/review_screen.dart. The first
// widget test for this screen -- nothing else in test/ pumps it directly
// yet.
//
// ReviewScreen's initState fetches the backdrop library
// (ApiClient.backdrops()) unconditionally, so apiClientProvider needs a
// real ApiClient over a stand-in dio transport rather than the default one
// that would otherwise attempt a real network call -- the same "real
// ApiClient over a fake HttpClientAdapter" convention medium_demo_test.dart
// and session_expiry_test.dart already use. An empty backdrop library is
// enough: nothing here cares which backdrop is picked, only what the photo
// grid itself renders.
//
// A grid tile's Image.file needs bytes that actually decode -- an
// undecodable file reports a Flutter framework error that fails the test --
// so the one captured photo in these tests is a real bundled demo sample
// (loadDemoSamplePhoto, the same asset capture_demo_mode_test.dart's own
// filmstrip tests capture through the live screen), copied out via
// tester.runAsync the way every real-file-I/O test in this suite already
// does, over path_provider answered on its method channel.
//
// Reduced motion is simulated the way Flutter's own framework tests do it:
// tester.platformDispatcher.accessibilityFeaturesTestValue, which is what
// MediaQuery.of(context).disableAnimations reads underneath MaterialApp.

import 'dart:convert';
import 'dart:io';

import 'package:camera/camera.dart' show XFile;
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/demo_sample_photos.dart';
import 'package:autopivot/features/capture/review_screen.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');

/// Answers GET /api/backdrops with an empty library and refuses anything
/// else -- no test here drives the backdrop picker or the URL autofill.
class _NoBackdropsBackend implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.path == '/api/backdrops') {
      return ResponseBody.fromString(
        jsonEncode(<Object?>[]),
        200,
        headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        },
      );
    }
    return ResponseBody.fromString(
      jsonEncode({'detail': 'Not found.'}),
      404,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Future<void> _pumpReviewScreen(
  WidgetTester tester,
  Map<CaptureAngle, XFile> initialCaptured,
) async {
  final container = ProviderContainer(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(
          baseUrl: 'http://autopivot.test',
          httpClientAdapter: _NoBackdropsBackend(),
        ),
      ),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(home: ReviewScreen(initialCaptured: initialCaptured)),
    ),
  );
  await tester.pumpAndSettle();
}

void _reduceMotion(WidgetTester tester) {
  tester.platformDispatcher.accessibilityFeaturesTestValue =
      const FakeAccessibilityFeatures(disableAnimations: true);
  addTearDown(tester.platformDispatcher.clearAllTestValues);
}

/// The grid tile's photo for Front -- backed by exactly the file
/// loadDemoSamplePhoto writes (see that function's own doc comment for the
/// `demo_<angle>_...` name), the same predicate
/// capture_demo_mode_test.dart already checks captures with.
final _frontThumbnail = find.byWidgetPredicate((widget) {
  if (widget is! Image) return false;
  final image = widget.image;
  return image is FileImage && image.file.path.contains('demo_front_');
});

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory temporary;

  setUp(() {
    temporary = Directory.systemTemp.createTempSync('review_screen_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          _pathProvider,
          (call) async => temporary.path,
        );
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, null);
    temporary.deleteSync(recursive: true);
  });

  testWidgets(
    'a captured grid tile wraps its photo in a Hero tagged to match the '
    'filmstrip, when motion is allowed',
    (tester) async {
      final front = await tester.runAsync(
        () => loadDemoSamplePhoto(CaptureAngle.front),
      );

      await _pumpReviewScreen(tester, {CaptureAngle.front: front!});

      // Only the one captured tile (of all 8 in the grid) gets a Hero.
      expect(find.byType(Hero), findsOneWidget);
      final hero = tester.widget<Hero>(
        find.ancestor(of: _frontThumbnail, matching: find.byType(Hero)),
      );
      expect(hero.tag, 'capture-photo-front');
    },
  );

  testWidgets(
    'with reduced motion, the same grid tile renders a plain image with '
    'no Hero',
    (tester) async {
      final front = await tester.runAsync(
        () => loadDemoSamplePhoto(CaptureAngle.front),
      );

      _reduceMotion(tester);
      await _pumpReviewScreen(tester, {CaptureAngle.front: front!});

      expect(_frontThumbnail, findsOneWidget);
      expect(find.byType(Hero), findsNothing);
    },
  );
}
