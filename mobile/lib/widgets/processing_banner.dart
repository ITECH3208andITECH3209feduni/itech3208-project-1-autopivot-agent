/// A slim, dismissable-by-nature banner in [AppShell]'s chrome: "N vehicles
/// processing…", visible from every screen inside the shell, not only the
/// one you happened to submit a set from.
///
/// `listing_detail_screen.dart` already polls for progress, but only while
/// that specific listing's detail screen is the one on screen — leave it for
/// the vehicles list or a second listing and that polling, and the reason to
/// keep checking back, both stop. This is the app-wide version of the same
/// idea: a background administrator doesn't watch a spinner, they get on
/// with something else and this tells them when there is still something
/// to come back for.
///
/// Deliberately not a push notification. A real "tell me even after I've
/// closed the app" needs a server that can wake a suspended app — APNs on
/// iOS, FCM on Android — which this backend does not send yet. A
/// `Timer.periodic` like this one only ever runs while the process is alive,
/// which is an honest, smaller promise: the same one this banner keeps.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_exception.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/typography.dart';
import '../routes.dart';

class ProcessingBanner extends ConsumerStatefulWidget {
  const ProcessingBanner({super.key});

  @override
  ConsumerState<ProcessingBanner> createState() => _ProcessingBannerState();
}

class _ProcessingBannerState extends ConsumerState<ProcessingBanner> {
  Timer? _timer;

  /// Null until the first check completes — nothing renders in that gap
  /// rather than a banner flashing in and straight back out on every cold
  /// start.
  int? _count;

  @override
  void initState() {
    super.initState();
    // A platform administrator belongs to no dealership — the endpoints
    // this polls would just 403 every 25 seconds for that role, for a
    // banner that could never have anything to say to them anyway.
    if (ref.read(currentUserProvider)?.role != 'platform_admin') {
      _poll();
      _timer = Timer.periodic(const Duration(seconds: 25), (_) => _poll());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    final api = ref.read(apiClientProvider);
    try {
      // 'processing' only. A listing still 'pending' has never had anything
      // queued (the server's word for no jobs at all, not jobs waiting), so
      // counting it announced vehicles "still processing" that nothing was
      // working on — for good, on a server without the vision stack, which
      // refuses to queue anything.
      final processing = await api.listings(
        processingStatus: 'processing',
        limit: 50,
      );
      if (!mounted) return;
      setState(() => _count = processing.length);
    } on ApiException {
      // A failed background check is not worth surfacing — the banner
      // simply keeps whatever it last knew, or stays absent if it has never
      // learned anything yet. The screen it sits above has its own, louder
      // way to report a real problem.
    }
  }

  @override
  Widget build(BuildContext context) {
    final count = _count;
    if (count == null || count == 0) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.fromLTRB(Space.lg, Space.sm, Space.lg, 0),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: Radii.controlAll,
          // The full vehicle list, not the dashboard's own abbreviated
          // "recent" gallery — this banner exists to let someone track down
          // exactly what is still processing, which the unfiltered list
          // shows in full. Pushed over wherever this was tapped, not go()'s
          // replacing everything beneath it: the list is nobody's home
          // screen, and with the Overview gone from under it there was no
          // way back. Not pushed again over itself, though.
          onTap: () {
            final router = GoRouter.of(context);
            if (router.state.uri.path == AppRoutes.vehicles) return;
            router.push(AppRoutes.vehicles);
          },
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(
              horizontal: Space.md,
              vertical: Space.sm,
            ),
            decoration: BoxDecoration(
              color: C.amberTint,
              borderRadius: Radii.controlAll,
            ),
            child: Row(
              children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: C.amberText,
                  ),
                ),
                const SizedBox(width: Space.sm),
                Expanded(
                  child: Text(
                    '$count vehicle${count == 1 ? '' : 's'} still processing',
                    style: T.bodySmall.copyWith(color: C.amberText),
                  ),
                ),
                const Icon(Icons.chevron_right, size: 16, color: C.amberText),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
