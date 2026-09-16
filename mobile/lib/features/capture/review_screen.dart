/// The screen shown after capture, replacing the old "submit" bottom sheet.
///
/// Two steps in one screen rather than two routes: a photo grid — tap any
/// tile to expand it with Retake / Delete this angle / Close — then an
/// overview step asking for make, model, year and an optional backdrop
/// before submitting. [CaptureScreen] pushes this and reads back a
/// [ReviewResult] once it closes; every branch of that result carries the
/// current [ReviewResult.photos] map, so a photo deleted here is never lost
/// even if the review ends in a retake rather than a submit.
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

sealed class ReviewResult {
  const ReviewResult({required this.photos});
  final Map<CaptureAngle, XFile> photos;
}

/// The photographer closed the review without submitting. [CaptureScreen]
/// returns to the live camera with [photos] as the new source of truth.
final class ReviewClosed extends ReviewResult {
  const ReviewClosed({required super.photos});
}

/// Reshoot one angle. [CaptureScreen] jumps the live camera to [angle].
final class ReviewRetake extends ReviewResult {
  const ReviewRetake({required this.angle, required super.photos});
  final CaptureAngle angle;
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

enum _Step { grid, overview }

class ReviewScreen extends ConsumerStatefulWidget {
  const ReviewScreen({super.key, required this.initialCaptured});

  final Map<CaptureAngle, XFile> initialCaptured;

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen> {
  late final Map<CaptureAngle, XFile> _photos = Map.of(widget.initialCaptured);
  _Step _step = _Step.grid;

  void _closeWithCurrentPhotos() =>
      Navigator.of(context).pop(ReviewClosed(photos: _photos));

  Future<void> _openViewer(CaptureAngle angle) async {
    final file = _photos[angle];
    if (file == null) {
      // An unfilmed slot in the grid — tapping it means "shoot this one",
      // not "expand a photo that does not exist yet".
      Navigator.of(context).pop(ReviewRetake(angle: angle, photos: _photos));
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
        Navigator.of(context).pop(ReviewRetake(angle: angle, photos: _photos));
      case _ViewerAction.delete:
        setState(() => _photos.remove(angle));
      case null:
        break;
    }
  }

  void _submit(VehicleDetails details, int? backdropId) {
    Navigator.of(context).pop(
      ReviewSubmit(photos: _photos, details: details, backdropId: backdropId),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _closeWithCurrentPhotos();
      },
      child: switch (_step) {
        _Step.grid => _GridStep(
          photos: _photos,
          onClose: _closeWithCurrentPhotos,
          onOpen: _openViewer,
          onContinue: _photos.isNotEmpty
              ? () => setState(() => _step = _Step.overview)
              : null,
        ),
        _Step.overview => _OverviewStep(
          photoCount: _photos.length,
          onBack: () => setState(() => _step = _Step.grid),
          onSubmit: _submit,
        ),
      },
    );
  }
}

// ── Grid step ────────────────────────────────────────────────────────────────

class _GridStep extends StatelessWidget {
  const _GridStep({
    required this.photos,
    required this.onClose,
    required this.onOpen,
    required this.onContinue,
  });

  final Map<CaptureAngle, XFile> photos;
  final VoidCallback onClose;
  final ValueChanged<CaptureAngle> onOpen;
  final VoidCallback? onContinue;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
                    onPressed: onClose,
                    icon: const Icon(Icons.close, color: C.ink),
                    tooltip: 'Close',
                  ),
                  const SizedBox(width: Space.xs),
                  Expanded(
                    child: Text(
                      'Review · ${photos.length} of ${CaptureAngle.values.length}',
                      style: T.label,
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.fromLTRB(
                  Space.lg,
                  0,
                  Space.lg,
                  Space.lg,
                ),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
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
                    file: photos[angle],
                    onTap: () => onOpen(angle),
                  );
                },
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
                  onPressed: onContinue,
                  child: Text(
                    photos.isEmpty
                        ? 'Take at least one photo to continue'
                        : 'Continue',
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

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

// ── Overview step ────────────────────────────────────────────────────────────

class _OverviewStep extends ConsumerStatefulWidget {
  const _OverviewStep({
    required this.photoCount,
    required this.onBack,
    required this.onSubmit,
  });

  final int photoCount;
  final VoidCallback onBack;
  final void Function(VehicleDetails details, int? backdropId) onSubmit;

  @override
  ConsumerState<_OverviewStep> createState() => _OverviewStepState();
}

class _OverviewStepState extends ConsumerState<_OverviewStep> {
  final _formKey = GlobalKey<FormState>();
  final _makeController = TextEditingController();
  final _modelController = TextEditingController();
  final _yearController = TextEditingController(
    text: DateTime.now().year.toString(),
  );
  final _variantController = TextEditingController();
  final _urlController = TextEditingController();

  bool _autofilling = false;
  String? _autofillMessage;

  List<Backdrop>? _backdrops;
  String? _backdropsError;
  int? _selectedBackdropId;

  @override
  void initState() {
    super.initState();
    _loadBackdrops();
  }

  Future<void> _loadBackdrops() async {
    try {
      final backdrops = await ref.read(apiClientProvider).backdrops();
      if (!mounted) return;
      setState(() {
        _backdrops = backdrops;
        _selectedBackdropId = backdrops
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

  void _confirm() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    widget.onSubmit(
      VehicleDetails(
        make: _makeController.text.trim(),
        model: _modelController.text.trim(),
        year: int.parse(_yearController.text.trim()),
        variant: _variantController.text.trim().isEmpty
            ? null
            : _variantController.text.trim(),
      ),
      _selectedBackdropId,
    );
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
                    onPressed: widget.onBack,
                    icon: const Icon(Icons.arrow_back, color: C.ink),
                    tooltip: 'Back to photos',
                  ),
                  const SizedBox(width: Space.xs),
                  Text('Vehicle details', style: T.label),
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
                      Text(
                        '${widget.photoCount} photograph'
                        '${widget.photoCount == 1 ? '' : 's'} ready to submit.',
                        style: T.bodySmall,
                      ),
                      const SizedBox(height: Space.lg),
                      Text('FROM A LISTING URL (OPTIONAL)', style: T.caption),
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
                            onPressed: _autofilling ? null : _autofillFromUrl,
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
                        decoration: const InputDecoration(labelText: 'Model'),
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
                      const SizedBox(height: Space.xl),
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
                  onPressed: _confirm,
                  child: Text('Submit set (${widget.photoCount})'),
                ),
              ),
            ),
          ],
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
                        child: Icon(Icons.block, size: 18, color: C.lineStrong),
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
