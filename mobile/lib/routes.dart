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

  /// The dealership's home screen — an overview (this month's figures,
  /// recent vehicles with their own processed imagery), not the full list.
  /// See `features/dashboard/dashboard_screen.dart`'s own doc comment for
  /// why this changed from being the full list itself.
  static const home = '/';

  /// The full, filterable vehicle list — one tap from [home] via "All
  /// vehicles", the same relationship the web platform's sidebar draws
  /// between its own "Overview" and "Vehicles".
  static const vehicles = '/vehicles';

  static const listingDetail = '/listings/:id';

  /// The dealership's own team — reached from the account sheet's Team row,
  /// and only ever offered there to a `dealership_admin` (see
  /// `app_shell.dart`). Outside the shell route deliberately: this is a
  /// drill-down from the account sheet, not part of the shell's own
  /// navigation, and the camera FAB has no business floating over a team
  /// roster.
  static const team = '/team';

  /// Every dealership on the platform — the same account-sheet row as
  /// [team] above (there labelled "Dealerships" rather than "Team"), but
  /// offered instead of it to a `platform_admin`, who has no team of their
  /// own to manage (they belong to no dealership at all).
  static const dealerships = '/dealerships';

  /// One dealership's team, as a `platform_admin` sees it — reached by
  /// tapping a row on [dealerships], not from the account sheet directly.
  /// Distinct from [team]: that path always means "my own dealership" and
  /// takes no id, this one is always about a dealership the caller does not
  /// belong to, which is why it needs one.
  static const dealershipTeam = '/dealerships/:id/team';

  /// App preferences — biometric lock, haptics, the welcome tour. Reached
  /// from the account sheet's own Settings row, which is what that row
  /// actually means here; [team] and [dealerships] are administration, a
  /// different thing this app happened to also reach from the same sheet.
  static const settings = '/settings';

  /// The real-pipeline walkthrough with a bundled sample photograph — a
  /// Settings row every role gets, same as [settings] itself.
  static const demo = '/settings/demo';

  /// A voluntary password change, reached from Settings — distinct from
  /// [changePassword] above, which the router forces on anyone whose
  /// account still carries a temporary one. Sharing that path would have
  /// the redirect in `app.dart` bounce a voluntary visit straight back out,
  /// since `mustChangePassword` is already false for anyone who can reach
  /// Settings at all.
  static const settingsChangePassword = '/settings/change-password';

  static String listingDetailPath(int id) => '/listings/$id';

  static String dealershipTeamPath(int id) => '/dealerships/$id/team';
}
