/// The dealership's home screen — its recent work, shown as work rather
/// than as numbers.
///
/// Ported from the web platform's `DashboardPage.tsx`, whose own doc
/// comment records why it looks like this rather than the three-stat-cards-
/// and-a-table shape an earlier version had: the question a dealer opens
/// the app with is "does what came out look good enough to publish", not
/// "how much volume have we run". So the vehicles lead, shown through their
/// own processed imagery — and only when there is nothing to show do the
/// counts get to speak on their own. The counts stay, but as a masthead
/// line, not the subject of the page.
///
/// [ListingsScreen] — the full, filterable list — used to be this app's
/// home; it now lives at [AppRoutes.vehicles], one tap away via "All
/// vehicles", the same relationship the web platform's own sidebar has
/// between "Overview" and "Vehicles".
library;

import 'dart:async' show unawaited;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../api/api_exception.dart';
import '../../api/models/dashboard_stats.dart';
import '../../api/models/listing_detail.dart';
import '../../api/models/listing_image.dart';
import '../../api/models/vehicle_listing.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../routes.dart';
import '../../widgets/authed_image.dart';
import '../../widgets/primitives.dart';
import '../../widgets/skeleton.dart';

/// Eight is enough to fill a phone screen without scrolling forever, and
/// each one costs a full listing-detail request just to find its hero
/// image — see [_DashboardScreenState._load] — so this is a bandwidth
/// choice as much as a layout one, the same reasoning the web page's own
/// `GALLERY_LIMIT` documents.
const _galleryLimit = 8;

/// "2 hours ago" / "Yesterday" / "3 days ago" — a straight port of the web
/// page's own `relativeTime`, so a dealer who uses both sees the same word
/// for the same span.
String _relativeTime(DateTime when) {
  final minutes = DateTime.now().difference(when).inMinutes.clamp(0, 1 << 31);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return '$minutes minute${minutes == 1 ? '' : 's'} ago';
  final hours = (minutes / 60).round();
  if (hours < 24) return '$hours hour${hours == 1 ? '' : 's'} ago';
  final days = (hours / 24).round();
  if (days == 1) return 'Yesterday';
  if (days < 30) return '$days days ago';
  final months = (days / 30).round();
  return '$months month${months == 1 ? '' : 's'} ago';
}

sealed class _Load {
  const _Load();
}

final class _Loading extends _Load {
  const _Loading();
}

final class _Loaded extends _Load {
  const _Loaded(this.stats, this.listings);
  final DashboardStats stats;
  final List<VehicleListing> listings;
}

final class _LoadFailed extends _Load {
  const _LoadFailed(this.message);
  final String message;
}

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  _Load _state = const _Loading();

  /// Absent (no key) means still fetching that listing's own detail; an
  /// explicit `null` value means the fetch finished and there is genuinely
  /// no photograph to show — the same distinction the web page's own
  /// `Record<number, Hero | null>` draws, and for the same reason: an
  /// unlabelled bone-coloured well reads as "loading" either way, so the
  /// difference only matters to this map, never to what gets painted.
  final Map<int, ListingImage?> _heroes = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Fetches from scratch, showing the loading skeleton first. Used on
  /// first build and after a failed load's retry, where there is nothing
  /// worth keeping on screen during the fetch.
  Future<void> _load() async {
    setState(() {
      _state = const _Loading();
      _heroes.clear();
    });
    await _fetch();
  }

  /// Re-fetches without the interim skeleton — what pull-to-refresh calls.
  /// [RefreshIndicator] already shows its own progress spinner while
  /// [onRefresh] is in flight, so swapping the whole page out for a
  /// full-screen skeleton mid-pull would be a second, competing loading
  /// affordance on top of content that was, a moment ago, perfectly good —
  /// the same reasoning `listings_screen.dart`'s own `_fetch` documents.
  Future<void> _fetch() async {
    final api = ref.read(apiClientProvider);
    try {
      final results = await Future.wait([
        api.dashboardStats(),
        api.listings(limit: _galleryLimit),
      ]);
      if (!mounted) return;
      final stats = results[0] as DashboardStats;
      final listings = results[1] as List<VehicleListing>;
      setState(() => _state = _Loaded(stats, listings));

      // GET /api/listings carries no imagery at all, only a count — the
      // only way to show a vehicle as a photograph is to ask for each
      // listing's own detail in turn, same as the web page does. Run in
      // parallel and bounded by _galleryLimit; one listing's detail
      // failing shows no picture for that card rather than taking the
      // whole gallery down with it.
      for (final listing in listings) {
        unawaited(_loadHero(api, listing.id));
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  /// One listing's own detail, purely to find a photograph for its card —
  /// a failure here (network, a listing deleted between the two requests)
  /// leaves that one card with no picture rather than failing the load.
  Future<void> _loadHero(ApiClient api, int listingId) async {
    VehicleListingDetail? detail;
    try {
      detail = await api.listing(listingId);
    } on ApiException {
      detail = null;
    }
    if (!mounted) return;
    setState(() => _heroes[listingId] = _heroFor(detail));
  }

  /// The processed result if one exists, else the original — matching the
  /// web page's own preference. Null either means the detail fetch failed
  /// (caught above) or the listing genuinely has no photographs yet.
  ListingImage? _heroFor(VehicleListingDetail? detail) {
    if (detail == null) return null;
    if (detail.processed.isNotEmpty) return detail.processed.first;
    if (detail.originals.isNotEmpty) return detail.originals.first;
    return null;
  }

  @override
  Widget build(BuildContext context) {
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
                  Space.lg,
                ),
                sliver: SliverToBoxAdapter(
                  child: Text('Overview', style: serif(32)),
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
    _Loading() => SliverPadding(
      padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.lg),
      sliver: SliverToBoxAdapter(child: _DashboardSkeleton()),
    ),
    _LoadFailed(:final message) => SliverFillRemaining(
      hasScrollBody: false,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(Space.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppErrorBanner(message),
              const SizedBox(height: Space.lg),
              FilledButton(onPressed: _load, child: const Text('Try again')),
            ],
          ),
        ),
      ),
    ),
    _Loaded(:final stats, :final listings) => SliverPadding(
      padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.xl),
      sliver: SliverToBoxAdapter(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _StatStrip(stats),
            const SizedBox(height: Space.xl),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Recent vehicles', style: T.label.copyWith(fontSize: 17)),
                if (listings.isNotEmpty)
                  TextButton(
                    onPressed: () => context.push(AppRoutes.vehicles),
                    child: const Text('All vehicles'),
                  ),
              ],
            ),
            const SizedBox(height: Space.sm),
            if (listings.isEmpty)
              const EmptyState(
                title: 'Nothing has been through the pipeline yet',
                body:
                    'Tap the camera button below to photograph your first '
                    'vehicle. Once it has been processed it appears here.',
              )
            else
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 220,
                  mainAxisSpacing: Space.md,
                  crossAxisSpacing: Space.md,
                  childAspectRatio: 0.78,
                ),
                itemCount: listings.length,
                itemBuilder: (context, index) {
                  final listing = listings[index];
                  return _VehicleCard(
                    listing: listing,
                    hero: _heroes[listing.id],
                    heroLoaded: _heroes.containsKey(listing.id),
                    onTap: () => context.push(
                      AppRoutes.listingDetailPath(listing.id),
                      extra: listing,
                    ),
                  );
                },
              ),
          ],
        ),
      ),
    ),
  };
}

class _StatStrip extends StatelessWidget {
  const _StatStrip(this.stats);

  final DashboardStats stats;

  @override
  Widget build(BuildContext context) {
    final items = [
      ('VEHICLES THIS MONTH', stats.vehiclesThisMonth, false),
      ('IMAGES PROCESSED', stats.imagesProcessed, false),
      ('NEEDS REVIEW', stats.needsReview, stats.needsReview > 0),
    ];

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < items.length; i++) ...[
          if (i > 0) const SizedBox(width: Space.lg),
          Expanded(
            child: Container(
              padding: const EdgeInsets.only(top: Space.sm),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: C.line)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(items[i].$1, style: T.caption),
                  const SizedBox(height: 4),
                  Text(
                    '${items[i].$2}',
                    style: T.label.copyWith(
                      fontSize: 20,
                      color: items[i].$3 ? C.rust : C.ink,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _VehicleCard extends StatelessWidget {
  const _VehicleCard({
    required this.listing,
    required this.hero,
    required this.heroLoaded,
    required this.onTap,
  });

  final VehicleListing listing;
  final ListingImage? hero;
  final bool heroLoaded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final processing = ProcessingState.parse(listing.processingStatus);
    final comparable = hero?.isProcessed == true;
    final photoLabel =
        '${listing.imageCount} photo${listing.imageCount == 1 ? '' : 's'}'
        '${hero == null ? '' : (comparable ? ' · processed' : ' · original')}'
        ' · ${_relativeTime(listing.createdAt)}';

    return Semantics(
      button: true,
      label: comparable
          ? '${listing.title}, before and after available'
          : listing.title,
      excludeSemantics: true,
      child: AppCard(
        padding: EdgeInsets.zero,
        child: Material(
          type: MaterialType.transparency,
          borderRadius: Radii.cardAll,
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AspectRatio(
                  aspectRatio: 4 / 3,
                  child: !heroLoaded
                      ? const ShimmerGroup(
                          child: SkeletonBox(borderRadius: BorderRadius.zero),
                        )
                      : hero == null
                      ? const DecoratedBox(
                          decoration: BoxDecoration(color: C.bone),
                          child: Center(
                            child: Text('No photograph', style: T.caption),
                          ),
                        )
                      : AuthedImage(
                          storagePath: hero!.imageUrl,
                          semanticLabel: comparable
                              ? '${listing.title}, processed'
                              : '${listing.title}, original photograph',
                          fit: BoxFit.cover,
                        ),
                ),
                Padding(
                  padding: const EdgeInsets.all(Space.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              listing.title,
                              style: T.label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          const SizedBox(width: Space.xs),
                          // Same tag listings_screen.dart's own row uses —
                          // this card is as valid a flight origin into the
                          // detail screen as that row is, and Hero simply
                          // does not animate when the destination's own tag
                          // cannot be matched, so there is no conflict in
                          // being the entry point either screen used.
                          Hero(
                            tag: 'listing-status-${listing.id}',
                            child: StatusPill(processing),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        photoLabel,
                        style: T.caption,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _DashboardSkeleton extends StatelessWidget {
  const _DashboardSkeleton();

  @override
  Widget build(BuildContext context) {
    return ShimmerGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              for (var i = 0; i < 3; i++) ...[
                if (i > 0) const SizedBox(width: Space.lg),
                const Expanded(child: SkeletonBox(height: 40)),
              ],
            ],
          ),
          const SizedBox(height: Space.xl),
          const SkeletonBox(height: 17, width: 140),
          const SizedBox(height: Space.md),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 220,
              mainAxisSpacing: Space.md,
              crossAxisSpacing: Space.md,
              childAspectRatio: 0.78,
            ),
            itemCount: 4,
            itemBuilder: (context, index) =>
                SkeletonBox(borderRadius: Radii.cardAll),
          ),
        ],
      ),
    );
  }
}
