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

import 'auth/auth_controller.dart';
import 'design/theme.dart';
import 'design/tokens.dart';
import 'design/typography.dart';
import 'features/change_password/change_password_screen.dart';
import 'features/listing_detail/listing_detail_screen.dart';
import 'features/listings/listings_screen.dart';
import 'features/sign_in/sign_in_screen.dart';
import 'routes.dart';
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
    initialLocation: AppRoutes.listings,
    refreshListenable: ref.watch(_routerRefreshProvider),
    routes: [
      GoRoute(
        path: AppRoutes.signIn,
        builder: (context, state) => const SignInScreen(),
      ),
      GoRoute(
        path: AppRoutes.changePassword,
        builder: (context, state) => const ChangePasswordScreen(),
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
            path: AppRoutes.listings,
            builder: (context, state) => const ListingsScreen(),
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
                return const _InvalidListingScreen();
              }
              return ListingDetailScreen(listingId: id);
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

        case AuthSignedIn(:final mustChangePassword):
          if (mustChangePassword) {
            return target == AppRoutes.changePassword
                ? null
                : AppRoutes.changePassword;
          }
          // A signed-in user with nothing left to do on sign-in or
          // change-password is sent to the listings screen; anywhere else
          // they were already headed is left alone.
          if (target == AppRoutes.signIn || target == AppRoutes.changePassword) {
            return AppRoutes.listings;
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
class _InvalidListingScreen extends StatelessWidget {
  const _InvalidListingScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Space.xl),
            child: Text(
              'That vehicle could not be found.',
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
      body: Center(
        child: CircularProgressIndicator(color: C.forest),
      ),
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
