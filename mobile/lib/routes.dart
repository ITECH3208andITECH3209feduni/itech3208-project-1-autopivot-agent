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

  static String listingDetailPath(int id) => '/listings/$id';
}
