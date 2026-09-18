/// The full, filterable vehicle list — reached from the dashboard
/// (`features/dashboard/dashboard_screen.dart`) via "All vehicles", at
/// [AppRoutes.vehicles]. Used to be this app's home screen at `/`; the
/// dashboard took that role over once it existed, the same relationship the
/// web platform's own "Overview" and "Vehicles" sidebar entries have.
///
/// A row opens the listing detail screen; swiping one left archives it —
/// see [_ArchiveConfirmDialog] — and the filter bar above the list narrows
/// it to one [ProcessingState] at a time.
///
/// Two axes matter for a listing and must not be conflated:
/// [VehicleListing] carries a sales `status` (draft, active, sold,
/// archived) and a separate `processingStatus` for where its photographs
/// are in the pipeline. The filter bar and [StatusPill] both work in terms
/// of the latter; the former only shows up here as the thing "archive"
/// changes, not as a filterable dimension of its own — that would need a
/// screen of its own to do properly, and showing half of it here would be
/// worse than showing neither.
///
/// [VehicleListing] also carries no image URL — only an `imageCount` — so
/// there is nothing to fetch a thumbnail from. Rows here stay text-only for
/// that reason; the dashboard's own gallery cards fetch each listing's full
/// detail to find a photograph, a cost this longer list deliberately does
/// not pay per row.
///
/// The dealership name and sign-out, both originally rendered here, now live
/// in `AppShell` instead — persistent chrome that wraps this screen and the
/// listing detail screen it leads to, rather than something each screen
/// inside that shell would otherwise have to repeat. This screen keeps only
/// what is specifically its own: the page title, the filter bar, and the
/// list.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_exception.dart';
import '../../api/models/vehicle_listing.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../routes.dart';
import '../../settings/app_preferences.dart';
import '../../widgets/primitives.dart';
import '../../widgets/skeleton.dart';

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

  /// Null means "every pipeline state" — the one filter option that is not
  /// itself a [ProcessingState] value, so it cannot be expressed as one.
  String? _statusFilter;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _setFilter(String? status) {
    if (status == _statusFilter) return;
    setState(() => _statusFilter = status);
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
      final listings = await api.listings(
        limit: 100,
        processingStatus: _statusFilter,
      );
      if (!mounted) return;
      setState(() => _state = _Loaded(listings));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  void _openListing(VehicleListing listing) =>
      context.push(AppRoutes.listingDetailPath(listing.id), extra: listing);

  /// Confirms, then archives, one vehicle — the [Dismissible] wrapping each
  /// row calls this as `confirmDismiss`, which is why it returns whether the
  /// swipe should actually complete rather than performing the archive and
  /// reporting nothing back. Returning `false` on either a decline or a
  /// failed request animates the row back into place instead of leaving a
  /// gap for a vehicle that, from the server's side, was never touched.
  Future<bool> _confirmArchive(VehicleListing listing) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => _ArchiveConfirmDialog(listing: listing),
    );
    if (confirmed != true || !mounted) return false;

    try {
      await ref
          .read(apiClientProvider)
          .updateListingStatus(listing.id, 'archived');
      haptic(ref, HapticFeedbackType.medium);
      return true;
    } on ApiException catch (e) {
      if (!mounted) return false;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
      return false;
    }
  }

  void _removeFromList(int listingId) {
    final current = _state;
    if (current is! _Loaded) return;
    setState(
      () => _state = _Loaded(
        current.listings.where((l) => l.id != listingId).toList(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _fetch,
          child: CustomScrollView(
            slivers: [
              const SliverPadding(
                padding: EdgeInsets.fromLTRB(
                  Space.lg,
                  Space.lg,
                  Space.lg,
                  Space.md,
                ),
                sliver: SliverToBoxAdapter(child: _Header()),
              ),
              SliverToBoxAdapter(
                child: _StatusFilterBar(
                  selected: _statusFilter,
                  onSelect: _setFilter,
                ),
              ),
              const SliverPadding(
                padding: EdgeInsets.only(top: Space.md),
                sliver: SliverToBoxAdapter(),
              ),
              _content(_state),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content(_Load state) => switch (state) {
    _Loading() => const SliverPadding(
      padding: EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.lg),
      sliver: SliverToBoxAdapter(child: _ListingsSkeleton()),
    ),
    _LoadFailed(:final message) => SliverFillRemaining(
      hasScrollBody: false,
      child: _RetryPanel(message: message, onRetry: _load),
    ),
    // A dealership genuinely starting with nothing is a real, valid state —
    // not an error — which is why this reaches EmptyState's honest wording
    // rather than the retry panel above. A filter that simply has no matches
    // is a different, equally real state from "no vehicles at all", and gets
    // its own wording rather than implying the dealership's inventory is
    // empty when it is only this one slice of it.
    _Loaded(:final listings) when listings.isEmpty => SliverFillRemaining(
      hasScrollBody: false,
      child: _statusFilter == null
          ? const EmptyState(
              title: 'No vehicles yet',
              body: 'Vehicles added to your dealership will appear here.',
            )
          : EmptyState(
              title:
                  'Nothing ${ProcessingState.parse(_statusFilter!).label.toLowerCase()}',
              body: 'No vehicles currently match this filter.',
            ),
    ),
    _Loaded(:final listings) => SliverPadding(
      padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.lg),
      sliver: SliverList(
        delegate: SliverChildBuilderDelegate((context, index) {
          final listing = listings[index];
          return Padding(
            padding: EdgeInsets.only(
              bottom: index == listings.length - 1 ? 0 : Space.md,
            ),
            child: Dismissible(
              key: ValueKey(listing.id),
              direction: DismissDirection.endToStart,
              confirmDismiss: (_) => _confirmArchive(listing),
              onDismissed: (_) => _removeFromList(listing.id),
              background: const _ArchiveBackground(),
              child: _ListingRow(
                listing: listing,
                onTap: () => _openListing(listing),
              ),
            ),
          );
        }, childCount: listings.length),
      ),
    ),
  };
}

/// The page title.
///
/// Not an [AppBar]: the brief calls for a serif display heading at 28px or
/// larger for the screen title, and `AppBarTheme` styles every app bar's
/// title in IBM Plex Sans for every other use in the app. A plain header
/// inside the scrollable body sidesteps that clash and scrolls away with the
/// rest of the content, which reads better on a small screen than a title
/// that stays pinned above an otherwise short list.
class _Header extends StatelessWidget {
  const _Header();

  @override
  Widget build(BuildContext context) {
    return Text('Vehicles', style: serif(32));
  }
}

/// Which pipeline state the list is narrowed to — a horizontally scrolling
/// row of pills rather than a dropdown, so switching filters is a single tap
/// and the current choice stays visible without opening anything.
class _StatusFilterBar extends StatelessWidget {
  const _StatusFilterBar({required this.selected, required this.onSelect});

  /// Null means "All".
  final String? selected;
  final ValueChanged<String?> onSelect;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 34,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: Space.lg),
        children: [
          _FilterChip(
            label: 'All',
            selected: selected == null,
            onTap: () => onSelect(null),
          ),
          for (final state in ProcessingState.values) ...[
            const SizedBox(width: Space.sm),
            _FilterChip(
              label: state.label,
              selected: selected == state.wireValue,
              onTap: () => onSelect(state.wireValue),
            ),
          ],
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      excludeSemantics: true,
      label: label,
      child: Material(
        color: selected ? C.forestTint : C.white,
        shape: RoundedRectangleBorder(
          borderRadius: Radii.controlAll,
          side: BorderSide(color: selected ? C.forest : C.line),
        ),
        child: InkWell(
          borderRadius: Radii.controlAll,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: Space.md,
              vertical: 6,
            ),
            child: Center(
              child: Text(
                label,
                style: T.label.copyWith(
                  fontSize: 13,
                  color: selected ? C.forest : C.inkSoft,
                ),
              ),
            ),
          ),
        ),
      ),
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

/// Placeholder rows shaped like [_ListingRow] itself, shown while the first
/// fetch is in flight. Five rows regardless of how many the dealership
/// actually has — nothing on screen yet says how many are coming, so this is
/// a guess at "a typical screenful", not a claim about the real count.
class _ListingsSkeleton extends StatelessWidget {
  const _ListingsSkeleton();

  @override
  Widget build(BuildContext context) {
    return ShimmerGroup(
      child: Column(
        children: [
          for (var i = 0; i < 5; i++) ...[
            const SkeletonCard(lines: [0.3]),
            if (i < 4) const SizedBox(height: Space.md),
          ],
        ],
      ),
    );
  }
}

/// One vehicle: its title, its pipeline status, its stock number if it has
/// one, and its image count. Opens the listing detail screen on tap — its
/// photographs, and the ability to remove one that turned out to be no good.
class _ListingRow extends StatelessWidget {
  const _ListingRow({required this.listing, required this.onTap});

  final VehicleListing listing;
  final VoidCallback onTap;

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
      button: true,
      container: true,
      excludeSemantics: true,
      label: semanticLabel,
      child: AppCard(
        // AppCard itself has no ink response — Material wraps it so the tap
        // reads as a tap rather than the whole card silently swallowing the
        // gesture with nothing to show for it.
        padding: EdgeInsets.zero,
        child: Material(
          type: MaterialType.transparency,
          borderRadius: Radii.cardAll,
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(Space.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: Text(listing.title, style: T.label)),
                      const SizedBox(width: Space.sm),
                      Hero(
                        tag: 'listing-status-${listing.id}',
                        child: StatusPill(processing),
                      ),
                    ],
                  ),
                  const SizedBox(height: Space.sm),
                  // Figures — anything countable — set in T.figure, matching
                  // how the rest of this codebase treats a stock number or a
                  // count.
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
          ),
        ),
      ),
    );
  }
}

// ── Swipe to archive ─────────────────────────────────────────────────────────

/// Revealed behind a row as it swipes left — the same rust used for every
/// other destructive-leaning action in this app (delete a photograph,
/// deactivate a teammate), even though archiving is not itself destructive:
/// there is no "unarchive" in this app yet, so from here it reads the same
/// as one-way.
class _ArchiveBackground extends StatelessWidget {
  const _ArchiveBackground();

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.centerRight,
      padding: const EdgeInsets.symmetric(horizontal: Space.lg),
      decoration: BoxDecoration(color: C.rustTint, borderRadius: Radii.cardAll),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.archive_outlined, size: 18, color: C.rust),
          const SizedBox(width: Space.xs),
          Text('Archive', style: T.label.copyWith(color: C.rust)),
        ],
      ),
    );
  }
}

/// Confirms before archiving — called from [Dismissible.confirmDismiss],
/// which is why declining has to leave the row exactly where it was rather
/// than treating "cancel" as "dismiss anyway".
class _ArchiveConfirmDialog extends StatelessWidget {
  const _ArchiveConfirmDialog({required this.listing});

  final VehicleListing listing;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: C.white,
      shape: const RoundedRectangleBorder(borderRadius: Radii.cardAll),
      child: Padding(
        padding: const EdgeInsets.all(Space.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Archive ${listing.title}?', style: serif(24)),
            const SizedBox(height: Space.sm),
            const Text(
              'It leaves this list. Photographs already processed are kept — '
              'this only changes where the vehicle sits in the sales cycle.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    child: const Text('Cancel'),
                  ),
                ),
                const SizedBox(width: Space.sm),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: C.rust,
                      minimumSize: const Size(0, 48),
                    ),
                    onPressed: () => Navigator.of(context).pop(true),
                    child: const Text('Archive'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
