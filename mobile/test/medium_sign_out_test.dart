// What a session leaves on the phone besides its token, and when it goes: the
// capture draft (lib/features/capture/capture_draft.dart), which the camera
// offers to whoever opens it next, and the photographs the session was shown
// (lib/widgets/authed_image.dart), cached in memory and on disk. Ended by
// lib/auth/auth_controller.dart.
//
// Plain test() rather than testWidgets(): the draft and the photograph cache
// are real files, and real file I/O never completes inside testWidgets'
// FakeAsync zone. path_provider is answered on its method channel with a
// temporary directory this file makes and removes, standing in for both the
// documents and the cache directory, as in capture_draft_test.dart.
//
// The real ApiClient makes every request, over a stand-in transport, as in
// session_expiry_test.dart. Riverpod retries a failed provider by itself, ten
// times over about forty seconds, and leaves the failure in place after that;
// the containers here never retry, which is where a photograph that failed
// ends up once those retries have run out.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/api/api_exception.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/capture_draft.dart';
import 'package:autopivot/widgets/authed_image.dart';

const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');
const _password = 'correct horse battery';
const _photoPath = '/api/files/3/original/front.jpg';
final _photoBytes = Uint8List.fromList(List.generate(64, (i) => i));

class _MemoryTokenStore extends TokenStore {
  // As in widget_test.dart, the FlutterSecureStorage handed up is never
  // touched: every method below is overridden.
  _MemoryTokenStore() : super(const FlutterSecureStorage());

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

/// Stands in for the server at the transport, as in session_expiry_test.dart.
class _FakeBackend implements HttpClientAdapter {
  _FakeBackend(this._answer);

  final FutureOr<ResponseBody> Function(RequestOptions request) _answer;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => _answer(options);

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

/// get_current_user's answer (api/deps.py) to a token it no longer accepts.
ResponseBody _refused() => ResponseBody.fromString(
  jsonEncode({'detail': 'Not authenticated.'}),
  401,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
    'www-authenticate': ['Bearer'],
  },
);

ResponseBody _photograph() => ResponseBody.fromBytes(
  _photoBytes,
  200,
  headers: {
    Headers.contentTypeHeader: ['image/jpeg'],
  },
);

Map<String, Object?> _account(int id, String firstName, String lastName) => {
  'id': id,
  'email': '${firstName.toLowerCase()}@northshore.test',
  'first_name': firstName,
  'last_name': lastName,
  'role': 'dealership_staff',
  'is_active': true,
  'must_change_password': false,
  'dealership': {
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

final _sam = _account(7, 'Sam', 'Taylor');
final _alex = _account(9, 'Alex', 'Chen');

/// /auth/login's answer (api/routes_auth.py).
ResponseBody _signedIn(Map<String, Object?> account) => _json(200, {
  'access_token': 'session-for-${account['id']}',
  'token_type': 'bearer',
  'expires_in': 28800,
  'user': account,
});

ProviderContainer _container(_FakeBackend backend) {
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore()),
      apiClientProvider.overrideWithValue(
        ApiClient(baseUrl: 'http://autopivot.test', httpClientAdapter: backend),
      ),
    ],
    retry: (retryCount, error) => null,
  );
  addTearDown(container.dispose);
  return container;
}

Future<void> _signIn(ProviderContainer container, Map<String, Object?> who) =>
    container
        .read(authProvider.notifier)
        .signIn(email: who['email'] as String, password: _password);

/// One photograph the way a tile shows it: asked for, shown once it
/// arrives, then let go as the tile scrolls away or its screen closes.
Future<Uint8List> _photo(ProviderContainer container) async {
  final tile = container.listen(authedImageBytes(_photoPath).future, (_, _) {});
  try {
    return await tile.read();
  } finally {
    tile.close();
  }
}

/// Lets what is in flight run until [done] holds.
Future<void> _until(bool Function() done) async {
  for (var i = 0; i < 200 && !done(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  expect(done(), isTrue);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory phone;
  late Directory camera;

  setUp(() async {
    phone = await Directory.systemTemp.createTemp('sign_out_phone_');
    camera = await Directory.systemTemp.createTemp('sign_out_camera_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, (call) async => phone.path);
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_pathProvider, null);
    // Someone else signing in clears the last account's files without the
    // sign-in waiting for it, so that clean-up can still be finishing here.
    for (final directory in [phone, camera]) {
      try {
        await directory.delete(recursive: true);
      } on FileSystemException {
        // Already gone, or going: either way nothing is left to remove.
      }
    }
  });

  /// A set with one photograph in it, saved as the capture screen saves it.
  Future<void> saveDraft() async {
    final shot = File('${camera.path}/CAP_1.jpg');
    await shot.writeAsString('front');
    await saveCaptureDraft(
      capturedPaths: {CaptureAngle.front: shot.path},
      skipped: {},
    );
  }

  group('the capture draft', () {
    test('goes when its photographer signs out', () async {
      final container = _container(
        _FakeBackend(
          (request) =>
              request.path == '/auth/login' ? _signedIn(_sam) : _notFound(),
        ),
      );
      await _signIn(container, _sam);
      await saveDraft();
      expect(await loadCaptureDraft(), isNotNull);

      await container.read(authProvider.notifier).signOut();

      expect(await loadCaptureDraft(), isNull);
    });

    test(
      'stays for the same photographer after the server ends the session',
      () async {
        final container = _container(
          _FakeBackend(
            (request) =>
                request.path == '/auth/login' ? _signedIn(_sam) : _refused(),
          ),
        );
        await _signIn(container, _sam);
        await saveDraft();

        // The token runs out part-way through the day.
        await expectLater(
          container.read(apiClientProvider).counts(),
          throwsA(isA<ApiUnauthorisedException>()),
        );
        expect(container.read(authProvider), isA<AuthSignedOut>());

        await _signIn(container, _sam);

        final draft = await loadCaptureDraft();
        expect(draft?.shotCount, 1);
      },
    );

    test(
      'goes when someone else signs in after the server ended the session',
      () async {
        final accounts = [_sam, _alex];
        final container = _container(
          _FakeBackend(
            (request) => request.path == '/auth/login'
                ? _signedIn(accounts.removeAt(0))
                : _refused(),
          ),
        );
        await _signIn(container, _sam);
        await saveDraft();
        await expectLater(
          container.read(apiClientProvider).counts(),
          throwsA(isA<ApiUnauthorisedException>()),
        );

        // Sam never comes back for it: Alex signs in on the same phone.
        await _signIn(container, _alex);

        expect(await loadCaptureDraft(), isNull);
      },
    );
  });

  group('a photograph', () {
    test('shown to one account is fetched afresh after it signs out', () async {
      final accounts = [_sam, _alex];
      var fetched = 0;
      final container = _container(
        _FakeBackend((request) {
          if (request.path == '/auth/login') {
            return _signedIn(accounts.removeAt(0));
          }
          if (request.path == _photoPath) {
            fetched++;
            return _photograph();
          }
          return _notFound();
        }),
      );
      await _signIn(container, _sam);

      expect(await _photo(container), _photoBytes);
      // Shown again in the same session: kept, not fetched again.
      expect(await _photo(container), _photoBytes);
      expect(fetched, 1);

      await container.read(authProvider.notifier).signOut();
      await _signIn(container, _alex);

      expect(await _photo(container), _photoBytes);
      expect(fetched, 2);
    });

    test('that failed to load is asked for again when next shown', () async {
      var reachable = false;
      final container = _container(
        _FakeBackend((request) {
          if (request.path == '/auth/login') return _signedIn(_sam);
          if (request.path == _photoPath) {
            return reachable
                ? _photograph()
                : _json(503, {'detail': 'Service Unavailable'});
          }
          return _notFound();
        }),
      );
      await _signIn(container, _sam);

      // The server has a bad moment while the photograph is on screen...
      await expectLater(_photo(container), throwsA(isA<ApiServerException>()));
      reachable = true;
      // ...and by the time it is shown again, its tile has long gone.
      await Future<void>.delayed(Duration.zero);

      expect(await _photo(container), _photoBytes);
    });

    test('refused as the session ended loads once signed back in', () async {
      var sessions = 0;
      final container = _container(
        _FakeBackend((request) {
          if (request.path == '/auth/login') {
            sessions++;
            return _json(200, {
              'access_token': 'session-$sessions',
              'token_type': 'bearer',
              'expires_in': 28800,
              'user': _sam,
            });
          }
          if (request.path == _photoPath) {
            // The first session's token stops being accepted with this very
            // photograph.
            return request.headers['Authorization'] == 'Bearer session-1'
                ? _refused()
                : _photograph();
          }
          return _notFound();
        }),
      );
      await _signIn(container, _sam);

      // A tile on screen as the session ends under it.
      final tile = container.listen(authedImageBytes(_photoPath), (_, _) {});
      addTearDown(tile.close);
      await _until(() => container.read(authProvider) is AuthSignedOut);

      await _signIn(container, _sam);

      expect(
        await container.read(authedImageBytes(_photoPath).future),
        _photoBytes,
      );
    });
  });
}
