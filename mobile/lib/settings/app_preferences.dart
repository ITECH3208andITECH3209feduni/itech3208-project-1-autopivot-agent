/// Where the toggles on the Settings screen live — biometric unlock, haptic
/// feedback, and whether the welcome tour has already been shown.
///
/// Secure storage, the same mechanism `auth/token_store.dart` uses for the
/// session token, rather than a new dependency like `shared_preferences` for
/// three small values: nothing here is sensitive the way a bearer token is,
/// but reusing what is already wired in is simpler than a second storage
/// mechanism for a handful of booleans, and the values are not large or
/// numerous enough for that to cost anything.
library;

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AppPreferences {
  const AppPreferences(this._storage);

  static const _biometricLockKey = 'autopivot.biometric_lock_enabled';
  static const _hapticsKey = 'autopivot.haptics_enabled';
  static const _welcomeTourSeenKey = 'autopivot.welcome_tour_seen';

  final FlutterSecureStorage _storage;

  factory AppPreferences.standard() =>
      const AppPreferences(FlutterSecureStorage());

  /// Off by default — turning on a lock screen someone did not ask for is a
  /// worse surprise than leaving one off they might have wanted.
  Future<bool> biometricLockEnabled() async =>
      await _storage.read(key: _biometricLockKey) == 'true';

  Future<void> setBiometricLockEnabled(bool value) =>
      _storage.write(key: _biometricLockKey, value: value.toString());

  /// On by default — matches the platform convention every iOS and Android
  /// app already sets for its own haptics, so this is opting out, not in.
  Future<bool> hapticsEnabled() async =>
      await _storage.read(key: _hapticsKey) != 'false';

  Future<void> setHapticsEnabled(bool value) =>
      _storage.write(key: _hapticsKey, value: value.toString());

  Future<bool> welcomeTourSeen() async =>
      await _storage.read(key: _welcomeTourSeenKey) == 'true';

  Future<void> setWelcomeTourSeen(bool value) =>
      _storage.write(key: _welcomeTourSeenKey, value: value.toString());
}

// ── State ─────────────────────────────────────────────────────────────────

class AppPreferencesState {
  const AppPreferencesState({
    required this.loaded,
    required this.biometricLockEnabled,
    required this.hapticsEnabled,
    required this.welcomeTourSeen,
  });

  const AppPreferencesState.initial()
    : loaded = false,
      biometricLockEnabled = false,
      hapticsEnabled = true,
      welcomeTourSeen =
          true; // assumed seen until proven otherwise — see load()

  /// False for the one frame before [AppPreferencesController.load] resolves.
  /// Nothing reads the three booleans below as meaningful until this is true;
  /// see that method's own doc comment for why [welcomeTourSeen] in
  /// particular defaults to true rather than false while this is false.
  final bool loaded;
  final bool biometricLockEnabled;
  final bool hapticsEnabled;
  final bool welcomeTourSeen;

  AppPreferencesState copyWith({
    bool? loaded,
    bool? biometricLockEnabled,
    bool? hapticsEnabled,
    bool? welcomeTourSeen,
  }) => AppPreferencesState(
    loaded: loaded ?? this.loaded,
    biometricLockEnabled: biometricLockEnabled ?? this.biometricLockEnabled,
    hapticsEnabled: hapticsEnabled ?? this.hapticsEnabled,
    welcomeTourSeen: welcomeTourSeen ?? this.welcomeTourSeen,
  );
}

final appPreferencesStoreProvider = Provider<AppPreferences>(
  (ref) => AppPreferences.standard(),
);

final appPreferencesProvider =
    NotifierProvider<AppPreferencesController, AppPreferencesState>(
      AppPreferencesController.new,
    );

class AppPreferencesController extends Notifier<AppPreferencesState> {
  @override
  AppPreferencesState build() => const AppPreferencesState.initial();

  AppPreferences get _store => ref.read(appPreferencesStoreProvider);

  /// Called once from [AppBootstrap], alongside [AuthController.restore] —
  /// both are "read secure storage before the first real frame" concerns,
  /// just for two different kinds of value.
  ///
  /// [AppPreferencesState.initial] defaults `welcomeTourSeen` to true
  /// specifically so the tour cannot flash on screen for a returning user
  /// during the one frame before this resolves; it is corrected to the real,
  /// stored value here, which is false — and the tour genuinely shown — only
  /// for an account that has truly never seen it.
  Future<void> load() async {
    final results = await Future.wait([
      _store.biometricLockEnabled(),
      _store.hapticsEnabled(),
      _store.welcomeTourSeen(),
    ]);
    state = AppPreferencesState(
      loaded: true,
      biometricLockEnabled: results[0],
      hapticsEnabled: results[1],
      welcomeTourSeen: results[2],
    );
  }

  Future<void> setBiometricLockEnabled(bool value) async {
    state = state.copyWith(biometricLockEnabled: value);
    await _store.setBiometricLockEnabled(value);
  }

  Future<void> setHapticsEnabled(bool value) async {
    state = state.copyWith(hapticsEnabled: value);
    await _store.setHapticsEnabled(value);
  }

  Future<void> setWelcomeTourSeen(bool value) async {
    state = state.copyWith(welcomeTourSeen: value);
    await _store.setWelcomeTourSeen(value);
  }
}

// ── Haptics ──────────────────────────────────────────────────────────────

/// The one place every haptic in this app fires through, so the toggle in
/// Settings genuinely controls all of them rather than whichever call sites
/// remembered to check it.
void haptic(
  WidgetRef ref, [
  HapticFeedbackType type = HapticFeedbackType.light,
]) {
  if (!ref.read(appPreferencesProvider).hapticsEnabled) return;
  switch (type) {
    case HapticFeedbackType.light:
      HapticFeedback.lightImpact();
    case HapticFeedbackType.medium:
      HapticFeedback.mediumImpact();
    case HapticFeedbackType.selection:
      HapticFeedback.selectionClick();
  }
}

enum HapticFeedbackType { light, medium, selection }
