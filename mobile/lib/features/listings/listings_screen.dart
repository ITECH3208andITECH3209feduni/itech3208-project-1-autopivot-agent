/// The vehicle listings screen — the home screen a signed-in dealership user
/// lands on.
///
/// This sprint's story is "see your dealership's vehicles" and nothing more:
/// no creating a listing, no opening a detail view, no camera capture. Those
/// are separate, later stories, so a row here is informational only and
/// carries no tap target — adding one now would promise a screen that does
/// not exist yet.
///
/// Two axes matter for a listing and must not be conflated: [VehicleListing]
/// carries a sales `status` (draft, active, sold, archived) and a separate
/// `processingStatus` for where its photographs are in the pipeline. This
/// screen shows only the latter, via [StatusPill], because the pipeline is
/// what this sprint's story is about; the sales status has no screen of its
/// own yet and showing half of it here would be worse than showing neither.
///
/// [VehicleListing] also carries no image URL — only an `imageCount` — so
/// there is nothing to fetch a thumbnail from. [AuthedImage] exists for the
/// capture story this app grows into next, not for this screen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models/vehicle_listing.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/primitives.dart';

/// What the screen currently has to show.
///
/// A sealed hierarchy rather than a loading flag plus a nullable list and a
/// nullable error message, because the three are mutually exclusive and the
/// compiler should be the thing enforcing that — the same reasoning behind
/// `AuthState` in `auth_controller.dart`.
sealed class _Load {
  const _Load();
}

final class _Loading extends _Load {
  const _Loading();
}

final class _Loaded extends _Load {
  const _Loaded(this.listings);
  final List<VehicleListing> listings;
}

final class _LoadFailed extends _Load {
  const _LoadFailed(this.message);

  /// Already safe to show a user as-is — see [ApiException.message].
  final String message;
}

class ListingsScreen extends ConsumerStatefulWidget {
  const ListingsScreen({super.key});

  @override
  ConsumerState<ListingsScreen> createState() => _ListingsScreenState();
}

class _ListingsScreenState extends ConsumerState<ListingsScreen> {
  _Load _state = const _Loading();

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Fetches from scratch, showing the loading indicator first.
  ///
  /// Used on first build and after a failed load's retry. In both cases there
  /// is no list on screen yet — an empty list mid-fetch would look exactly
  /// like a dealership that genuinely has no vehicles, which is why the two
  /// states are kept distinct in [_Load] rather than inferred from an empty
  /// list plus a loading flag.
  Future<void> _load() async {
    setState(() => _state = const _Loading());
    await _fetch();
  }

  /// Re-fetches without an interim loading state.
  ///
  /// Used for pull-to-refresh: [RefreshIndicator] already shows its own
  /// progress spinner while [onRefresh] is in flight, so swapping the list
  /// out for a full-screen spinner mid-pull would just be a second, competing
  /// loading affordance.
  Future<void> _fetch() async {
    final api = ref.read(apiClientProvider);
    try {
      // The limit is explicit and set to the client's own default on purpose:
      // the server itself defaults to 20, so leaving this out would silently
      // truncate a larger dealership's inventory to that, with nothing on
      // screen to say the list was cut short.
      final listings = await api.listings(limit: 100);
      if (!mounted) return;
      setState(() => _state = _Loaded(listings));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  Future<void> _signOut() => ref.read(authProvider.notifier).signOut();

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(currentUserProvider);
    final dealershipName = user?.dealership?.name ?? 'AutoPivot';

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _fetch,
          child: CustomScrollView(
            slivers: [
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(
                  Space.lg,
                  Space.lg,
                  Space.lg,
                  Space.md,
                ),
                sliver: SliverToBoxAdapter(
                  child: _Header(
                    dealershipName: dealershipName,
                    onSignOut: _signOut,
                  ),
                ),
              ),
              _content(_state),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content(_Load state) => switch (state) {
    _Loading() => const SliverFillRemaining(
      hasScrollBody: false,
      child: Center(child: CircularProgressIndicator()),
    ),
    _LoadFailed(:final message) => SliverFillRemaining(
      hasScrollBody: false,
      child: _RetryPanel(message: message, onRetry: _load),
    ),
    // A dealership genuinely starting with nothing is a real, valid state —
    // not an error — which is why this reaches EmptyState's honest wording
    // rather than the retry panel above.
    _Loaded(:final listings) when listings.isEmpty => const SliverFillRemaining(
      hasScrollBody: false,
      child: EmptyState(
        title: 'No vehicles yet',
        body: 'Vehicles added to your dealership will appear here.',
      ),
    ),
    _Loaded(:final listings) => SliverPadding(
      padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.lg),
      sliver: SliverList(
        delegate: SliverChildBuilderDelegate(
          (context, index) => Padding(
            padding: EdgeInsets.only(
              bottom: index == listings.length - 1 ? 0 : Space.md,
            ),
            child: _ListingRow(listing: listings[index]),
          ),
          childCount: listings.length,
        ),
      ),
    ),
  };
}

/// The dealership's name and a way to sign out.
///
/// Not an [AppBar]: the brief calls for a serif display heading at 28px or
/// larger for the screen title, and `AppBarTheme` styles every app bar's
/// title in IBM Plex Sans for every other use in the app. A plain header
/// inside the scrollable body sidesteps that clash and scrolls away with the
/// rest of the content, which reads better on a small screen than a title
/// that stays pinned above an otherwise short list.
class _Header extends StatelessWidget {
  const _Header({required this.dealershipName, required this.onSignOut});

  final String dealershipName;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(dealershipName, style: T.label),
              const SizedBox(height: Space.xs),
              Text('Vehicles', style: serif(32)),
            ],
          ),
        ),
        // Icon-only, so the tooltip carries the accessible name — Flutter
        // surfaces an IconButton's tooltip as its semantic label, which is
        // what a screen reader announces in place of the bare icon.
        IconButton(
          onPressed: onSignOut,
          icon: const Icon(Icons.logout, color: C.inkSoft),
          tooltip: 'Sign out',
        ),
      ],
    );
  }
}

/// Shown after a failed fetch: the exception's own message, already safe to
/// display per [ApiException], plus a way to try again rather than leaving
/// the screen blank.
class _RetryPanel extends StatelessWidget {
  const _RetryPanel({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppErrorBanner(message),
            const SizedBox(height: Space.lg),
            // The button's own visible text is its accessible name, so no
            // separate Semantics label is needed to satisfy "a clear label".
            FilledButton(onPressed: onRetry, child: const Text('Try again')),
          ],
        ),
      ),
    );
  }
}

/// One vehicle: its title, its pipeline status, its stock number if it has
/// one, and its image count. Presentational only — this sprint has nowhere
/// for a tap on the row to go, so it carries no gesture handler.
class _ListingRow extends StatelessWidget {
  const _ListingRow({required this.listing});

  final VehicleListing listing;

  @override
  Widget build(BuildContext context) {
    final processing = ProcessingState.parse(listing.processingStatus);
    final stockNumber = listing.stockNumber;
    final hasStockNumber = stockNumber != null && stockNumber.isNotEmpty;
    final photoLabel =
        '${listing.imageCount} photo${listing.imageCount == 1 ? '' : 's'}';

    // One semantic unit rather than several unlabelled fragments: a screen
    // reader lands on the row once and hears the title, its pipeline status,
    // the stock number when there is one, and the photo count together, in
    // that order, instead of four separate unlabelled swipes.
    final semanticLabel = [
      listing.title,
      processing.label,
      if (hasStockNumber) 'stock number $stockNumber',
      photoLabel,
    ].join(', ');

    return Semantics(
      container: true,
      excludeSemantics: true,
      label: semanticLabel,
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: Text(listing.title, style: T.label)),
                const SizedBox(width: Space.sm),
                StatusPill(processing),
              ],
            ),
            const SizedBox(height: Space.sm),
            // Figures — anything countable — set in T.figure, matching how
            // the rest of this codebase treats a stock number or a count.
            Row(
              children: [
                if (hasStockNumber) ...[
                  Text('#$stockNumber', style: T.figure),
                  const SizedBox(width: Space.sm),
                  const Text('·', style: T.bodySmall),
                  const SizedBox(width: Space.sm),
                ],
                Text(photoLabel, style: T.figure),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
