/// Session state, and the only thing allowed to change it.
///
/// Riverpod rather than an InheritedWidget: the router has to read this to
/// decide a redirect, and screens have to read it to render — Riverpod reaches
/// both without a `BuildContext`, and the controller can be tested without
/// pumping a widget tree.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/models/user.dart';
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
  const AuthSignedIn(this.user);

  final User user;

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
  AuthState build() => const AuthChecking();

  ApiClient get _api => ref.read(apiClientProvider);
  TokenStore get _tokens => ref.read(tokenStoreProvider);

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
      state = AuthSignedIn(await _api.me());
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

  Future<void> signIn({
    required String email,
    required String password,
  }) async {
    final result = await _api.login(email: email.trim(), password: password);
    await _tokens.write(result.accessToken);
    _api.token = result.accessToken;
    state = AuthSignedIn(result.user);
  }

  /// Rotate the password on a provisioned account.
  ///
  /// The server enforces a 12 character minimum and rejects reusing the current
  /// password; both come back as a message worth showing.
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final user = await _api.changePassword(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    state = AuthSignedIn(user);
  }

  Future<void> signOut() async {
    await _signOutLocally();
    state = const AuthSignedOut();
  }

  /// Called when any request comes back 401 mid-session.
  Future<void> sessionExpired(String message) async {
    await _signOutLocally();
    state = AuthSignedOut(message: message);
  }

  Future<void> _signOutLocally() async {
    await _tokens.clear();
    _api.token = null;
  }
}
