// Two things an account can do to its own password. Change it —
// lib/api/api_client.dart, lib/auth/auth_controller.dart and the forced
// change-password screen — and, for a dealership administrator, not reset it
// from the team roster (lib/features/settings/team_screen.dart), which offers
// that on every other row.
//
// POST /auth/change-password (api/routes_auth.py) revokes every token issued
// before it, the one that asked included, and answers the way POST
// /auth/login does: {access_token, token_type, expires_in, user}. _Server
// below enforces that revocation, so a client still sending the old token is
// refused, as the real server refuses it.
//
// The real ApiClient makes every request, over a stand-in transport, as in
// session_expiry_test.dart, and the widget tests settle the way that file's
// do.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/app.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/change_password/change_password_screen.dart';
import 'package:autopivot/features/settings/team_screen.dart';
import 'package:autopivot/routes.dart';
import 'package:autopivot/widgets/primitives.dart';

const _email = 'sam@northshore.test';
const _generated = 'the generated one';
const _chosen = 'a much longer passphrase';
const _before = 'before-the-change';
const _after = 'after-the-change';

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

/// Stands in for the server at the transport, as in session_expiry_test.dart.
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

Map<String, Object?> _user({
  int id = 7,
  String firstName = 'Sam',
  String lastName = 'Taylor',
  String role = 'dealership_staff',
  bool mustChangePassword = false,
}) => {
  'id': id,
  'email': '${firstName.toLowerCase()}@northshore.test',
  'first_name': firstName,
  'last_name': lastName,
  'role': role,
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

/// The shape POST /auth/login and POST /auth/change-password both answer
/// with.
ResponseBody _session(String token, {required bool mustChangePassword}) =>
    _json(200, {
      'access_token': token,
      'token_type': 'bearer',
      'expires_in': 28800,
      'user': _user(mustChangePassword: mustChangePassword),
    });

/// Sam's account, provisioned with a generated password, as
/// api/routes_auth.py and api/deps.py answer for it.
class _Server {
  var changed = false;

  late final backend = _FakeBackend(_answer);

  ResponseBody _answer(RequestOptions request) {
    final bearer = request.headers['Authorization'];
    switch (request.path) {
      case '/auth/login':
        return _session(_before, mustChangePassword: true);
      case '/auth/change-password':
        if (changed || bearer != 'Bearer $_before') return _refused();
        changed = true;
        return _session(_after, mustChangePassword: false);
    }
    if (!changed && bearer == 'Bearer $_before') {
      // get_ready_user: nothing but the change itself, until it is made.
      return request.path == '/auth/me'
          ? _json(200, _user(mustChangePassword: true))
          : _json(403, {
              'detail':
                  'You must change your initial password before continuing.',
            });
    }
    // Revoked by the change, or never valid.
    if (bearer != 'Bearer $_after') return _refused();
    return switch (request.path) {
      '/auth/me' => _json(200, _user()),
      '/api/dashboard/stats' => _json(200, {
        'vehicles_this_month': 0,
        'images_processed': 0,
        'needs_review': 0,
      }),
      '/api/listings' => _json(200, <Object?>[]),
      _ => _notFound(),
    };
  }
}

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

/// Runs every request in flight to its answer, and builds what follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 30; i++) {
    await tester.pump(Duration.zero);
  }
}

/// A dealership administrator's own team roster: Sam, who is signed in, and
/// Alex.
Future<void> _openTeam(WidgetTester tester) async {
  Map<String, Object?> member(Map<String, Object?> user) => {
    for (final key in [
      'id',
      'email',
      'first_name',
      'last_name',
      'role',
      'is_active',
      'must_change_password',
    ])
      key: user[key],
  };
  final sam = _user(role: 'dealership_admin');
  final alex = _user(id: 8, firstName: 'Alex', lastName: 'Chen');
  final backend = _FakeBackend(
    (request) => switch (request.path) {
      '/auth/me' => _json(200, sam),
      '/api/dealership/users' => _json(200, [member(sam), member(alex)]),
      _ => _notFound(),
    },
  );
  final container = _container(_MemoryTokenStore('an-admins-session'), backend);
  final router = GoRouter(
    initialLocation: AppRoutes.team,
    routes: [
      GoRoute(
        path: AppRoutes.team,
        builder: (context, state) => const TeamScreen(),
      ),
      GoRoute(
        path: AppRoutes.settingsChangePassword,
        builder: (context, state) =>
            const ChangePasswordScreen(dismissible: true),
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
  unawaited(container.read(authProvider.notifier).restore());
  await _settle(tester);
}

/// Opens the actions menu on the row for [name].
Future<void> _openActions(WidgetTester tester, String name) async {
  final row = find.ancestor(
    of: find.text(name),
    matching: find.byType(AppCard),
  );
  await tester.tap(
    find.descendant(of: row, matching: find.byTooltip('Actions')),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  group('changing a password', () {
    test('carries on with the token the server hands back', () async {
      final server = _Server();
      final store = _MemoryTokenStore();
      final container = _container(store, server.backend);
      final auth = container.read(authProvider.notifier);

      await auth.signIn(email: _email, password: _generated);
      await auth.changePassword(
        currentPassword: _generated,
        newPassword: _chosen,
      );

      expect(
        container.read(authProvider),
        isA<AuthSignedIn>().having(
          (s) => s.mustChangePassword,
          'mustChangePassword',
          isFalse,
        ),
      );
      expect(store.token, _after);

      // The next request goes with the new token, and the session carries on.
      await container.read(apiClientProvider).dashboardStats();
      expect(
        server.backend.received.last.headers['Authorization'],
        'Bearer $_after',
      );
      expect(container.read(authProvider), isA<AuthSignedIn>());
    });

    testWidgets(
      'the forced change goes on into the app, not back out to sign-in',
      (tester) async {
        final server = _Server();
        final store = _MemoryTokenStore(_before);
        final container = _container(store, server.backend);
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: const AutoPivotApp(),
          ),
        );
        unawaited(container.read(authProvider.notifier).restore());
        await _settle(tester);
        expect(find.byType(ChangePasswordScreen), findsOneWidget);

        final fields = find.byType(TextFormField);
        await tester.enterText(fields.at(0), _generated);
        await tester.enterText(fields.at(1), _chosen);
        await tester.enterText(fields.at(2), _chosen);
        final change = find.widgetWithText(FilledButton, 'Change password');
        await tester.ensureVisible(change);
        await tester.pump();
        await tester.tap(change);
        await _settle(tester);

        expect(find.text('Overview'), findsOneWidget);
        expect(container.read(authProvider), isA<AuthSignedIn>());
        expect(store.token, _after);
        final afterwards = server.backend.received
            .skipWhile((r) => r.path != '/auth/change-password')
            .skip(1)
            .toList();
        expect(afterwards, isNotEmpty);
        expect(
          afterwards.map((r) => r.headers['Authorization']),
          everyElement('Bearer $_after'),
        );
      },
    );
  });

  group('the team roster', () {
    testWidgets(
      "offers an administrator's own row Change password, not a reset",
      (tester) async {
        await _openTeam(tester);
        await _openActions(tester, 'Sam Taylor');

        expect(find.text('Reset password'), findsNothing);
        expect(find.text('Deactivate'), findsNothing);

        await tester.tap(find.text('Change password'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 600));
        expect(find.byType(ChangePasswordScreen), findsOneWidget);
      },
    );

    testWidgets("still offers a reset and deactivation on everyone else's", (
      tester,
    ) async {
      await _openTeam(tester);
      await _openActions(tester, 'Alex Chen');

      expect(find.text('Reset password'), findsOneWidget);
      expect(find.text('Deactivate'), findsOneWidget);
    });
  });
}
