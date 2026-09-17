/// The listing detail screen: one vehicle, every photograph attached to it,
/// and the means to remove one that turned out not to be usable.
///
/// This is the detail view [ListingsScreen]'s rows point at, reached with a
/// numeric listing id parsed from the route. It owns its own [Scaffold] and
/// its own way back — the router that wires this screen in cannot see this
/// file, so nothing here may assume it is hosted inside somebody else's
/// [AppBar] or navigation chrome.
///
/// [VehicleListingDetail.images] mixes originals, processed results and a
/// couple of pipeline-internal image types together; [ListingImage.isOriginal]
/// and [ListingImage.isProcessed] are what separate them, and
/// [ListingImage.isExcluded] is what marks an original the classifier decided
/// was not a photograph of the vehicle's exterior — an advertisement, an
/// interior shot, a close-up. A dealer looking at their own listing needs to
/// know *why* a photograph was left out, not just that it was, so every
/// excluded original carries a full-sentence reason rather than the raw
/// `imageKind` string — see [_exclusionReason], which mirrors the equivalent
/// wording in `_NOT_A_VEHICLE_PHOTO` in `autopivot_backend.py` deliberately,
/// so a dealer sees the same explanation on the phone as anywhere else in the
/// product.
///
/// A photograph the pipeline ran but found no vehicle in is a different
/// thing again from an excluded one: nothing about the *image* explains it
/// (`imageKind` may be null, or even 'exterior' if the classifier agreed but
/// detection still failed), because the explanation lives on the *job* —
/// [ProcessingJobSummary.reviewState] and `.errorMessage`, fetched
/// separately via `/jobs` and correlated back to each original by
/// `inputImageId`. Without that correlation this screen cannot tell "still
/// queued" apart from "ran and gave up", and both used to sit in the same
/// unexplained "awaiting processing" bucket — see `_loadedBody`'s
/// `needsReviewOriginals` split and [_NeedsReviewTile].
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models/listing_detail.dart';
import '../../api/models/listing_image.dart';
import '../../api/models/processing_summary.dart';
import '../../api/models/vehicle_listing.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/authed_image.dart';
import '../../widgets/primitives.dart';
import '../../widgets/skeleton.dart';

// ── Load state ──────────────────────────────────────────────────────────────

/// What the screen currently has to show.
///
/// A sealed hierarchy rather than a loading flag plus a nullable listing and a
/// nullable error message, for the same reason `_Load` exists in
/// `listings_screen.dart`: the three states are mutually exclusive, and the
/// compiler — not a runtime assumption about which fields happen to be set —
/// should be the thing enforcing that.
sealed class _Load {
  const _Load();
}

final class _Loading extends _Load {
  const _Loading();
}

final class _Loaded extends _Load {
  const _Loaded(this.listing);
  final VehicleListingDetail listing;
}

final class _LoadFailed extends _Load {
  const _LoadFailed(this.message);

  /// Already safe to show a user as-is — see [ApiException.message].
  final String message;
}

// ── Exclusion reasons ────────────────────────────────────────────────────────

/// Why the classifier left this photograph out of the usable set, as a full
/// sentence rather than the raw `imageKind` value.
///
/// [ListingImage.isExcluded] is only ever true for a non-null `imageKind`
/// other than `'exterior'`, so in practice the fallback branch below is
/// unreachable against today's classifier vocabulary. It is kept anyway,
/// rather than asserting or unwrapping with `!`, because a future
/// classification the client has not been told about should degrade to a
/// still-true, still-plain sentence rather than a crash.
String _exclusionReason(String? imageKind) => switch (imageKind) {
  'advertisement' =>
    'This looks like an advertisement or a dealer badge rather than a '
        "photograph of the vehicle.",
  'interior' =>
    'This is an interior shot, so there is no exterior to place on a '
        'backdrop.',
  'detail' =>
    'This is a close-up of part of the vehicle rather than the '
        'whole car.',
  'unknown' =>
    "This could not be identified as a photograph of the vehicle's "
        'exterior.',
  _ =>
    'This was not used because it could not be identified as a '
        "photograph of the vehicle's exterior.",
};

// ── Screen ───────────────────────────────────────────────────────────────────

class ListingDetailScreen extends ConsumerStatefulWidget {
  const ListingDetailScreen({super.key, required this.listingId, this.preview});

  final int listingId;

  /// What the vehicles list already knew about this listing before it was
  /// tapped — title, pipeline status, stock number. Optional: a deep link
  /// or a stale bookmark reaches this screen with only an id and none of
  /// this, which the plain loading skeleton in [_loadingBody] still covers.
  /// When it is available, the header shows immediately instead of waiting
  /// on this screen's own fetch, and carries the [Hero] flight from the
  /// list row's status pill through to a real destination rather than one
  /// that only exists after a round trip completes.
  final VehicleListing? preview;

  @override
  ConsumerState<ListingDetailScreen> createState() =>
      _ListingDetailScreenState();
}

class _ListingDetailScreenState extends ConsumerState<ListingDetailScreen> {
  _Load _state = const _Loading();

  /// Ids of images currently being deleted or included.
  ///
  /// Keyed by image id rather than a single screen-wide flag so that, if a
  /// dealer starts a second action while the first is still in flight, only
  /// the tile actually busy shows as busy — the rest of the grid stays
  /// interactive.
  Set<int> _deletingImageIds = const {};
  Set<int> _includingImageIds = const {};
  bool _retrying = false;
  bool _deletingListing = false;

  /// The most recent delete or include failure, already safe to show as-is
  /// per [ApiException.message]. Cleared at the start of the next attempt
  /// rather than on a timer or a dismiss button, neither of which the brief
  /// asks for.
  String? _actionErrorMessage;

  /// Latest processing counts, polled while the pipeline still has work to
  /// do — see [_pollWhileProcessing]. Null before the first load finishes,
  /// and left at its last value once processing is done, since nothing
  /// after that point invalidates it.
  ProcessingSummary? _progress;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _state = const _Loading());
    final api = ref.read(apiClientProvider);
    try {
      final listing = await api.listing(widget.listingId);
      if (!mounted) return;
      setState(() => _state = _Loaded(listing));
      // Best-effort and unconditional — not only while polling — because a
      // needs_review photograph needs job.errorMessage to explain itself no
      // matter what the listing's overall processingStatus already is.
      await _refreshProgress();
      if (!mounted) return;
      _pollWhileProcessing(listing.processingStatus);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  /// See [_load]'s call to this: a failure here is not worth taking the
  /// whole screen down for, the same reasoning the poll below already
  /// applies to itself — [_progress] only ever adds detail on top of a
  /// listing that already loaded, it gates nothing the screen needs to work.
  Future<void> _refreshProgress() async {
    try {
      final summary = await ref
          .read(apiClientProvider)
          .listingJobs(widget.listingId);
      if (mounted) setState(() => _progress = summary);
    } on ApiException {
      // Leave whatever _progress already had.
    }
  }

  /// Polls `/jobs` for progress counts every few seconds while the pipeline
  /// is still working, and re-fetches the full listing once it finishes —
  /// otherwise a dealer who left this screen open would see the same
  /// "processing" state indefinitely rather than the finished photographs
  /// landing on their own.
  ///
  /// A plain fixed interval, not exponential backoff: this screen is only
  /// polling while someone is actually looking at it (the timer is cancelled
  /// in [dispose]), so the choice is between "check every few seconds while
  /// visible" and "make the dealer pull to refresh" — not between that and
  /// polling forever in the background.
  void _pollWhileProcessing(String processingStatus) {
    _pollTimer?.cancel();
    if (processingStatus != 'pending' && processingStatus != 'processing') {
      return;
    }

    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) async {
      final api = ref.read(apiClientProvider);
      try {
        final summary = await api.listingJobs(widget.listingId);
        if (!mounted) return;
        setState(() => _progress = summary);
        if (!summary.isInProgress) {
          _pollTimer?.cancel();
          await _load();
        }
      } on ApiException {
        // A transient failure on a background poll is not worth surfacing —
        // the next tick tries again, and a dealer actively looking at the
        // screen can still pull to refresh if it never recovers.
      }
    });
  }

  /// Confirms, then deletes, one photograph.
  ///
  /// `context` is only touched before the first `await` — for the
  /// confirmation dialog itself — so there is no use of a `BuildContext`
  /// across an async gap here.
  Future<void> _handleDelete(ListingImage image) async {
    if (_deletingImageIds.contains(image.id)) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => _DeleteConfirmDialog(image: image),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _deletingImageIds = {..._deletingImageIds, image.id};
      _actionErrorMessage = null;
    });

    try {
      await ref.read(apiClientProvider).deleteImage(widget.listingId, image.id);
      if (!mounted) return;

      // Re-read the current state rather than closing over the listing this
      // method started with: nothing else can mutate it between the await
      // above and here, but reading it fresh is what actually justifies that
      // assumption rather than just hoping it holds.
      final current = _state;
      if (current is _Loaded) {
        final remaining = current.listing.images
            .where((i) => i.id != image.id)
            .toList();
        setState(() {
          _state = _Loaded(current.listing.copyWithImages(remaining));
          _deletingImageIds = {..._deletingImageIds}..remove(image.id);
        });
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _deletingImageIds = {..._deletingImageIds}..remove(image.id);
        _actionErrorMessage = e.message;
      });
    }
  }

  /// Deletes the whole listing, not just one photograph — reached from the
  /// header's overflow menu, deliberately a step further away than the
  /// per-photograph delete button that sits right on every tile.
  Future<void> _handleDeleteListing(VehicleListingDetail listing) async {
    if (_deletingListing) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) =>
          _DeleteListingConfirmDialog(title: listing.title),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _deletingListing = true);
    try {
      await ref.read(apiClientProvider).deleteListing(widget.listingId);
      if (!mounted) return;
      // The listing this screen was showing no longer exists — back to
      // wherever it was reached from, the same as every other screen in
      // this app leaves once its own subject is gone.
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _deletingListing = false;
        _actionErrorMessage = e.message;
      });
    }
  }

  /// Overrides the classifier's exclusion for one photograph — see the
  /// server route's own doc comment for why this is one-way, not a toggle
  /// back to the original classification.
  Future<void> _handleInclude(ListingImage image) async {
    if (_includingImageIds.contains(image.id)) return;

    setState(() {
      _includingImageIds = {..._includingImageIds, image.id};
      _actionErrorMessage = null;
    });

    try {
      final updated = await ref
          .read(apiClientProvider)
          .includeImage(widget.listingId, image.id);
      if (!mounted) return;

      final current = _state;
      if (current is _Loaded) {
        final images = current.listing.images
            .map((i) => i.id == updated.id ? updated : i)
            .toList();
        setState(() {
          _state = _Loaded(current.listing.copyWithImages(images));
          _includingImageIds = {..._includingImageIds}..remove(image.id);
        });
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _includingImageIds = {..._includingImageIds}..remove(image.id);
        _actionErrorMessage = e.message;
      });
    }
  }

  /// The backdrop a needs_review photograph last ran with, if any — reused
  /// so pressing Retry does not silently fall back to a transparent
  /// background just because this screen was not the one that originally
  /// chose one. Every flagged photograph on one listing was queued together
  /// from the same review-screen choice, so the first one found is as good
  /// as any.
  int? _retryBackdropId() {
    for (final job in _progress?.jobs ?? const <ProcessingJobSummary>[]) {
      if (job.backdropId != null) return job.backdropId;
    }
    return null;
  }

  /// Queues every outstanding photograph again — including one flagged
  /// needs_review, now that `create_jobs` on the server treats that as
  /// unfinished rather than done. Listing-wide because there is no
  /// per-photograph retry endpoint: `POST /process` is what Reprocess has
  /// always meant here, for the set the review screen originally submitted.
  Future<void> _handleRetry() async {
    if (_retrying) return;
    setState(() {
      _retrying = true;
      _actionErrorMessage = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .processListing(widget.listingId, backdropId: _retryBackdropId());
      if (!mounted) return;
      await _load();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _actionErrorMessage = e.message);
    } finally {
      if (mounted) setState(() => _retrying = false);
    }
  }

  IconButton _backButton() => IconButton(
    onPressed: () => Navigator.of(context).pop(),
    icon: const Icon(Icons.arrow_back, color: C.inkSoft),
    tooltip: 'Back to vehicles',
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(body: SafeArea(child: _content(_state)));
  }

  Widget _content(_Load state) => switch (state) {
    _Loading() => _loadingBody(),
    _LoadFailed(:final message) => _failedBody(message),
    _Loaded(:final listing) => _loadedBody(listing),
  };

  Widget _loadingBody() {
    final preview = widget.preview;

    return Column(
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _backButton(),
            // A real title and status pill — including the Hero this
            // screen's own StatusPill is the destination half of — as soon
            // as the list row that opened this screen already knew them,
            // rather than making even that wait on this screen's fetch.
            if (preview != null)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: Space.sm),
                  child: _PreviewHeader(preview),
                ),
              ),
          ],
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(
              Space.lg,
              Space.sm,
              Space.lg,
              Space.lg,
            ),
            child: ShimmerGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (preview == null) ...[
                    Row(
                      children: [
                        const Expanded(child: SkeletonBox(height: 26)),
                        const SizedBox(width: Space.sm),
                        SkeletonBox(
                          width: 72,
                          height: 22,
                          borderRadius: Radii.controlAll,
                        ),
                      ],
                    ),
                    const SizedBox(height: Space.lg),
                  ],
                  const SkeletonBox(height: 11, width: 90),
                  const SizedBox(height: Space.sm),
                  for (var i = 0; i < 2; i++) ...[
                    const _BeforeAfterSkeletonTile(),
                    if (i < 1) const SizedBox(height: Space.sm),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _failedBody(String message) => Column(
    children: [
      Align(alignment: Alignment.centerLeft, child: _backButton()),
      Expanded(
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
    ],
  );

  Widget _loadedBody(VehicleListingDetail listing) {
    // Every processed image that traces back to an original via
    // sourceImageId becomes a before/after pair — regardless of the
    // listing's overall processingStatus, so a set that is otherwise
    // "needs_review" (because one photograph needed a second look) still
    // shows every pair that did complete rather than hiding all of them
    // behind that one outstanding job.
    final processed = listing.processed.where((i) => !i.isExcluded).toList();
    final originalsById = {for (final o in listing.originals) o.id: o};
    final pairedOriginalIds = <int>{};
    final pairs = <(ListingImage, ListingImage?)>[];
    for (final result in processed) {
      final original = result.sourceImageId != null
          ? originalsById[result.sourceImageId]
          : null;
      if (original != null) pairedOriginalIds.add(original.id);
      pairs.add((result, original));
    }

    // A job's own review_state is what actually distinguishes "still queued"
    // from "the pipeline ran and found nothing to cut out" — both look
    // identical from the image alone (no processed pair, not excluded), so
    // without this a needs_review photograph sat in "awaiting processing"
    // forever with no explanation and nothing to do about it.
    final jobsByInputImageId = {
      for (final job in _progress?.jobs ?? const <ProcessingJobSummary>[])
        job.inputImageId: job,
    };

    final originals = listing.originals;
    final awaitingOriginals = <ListingImage>[];
    final needsReviewOriginals = <ListingImage>[];
    for (final image in originals) {
      if (image.isExcluded || pairedOriginalIds.contains(image.id)) continue;
      if (jobsByInputImageId[image.id]?.reviewState == 'needs_review') {
        needsReviewOriginals.add(image);
      } else {
        awaitingOriginals.add(image);
      }
    }
    final excludedOriginals = originals.where((i) => i.isExcluded).toList();

    return CustomScrollView(
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(
            Space.sm,
            Space.sm,
            Space.lg,
            Space.md,
          ),
          sliver: SliverToBoxAdapter(child: _header(listing)),
        ),
        if (_actionErrorMessage != null)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.md),
            sliver: SliverToBoxAdapter(
              child: AppErrorBanner(_actionErrorMessage!),
            ),
          ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.xl),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeading('BEFORE / AFTER (${pairs.length})'),
                const SizedBox(height: Space.sm),
                // An empty list with no explanation would read as a bug
                // rather than "still waiting on the pipeline", so this says
                // so plainly instead.
                if (pairs.isEmpty)
                  Text('No processed photographs yet.', style: T.bodySmall)
                else
                  Column(
                    children: [
                      for (final (result, original) in pairs) ...[
                        _BeforeAfterTile(processed: result, original: original),
                        const SizedBox(height: Space.sm),
                      ],
                    ],
                  ),
                if (awaitingOriginals.isNotEmpty) ...[
                  const SizedBox(height: Space.xl),
                  _sectionHeading(
                    'AWAITING PROCESSING (${awaitingOriginals.length})',
                  ),
                  const SizedBox(height: Space.sm),
                  _plainGrid(
                    awaitingOriginals,
                    semanticRole: 'Original photograph',
                  ),
                ],
                if (needsReviewOriginals.isNotEmpty) ...[
                  const SizedBox(height: Space.xl),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _sectionHeading(
                        'NEEDS REVIEW (${needsReviewOriginals.length})',
                      ),
                      TextButton(
                        onPressed: _retrying ? null : _handleRetry,
                        style: TextButton.styleFrom(
                          padding: EdgeInsets.zero,
                          minimumSize: Size.zero,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                        child: Text(
                          _retrying ? 'Retrying…' : 'Retry',
                          style: T.caption.copyWith(color: C.forest),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: Space.sm),
                  _needsReviewWrap(needsReviewOriginals, jobsByInputImageId),
                ],
                if (excludedOriginals.isNotEmpty) ...[
                  const SizedBox(height: Space.xl),
                  _sectionHeading('EXCLUDED (${excludedOriginals.length})'),
                  const SizedBox(height: Space.sm),
                  _excludedWrap(excludedOriginals),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }

  /// Back button, title, pipeline status, stock number and description.
  Widget _header(VehicleListingDetail listing) {
    final processing = ProcessingState.parse(listing.processingStatus);
    final stockNumber = listing.stockNumber;
    final hasStockNumber = stockNumber != null && stockNumber.isNotEmpty;
    final description = listing.description;
    final hasDescription = description != null && description.isNotEmpty;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _backButton(),
        const SizedBox(width: Space.xs),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(top: Space.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: Text(listing.title, style: serif(28))),
                    const SizedBox(width: Space.sm),
                    Hero(
                      tag: 'listing-status-${listing.id}',
                      child: StatusPill(processing),
                    ),
                  ],
                ),
                if (hasStockNumber) ...[
                  const SizedBox(height: Space.xs),
                  Text('#$stockNumber', style: T.figure),
                ],
                if (_progress case final progress?
                    when progress.isInProgress) ...[
                  const SizedBox(height: Space.xs),
                  Text(
                    'Processing — ${progress.completed} of '
                    '${progress.total} done',
                    style: T.bodySmall,
                  ),
                ],
                if (hasDescription) ...[
                  const SizedBox(height: Space.sm),
                  Text(description, style: T.body),
                ],
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: Space.sm),
          child: PopupMenuButton<void>(
            enabled: !_deletingListing,
            icon: Icon(
              Icons.more_vert,
              color: _deletingListing ? C.inkSoft : C.ink,
            ),
            tooltip: 'More',
            itemBuilder: (context) => [
              PopupMenuItem<void>(
                onTap: () => _handleDeleteListing(listing),
                child: Text(
                  'Delete listing',
                  style: T.body.copyWith(color: C.rust),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _sectionHeading(String label) => Text(label, style: T.caption);

  /// A responsive grid of plain (non-excluded) photographs — processed
  /// results or usable originals. Square tiles at a target width, rather than
  /// a fixed column count, so the same section reads sensibly on a phone in
  /// portrait and on a wider device later.
  Widget _plainGrid(List<ListingImage> images, {required String semanticRole}) {
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 130,
        mainAxisSpacing: Space.sm,
        crossAxisSpacing: Space.sm,
        childAspectRatio: 1,
      ),
      itemCount: images.length,
      itemBuilder: (context, index) {
        final image = images[index];
        return _PhotoTile(
          image: image,
          semanticLabel: '$semanticRole: ${image.originalFilename}',
          isDeleting: _deletingImageIds.contains(image.id),
          onDelete: () => _handleDelete(image),
        );
      },
    );
  }

  /// The needs_review originals, each with the job's own explanation
  /// underneath it — see [_NeedsReviewTile]. No per-tile "include anyway"
  /// here, unlike [_excludedWrap]: an excluded tile still has a classifier
  /// guess a dealer can overrule, but a needs_review job produced no
  /// processed image at all, so there is nothing a per-photograph override
  /// could promote — Retry, above the section, is the one action that can
  /// actually change the outcome.
  Widget _needsReviewWrap(
    List<ListingImage> images,
    Map<int, ProcessingJobSummary> jobsByInputImageId,
  ) {
    return Wrap(
      spacing: Space.sm,
      runSpacing: Space.md,
      children: images.map((image) {
        final reason =
            jobsByInputImageId[image.id]?.errorMessage ??
            'No vehicle was found in this photograph.';
        return SizedBox(
          width: 148,
          child: _NeedsReviewTile(
            image: image,
            reason: reason,
            semanticLabel:
                'Photograph needing review: ${image.originalFilename}. '
                '$reason',
            isDeleting: _deletingImageIds.contains(image.id),
            onDelete: () => _handleDelete(image),
          ),
        );
      }).toList(),
    );
  }

  /// The excluded originals, each with a visible reason underneath it.
  ///
  /// A [Wrap] rather than the [GridView] used above: an excluded tile carries
  /// a full-sentence caption of variable length, and at a phone's default
  /// text scale that wraps to a different number of lines per sentence. A
  /// [GridView] cell needs a height fixed up front (via `childAspectRatio` or
  /// `mainAxisExtent`); pick one generous enough for the longest reason at
  /// the largest supported text scale and every shorter caption leaves an
  /// awkward gap, pick one too tight and a dealer with larger system text
  /// gets a caption that overflows its tile. `Wrap` gives each tile its own
  /// intrinsic height instead, which is the "or similar" the brief allows for
  /// exactly this reason.
  Widget _excludedWrap(List<ListingImage> images) {
    return Wrap(
      spacing: Space.sm,
      runSpacing: Space.md,
      children: images.map((image) {
        final reason = _exclusionReason(image.imageKind);
        return SizedBox(
          width: 148,
          child: _ExcludedTile(
            image: image,
            reason: reason,
            semanticLabel:
                'Excluded original photograph: ${image.originalFilename}. '
                '$reason',
            isDeleting: _deletingImageIds.contains(image.id),
            isIncluding: _includingImageIds.contains(image.id),
            onDelete: () => _handleDelete(image),
            onInclude: () => _handleInclude(image),
          ),
        );
      }).toList(),
    );
  }
}

// ── Tile ─────────────────────────────────────────────────────────────────────

/// One photograph: the image itself, a delete button overlaid in a corner,
/// Used for processed results and usable originals; an excluded original
/// uses [_ExcludedTile] instead, which needs a reason caption and a second
/// action this tile does not.
class _PhotoTile extends StatelessWidget {
  const _PhotoTile({
    required this.image,
    required this.semanticLabel,
    required this.isDeleting,
    required this.onDelete,
  });

  final ListingImage image;
  final String semanticLabel;
  final bool isDeleting;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: Radii.controlAll,
      child: AspectRatio(
        aspectRatio: 1,
        child: Stack(
          fit: StackFit.expand,
          children: [
            AuthedImage(
              storagePath: image.imageUrl,
              semanticLabel: semanticLabel,
              fit: BoxFit.cover,
            ),
            Positioned(
              top: Space.xs,
              right: Space.xs,
              child: IconButton(
                onPressed: isDeleting ? null : onDelete,
                tooltip: 'Delete this photograph',
                icon: const Icon(Icons.delete_outline),
                iconSize: 16,
                style: IconButton.styleFrom(
                  backgroundColor: C.ink,
                  foregroundColor: C.white,
                  disabledBackgroundColor: C.inkSoft,
                  disabledForegroundColor: C.white,
                  minimumSize: const Size(32, 32),
                  padding: EdgeInsets.zero,
                ),
              ),
            ),
            if (isDeleting)
              Semantics(
                label: 'Deleting this photograph',
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Opacity(
                      opacity: 0.55,
                      child: const ColoredBox(color: C.ink),
                    ),
                    const Center(
                      child: SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: C.white,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ── Before / after ───────────────────────────────────────────────────────────

/// The loading-state stand-in for [_BeforeAfterTile] — same card, same two
/// square panes side by side, so the skeleton and the real content occupy
/// exactly the same footprint and nothing jumps when the fetch resolves.
/// The title-and-pill half of [_ListingDetailScreenState._header], built
/// from a list row's own [VehicleListing] instead of the full
/// [VehicleListingDetail] this screen otherwise waits on — used only in
/// [_ListingDetailScreenState._loadingBody], while that fetch is still in
/// flight. Carries the same `'listing-status-…'` [Hero] tag as [_header]
/// itself, so the flight lands on whichever of the two actually ends up on
/// screen once the fetch resolves; a stock number and description are no
/// less real for the delay, so this does not attempt a second copy of them.
class _PreviewHeader extends StatelessWidget {
  const _PreviewHeader(this.listing);

  final VehicleListing listing;

  @override
  Widget build(BuildContext context) {
    final processing = ProcessingState.parse(listing.processingStatus);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: Text(listing.title, style: serif(28))),
        const SizedBox(width: Space.sm),
        Hero(
          tag: 'listing-status-${listing.id}',
          child: StatusPill(processing),
        ),
      ],
    );
  }
}

class _BeforeAfterSkeletonTile extends StatelessWidget {
  const _BeforeAfterSkeletonTile();

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: _pane()),
          const SizedBox(width: Space.sm),
          Expanded(child: _pane()),
        ],
      ),
    );
  }

  Widget _pane() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SkeletonBox(height: 11, width: 44),
        const SizedBox(height: Space.xs),
        AspectRatio(
          aspectRatio: 1,
          child: SkeletonBox(borderRadius: Radii.controlAll),
        ),
      ],
    );
  }
}

/// One processed photograph beside the original it came from — shown
/// regardless of the listing's overall processing status, so a set that
/// still has one photograph outstanding does not hide every pair that
/// already finished.
///
/// [original] is null for a processed image saved before `source_image_id`
/// existed — rare, but real for anything processed early enough, and shown
/// as the result alone rather than crashing on a pairing that cannot be made.
/// Drag (or tap) anywhere across the photograph to move the split — left of
/// it shows the original, right of it shows the processed result. Replaces
/// the side-by-side pair this tile used to show: comparing two separate
/// squares means moving your eyes back and forth and holding the difference
/// in memory, where a slider lets the same patch of the vehicle be either
/// photograph on demand, which is what actually answers "what did the
/// pipeline change here".
class _BeforeAfterTile extends StatefulWidget {
  const _BeforeAfterTile({required this.processed, required this.original});

  final ListingImage processed;
  final ListingImage? original;

  @override
  State<_BeforeAfterTile> createState() => _BeforeAfterTileState();
}

class _BeforeAfterTileState extends State<_BeforeAfterTile> {
  /// 0 shows only the processed result, 1 shows only the original. Starts
  /// at the midpoint — the same split point the old side-by-side layout
  /// showed by default, just now adjustable instead of fixed.
  double _split = 0.5;

  void _setSplitFromDx(double dx, double width) {
    if (width <= 0) return;
    setState(() => _split = (dx / width).clamp(0.0, 1.0));
  }

  @override
  Widget build(BuildContext context) {
    final original = widget.original;

    // No pairing to compare — the single-pane fallback this tile has always
    // had for a processed image saved before source_image_id existed.
    if (original == null) {
      return AppCard(
        child: ClipRRect(
          borderRadius: Radii.controlAll,
          child: AspectRatio(
            aspectRatio: 1,
            child: AuthedImage(
              storagePath: widget.processed.imageUrl,
              semanticLabel: 'Processed photograph',
              fit: BoxFit.cover,
            ),
          ),
        ),
      );
    }

    return AppCard(
      padding: const EdgeInsets.all(Space.sm),
      child: Semantics(
        label:
            'Before and after comparison, ${(_split * 100).round()}% '
            'original. Drag across the photograph to compare.',
        child: ClipRRect(
          borderRadius: Radii.controlAll,
          child: AspectRatio(
            aspectRatio: 1,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final width = constraints.maxWidth;
                return GestureDetector(
                  onHorizontalDragUpdate: (details) =>
                      _setSplitFromDx(details.localPosition.dx, width),
                  onTapUp: (details) =>
                      _setSplitFromDx(details.localPosition.dx, width),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      AuthedImage(
                        storagePath: widget.processed.imageUrl,
                        semanticLabel: 'Processed photograph',
                        fit: BoxFit.cover,
                      ),
                      ClipRect(
                        clipper: _SplitClipper(fraction: _split),
                        child: AuthedImage(
                          storagePath: original.imageUrl,
                          semanticLabel: 'Original photograph',
                          fit: BoxFit.cover,
                        ),
                      ),
                      const Positioned(
                        top: Space.xs,
                        right: Space.xs,
                        child: _CompareTag('AFTER'),
                      ),
                      Positioned(
                        top: Space.xs,
                        left: Space.xs,
                        child: const _CompareTag('BEFORE'),
                      ),
                      Positioned(
                        left: (width * _split - 1).clamp(0, width - 2),
                        top: 0,
                        bottom: 0,
                        child: const IgnorePointer(child: _SplitHandle()),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

/// Clips to the left fraction of the box — the region the original photo
/// occupies, to the left of the drag handle.
class _SplitClipper extends CustomClipper<Rect> {
  const _SplitClipper({required this.fraction});

  final double fraction;

  @override
  Rect getClip(Size size) =>
      Rect.fromLTRB(0, 0, size.width * fraction, size.height);

  @override
  bool shouldReclip(_SplitClipper oldClipper) =>
      fraction != oldClipper.fraction;
}

/// The vertical line and grip at the current split position. Wrapped in
/// [IgnorePointer] by its caller — the drag is handled by the
/// [GestureDetector] beneath the whole tile, not by this line specifically,
/// so it must never itself intercept the gesture.
class _SplitHandle extends StatelessWidget {
  const _SplitHandle();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 2,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          const DecoratedBox(decoration: BoxDecoration(color: C.white)),
          Positioned(
            top: 0,
            bottom: 0,
            left: -11,
            child: Center(
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: C.white,
                  shape: BoxShape.circle,
                  boxShadow: cardShadow,
                ),
                child: const Icon(
                  Icons.drag_indicator,
                  size: 16,
                  color: C.inkSoft,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A small "BEFORE"/"AFTER" corner label, legible over any photograph
/// regardless of its own colours — the reason for the dark scrim rather
/// than relying on the photo behind it for contrast.
class _CompareTag extends StatelessWidget {
  const _CompareTag(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: Radii.controlAll,
      ),
      child: Text(
        label,
        style: T.caption.copyWith(color: C.white, letterSpacing: 0.6),
      ),
    );
  }
}

// ── Excluded tile ────────────────────────────────────────────────────────────

/// An excluded original: the image, dimmed, a reason underneath it, and two
/// actions — Include (overrides the classifier) or Delete. Until now Delete
/// was the only action available here, which meant a photograph the
/// classifier misjudged — an interior shot a dealer actually wanted, say —
/// had no way back in except leaving it out entirely.
class _ExcludedTile extends StatelessWidget {
  const _ExcludedTile({
    required this.image,
    required this.reason,
    required this.semanticLabel,
    required this.isDeleting,
    required this.isIncluding,
    required this.onDelete,
    required this.onInclude,
  });

  final ListingImage image;
  final String reason;
  final String semanticLabel;
  final bool isDeleting;
  final bool isIncluding;
  final VoidCallback onDelete;
  final VoidCallback onInclude;

  @override
  Widget build(BuildContext context) {
    final busy = isDeleting || isIncluding;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        ClipRRect(
          borderRadius: Radii.controlAll,
          child: AspectRatio(
            aspectRatio: 1,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Opacity(
                  opacity: 0.45,
                  child: AuthedImage(
                    storagePath: image.imageUrl,
                    semanticLabel: semanticLabel,
                    fit: BoxFit.cover,
                  ),
                ),
                if (busy)
                  Semantics(
                    label: isIncluding
                        ? 'Including this photograph'
                        : 'Deleting this photograph',
                    child: const Stack(
                      fit: StackFit.expand,
                      children: [
                        Opacity(opacity: 0.55, child: ColoredBox(color: C.ink)),
                        Center(
                          child: SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: C.white,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: Space.xs),
        Text(reason, style: T.bodySmall),
        const SizedBox(height: Space.xs),
        Row(
          children: [
            Expanded(
              child: TextButton(
                onPressed: busy ? null : onInclude,
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
                child: Text(
                  'Include',
                  style: T.caption.copyWith(color: C.forest),
                ),
              ),
            ),
            Expanded(
              child: TextButton(
                onPressed: busy ? null : onDelete,
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
                child: Text('Delete', style: T.caption.copyWith(color: C.rust)),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// One photograph the pipeline ran but found no vehicle to cut out —
/// [reason] is the job's own [ProcessingJobSummary.errorMessage], not a
/// guess made on this screen. Deleting it is the one per-photograph action;
/// see [ListingDetailScreen]'s `_needsReviewWrap` for why there is no
/// per-tile "include anyway" here the way [_ExcludedTile] has.
class _NeedsReviewTile extends StatelessWidget {
  const _NeedsReviewTile({
    required this.image,
    required this.reason,
    required this.semanticLabel,
    required this.isDeleting,
    required this.onDelete,
  });

  final ListingImage image;
  final String reason;
  final String semanticLabel;
  final bool isDeleting;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        ClipRRect(
          borderRadius: Radii.controlAll,
          child: AspectRatio(
            aspectRatio: 1,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Opacity(
                  opacity: 0.45,
                  child: AuthedImage(
                    storagePath: image.imageUrl,
                    semanticLabel: semanticLabel,
                    fit: BoxFit.cover,
                  ),
                ),
                if (isDeleting)
                  Semantics(
                    label: 'Deleting this photograph',
                    child: const Stack(
                      fit: StackFit.expand,
                      children: [
                        Opacity(opacity: 0.55, child: ColoredBox(color: C.ink)),
                        Center(
                          child: SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: C.white,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: Space.xs),
        Text(reason, style: T.bodySmall),
        const SizedBox(height: Space.xs),
        TextButton(
          onPressed: isDeleting ? null : onDelete,
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
          child: Text('Delete', style: T.caption.copyWith(color: C.rust)),
        ),
      ],
    );
  }
}

// ── Delete confirmation ──────────────────────────────────────────────────────

/// A small, screen-scoped confirmation dialog.
///
/// There is no shared confirm-dialog primitive in this codebase yet — that
/// exists on the web client, not here — so this is deliberately local to this
/// screen rather than a new addition to `widgets/primitives.dart`, which is
/// owned elsewhere.
class _DeleteConfirmDialog extends StatelessWidget {
  const _DeleteConfirmDialog({required this.image});

  final ListingImage image;

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
            Text('Delete this photograph?', style: serif(24)),
            const SizedBox(height: Space.sm),
            Text(
              'This removes "${image.originalFilename}" from this listing. '
              'This cannot be undone.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            Row(
              children: [
                // Wrapped in Expanded rather than left to size themselves:
                // FilledButtonThemeData sets a house-wide minimumSize of
                // Size.fromHeight(48), which is Size(double.infinity, 48) —
                // correct for a single full-width button, but an unbounded
                // width request inside a bare Row (no Expanded) is exactly
                // the shape of a RenderFlex layout failure. Expanded gives
                // both buttons a tight, finite width to satisfy instead.
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
                    child: const Text('Delete'),
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

/// Confirms before deleting the whole listing — every photograph on it, not
/// one at a time. Same shape as [_DeleteConfirmDialog], one level up.
class _DeleteListingConfirmDialog extends StatelessWidget {
  const _DeleteListingConfirmDialog({required this.title});

  final String title;

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
            Text('Delete "$title"?', style: serif(24)),
            const SizedBox(height: Space.sm),
            Text(
              'This removes the listing and every photograph on it — '
              'originals and processed results alike. This cannot be undone.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            Row(
              children: [
                // See _DeleteConfirmDialog's own comment on this same shape
                // for why both buttons are wrapped in Expanded.
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
                    child: const Text('Delete listing'),
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
