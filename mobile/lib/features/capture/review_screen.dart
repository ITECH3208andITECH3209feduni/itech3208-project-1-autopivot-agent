/// The screen shown after capture, replacing the old "submit" bottom sheet.
///
/// One screen, not the grid-then-details-form split this used to be: the
/// photo grid — tap any tile to expand it with Retake / Delete this angle /
/// Close, or tap an empty slot to jump straight back to shooting it — sits
/// above the vehicle-details form, with Submit Set as the one button at the
/// bottom. [CaptureScreen] pushes this and reads back a [ReviewResult] once
/// it closes.
///
/// [ReviewClosed] and [ReviewRetake] both carry a [ReviewDraft] snapshot of
/// whatever the form held at the moment of exit, alongside the current
/// photos — merging the old two steps means a retake can now happen *after*
/// the photographer has already typed in make/model/year, so without
/// carrying the draft forward, jumping back to the camera for one more angle
/// would silently wipe out everything already typed. [ReviewSubmit] needs no
/// such thing: it is the one exit with nothing left to resume.
library;

import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models/backdrop.dart';
import '../../api/models/url_vehicle_guess.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/authed_image.dart';
import 'capture_angles.dart';

/// What the review screen asked the pipeline for — the fields the server's
/// `VehicleListingCreate` requires plus an optional backdrop choice.
class VehicleDetails {
  const VehicleDetails({
    required this.make,
    required this.model,
    required this.year,
    this.variant,
  });

  final String make;
  final String model;
  final int year;
  final String? variant;
}

/// The vehicle-details form's raw, possibly-incomplete contents — carried
/// through [ReviewClosed] and [ReviewRetake] so re-opening this screen picks
/// up exactly where the form was left. Unlike [VehicleDetails], nothing here
/// is validated: a half-typed year or an empty make is exactly what a draft
/// looks like mid-edit.
class ReviewDraft {
  const ReviewDraft({
    this.make = '',
    this.model = '',
    this.year = '',
    this.variant = '',
    this.url = '',
    this.backdropId,
  });

  final String make;
  final String model;
  final String year;
  final String variant;
  final String url;
  final int? backdropId;
}

sealed class ReviewResult {
  const ReviewResult({required this.photos});
  final Map<CaptureAngle, XFile> photos;
}

/// The photographer closed the review without submitting. [CaptureScreen]
/// returns to the live camera with [photos] as the new source of truth, and
/// hands [draft] back the next time this screen opens.
final class ReviewClosed extends ReviewResult {
  const ReviewClosed({required super.photos, required this.draft});
  final ReviewDraft draft;
}

/// Reshoot one angle. [CaptureScreen] jumps the live camera to [angle] and
/// hands [draft] back the next time this screen opens.
final class ReviewRetake extends ReviewResult {
  const ReviewRetake({
    required this.angle,
    required super.photos,
    required this.draft,
  });
  final CaptureAngle angle;
  final ReviewDraft draft;
}

/// Create the listing, upload [photos] and queue it for processing.
final class ReviewSubmit extends ReviewResult {
  const ReviewSubmit({
    required super.photos,
    required this.details,
    this.backdropId,
  });
  final VehicleDetails details;
  final int? backdropId;
}

class ReviewScreen extends ConsumerStatefulWidget {
  const ReviewScreen({
    super.key,
    required this.initialCaptured,
    this.initialDraft = const ReviewDraft(),
  });

  final Map<CaptureAngle, XFile> initialCaptured;
  final ReviewDraft initialDraft;

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen> {
  late final Map<CaptureAngle, XFile> _photos = Map.of(widget.initialCaptured);

  final _formKey = GlobalKey<FormState>();
  final _detailsSectionKey = GlobalKey();
  late final _makeController = TextEditingController(
    text: widget.initialDraft.make,
  );
  late final _modelController = TextEditingController(
    text: widget.initialDraft.model,
  );
  late final _yearController = TextEditingController(
    text: widget.initialDraft.year.isEmpty
        ? DateTime.now().year.toString()
        : widget.initialDraft.year,
  );
  late final _variantController = TextEditingController(
    text: widget.initialDraft.variant,
  );
  late final _urlController = TextEditingController(
    text: widget.initialDraft.url,
  );
  late int? _selectedBackdropId = widget.initialDraft.backdropId;

  bool _autofilling = false;
  String? _autofillMessage;

  List<Backdrop>? _backdrops;
  String? _backdropsError;

  @override
  void initState() {
    super.initState();
    _loadBackdrops();
  }

  @override
  void dispose() {
    _makeController.dispose();
    _modelController.dispose();
    _yearController.dispose();
    _variantController.dispose();
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _loadBackdrops() async {
    try {
      final backdrops = await ref.read(apiClientProvider).backdrops();
      if (!mounted) return;
      setState(() {
        _backdrops = backdrops;
        // A draft's own choice always wins — only default when nothing had
        // been chosen yet before this fetch resolved.
        _selectedBackdropId ??= backdrops
            .where((b) => b.isDefault)
            .map((b) => b.id)
            .firstOrNullValue;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _backdropsError = e.message);
    }
  }

  Future<void> _autofillFromUrl() async {
    final url = _urlController.text.trim();
    if (url.isEmpty) return;
    setState(() {
      _autofilling = true;
      _autofillMessage = null;
    });
    try {
      final UrlVehicleGuess guess = await ref
          .read(apiClientProvider)
          .parseListingUrl(url);
      if (!mounted) return;
      if (guess.isEmpty) {
        setState(
          () => _autofillMessage =
              "That link's make, model and year "
              "could not be read — enter them below instead.",
        );
        return;
      }
      setState(() {
        if (guess.make != null) _makeController.text = guess.make!;
        if (guess.model != null) _modelController.text = guess.model!;
        if (guess.year != null) _yearController.text = guess.year.toString();
        if (guess.variant != null) _variantController.text = guess.variant!;
        _autofillMessage = 'Filled in below — check it before submitting.';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _autofillMessage = e.message);
    } finally {
      if (mounted) setState(() => _autofilling = false);
    }
  }

  ReviewDraft get _currentDraft => ReviewDraft(
    make: _makeController.text,
    model: _modelController.text,
    year: _yearController.text,
    variant: _variantController.text,
    url: _urlController.text,
    backdropId: _selectedBackdropId,
  );

  void _closeWithCurrentPhotos() => Navigator.of(
    context,
  ).pop(ReviewClosed(photos: _photos, draft: _currentDraft));

  Future<void> _openViewer(CaptureAngle angle) async {
    final file = _photos[angle];
    if (file == null) {
      // An unfilmed slot in the grid — tapping it means "shoot this one",
      // not "expand a photo that does not exist yet".
      Navigator.of(context).pop(
        ReviewRetake(angle: angle, photos: _photos, draft: _currentDraft),
      );
      return;
    }
    final action = await Navigator.of(context).push<_ViewerAction>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => _PhotoViewer(angle: angle, file: file),
      ),
    );
    if (!mounted) return;
    switch (action) {
      case _ViewerAction.retake:
        Navigator.of(context).pop(
          ReviewRetake(angle: angle, photos: _photos, draft: _currentDraft),
        );
      case _ViewerAction.delete:
        setState(() => _photos.remove(angle));
      case null:
        break;
    }
  }

  void _submit() {
    if (_photos.isEmpty) return;
    if (!(_formKey.currentState?.validate() ?? false)) {
      final sectionContext = _detailsSectionKey.currentContext;
      if (sectionContext != null) {
        Scrollable.ensureVisible(
          sectionContext,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
      return;
    }
    Navigator.of(context).pop(
      ReviewSubmit(
        photos: _photos,
        details: VehicleDetails(
          make: _makeController.text.trim(),
          model: _modelController.text.trim(),
          year: int.parse(_yearController.text.trim()),
          variant: _variantController.text.trim().isEmpty
              ? null
              : _variantController.text.trim(),
        ),
        backdropId: _selectedBackdropId,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _closeWithCurrentPhotos();
      },
      child: Scaffold(
        backgroundColor: C.paper,
        body: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  Space.md,
                  Space.sm,
                  Space.lg,
                  Space.sm,
                ),
                child: Row(
                  children: [
                    IconButton(
                      onPressed: _closeWithCurrentPhotos,
                      icon: const Icon(Icons.close, color: C.ink),
                      tooltip: 'Close',
                    ),
                    const SizedBox(width: Space.xs),
                    Expanded(
                      child: Text(
                        'Review · ${_photos.length} of '
                        '${CaptureAngle.values.length}',
                        style: T.label,
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(
                    Space.lg,
                    0,
                    Space.lg,
                    Space.lg,
                  ),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('PHOTOS', style: T.caption),
                        const SizedBox(height: Space.sm),
                        GridView.builder(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          gridDelegate:
                              const SliverGridDelegateWithMaxCrossAxisExtent(
                                maxCrossAxisExtent: 170,
                                mainAxisSpacing: Space.sm,
                                crossAxisSpacing: Space.sm,
                                childAspectRatio: 0.82,
                              ),
                          itemCount: CaptureAngle.values.length,
                          itemBuilder: (context, index) {
                            final angle = CaptureAngle.values[index];
                            return _GridTile(
                              angle: angle,
                              file: _photos[angle],
                              onTap: () => _openViewer(angle),
                            );
                          },
                        ),
                        const SizedBox(height: Space.xl),
                        Text(
                          'VEHICLE DETAILS',
                          key: _detailsSectionKey,
                          style: T.caption,
                        ),
                        const SizedBox(height: Space.md),
                        Text(
                          'FROM A LISTING URL (OPTIONAL)',
                          style: T.caption,
                        ),
                        const SizedBox(height: Space.sm),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: TextFormField(
                                controller: _urlController,
                                keyboardType: TextInputType.url,
                                decoration: const InputDecoration(
                                  labelText: 'Paste a listing link',
                                  hintText: 'https://…',
                                ),
                              ),
                            ),
                            const SizedBox(width: Space.sm),
                            FilledButton(
                              // minimumSize overrides the house-wide
                              // full-width default (see the equivalent note
                              // in listing_detail_screen.dart's delete
                              // dialog) — this button sits beside the URL
                              // field, not stretched across the row, and a
                              // bare FilledButton here would ask a Row for
                              // infinite width and crash.
                              style: FilledButton.styleFrom(
                                minimumSize: const Size(0, 48),
                              ),
                              onPressed: _autofilling
                                  ? null
                                  : _autofillFromUrl,
                              child: _autofilling
                                  ? const SizedBox(
                                      width: 16,
                                      height: 16,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: C.white,
                                      ),
                                    )
                                  : const Text('Fill in'),
                            ),
                          ],
                        ),
                        if (_autofillMessage != null) ...[
                          const SizedBox(height: Space.xs),
                          Text(_autofillMessage!, style: T.bodySmall),
                        ],
                        const SizedBox(height: Space.lg),
                        TextFormField(
                          controller: _makeController,
                          textCapitalization: TextCapitalization.words,
                          decoration: const InputDecoration(labelText: 'Make'),
                          validator: (value) =>
                              (value == null || value.trim().isEmpty)
                              ? 'Required'
                              : null,
                        ),
                        const SizedBox(height: Space.md),
                        TextFormField(
                          controller: _modelController,
                          textCapitalization: TextCapitalization.words,
                          decoration: const InputDecoration(
                            labelText: 'Model',
                          ),
                          validator: (value) =>
                              (value == null || value.trim().isEmpty)
                              ? 'Required'
                              : null,
                        ),
                        const SizedBox(height: Space.md),
                        TextFormField(
                          controller: _yearController,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(labelText: 'Year'),
                          validator: (value) {
                            final year = int.tryParse(value?.trim() ?? '');
                            if (year == null) return 'Enter a valid year';
                            if (year < 1886 || year > 2100) {
                              return 'Enter a valid year';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: Space.md),
                        TextFormField(
                          controller: _variantController,
                          textCapitalization: TextCapitalization.words,
                          decoration: const InputDecoration(
                            labelText: 'Variant (optional)',
                          ),
                        ),
                        const SizedBox(height: Space.lg),
                        Text('BACKDROP (OPTIONAL)', style: T.caption),
                        const SizedBox(height: Space.sm),
                        _backdropPicker(),
                      ],
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  Space.lg,
                  0,
                  Space.lg,
                  Space.lg,
                ),
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _photos.isEmpty ? null : _submit,
                    child: Text(
                      _photos.isEmpty
                          ? 'Take at least one photo to continue'
                          : 'Submit set (${_photos.length})',
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _backdropPicker() {
    if (_backdropsError != null) {
      return Text(
        "Couldn't load backdrops — the vehicle will be returned on a "
        'transparent background instead.',
        style: T.bodySmall,
      );
    }
    final backdrops = _backdrops;
    if (backdrops == null) {
      return const SizedBox(
        height: 32,
        child: Center(
          child: SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }
    if (backdrops.isEmpty) {
      return Text(
        'No backdrops in the library yet — the vehicle will be returned on '
        'a transparent background.',
        style: T.bodySmall,
      );
    }
    return SizedBox(
      height: 96,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: backdrops.length + 1,
        separatorBuilder: (_, _) => const SizedBox(width: Space.sm),
        itemBuilder: (context, index) {
          if (index == 0) {
            return _BackdropChoice(
              label: 'None',
              selected: _selectedBackdropId == null,
              onTap: () => setState(() => _selectedBackdropId = null),
            );
          }
          final backdrop = backdrops[index - 1];
          return _BackdropChoice(
            label: backdrop.name,
            imagePath: backdrop.imageUrl,
            selected: _selectedBackdropId == backdrop.id,
            onTap: () => setState(() => _selectedBackdropId = backdrop.id),
          );
        },
      ),
    );
  }
}

// ── Grid tile ────────────────────────────────────────────────────────────────

class _GridTile extends StatelessWidget {
  const _GridTile({
    required this.angle,
    required this.file,
    required this.onTap,
  });

  final CaptureAngle angle;
  final XFile? file;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final captured = file != null;

    return InkWell(
      onTap: onTap,
      borderRadius: Radii.controlAll,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: Radii.controlAll,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (captured)
                    Image.file(File(file!.path), fit: BoxFit.cover)
                  else
                    DecoratedBox(
                      decoration: BoxDecoration(
                        color: C.bone,
                        border: Border.all(color: C.line),
                      ),
                      child: const Center(
                        child: Icon(
                          Icons.camera_alt_outlined,
                          color: C.lineStrong,
                        ),
                      ),
                    ),
                  if (captured)
                    Positioned(
                      top: Space.xs,
                      right: Space.xs,
                      child: Container(
                        width: 22,
                        height: 22,
                        decoration: const BoxDecoration(
                          color: C.forestLift,
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(
                          Icons.check,
                          size: 14,
                          color: C.white,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            angle.label,
            style: T.caption,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

// ── Photo viewer ─────────────────────────────────────────────────────────────

enum _ViewerAction { retake, delete }

class _PhotoViewer extends StatelessWidget {
  const _PhotoViewer({required this.angle, required this.file});

  final CaptureAngle angle;
  final XFile file;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                Space.xs,
                Space.xs,
                Space.md,
                Space.sm,
              ),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close, color: C.white),
                    tooltip: 'Close',
                  ),
                  const SizedBox(width: Space.xs),
                  Expanded(
                    child: Text(
                      angle.label,
                      style: T.label.copyWith(color: C.white),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: Space.md),
                child: ClipRRect(
                  borderRadius: Radii.cardAll,
                  child: Image.file(File(file.path), fit: BoxFit.contain),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(Space.lg),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        foregroundColor: C.white,
                        side: const BorderSide(color: C.lineStrong),
                      ),
                      onPressed: () =>
                          Navigator.of(context).pop(_ViewerAction.retake),
                      icon: const Icon(Icons.replay),
                      label: const Text('Retake'),
                    ),
                  ),
                  const SizedBox(width: Space.sm),
                  Expanded(
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        foregroundColor: C.rust,
                        side: const BorderSide(color: C.rust),
                      ),
                      onPressed: () =>
                          Navigator.of(context).pop(_ViewerAction.delete),
                      icon: const Icon(Icons.delete_outline),
                      label: const Text('Delete'),
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

extension<T> on Iterable<T> {
  /// The first element, or null for an empty iterable — `firstWhere` has no
  /// such fallback built in, and pulling in `package:collection` for one
  /// method is not worth the new dependency.
  T? get firstOrNullValue {
    final iterator = this.iterator;
    return iterator.moveNext() ? iterator.current : null;
  }
}

class _BackdropChoice extends StatelessWidget {
  const _BackdropChoice({
    required this.label,
    required this.selected,
    required this.onTap,
    this.imagePath,
  });

  final String label;
  final String? imagePath;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: Radii.controlAll,
      child: Container(
        width: 76,
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          borderRadius: Radii.controlAll,
          border: Border.all(
            color: selected ? C.forestLift : C.line,
            width: selected ? 2 : 1,
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: imagePath == null
                    ? const DecoratedBox(
                        decoration: BoxDecoration(color: C.bone),
                        child: Icon(
                          Icons.block,
                          size: 18,
                          color: C.lineStrong,
                        ),
                      )
                    : AuthedImage(
                        storagePath: imagePath!,
                        semanticLabel: 'Backdrop: $label',
                        fit: BoxFit.cover,
                      ),
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: T.caption,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}
