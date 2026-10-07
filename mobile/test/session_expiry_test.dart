// A session the server stops accepting ends: lib/api/api_client.dart notices
// the 401, lib/auth/auth_controller.dart ends the session, app.dart's
// redirect lands on sign-in, and sign-in says why.
//
// The real ApiClient makes every request here, status mapping included; only
// its transport is swapped for _FakeBackend, which answers the way the server
// does. A stand-in ApiClient that simply threw ApiUnauthorisedException would
// skip the very code under test.
//
// tokenStoreProvider is faked for the reason widget_test.dart gives. The
// widget tests settle with pump(Duration.zero) rather than a bare pump(): dio
// moves each request along through zero-length timers, and only an elapse of
// fake time, even of none, fires one. Never pumpAndSettle(), for
// widget_test.dart's reason: the splash spinner, and the dashboard's loading
// skeleton after it, animate forever.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/api/api_exception.dart';
import 'package:autopivot/app.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/change_password/change_password_screen.dart';
import 'package:autopivot/features/sign_in/sign_in_screen.dart';

const _sessionEnded = 'Your session has ended. Please sign in again.';

class _MemoryTokenStore extends TokenStore {
  // As in widget_test.dart, the FlutterSecureStorage handed up is never
  // touched: every method below is overridden.
  _MemoryTokenStore([this.token]) : super(const FlutterSecureStorage());

  String? token;
  int clears = 0;

  /// Clearing real storage is a platform round trip, not instant. Set, it
  /// holds every clear open until completed, for a test that needs to act
  /// inside that gap.
  Completer<void>? holdClears;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async {
    clears++;
    await holdClears?.future;
    token = null;
  }
}

/// Stands in for the server at the transport, so everything above it (the
/// headers ApiClient sends, how it reads each status) is the real thing.
class _FakeBackend implements HttpClientAdapter {
  _FakeBackend(this._answer);

  final FutureOr<ResponseBody> Function(RequestOptions request) _answer;

  /// Every request received, in order, with the headers it carried.
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

ResponseBody _json(
  int status,
  Object body, {
  Map<String, List<String>> headers = const {},
}) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
    ...headers,
  },
);

/// get_current_user's answer (api/deps.py) to a token it no longer accepts:
/// expired, revoked by an admin's reset or deactivation, or signed with a
/// secret the server has since lost.
ResponseBody _refused() => _json(
  401,
  {'detail': 'Not authenticated.'},
  headers: {
    'www-authenticate': ['Bearer'],
  },
);

/// /auth/login's answer to a wrong password, an unknown email and a
/// deactivated account alike (api/routes_auth.py).
ResponseBody _wrongCredentials() => _json(
  401,
  {'detail': 'Incorrect email or password.'},
  headers: {
    'www-authenticate': ['Bearer'],
  },
);

/// get_ready_user's answer (api/deps.py) to anything but the password change
/// itself, for an account still on its generated password.
ResponseBody _changePasswordFirst() => _json(403, {
  'detail': 'You must change your initial password before continuing.',
});

Map<String, Object?> _user({bool mustChangePassword = false}) => {
  'id': 7,
  'email': 'sam@northshore.test',
  'first_name': 'Sam',
  'last_name': 'Taylor',
  'role': 'dealership_staff',
  'is_active': true,
  'must_change_password': mustChangePassword,
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

ResponseBody _signedIn(String token) => _json(200, {
  'access_token': token,
  'token_type': 'bearer',
  'expires_in': 28800,
  'user': _user(),
});

ProviderContainer _container(_MemoryTokenStore store, _FakeBackend backend) {
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(
        ApiClient(baseUrl: 'http://autopivot.test', httpClientAdapter: backend),
      ),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

/// The app at cold start. restore() is what AppBootstrap.initState calls,
/// called directly here for the reason widget_test.dart gives.
Future<void> _coldStart(
  WidgetTester tester,
  ProviderContainer container,
) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const AutoPivotApp(),
    ),
  );
  unawaited(container.read(authProvider.notifier).restore());
  await _settle(tester);
}

/// Runs every request in flight to its answer, and builds what follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 5; i++) {
    await tester.pump(Duration.zero);
  }
}

/// The error a call failed with, or null if it succeeded, so that several
/// calls can be awaited together.
Future<Object?> _errorOf(Future<Object?> call) =>
    call.then<Object?>((_) => null, onError: (Object error) => error);

const _email = 'sam@northshore.test';
const _password = 'correct horse battery';

void main() {
  group('a session the server stops accepting', () {
    testWidgets('ends mid-session, and sign-in says why', (tester) async {
      final store = _MemoryTokenStore('eight-hours-old');
      // /auth/me took the token at start-up; by the time the dashboard and
      // the processing banner ask for anything, the server no longer does.
      final backend = _FakeBackend(
        (request) =>
            request.path == '/auth/me' ? _json(200, _user()) : _refused(),
      );
      final container = _container(store, backend);

      await _coldStart(tester, container);

      expect(
        container.read(authProvider),
        isA<AuthSignedOut>().having((s) => s.message, 'message', _sessionEnded),
      );
      expect(store.token, isNull);
      expect(store.clears, 1);
      expect(
        find.descendant(
          of: find.byType(SignInScreen),
          matching: find.text(_sessionEnded),
        ),
        findsOneWidget,
      );

      // Nothing is left behind still asking: the processing banner's poll
      // went with the shell it sits in.
      final asked = backend.received.length;
      await tester.pump(const Duration(seconds: 30));
      expect(backend.received, hasLength(asked));
    });

    testWidgets('ends once at cold start, and sign-in says why', (
      tester,
    ) async {
      final store = _MemoryTokenStore('expired-overnight');
      final backend = _FakeBackend((request) => _refused());
      final container = _container(store, backend);

      await _coldStart(tester, container);

      expect(
        find.descendant(
          of: find.byType(SignInScreen),
          matching: find.text(_sessionEnded),
        ),
        findsOneWidget,
      );
      // restore() ends this session itself. The same refusal must not also
      // be taken for a signed-in session expiring and end it a second time.
      expect(store.clears, 1);
    });

    test('ends once, however many requests are refused together', () async {
      final store = _MemoryTokenStore();
      final together = Completer<void>();
      var waiting = 0;
      final backend = _FakeBackend((request) async {
        if (request.path == '/auth/login') return _signedIn('the-session');
        // Held until all three have arrived, then answered at once.
        if (++waiting == 3) together.complete();
        await together.future;
        return _refused();
      });
      final container = _container(store, backend);
      await container
          .read(authProvider.notifier)
          .signIn(email: _email, password: _password);

      final signOuts = <AuthState>[];
      container.listen<AuthState>(authProvider, (_, next) {
        if (next is AuthSignedOut) signOuts.add(next);
      });
      // Storage is still being cleared while the other refusals land.
      store.holdClears = Completer<void>();

      final api = container.read(apiClientProvider);
      final errors = await Future.wait([
        _errorOf(api.dashboardStats()),
        _errorOf(api.listings()),
        _errorOf(api.counts()),
      ]);

      // Every caller still hears about its own refusal...
      expect(errors, everyElement(isA<ApiUnauthorisedException>()));
      // ...but the session ends once.
      expect(signOuts, hasLength(1));
      expect(store.clears, 1);

      store.holdClears!.complete();
      await Future<void>.delayed(Duration.zero);
      expect(
        container.read(authProvider),
        isA<AuthSignedOut>().having((s) => s.message, 'message', _sessionEnded),
      );
      expect(store.token, isNull);
    });

    test('does not end the next one with a refusal it left behind', () async {
      final store = _MemoryTokenStore();
      final tokens = ['first-session', 'second-session'];
      final slowAnswer = Completer<void>();
      final backend = _FakeBackend((request) async {
        if (request.path == '/auth/login') return _signedIn(tokens.removeAt(0));
        // This one's answer is slow to come back, the way an upload of a
        // whole set is over a poor connection.
        if (request.path == '/api/listings/1/jobs') await slowAnswer.future;
        // The server no longer takes the first session's token, which is
        // the only one anything below is sent with.
        return _refused();
      });
      final container = _container(store, backend);
      final auth = container.read(authProvider.notifier);
      final api = container.read(apiClientProvider);

      await auth.signIn(email: _email, password: _password);
      final slow = _errorOf(api.listingJobs(1));

      // Another request is refused first, which ends the first session...
      expect(await _errorOf(api.counts()), isA<ApiUnauthorisedException>());
      expect(container.read(authProvider), isA<AuthSignedOut>());

      // ...the person signs straight back in...
      await auth.signIn(email: _email, password: _password);

      // ...and only then does the slow request's refusal arrive.
      slowAnswer.complete();
      expect(await slow, isA<ApiUnauthorisedException>());
      expect(
        backend.received
            .firstWhere((r) => r.path == '/api/listings/1/jobs')
            .headers['Authorization'],
        'Bearer first-session',
      );
      expect(container.read(authProvider), isA<AuthSignedIn>());
      expect(store.token, 'second-session');
    });
  });

  testWidgets('a wrong password is reported as one, and ends no session', (
    tester,
  ) async {
    final store = _MemoryTokenStore();
    final backend = _FakeBackend((request) => _wrongCredentials());
    final container = _container(store, backend);
    await _coldStart(tester, container);

    await tester.enterText(find.byType(TextFormField).at(0), _email);
    await tester.enterText(find.byType(TextFormField).at(1), 'not it');
    await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
    await _settle(tester);

    expect(
      find.text('That email and password do not match an account.'),
      findsOneWidget,
    );
    expect(find.text(_sessionEnded), findsNothing);
    expect(
      container.read(authProvider),
      isA<AuthSignedOut>().having((s) => s.message, 'message', isNull),
    );
    expect(store.clears, 0);
    expect(backend.received.map((r) => r.path), ['/auth/login']);
  });

  testWidgets('the forced password change can be left by signing out', (
    tester,
  ) async {
    final store = _MemoryTokenStore('provisioned');
    final backend = _FakeBackend(
      (request) => request.path == '/auth/me'
          ? _json(200, _user(mustChangePassword: true))
          : _changePasswordFirst(),
    );
    final container = _container(store, backend);
    await _coldStart(tester, container);
    expect(find.byType(ChangePasswordScreen), findsOneWidget);

    final signOut = find.widgetWithText(TextButton, 'Sign out instead');
    expect(signOut, findsOneWidget);
    await tester.ensureVisible(signOut);
    await tester.pump();
    await tester.tap(signOut);
    await _settle(tester);

    expect(
      container.read(authProvider),
      isA<AuthSignedOut>().having((s) => s.message, 'message', isNull),
    );
    expect(store.token, isNull);
    expect(find.byType(SignInScreen), findsOneWidget);
  });
}
