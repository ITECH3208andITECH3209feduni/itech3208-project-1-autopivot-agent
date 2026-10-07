/// Session state, and the only thing allowed to change it.
///
/// Riverpod rather than an InheritedWidget: the router has to read this to
/// decide a redirect, and screens have to read it to render — Riverpod reaches
/// both without a `BuildContext`, and the controller can be tested without
/// pumping a widget tree.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/models/user.dart';
import '../features/capture/capture_draft.dart' show clearCaptureDraft;
import '../widgets/authed_image.dart' show clearAuthedImageCache;
import 'token_store.dart';

// ── State ─────────────────────────────────────────────────────────────────

sealed class AuthState {
  const AuthState();
}

/// Start-up, validating a stored token. The router waits here rather than
/// guessing — without this, every cold start flashes the sign-in screen at a
/// user who is already signed in.
final class AuthChecking extends AuthState {
  const AuthChecking();
}

final class AuthSignedOut extends AuthState {
  const AuthSignedOut({this.message});

  /// Set when the session ended rather than the user leaving: expired, revoked,
  /// or the account deactivated. Shown once on the sign-in screen.
  final String? message;
}

final class AuthSignedIn extends AuthState {
  const AuthSignedIn(this.user, {this.byPassword = false});

  final User user;

  /// True when this session's token came from the password being typed on
  /// this phone just now — [AuthController.signIn], or a password change —
  /// and false for one restored from storage at start-up. The app lock
  /// (settings/app_lock.dart) counts the first as already unlocked.
  final bool byPassword;

  /// Provisioned accounts start with a generated password. Until this is
  /// false the user goes nowhere else, and cannot skip it.
  bool get mustChangePassword => user.mustChangePassword;
}

/// A token exists but could not be checked, because the server was unreachable.
///
/// Deliberately not [AuthSignedOut]: the token has not been shown to be
/// invalid, so it is kept. Signing someone out because their train went into a
/// tunnel is the failure this state exists to prevent.
final class AuthUnavailable extends AuthState {
  const AuthUnavailable(this.message);

  final String message;
}

// ── Providers ─────────────────────────────────────────────────────────────

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore.standard());

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

final authProvider = NotifierProvider<AuthController, AuthState>(
  AuthController.new,
);

/// The signed-in user, or null. Saves every screen unpacking the state.
final currentUserProvider = Provider<User?>((ref) {
  final state = ref.watch(authProvider);
  return state is AuthSignedIn ? state.user : null;
});

// ── Controller ────────────────────────────────────────────────────────────

class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    // Wired here, not where the client is built, so it holds for whichever
    // ApiClient the scope provides, an overrideWithValue included (the dev
    // tools' real-backend mode is one), with nothing else to remember it.
    _api.onSessionExpired = sessionExpired;
    return const AuthChecking();
  }

  ApiClient get _api => ref.read(apiClientProvider);
  TokenStore get _tokens => ref.read(tokenStoreProvider);

  /// Whose the last session here was, kept after it ends. A session the
  /// server ended (expired, revoked) leaves its capture draft for that same
  /// person to pick back up after signing in again, and only a different
  /// account signing in next means the draft is someone else's work. Known
  /// only for sessions this run of the app has seen.
  int? _lastUserId;

  /// Restore a session from storage, if there is one.
  ///
  /// Called once at start-up. The stored token is *validated* rather than
  /// trusted: `/auth/me` re-reads `is_active` server-side, so an account
  /// deactivated since the token was issued stops working now rather than when
  /// the token expires.
  Future<void> restore() async {
    final token = await _tokens.read();
    if (token == null) {
      state = const AuthSignedOut();
      return;
    }

    _api.token = token;
    try {
      final user = await _api.me();
      _lastUserId = user.id;
      state = AuthSignedIn(user);
    } on ApiUnauthorisedException catch (e) {
      // The one case that clears the token.
      await _signOutLocally();
      state = AuthSignedOut(message: e.message);
    } on ApiException catch (e) {
      // Network or server trouble. The token is kept and the user is offered a
      // retry, because nothing here shows the session to be invalid.
      state = AuthUnavailable(e.message);
    }
  }

  Future<void> signIn({required String email, required String password}) async {
    final result = await _api.login(email: email.trim(), password: password);
    await _tokens.write(result.accessToken);
    _api.token = result.accessToken;
    if (_lastUserId != null && _lastUserId != result.user.id) {
      // Someone else's session ended here without them signing out. Not
      // awaited: the draft store runs its operations in the order asked, so
      // this is done before the camera can ask whether there is a draft to
      // resume, without the sign-in waiting on file clean-up.
      unawaited(_discardAccountData());
    }
    _lastUserId = result.user.id;
    state = AuthSignedIn(result.user, byPassword: true);
  }

  /// Rotate the password on the signed-in account.
  ///
  /// The server enforces a 12 character minimum and rejects reusing the current
  /// password; both come back as a message worth showing.
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final result = await _api.changePassword(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    // The change revoked every token issued before it, the one that asked
    // included; the reply carries the session's next one. Held in memory
    // first, before anything is awaited: a refusal of the revoked token
    // arriving after that is about a token already gone, not this session.
    _api.token = result.accessToken;
    await _tokens.write(result.accessToken);
    _lastUserId = result.user.id;
    state = AuthSignedIn(result.user, byPassword: true);
  }

  /// Ends the session, and takes the account's work off the phone with it —
  /// see [_discardAccountData].
  Future<void> signOut() async {
    await _signOutLocally();
    state = const AuthSignedOut();
    // After the state change rather than before: nothing about the sign-in
    // screen has to wait on file clean-up.
    await _discardAccountData();
  }

  /// Called by [ApiClient] when the server refuses the session's token.
  ///
  /// Ends the session once however many requests are refused together: the
  /// state flips before anything is awaited, so every refusal after the
  /// first finds no signed-in session left to end. The same check leaves a
  /// refusal during [restore] to [restore], which ends that one itself.
  Future<void> sessionExpired(String message) async {
    // The client can outlive this controller (the dev tools discard a whole
    // ProviderScope with requests still in flight), and a refusal arriving
    // after that has no session to end.
    if (!ref.mounted || state is! AuthSignedIn) return;
    state = AuthSignedOut(message: message);
    await _signOutLocally();
  }

  Future<void> _signOutLocally() async {
    // The in-memory token goes first, before anything is awaited: from here
    // on no request is sent with it, and no refusal of it is news.
    _api.token = null;
    await _tokens.clear();
  }

  /// Removes what an account leaves on the phone besides its token: an
  /// unfinished capture set (Documents/capture_draft), which the camera
  /// offers to whoever opens it next — to resume and upload into their own
  /// dealership — and the photographs the session was shown, cached in
  /// memory and on disk.
  ///
  /// Only for an account that has gone for good: signing out, or someone
  /// else signing in. A session the server ends keeps the draft, because
  /// the person it belongs to is about to sign straight back in to finish
  /// it. Neither step may fail the sign-out: a file that cannot be deleted
  /// is not a reason to leave anyone signed in.
  Future<void> _discardAccountData() async {
    await Future.wait([
      _quietly(clearCaptureDraft),
      _quietly(() => clearAuthedImageCache(ref)),
    ]);
  }
}

Future<void> _quietly(Future<void> Function() step) async {
  try {
    await step();
  } catch (_) {
    // See AuthController._discardAccountData.
  }
}
