/// Gates the signed-in app behind a biometric prompt when the Settings
/// toggle for it is on — wired into `app.dart`'s builder, alongside
/// `AuthChecking`/`AuthUnavailable`, rather than into the auth state machine
/// itself. A failed or declined unlock is not a reason to end the session:
/// [AuthController] is "the only thing allowed to change" [AuthState] per
/// its own doc comment, and a wrong Face ID read is not that — the token
/// stays valid, and [AppLockScreen] stays over the app until the check
/// succeeds, or until the person signs out and back in with their password.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/typography.dart';
import 'app_preferences.dart';
import 'biometric_auth.dart';

/// True once unlocked for this app session. A session restored at cold start
/// starts locked — the same "assume nothing until proven" as [AuthState]
/// starting at [AuthChecking] — and one begun by typing the password does
/// not.
final appLockProvider = NotifierProvider<AppLockController, bool>(
  AppLockController.new,
);

class AppLockController extends Notifier<bool> {
  /// A fresh sign-in has just reauthenticated the person by password, which
  /// is the stronger proof; demanding the phone's biometric on top makes the
  /// lock ask for a face or fingerprint that has nothing to do with the
  /// account just signed into — a company-assigned or shared device, refusing
  /// its user because *this phone's* enrolled biometric is someone else's.
  /// This used to start locked however the session began, with nothing but
  /// the biometric check able to unlock it, so for anyone the phone could not
  /// recognise (a passcode since removed, a shared device), "Sign out
  /// instead" led through the password sign-in straight back to the lock,
  /// for good: the setting belongs to the phone and survives sign-out.
  /// Watched, so every sign-in decides afresh.
  @override
  bool build() => ref.watch(
    authProvider.select((auth) => auth is AuthSignedIn && auth.byPassword),
  );

  void unlock() => state = true;

  /// Called when the app is backgrounded — the actual point of a lock
  /// screen is to cover the case where the phone (already unlocked at the
  /// OS level) is picked up by someone else while this app is what was left
  /// open.
  ///
  /// Deliberately *not* also called on a sign-out-then-sign-in — see
  /// [build] for why a password sign-in counts as unlocked. Backgrounding is
  /// the actual signal this screen exists to react to.
  void relock() => state = false;
}

/// Wraps the signed-in app, and covers it with [AppLockScreen] exactly when
/// biometric lock is on and this app session has not been unlocked yet.
///
/// Covers it rather than replacing it. Swapping the lock screen in for
/// [child] — the router, with every route, dialog and half-filled form on
/// it — disposed all of that on every trip to the background, a one-time
/// password shown "only now" included (team_screen.dart,
/// dealerships_screen.dart), and unlocking started the app over from its
/// route alone. Kept mounted underneath, it is also kept out of reach while
/// covered: no taps, no keyboard focus, nothing read out by a screen
/// reader, and no animations running.
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
    final locked = prefs.loaded && prefs.biometricLockEnabled && !unlocked;

    // The same widgets around the child whether locked or not, so that
    // locking changes their settings rather than the tree's shape, which
    // would rebuild the child from scratch.
    return Stack(
      fit: StackFit.expand,
      children: [
        ExcludeFocus(
          excluding: locked,
          child: ExcludeSemantics(
            excluding: locked,
            child: IgnorePointer(
              ignoring: locked,
              child: TickerMode(enabled: !locked, child: widget.child),
            ),
          ),
        ),
        if (locked) const AppLockScreen(),
      ],
    );
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
