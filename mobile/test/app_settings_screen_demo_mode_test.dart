// The "Demo capture mode" toggle on the Settings screen:
// lib/features/settings/app_settings_screen.dart, backed by
// lib/settings/app_preferences.dart.
//
// Pumps AppSettingsScreen directly rather than the whole app the way
// medium_app_lock_test.dart does for the biometric toggle: nothing exercised
// here needs routing, a signed-in session or a backend, only the
// preferences provider the screen reads from — which load() below fills in
// the same way AppBootstrap does at a real cold start.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/settings/app_settings_screen.dart';
import 'package:autopivot/settings/app_preferences.dart';
import 'package:autopivot/widgets/primitives.dart';

/// Everything AppSettingsScreen's build() reads from AppPreferences, kept in
/// memory — the same shape as medium_app_lock_test.dart's own fake, trimmed
/// to what this screen actually calls.
class _FakePreferences extends AppPreferences {
  _FakePreferences() : super(const FlutterSecureStorage());

  bool demoCaptureMode = false;

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
  Future<void> setDemoCaptureModeEnabled(bool value) async {
    demoCaptureMode = value;
  }
}

void main() {
  testWidgets(
    'the Demo capture mode toggle renders and flips the preference when tapped',
    (tester) async {
      final preferences = _FakePreferences();
      final container = ProviderContainer(
        overrides: [
          appPreferencesStoreProvider.overrideWithValue(preferences),
        ],
      );
      addTearDown(container.dispose);
      // As AppBootstrap does at a real cold start — without this, `loaded`
      // stays false and the screen renders nothing but its header.
      await container.read(appPreferencesProvider.notifier).load();

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: AppSettingsScreen()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Demo capture mode'), findsOneWidget);

      // The switch inside the same card as the title, not a positional
      // index, so this stays correct regardless of where the row sits
      // relative to the other toggles.
      final card = find.ancestor(
        of: find.text('Demo capture mode'),
        matching: find.byType(AppCard),
      );
      final toggle = find.descendant(of: card, matching: find.byType(Switch));
      expect(tester.widget<Switch>(toggle).value, isFalse);

      // The row sits below the fold at the test harness's default window
      // size, same as it would on a real phone with ACCOUNT, SECURITY and
      // FEEDBACK above it — scroll it into view the way a thumb would
      // rather than skip straight to tapping an offscreen offset.
      await tester.ensureVisible(toggle);
      await tester.pumpAndSettle();

      await tester.tap(toggle);
      await tester.pumpAndSettle();

      expect(preferences.demoCaptureMode, isTrue);
      expect(tester.widget<Switch>(toggle).value, isTrue);
    },
  );
}
