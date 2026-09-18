/// The app shell: theme, routing, and the redirect logic that keeps every
/// screen behind the right gate.
///
/// This is the one file that is allowed to know about every screen at once —
/// each screen itself only knows how to do its own job and calls the auth
/// controller when it is done; nothing in `features/` navigates directly. That
/// split is deliberate: three people can build three screens in parallel
/// against a fixed [AuthState] contract without ever touching this file or
/// each other's, and the redirect rules that connect them exist in exactly
/// one place instead of being reconstructed by each screen from its own
/// assumptions about what should happen next.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'api/models/vehicle_listing.dart';
import 'auth/auth_controller.dart';
import 'design/theme.dart';
import 'design/tokens.dart';
import 'design/typography.dart';
import 'features/change_password/change_password_screen.dart';
import 'features/dashboard/dashboard_screen.dart';
import 'features/listing_detail/listing_detail_screen.dart';
import 'features/listings/listings_screen.dart';
import 'features/settings/about_screen.dart';
import 'features/settings/app_settings_screen.dart';
import 'features/settings/demo_screen.dart';
import 'features/settings/dealerships_screen.dart';
import 'features/settings/team_screen.dart';
import 'features/settings/welcome_tour_screen.dart';
import 'features/sign_in/sign_in_screen.dart';
import 'routes.dart';
import 'settings/app_lock.dart';
import 'widgets/app_shell.dart';

/// Rebuilds the router's redirect decision whenever [AuthState] changes.
///
/// go_router only re-evaluates `redirect` on navigation or when the
/// `refreshListenable` it was given fires — without this, a sign-in
/// completing in the background would settle the provider into
/// [AuthSignedIn] and nothing would ever act on it, leaving the user stranded
/// on the sign-in screen with a state that says they are already in.
class _RouterRefreshListenable extends ChangeNotifier {
  _RouterRefreshListenable(Ref ref) {
    ref.listen<AuthState>(authProvider, (_, _) => notifyListeners());
  }
}

final _routerRefreshProvider = Provider<_RouterRefreshListenable>((ref) {
  final listenable = _RouterRefreshListenable(ref);
  ref.onDispose(listenable.dispose);
  return listenable;
});

final _routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: AppRoutes.home,
    refreshListenable: ref.watch(_routerRefreshProvider),
    routes: [
      GoRoute(
        path: AppRoutes.signIn,
        builder: (context, state) => const SignInScreen(),
      ),
      GoRoute(
        path: AppRoutes.changePassword,
        builder: (context, state) =>
            const ChangePasswordScreen(dismissible: false),
      ),
      // Outside the shell deliberately: this is a drill-down from the
      // account sheet's Team row, not part of the shell's own navigation,
      // and a team roster has no business under a floating camera action.
      // Unlike AppRoutes.dealerships below, this is never anyone's home
      // screen — a dealership_admin's home is still the dashboard — so it
      // has no need of the shell's header either. Any signed-in user can
      // reach the route itself — the actual gate is that nothing links here
      // for anyone but a dealership_admin (app_shell.dart), and every
      // request the screen makes is independently re-checked server-side
      // regardless.
      GoRoute(
        path: AppRoutes.team,
        builder: (context, state) => const TeamScreen(),
      ),
      // Every role reaches this one, unlike the two rows above — it is app
      // preferences, not administration, so who is signed in decides
      // nothing about whether the row is offered.
      GoRoute(
        path: AppRoutes.settings,
        builder: (context, state) => const AppSettingsScreen(),
      ),
      // A drill-down from Settings' own Help section, outside the shell for
      // the same reason AppRoutes.team is: it has its own back button and
      // ends by pushing into the shelled listing-detail route itself, not
      // by returning here.
      GoRoute(
        path: AppRoutes.demo,
        builder: (context, state) => const DemoScreen(),
      ),
      // Outside the shell alongside the two above: its own back button, and
      // nothing about reporting a build number wants a camera action
      // floating over it.
      GoRoute(
        path: AppRoutes.about,
        builder: (context, state) => const AboutScreen(),
      ),
      // Same screen as AppRoutes.changePassword, different mode and a
      // different path — see that route constant's own doc comment for why
      // it cannot be the same path.
      GoRoute(
        path: AppRoutes.settingsChangePassword,
        builder: (context, state) =>
            const ChangePasswordScreen(dismissible: true),
      ),
      // A drill-down from AppRoutes.dealerships, not Settings directly — see
      // that route's own doc comment. The dealership's name rides along as
      // `extra` rather than a query parameter purely so the header can show
      // it immediately, before the team list itself has loaded; the id in
      // the path is what every request actually uses. Outside the shell for
      // the same reason AppRoutes.team is: it has its own back button, and
      // nothing here needs the header or the (already hidden, for this
      // role) camera action.
      GoRoute(
        path: AppRoutes.dealershipTeam,
        builder: (context, state) {
          final id = int.tryParse(state.pathParameters['id'] ?? '');
          if (id == null) {
            return const _InvalidRouteScreen(
              message: 'That dealership could not be found.',
            );
          }
          return TeamScreen(
            dealershipId: id,
            dealershipName: state.extra as String?,
          );
        },
      ),
      // Everything a signed-in user with nothing forced on them can reach
      // shares one persistent shell — the dealership name and the camera
      // action stay mounted and keep their own state while only the content
      // beneath changes. Sign-in and the forced password change are
      // deliberately outside this: neither should show a way to sign out of
      // a screen the user cannot leave, or a camera button that goes
      // anywhere before they are actually in.
      ShellRoute(
        builder: (context, state, child) => AppShell(child: child),
        routes: [
          GoRoute(
            path: AppRoutes.home,
            builder: (context, state) => const DashboardScreen(),
          ),
          GoRoute(
            path: AppRoutes.vehicles,
            builder: (context, state) => const ListingsScreen(),
          ),
          // Unlike AppRoutes.team, this one IS inside the shell: it is
          // platform_admin's home screen (see the redirect below), not only
          // a Settings drill-down, so it needs the header for account access
          // and sign-out the same as the dashboard does for every other
          // role. app_shell.dart already hides the camera FAB for this role.
          GoRoute(
            path: AppRoutes.dealerships,
            builder: (context, state) => const DealershipsScreen(),
          ),
          GoRoute(
            path: AppRoutes.listingDetail,
            builder: (context, state) {
              final id = int.tryParse(state.pathParameters['id'] ?? '');
              // A malformed or missing id cannot build the real screen —
              // this is what a hand-typed or stale URL produces, not a
              // real navigation from within the app, since every real
              // navigation goes through AppRoutes.listingDetailPath with a
              // genuine int.
              if (id == null) {
                return const _InvalidRouteScreen(
                  message: 'That vehicle could not be found.',
                );
              }
              return ListingDetailScreen(
                listingId: id,
                preview: state.extra is VehicleListing
                    ? state.extra as VehicleListing
                    : null,
              );
            },
          ),
        ],
      ),
    ],

    // The single place every redirect rule lives. Each screen calls the auth
    // controller and stops; this is what turns that state change into
    // movement, so the three screens never need to know about each other or
    // call a navigation method themselves.
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final target = state.matchedLocation;

      switch (auth) {
        case AuthChecking():
        case AuthUnavailable():
          // Neither state says the session is good or bad — [AuthChecking]
          // has not asked the server yet, and [AuthUnavailable] asked and
          // could not reach it. Staying on the current route (handled by
          // _AuthGate below, not by a redirect target) is correct in both:
          // sending an [AuthUnavailable] user to sign-in would discard a
          // token that has not actually been shown to be invalid, which is
          // the exact mistake the brief calls out — a network blip must not
          // sign anyone out.
          return null;

        case AuthSignedOut():
          return target == AppRoutes.signIn ? null : AppRoutes.signIn;

        case AuthSignedIn(:final mustChangePassword, :final user):
          if (mustChangePassword) {
            return target == AppRoutes.changePassword
                ? null
                : AppRoutes.changePassword;
          }
          // A platform administrator belongs to no dealership, so the
          // dashboard — every other role's home screen — has nothing in it
          // for them and its own API calls refuse them outright
          // (`_dealership_id` in routes_dashboard.py / routes_listings.py).
          // Dealerships is the equivalent home screen for that role instead,
          // the same swap app_shell.dart's own nav already makes.
          if (target == AppRoutes.home && user.role == 'platform_admin') {
            return AppRoutes.dealerships;
          }
          // A signed-in user with nothing left to do on sign-in or
          // change-password is sent to their home screen; anywhere else
          // they were already headed is left alone.
          if (target == AppRoutes.signIn ||
              target == AppRoutes.changePassword) {
            return user.role == 'platform_admin'
                ? AppRoutes.dealerships
                : AppRoutes.home;
          }
          return null;
      }
    },
  );
});

class AutoPivotApp extends ConsumerWidget {
  const AutoPivotApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(_routerProvider);

    return MaterialApp.router(
      title: 'AutoPivot',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      routerConfig: router,
      // AuthChecking and AuthUnavailable have no route of their own — the
      // redirect above deliberately returns null for both, because the
      // correct route depends on which screen the user was already looking
      // at (or the initial one) rather than on a fixed destination. This
      // builder sits above the routed content and swaps in a splash or a
      // retry panel while either state holds, without moving the URL.
      builder: (context, child) {
        final auth = ref.watch(authProvider);
        return switch (auth) {
          AuthChecking() => const _SplashScreen(),
          AuthUnavailable(:final message) => _UnavailableScreen(
            message: message,
          ),
          // Only a signed-in session has anything a lock screen is
          // protecting — AuthSignedOut falls through to the sign-in screen
          // itself below, which needs no gate of its own. The welcome tour
          // sits inside the lock, not outside it: a locked phone has no
          // business showing anything about how to use the app yet, and
          // only shows itself at all once mustChangePassword is behind
          // them — a screen they cannot leave is not the moment for it.
          AuthSignedIn(:final mustChangePassword) => AppLockGate(
            child: mustChangePassword
                ? (child ?? const SizedBox.shrink())
                : WelcomeTourGate(child: child ?? const SizedBox.shrink()),
          ),
          _ => child ?? const SizedBox.shrink(),
        };
      },
    );
  }
}

/// A `/listings/{id}` reached with an id that will not parse as an int — a
/// hand-typed or stale URL, since every real navigation in this app goes
/// through `AppRoutes.listingDetailPath`, which only ever builds one from a
/// genuine int.
/// Shown for a hand-typed or stale URL whose id parameter will not parse as
/// an int — every real navigation in this app builds its path from a genuine
/// int (`AppRoutes.listingDetailPath`, `AppRoutes.dealershipTeamPath`), so
/// this is what reaching one some other way produces.
class _InvalidRouteScreen extends StatelessWidget {
  const _InvalidRouteScreen({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Space.xl),
            child: Text(
              message,
              style: T.bodySmall,
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }
}

/// Shown once, at cold start, while the stored token is being validated
/// against `/auth/me`.
///
/// Without this the app would render the sign-in screen for one frame before
/// the check comes back, which the brief specifically calls out: a signed-in
/// user must not see a flash of the sign-in screen on every cold start.
class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: C.paper,
      body: Center(child: CircularProgressIndicator(color: C.forest)),
    );
  }
}

/// Shown when a stored token exists but could not be checked because the
/// server was unreachable.
///
/// Deliberately not the sign-in screen: the token has not been shown to be
/// invalid, only unconfirmed, so offering "sign in again" here would suggest
/// the session is gone when it may well still be good. A retry re-runs the
/// same check; if it keeps failing the person is looking at a real outage,
/// which the message says plainly rather than implying anything about their
/// credentials.
class _UnavailableScreen extends ConsumerWidget {
  const _UnavailableScreen({required this.message});

  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Space.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'AutoPivot is unreachable',
                  style: serif(24),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: Space.sm),
                Text(message, style: T.bodySmall, textAlign: TextAlign.center),
                const SizedBox(height: Space.lg),
                FilledButton(
                  onPressed: () => ref.read(authProvider.notifier).restore(),
                  child: const Text('Try again'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
