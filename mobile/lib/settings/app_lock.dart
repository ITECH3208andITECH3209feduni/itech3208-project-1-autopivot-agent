/// Gates the signed-in app behind a biometric prompt when the Settings
/// toggle for it is on — wired into `app.dart`'s builder, alongside
/// `AuthChecking`/`AuthUnavailable`, rather than into the auth state machine
/// itself. A failed or declined unlock is not a reason to end the session:
/// [AuthController] is "the only thing allowed to change" [AuthState] per
/// its own doc comment, and a wrong Face ID read is not that — the token
/// stays valid, [AppLockController] just keeps showing [AppLockScreen] until
/// it succeeds.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/typography.dart';
import 'app_preferences.dart';
import 'biometric_auth.dart';

/// True once unlocked for this app session. Starts locked — the same
/// "assume nothing until proven" as [AuthState] starting at [AuthChecking].
final appLockProvider = NotifierProvider<AppLockController, bool>(
  AppLockController.new,
);

class AppLockController extends Notifier<bool> {
  @override
  bool build() {
    // Without this, signing out and straight back in — on the same device,
    // same app process, no restart — would carry the previous session's
    // unlock forward: this provider is created once and outlives any one
    // AuthState, so nothing else ever puts it back to locked for whoever
    // signs in next. A cold start needs no such reset — the initial `false`
    // below already covers it — this is specifically for the transition a
    // fresh build() never sees.
    ref.listen<AuthState>(authProvider, (previous, next) {
      if (previous is AuthSignedOut && next is AuthSignedIn) relock();
    });
    return false;
  }

  void unlock() => state = true;

  /// Called when the app is backgrounded — the actual point of a lock
  /// screen is to cover the case where the phone (already unlocked at the
  /// OS level) is picked up by someone else while this app is what was left
  /// open, not only a fresh launch. Also called on a fresh sign-in
  /// following a sign-out — see the comment in [build].
  void relock() => state = false;
}

/// Wraps the signed-in app. Shows [AppLockScreen] instead of [child] exactly
/// when biometric lock is on and this app session has not been unlocked yet;
/// otherwise transparent.
class AppLockGate extends ConsumerStatefulWidget {
  const AppLockGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<AppLockGate> createState() => _AppLockGateState();
}

class _AppLockGateState extends ConsumerState<AppLockGate>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycleState) {
    if (lifecycleState != AppLifecycleState.paused) return;
    if (!ref.read(appPreferencesProvider).biometricLockEnabled) return;
    ref.read(appLockProvider.notifier).relock();
  }

  @override
  Widget build(BuildContext context) {
    final prefs = ref.watch(appPreferencesProvider);
    final unlocked = ref.watch(appLockProvider);

    // Preferences load in parallel with auth at cold start (bootstrap.dart)
    // and are almost always the faster of the two reads; on the rare chance
    // this frame renders before they resolve, showing real content for one
    // frame is not a disclosure — the phone's own lock screen already had to
    // be open for this app to be in the foreground at all — so this treats
    // "not loaded yet" the same as "lock is off" rather than blocking on it.
    if (!prefs.loaded || !prefs.biometricLockEnabled || unlocked) {
      return widget.child;
    }
    return const AppLockScreen();
  }
}

class AppLockScreen extends ConsumerStatefulWidget {
  const AppLockScreen({super.key});

  @override
  ConsumerState<AppLockScreen> createState() => _AppLockScreenState();
}

class _AppLockScreenState extends ConsumerState<AppLockScreen> {
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    // Prompts immediately on arrival, matching how iOS's own apps greet a
    // Face-ID-locked screen with the prompt already open rather than making
    // the first tap be "ask for the prompt".
    WidgetsBinding.instance.addPostFrameCallback((_) => _attempt());
  }

  Future<void> _attempt() async {
    if (_checking) return;
    setState(() => _checking = true);
    final ok = await authenticate();
    if (!mounted) return;
    setState(() => _checking = false);
    if (ok) ref.read(appLockProvider.notifier).unlock();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Space.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.lock_outline, size: 40, color: C.forest),
                const SizedBox(height: Space.lg),
                Text('AutoPivot is locked', style: serif(24)),
                const SizedBox(height: Space.sm),
                const Text(
                  'Unlock to continue where you left off.',
                  style: T.bodySmall,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: Space.xl),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _checking ? null : _attempt,
                    child: Text(_checking ? 'Checking…' : 'Unlock'),
                  ),
                ),
                const SizedBox(height: Space.sm),
                TextButton(
                  onPressed: _checking
                      ? null
                      : () => ref.read(authProvider.notifier).signOut(),
                  child: const Text('Sign out instead'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
