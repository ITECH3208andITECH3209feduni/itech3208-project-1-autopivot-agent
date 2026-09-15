/// Route paths, in one place.
///
/// `app.dart` registers these with go_router; anywhere else that needs to
/// navigate to one — `listings_screen.dart`, tapping a row — imports this
/// rather than typing the path as a string literal a second time. Dart
/// privacy is per-file, so `app.dart`'s own route constants could not have
/// been reused directly even if they were not already private on purpose;
/// this file is what two files agreeing on a path actually looks like.
library;

abstract final class AppRoutes {
  static const signIn = '/sign-in';
  static const changePassword = '/change-password';
  static const listings = '/';
  static const listingDetail = '/listings/:id';

  /// The dealership's own team — reached from the account sheet's Settings
  /// row, and only ever offered there to a `dealership_admin` (see
  /// `app_shell.dart`). Outside the shell route deliberately: this is a
  /// drill-down from Settings, not part of the shell's own navigation, and
  /// the camera FAB has no business floating over a team roster.
  static const team = '/team';

  /// Every dealership on the platform — the same Settings row as [team]
  /// above, but offered instead of it to a `platform_admin`, who has no
  /// team of their own to manage (they belong to no dealership at all).
  static const dealerships = '/dealerships';

  static String listingDetailPath(int id) => '/listings/$id';
}
