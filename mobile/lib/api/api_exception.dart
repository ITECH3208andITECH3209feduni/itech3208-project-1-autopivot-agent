/// Failures the API layer can produce, as distinct types.
///
/// The distinction is not academic. The brief requires that a network blip and
/// an expired session produce different messages, and — more importantly — that
/// **only** an expired session signs the user out. Collapsing these into one
/// error type is how a user gets logged out because the backend restarted.
library;

sealed class ApiException implements Exception {
  const ApiException(this.message);

  /// Safe to show a user as-is: no status codes, no stack traces, no jargon.
  final String message;

  @override
  String toString() => '$runtimeType: $message';
}

/// The request never reached the server, or the reply never came back.
///
/// Explicitly *not* a reason to clear the stored token.
final class ApiNetworkException extends ApiException {
  const ApiNetworkException([
    super.message =
        'Could not reach AutoPivot. Check your connection and try again.',
  ]);
}

/// 401. The session is gone — expired, revoked, or the account deactivated.
///
/// This is the only failure that clears the token.
final class ApiUnauthorisedException extends ApiException {
  const ApiUnauthorisedException([
    super.message = 'Your session has ended. Please sign in again.',
  ]);
}

/// 401 from the sign-in endpoint specifically.
///
/// Deliberately one message for three causes — unknown email, wrong password,
/// deactivated account. The server returns an identical 401 for all three so
/// the endpoint cannot be used to discover which emails have accounts, and
/// the client must not undo that by guessing at the difference.
final class ApiInvalidCredentialsException extends ApiException {
  const ApiInvalidCredentialsException([
    super.message = 'That email and password do not match an account.',
  ]);
}

/// A 4xx the caller is expected to handle, carrying the server's own message.
///
/// The server writes these for people — "Your new password must be different
/// from your current one" — so they are shown rather than replaced.
final class ApiRequestException extends ApiException {
  const ApiRequestException(super.message, {required this.statusCode});

  final int statusCode;
}

/// 5xx, or a reply that could not be understood.
final class ApiServerException extends ApiException {
  const ApiServerException([
    super.message = 'AutoPivot had a problem. Please try again shortly.',
  ]);
}
