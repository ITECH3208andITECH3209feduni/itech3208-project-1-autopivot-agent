// A cold start with no stored session lands on the sign-in screen.
//
// tokenStoreProvider is overridden with a fake that never touches a platform
// channel. flutter_secure_storage's real read() does — and widget tests run
// inside a FakeAsync zone, where a Future tied to a genuine platform-channel
// round trip is created on the real zone and is never seen to resolve by
// pump() alone, whatever real or fake time is allowed to pass. That is a
// property of the test harness, not something this screen needs to cope
// with, so the fake sidesteps it rather than working around it.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/app.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';

class _FakeTokenStore extends TokenStore {
  // The real FlutterSecureStorage() passed here is never touched — every
  // method below is overridden — so constructing it costs nothing: no
  // platform channel is invoked by construction alone, only by a call.
  _FakeTokenStore() : super(const FlutterSecureStorage());

  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {}

  @override
  Future<void> clear() async {}
}

void main() {
  testWidgets('a cold start with no session shows sign-in, not the counter demo', (
    tester,
  ) async {
    final container = ProviderContainer(
      overrides: [tokenStoreProvider.overrideWithValue(_FakeTokenStore())],
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const AutoPivotApp(),
      ),
    );

    // In the real app this is kicked off by _Bootstrap.initState in
    // main.dart, which this test deliberately does not pump — _Bootstrap has
    // no behaviour of its own beyond this one call, and calling it directly
    // on a container built with the fake in place is what lets the rest of
    // the test target AutoPivotApp's routing without also exercising
    // _Bootstrap.
    await container.read(authProvider.notifier).restore();

    // Ordinary Dart async, no platform channel and no real Timer involved
    // once the fake is in place, so a couple of frames is enough for the
    // resulting state change to reach the router's redirect. Not
    // pumpAndSettle(): the splash screen's CircularProgressIndicator
    // animates forever and would make it wait for a frame that never stops
    // being scheduled.
    await tester.pump();
    await tester.pump();

    expect(find.text('AutoPivot'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Sign in'), findsOneWidget);
    expect(find.byType(TextFormField), findsNWidgets(2));

    // No sign-up or password-reset path exists anywhere in this app — see
    // app.dart and sign_in_screen.dart for why that is a hard constraint
    // rather than an oversight.
    expect(find.textContaining('Sign up'), findsNothing);
    expect(find.textContaining('Forgot'), findsNothing);
  });
}
