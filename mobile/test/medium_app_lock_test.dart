// The biometric lock: lib/settings/app_lock.dart, wired into app.dart's
// builder, and the Settings toggle that turns it on
// (lib/features/settings/app_settings_screen.dart).
//
// The device's own check is answered on local_auth's method channel, the
// implementation `flutter test` falls back to (plugin registration does not
// run under the test harness), so each prompt comes back with exactly the
// answer a test gives it. A prompt past the answers given stays open, the way
// a Face ID sheet waits for a face.
//
// Everything else is the real app: the real ApiClient over a stand-in
// transport, as in session_expiry_test.dart, and preferences kept in memory
// for the reason widget_test.dart gives for the token store. Settled with
// pump(Duration.zero), never pumpAndSettle(), for session_expiry_test.dart's
// reasons.

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/app.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/dashboard/dashboard_screen.dart';
import 'package:autopivot/features/settings/app_settings_screen.dart';
import 'package:autopivot/features/sign_in/sign_in_screen.dart';
import 'package:autopivot/routes.dart';
import 'package:autopivot/settings/app_preferences.dart';

const _locked = 'AutoPivot is locked';
const _email = 'sam@northshore.test';
const _password = 'correct horse battery';

/// Shown once and never retrievable again, like the generated password
/// team_screen.dart shows after adding someone.
const _shownOnce = 'Their password: 7Hq-2mZ-94xk';

const _localAuth = MethodChannel('plugins.flutter.io/local_auth');

class _MemoryTokenStore extends TokenStore {
  // As in widget_test.dart, the FlutterSecureStorage handed up is never
  // touched: every method below is overridden.
  _MemoryTokenStore(this.token) : super(const FlutterSecureStorage());

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

class _MemoryPreferences extends AppPreferences {
  _MemoryPreferences({required this.biometricLock})
    : super(const FlutterSecureStorage());

  bool biometricLock;

  @override
  Future<bool> biometricLockEnabled() async => biometricLock;

  @override
  Future<void> setBiometricLockEnabled(bool value) async =>
      biometricLock = value;

  @override
  Future<bool> hapticsEnabled() async => true;

  @override
  Future<void> setHapticsEnabled(bool value) async {}

  // Seen already, so the first-run tour stays out of the way.
  @override
  Future<bool> welcomeTourSeen() async => true;

  @override
  Future<void> setWelcomeTourSeen(bool value) async {}
}

/// The phone's own biometric or passcode check, as local_auth asks for it.
class _DeviceCheck {
  _DeviceCheck(this._answers) {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_localAuth, _answer);
    addTearDown(() => messenger.setMockMethodCallHandler(_localAuth, null));
  }

  /// What each prompt comes back with, in the order they are shown.
  final List<Future<bool>> _answers;

  /// How many times the person has been asked.
  int prompts = 0;

  Future<Object?> _answer(MethodCall call) async {
    switch (call.method) {
      case 'isDeviceSupported':
        return true;
      case 'authenticate':
        final answer = prompts < _answers.length
            ? _answers[prompts]
            : Completer<bool>().future;
        prompts++;
        return answer;
    }
    return null;
  }
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

Map<String, Object?> _user() => {
  'id': 7,
  'email': _email,
  'first_name': 'Sam',
  'last_name': 'Taylor',
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

/// A dealership with nothing in it yet, and Sam's account.
ResponseBody _server(RequestOptions request) => switch (request.path) {
  '/auth/me' => _json(200, _user()),
  '/auth/login' => _json(200, {
    'access_token': 'signed-in-with-a-password',
    'token_type': 'bearer',
    'expires_in': 28800,
    'user': _user(),
  }),
  '/api/dashboard/stats' => _json(200, {
    'vehicles_this_month': 0,
    'images_processed': 0,
    'needs_review': 0,
  }),
  '/api/listings' => _json(200, <Object?>[]),
  _ => _json(404, {'detail': 'Not found.'}),
};

ProviderContainer _container(_MemoryPreferences preferences) {
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore('from-earlier')),
      apiClientProvider.overrideWithValue(
        ApiClient(
          baseUrl: 'http://autopivot.test',
          httpClientAdapter: _FakeBackend(_server),
        ),
      ),
      appPreferencesStoreProvider.overrideWithValue(preferences),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

/// The app at cold start, with a session stored from earlier. Both calls are
/// what AppBootstrap.initState makes, made directly for the reason
/// widget_test.dart gives.
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
  await container.read(appPreferencesProvider.notifier).load();
  await _settle(tester);
}

/// Runs every request and prompt in flight to its answer, and builds what
/// follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 30; i++) {
    await tester.pump(Duration.zero);
  }
}

/// The app going to the background or coming back, sent the way the engine
/// sends it.
Future<void> _lifecycle(WidgetTester tester, AppLifecycleState state) =>
    tester.binding.defaultBinaryMessenger.handlePlatformMessage(
      SystemChannels.lifecycle.name,
      SystemChannels.lifecycle.codec.encodeMessage(state.toString()),
      (_) {},
    );

void main() {
  testWidgets(
    'signing in with the password after "Sign out instead" is not locked again',
    (tester) async {
      // A phone whose check this person cannot pass: someone else's face
      // enrolled on a shared device, or a passcode since removed.
      final device = _DeviceCheck([Future.value(false)]);
      final container = _container(_MemoryPreferences(biometricLock: true));

      await _coldStart(tester, container);
      expect(find.text(_locked), findsOneWidget);
      expect(device.prompts, 1);

      await tester.tap(find.widgetWithText(TextButton, 'Sign out instead'));
      await _settle(tester);
      expect(find.byType(SignInScreen), findsOneWidget);

      await tester.enterText(find.byType(TextFormField).at(0), _email);
      await tester.enterText(find.byType(TextFormField).at(1), _password);
      await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
      await _settle(tester);

      // The password just typed is proof enough of who is holding the phone.
      expect(find.text(_locked), findsNothing);
      expect(find.text('Overview'), findsOneWidget);
      expect(device.prompts, 1);
    },
  );

  testWidgets('turning the lock on does not lock the app straight away', (
    tester,
  ) async {
    // Turning it on asks once, to prove the phone can answer at all. A second
    // prompt would sit waiting.
    final device = _DeviceCheck([Future.value(true)]);
    final preferences = _MemoryPreferences(biometricLock: false);
    final container = _container(preferences);
    await _coldStart(tester, container);
    expect(find.text('Overview'), findsOneWidget);

    unawaited(
      GoRouter.of(tester.element(find.byType(DashboardScreen)))
          .push(AppRoutes.settings),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(AppSettingsScreen), findsOneWidget);

    // The first switch on the screen is the lock's; haptics come after it.
    await tester.tap(find.byType(Switch).first);
    await _settle(tester);

    expect(preferences.biometricLock, isTrue);
    expect(find.text(_locked), findsNothing);
    expect(find.byType(AppSettingsScreen), findsOneWidget);
    expect(device.prompts, 1);
  });

  testWidgets(
    'coming back to the app covers what was open instead of closing it',
    (tester) async {
      final comingBack = Completer<bool>();
      final device = _DeviceCheck([Future.value(true), comingBack.future]);
      final container = _container(_MemoryPreferences(biometricLock: true));
      await _coldStart(tester, container);
      // Unlocked at cold start by the first prompt.
      expect(find.text(_locked), findsNothing);

      unawaited(
        showDialog<void>(
          context: tester.element(find.byType(DashboardScreen)),
          builder: (context) => AlertDialog(
            content: const Text(_shownOnce),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Done'),
              ),
            ],
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text(_shownOnce), findsOneWidget);

      await _lifecycle(tester, AppLifecycleState.paused);
      await tester.pump();
      await _lifecycle(tester, AppLifecycleState.resumed);
      await _settle(tester);

      // Locked, with the prompt still up...
      expect(find.text(_locked), findsOneWidget);
      expect(device.prompts, 2);
      // ...over the dialog, which is still there underneath...
      expect(find.text(_shownOnce), findsOneWidget);
      // ...and out of reach while it is covered: not animating, not read out
      // by a screen reader, and not answering taps.
      expect(
        TickerMode.valuesOf(tester.element(find.text(_shownOnce))).enabled,
        isFalse,
      );
      expect(find.semantics.byLabel(RegExp('7Hq-2mZ-94xk')), findsNothing);
      await tester.tap(find.text('Done'), warnIfMissed: false);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text(_shownOnce), findsOneWidget);

      comingBack.complete(true);
      await _settle(tester);

      // Unlocked onto the same dialog, not a fresh start.
      expect(find.text(_locked), findsNothing);
      expect(find.text(_shownOnce), findsOneWidget);
      expect(find.semantics.byLabel(RegExp('7Hq-2mZ-94xk')), findsAny);
      await tester.tap(find.text('Done'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text(_shownOnce), findsNothing);
    },
  );
}
