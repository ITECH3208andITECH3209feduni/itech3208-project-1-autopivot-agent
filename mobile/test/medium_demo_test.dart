// The sample-car demo — lib/features/settings/demo_screen.dart — and the
// Settings row that offers it (lib/features/settings/app_settings_screen.dart).
//
// The server stores an original photograph once, under a content hash that
// has to be unique (upload_images in api/routes_listings.py), so a second
// copy of the same bundled sample is refused with a 409. The backends below
// refuse it the same way.
//
// The demo used to write the bundled photograph out to a temporary file
// before uploading it, and real file I/O only completes while real time
// passes, which testWidgets' FakeAsync zone does not allow by itself: _run
// lets it, with tester.runAsync for anything real and a pump for whatever
// follows. path_provider is answered on its method channel with a temporary
// directory this file makes and removes, as in capture_draft_test.dart;
// everything else is the real ApiClient over a stand-in transport, as in
// session_expiry_test.dart.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/settings/app_settings_screen.dart';
import 'package:autopivot/features/settings/demo_screen.dart';
import 'package:autopivot/routes.dart';
import 'package:autopivot/settings/app_preferences.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');
const _at = '2026-09-25T09:00:00';
const _alreadyUploaded = 'One of those photographs has already been uploaded.';

class _MemoryTokenStore extends TokenStore {
  // As in widget_test.dart, the FlutterSecureStorage handed up is never
  // touched: every method below is overridden.
  _MemoryTokenStore([this.token]) : super(const FlutterSecureStorage());

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

class _MemoryPreferences extends AppPreferences {
  _MemoryPreferences() : super(const FlutterSecureStorage());

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
}

/// Stands in for the server at the transport, as in session_expiry_test.dart.
class _FakeBackend implements HttpClientAdapter {
  _FakeBackend(this._answer);

  final FutureOr<ResponseBody> Function(RequestOptions request) _answer;

  /// Every request received, in order.
  final received = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    received.add(options);
    return _answer(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(int status, Object body) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

ResponseBody _notFound() => _json(404, {'detail': 'Not found.'});

/// upload_images' answer to a photograph whose bytes are already stored.
ResponseBody _duplicate() => _json(409, {'detail': _alreadyUploaded});

/// The listing the demo makes, as api/routes_listings.py serialises it.
Map<String, Object?> _sample(int id, {required bool withPhotograph}) => {
  'id': id,
  'stock_number': null,
  'title': '2026 Demo Sample Vehicle',
  'make': 'Demo',
  'model': 'Sample Vehicle',
  'year': 2026,
  'variant': null,
  'price': null,
  'status': 'draft',
  'processing_status': 'pending',
  'image_count': withPhotograph ? 1 : 0,
  'created_at': _at,
  'updated_at': _at,
};

Map<String, Object?> _sampleDetail(int id, {required bool withPhotograph}) => {
  ..._sample(id, withPhotograph: withPhotograph),
  'description': null,
  'images': [
    if (withPhotograph)
      {
        'id': 50,
        'image_type': 'original',
        'source_image_id': null,
        'image_kind': null,
        'kind_confidence': null,
        'original_filename': 'autopivot-demo-car.jpg',
        'image_url': '/api/files/3/original/demo.jpg',
        'width': 1600,
        'height': 900,
        'file_size_bytes': 285690,
        'created_at': _at,
      },
  ],
};

Map<String, Object?> _queued(int id) => {
  'listing_id': id,
  'processing_status': 'processing',
  'total': 1,
  'completed': 0,
  'failed': 0,
  'needs_review': 0,
  'jobs': <Object?>[],
};

Map<String, Object?> _person({required String role}) => {
  'id': 7,
  'email': 'sam@northshore.test',
  'first_name': 'Sam',
  'last_name': 'Taylor',
  'role': role,
  'is_active': true,
  'must_change_password': false,
  // A platform administrator belongs to no dealership (User.dealership).
  'dealership': role == 'platform_admin'
      ? null
      : {
          'id': 3,
          'name': 'North Shore Motors',
          'location': 'Auckland',
          'contact_name': null,
          'contact_email': null,
          'contact_phone': null,
          'status': 'active',
          'user_count': 4,
        },
};

ApiClient _client(_FakeBackend backend) =>
    ApiClient(baseUrl: 'http://autopivot.test', httpClientAdapter: backend);

/// Runs every request in flight to its answer, and builds what follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 30; i++) {
    await tester.pump(Duration.zero);
  }
}

/// Runs the demo through: its requests, and any real I/O on the way (the
/// sample photograph's own decoding on screen, and the file the old version
/// wrote it out to).
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

/// The demo screen, reached from Settings, over [backend]. A listing it
/// opens shows only its id.
Future<void> _openDemo(WidgetTester tester, _FakeBackend backend) async {
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore()),
      apiClientProvider.overrideWithValue(_client(backend)),
    ],
  );
  addTearDown(container.dispose);
  final router = GoRouter(
    initialLocation: AppRoutes.demo,
    routes: [
      GoRoute(
        path: AppRoutes.demo,
        builder: (context, state) => const DemoScreen(),
      ),
      GoRoute(
        path: AppRoutes.listingDetail,
        builder: (context, state) =>
            Scaffold(body: Text('Listing ${state.pathParameters['id']}')),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pump();
}

Future<void> _startDemo(WidgetTester tester) async {
  final start = find.widgetWithText(FilledButton, 'Start the demo');
  await tester.ensureVisible(start);
  await tester.pump();
  await tester.tap(start);
  await _run(tester);
  // The push onto the listing's own screen, when there is one to go to.
  await tester.pump(const Duration(milliseconds: 600));
}

/// Settings, for [user].
Future<void> _openSettings(
  WidgetTester tester,
  Map<String, Object?> user,
) async {
  final backend = _FakeBackend(
    (request) => request.path == '/auth/me' ? _json(200, user) : _notFound(),
  );
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore('a-session')),
      apiClientProvider.overrideWithValue(_client(backend)),
      appPreferencesStoreProvider.overrideWithValue(_MemoryPreferences()),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: AppSettingsScreen()),
    ),
  );
  // What AppBootstrap.initState does, called directly for the reason
  // widget_test.dart gives.
  unawaited(container.read(authProvider.notifier).restore());
  await container.read(appPreferencesProvider.notifier).load();
  await _settle(tester);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory temporary;

  setUp(() {
    temporary = Directory.systemTemp.createTempSync('demo_temporary_');
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

  group('the sample car', () {
    testWidgets('run again reuses its listing instead of adding an empty one', (
      tester,
    ) async {
      final backend = _FakeBackend((request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings'):
            // The run before this one left its listing, photograph and all.
            return _json(200, [_sample(5, withPhotograph: true)]);
          case ('GET', '/api/listings/5'):
            return _json(200, _sampleDetail(5, withPhotograph: true));
          case ('POST', '/api/listings/5/process'):
            return _json(200, _queued(5));
          case ('POST', '/api/listings'):
            return _json(201, _sampleDetail(6, withPhotograph: false));
          case ('POST', '/api/listings/6/images'):
            return _duplicate();
        }
        return _notFound();
      });
      await _openDemo(tester, backend);

      await _startDemo(tester);

      expect(
        backend.received.where(
          (r) => r.method == 'POST' && r.path == '/api/listings',
        ),
        isEmpty,
      );
      expect(find.text(_alreadyUploaded), findsNothing);
      expect(find.text('Listing 5'), findsOneWidget);
    });

    testWidgets('whose upload is refused takes its new listing back out', (
      tester,
    ) async {
      final backend = _FakeBackend((request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings'):
            return _json(200, <Object?>[]);
          case ('POST', '/api/listings'):
            return _json(201, _sampleDetail(6, withPhotograph: false));
          case ('POST', '/api/listings/6/images'):
            // The sample is already on a listing, one since renamed.
            return _duplicate();
          case ('DELETE', '/api/listings/6'):
            return ResponseBody.fromString('', 204);
        }
        return _notFound();
      });
      await _openDemo(tester, backend);

      await _startDemo(tester);

      expect(
        backend.received.where(
          (r) => r.method == 'POST' && r.path == '/api/listings/6/images',
        ),
        hasLength(1),
      );
      expect(
        backend.received.where(
          (r) => r.method == 'DELETE' && r.path == '/api/listings/6',
        ),
        hasLength(1),
      );
      expect(find.text(_alreadyUploaded), findsOneWidget);
      expect(find.text('Listing 6'), findsNothing);
    });
  });

  group('the Sample car row in Settings', () {
    testWidgets('is not offered to a platform administrator', (tester) async {
      await _openSettings(tester, _person(role: 'platform_admin'));

      expect(find.text('Sample car'), findsNothing);
    });

    testWidgets('is offered to someone with a dealership', (tester) async {
      await _openSettings(tester, _person(role: 'dealership_staff'));

      expect(find.text('Sample car'), findsOneWidget);
    });
  });
}
