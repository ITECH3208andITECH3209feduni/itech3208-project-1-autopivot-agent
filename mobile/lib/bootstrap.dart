/// Runs [AuthController.restore] exactly once before showing [child].
///
/// Pulled out of `main.dart` rather than kept private there, because the dev
/// tools' "connect to a real backend" flow (`dev/dev_tools_app.dart`) needs
/// the same guarantee: a fresh [ProviderScope] pointed at a chosen base URL
/// still has to validate whatever token is in secure storage against
/// `/auth/me` before the router is allowed to decide anything, exactly as the
/// real app does at cold start. Two copies of this widget would be two places
/// that guarantee could quietly stop matching.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth/auth_controller.dart';

class AppBootstrap extends ConsumerStatefulWidget {
  const AppBootstrap({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<AppBootstrap> createState() => _AppBootstrapState();
}

class _AppBootstrapState extends ConsumerState<AppBootstrap> {
  @override
  void initState() {
    super.initState();
    // initState, not build: it is Flutter's own guarantee of "runs once for
    // the life of this element". A call sitting in build has no such
    // guarantee and would fire again on any rebuild the framework decides to
    // run for unrelated reasons — and AuthController.restore is what decides
    // whether the very first frame is even allowed to show the sign-in
    // screen, so double-firing it, or missing the one guaranteed call, is not
    // safe to risk.
    ref.read(authProvider.notifier).restore();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
