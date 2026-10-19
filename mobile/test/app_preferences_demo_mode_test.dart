// AppPreferences.demoCaptureModeEnabled / setDemoCaptureModeEnabled, and the
// matching slice of AppPreferencesController: lib/settings/app_preferences.dart.
//
// The getter/setter pair is exercised against a mock of flutter_secure_storage's
// own method channel — the same approach medium_app_lock_test.dart uses for
// local_auth's channel — rather than a hand-rolled subclass of AppPreferences.
// A subclass overriding the new methods outright would only prove the
// override's own bookkeeping, not the 'true'/'false' string round-trip
// through storage that is the actual thing being added here.
//
// The controller half needs no storage at all: it is about ordering — state
// before persistence resolves — which a fake AppPreferences whose setter
// hands back a Future this test controls is enough to pin down.

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/settings/app_preferences.dart';

const _secureStorageChannel = MethodChannel(
  'plugins.it_nomads.com/flutter_secure_storage',
);

/// Answers flutter_secure_storage's own method channel from an in-memory map,
/// the way the real plugin would answer from the Keychain or Keystore.
/// Registered and torn down per test, the same lifecycle _DeviceCheck uses
/// for local_auth's channel in medium_app_lock_test.dart.
class _FakeSecureStorage {
  _FakeSecureStorage() {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_secureStorageChannel, _handle);
    addTearDown(
      () => messenger.setMockMethodCallHandler(_secureStorageChannel, null),
    );
  }

  final Map<String, String> _data = {};

  Future<Object?> _handle(MethodCall call) async {
    final args = call.arguments as Map;
    switch (call.method) {
      case 'read':
        return _data[args['key'] as String];
      case 'write':
        _data[args['key'] as String] = args['value'] as String;
        return null;
    }
    return null;
  }
}

/// Hands [write] back from [setDemoCaptureModeEnabled] instead of resolving
/// on its own, so the controller test can inspect state while the persist
/// call is still in flight.
class _StallingPreferences extends AppPreferences {
  _StallingPreferences(this.write) : super(const FlutterSecureStorage());

  final Future<void> write;

  @override
  Future<void> setDemoCaptureModeEnabled(bool value) => write;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    _FakeSecureStorage();
  });

  test('demoCaptureModeEnabled defaults to false before anything is stored', () async {
    final preferences = AppPreferences.standard();
    expect(await preferences.demoCaptureModeEnabled(), isFalse);
  });

  test(
    'demoCaptureModeEnabled returns true after setDemoCaptureModeEnabled(true)',
    () async {
      final preferences = AppPreferences.standard();
      await preferences.setDemoCaptureModeEnabled(true);
      expect(await preferences.demoCaptureModeEnabled(), isTrue);
    },
  );

  test(
    'AppPreferencesController.setDemoCaptureModeEnabled updates state before '
    'the storage write resolves',
    () async {
      final write = Completer<void>();
      final container = ProviderContainer(
        overrides: [
          appPreferencesStoreProvider.overrideWithValue(
            _StallingPreferences(write.future),
          ),
        ],
      );
      addTearDown(container.dispose);

      final pending = container
          .read(appPreferencesProvider.notifier)
          .setDemoCaptureModeEnabled(true);

      // Checked while `write` is still unresolved: state already flipped,
      // the same ordering setBiometricLockEnabled and setHapticsEnabled rely
      // on so a slow write never makes the toggle look like it did nothing.
      expect(
        container.read(appPreferencesProvider).demoCaptureModeEnabled,
        isTrue,
      );

      write.complete();
      await pending;
    },
  );
}
