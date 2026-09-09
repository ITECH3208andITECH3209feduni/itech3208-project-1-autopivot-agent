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
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models/listing_detail.dart';
import '../../api/models/listing_image.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/authed_image.dart';
import '../../widgets/primitives.dart';

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
  'detail' => 'This is a close-up of part of the vehicle rather than the '
      'whole car.',
  'unknown' =>
    "This could not be identified as a photograph of the vehicle's "
        'exterior.',
  _ => 'This was not used because it could not be identified as a '
      "photograph of the vehicle's exterior.",
};

// ── Screen ───────────────────────────────────────────────────────────────────

class ListingDetailScreen extends ConsumerStatefulWidget {
  const ListingDetailScreen({super.key, required this.listingId});

  final int listingId;

  @override
  ConsumerState<ListingDetailScreen> createState() =>
      _ListingDetailScreenState();
}

class _ListingDetailScreenState extends ConsumerState<ListingDetailScreen> {
  _Load _state = const _Loading();

  /// Ids of images currently being deleted.
  ///
  /// Keyed by image id rather than a single screen-wide flag so that, if a
  /// dealer starts a second delete while the first is still in flight, only
  /// the tile actually being deleted shows as busy — the rest of the grid
  /// stays interactive.
  Set<int> _deletingImageIds = const {};

  /// The most recent delete failure, already safe to show as-is per
  /// [ApiException.message]. Cleared at the start of the next delete attempt
  /// rather than on a timer or a dismiss button, neither of which the brief
  /// asks for.
  String? _deleteErrorMessage;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _state = const _Loading());
    final api = ref.read(apiClientProvider);
    try {
      final listing = await api.listing(widget.listingId);
      if (!mounted) return;
      setState(() => _state = _Loaded(listing));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
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
      _deleteErrorMessage = null;
    });

    try {
      await ref
          .read(apiClientProvider)
          .deleteImage(widget.listingId, image.id);
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
        _deleteErrorMessage = e.message;
      });
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

  Widget _loadingBody() => Column(
    children: [
      Align(alignment: Alignment.centerLeft, child: _backButton()),
      const Expanded(child: Center(child: CircularProgressIndicator())),
    ],
  );

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
    // Two axes on every image: pipeline stage (original vs. processed) and,
    // for an original, whether the classifier decided it was usable. These
    // three groups are disjoint by construction — isProcessed and isOriginal
    // partition [images], and isExcluded further splits the originals — so
    // there is no image counted in more than one section below.
    final processed = listing.processed.where((i) => !i.isExcluded).toList();
    final originals = listing.originals;
    final activeOriginals = originals.where((i) => !i.isExcluded).toList();
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
        if (_deleteErrorMessage != null)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(
              Space.lg,
              0,
              Space.lg,
              Space.md,
            ),
            sliver: SliverToBoxAdapter(
              child: AppErrorBanner(_deleteErrorMessage!),
            ),
          ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.xl),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeading('PROCESSED (${processed.length})'),
                const SizedBox(height: Space.sm),
                // The results a dealer would actually use. An empty grid with
                // no explanation would read as a bug rather than "still
                // waiting on the pipeline", so this says so plainly instead.
                if (processed.isEmpty)
                  Text(
                    'No processed photographs yet.',
                    style: T.bodySmall,
                  )
                else
                  _plainGrid(processed, semanticRole: 'Processed photograph'),
                if (originals.isNotEmpty) ...[
                  const SizedBox(height: Space.xl),
                  _sectionHeading('ORIGINALS (${originals.length})'),
                  const SizedBox(height: Space.sm),
                  if (activeOriginals.isNotEmpty)
                    _plainGrid(
                      activeOriginals,
                      semanticRole: 'Original photograph',
                    ),
                  if (excludedOriginals.isNotEmpty) ...[
                    if (activeOriginals.isNotEmpty)
                      const SizedBox(height: Space.md),
                    Text('EXCLUDED', style: T.caption),
                    const SizedBox(height: Space.sm),
                    _excludedWrap(excludedOriginals),
                  ],
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
                    StatusPill(processing),
                  ],
                ),
                if (hasStockNumber) ...[
                  const SizedBox(height: Space.xs),
                  Text('#$stockNumber', style: T.figure),
                ],
                if (hasDescription) ...[
                  const SizedBox(height: Space.sm),
                  Text(description, style: T.body),
                ],
              ],
            ),
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
          width: 128,
          child: _PhotoTile(
            image: image,
            dimmed: true,
            caption: reason,
            semanticLabel:
                'Excluded original photograph: ${image.originalFilename}. '
                '$reason',
            isDeleting: _deletingImageIds.contains(image.id),
            onDelete: () => _handleDelete(image),
          ),
        );
      }).toList(),
    );
  }
}

// ── Tile ─────────────────────────────────────────────────────────────────────

/// One photograph: the image itself, a delete button overlaid in a corner,
/// and — for an excluded original — a reason caption underneath it.
class _PhotoTile extends StatelessWidget {
  const _PhotoTile({
    required this.image,
    required this.semanticLabel,
    required this.isDeleting,
    required this.onDelete,
    this.dimmed = false,
    this.caption,
  });

  final ListingImage image;
  final String semanticLabel;
  final bool isDeleting;
  final VoidCallback onDelete;

  /// True for an excluded original. Only the image itself is faded — never
  /// the caption below it — because dimming label text alongside an image is
  /// exactly how a contrast failure quietly happens: the image can afford to
  /// lose contrast against its background, the sentence explaining why a
  /// dealer should not use it cannot.
  final bool dimmed;

  /// The reason sentence, shown under the tile. Null for a processed or
  /// active-original tile, which need no caption.
  final String? caption;

  @override
  Widget build(BuildContext context) {
    final photo = ClipRRect(
      borderRadius: Radii.controlAll,
      child: AspectRatio(
        aspectRatio: 1,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Opacity(
              opacity: dimmed ? 0.45 : 1,
              child: AuthedImage(
                storagePath: image.imageUrl,
                semanticLabel: semanticLabel,
                fit: BoxFit.cover,
              ),
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

    if (caption == null) return photo;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        photo,
        const SizedBox(height: Space.xs),
        Text(caption!, style: T.bodySmall),
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
