/// A guided walkthrough of AutoPivot's real pipeline using a bundled sample
/// photograph, for showing a prospective client (or anyone else) what
/// processing actually produces — without needing a vehicle in front of the
/// presenter, or a finished set already sitting on the account.
///
/// Deliberately not a canned before/after image pair: this creates a real
/// listing through the same three calls `capture_screen.dart`'s own submit
/// makes — create, upload, process — so what plays out afterward (the real
/// processing status, the real background removal, the real before/after
/// slider on the listing screen) is the actual product working, not a
/// mockup of it standing in for a live demo. `assets/demo/demo_car.jpg`
/// exists purely so this has something to submit without a camera.
///
/// The listing it creates is a real row in the dealership's own vehicle
/// list, and mobile has no way to delete a whole listing yet — only one
/// photograph at a time (`ApiClient.deleteImage`). Rather than hide that,
/// [_demoMake]/[_demoModel] make the result unmistakable in "All vehicles"
/// instead of quietly resembling real inventory.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:path_provider/path_provider.dart';

import '../../api/api_exception.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../routes.dart';
import '../../widgets/primitives.dart';

const _demoAssetPath = 'assets/demo/demo_car.jpg';
const _demoMake = 'Demo';
const _demoModel = 'Sample Vehicle';

class DemoScreen extends ConsumerStatefulWidget {
  const DemoScreen({super.key});

  @override
  ConsumerState<DemoScreen> createState() => _DemoScreenState();
}

class _DemoScreenState extends ConsumerState<DemoScreen> {
  bool _running = false;
  String? _errorMessage;

  /// Copies the bundled asset out to a real file — `ApiClient.uploadImages`
  /// takes filesystem paths, the same multipart contract a photograph fresh
  /// out of the camera satisfies, and an asset bundled into the app package
  /// is not one of those until it exists somewhere on disk.
  Future<String> _demoImagePath() async {
    final bytes = await rootBundle.load(_demoAssetPath);
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/autopivot-demo-car.jpg');
    await file.writeAsBytes(bytes.buffer.asUint8List(), flush: true);
    return file.path;
  }

  Future<void> _startDemo() async {
    if (_running) return;
    setState(() {
      _running = true;
      _errorMessage = null;
    });

    final api = ref.read(apiClientProvider);
    try {
      final path = await _demoImagePath();
      final listing = await api.createListing(
        make: _demoMake,
        model: _demoModel,
        year: DateTime.now().year,
      );
      await api.uploadImages(listing.id, [path]);
      // A processing failure here does not undo the listing or the upload —
      // both are real either way — so it is worth reaching the listing
      // screen regardless; see capture_screen.dart's own _submitListing for
      // the same reasoning between these two calls.
      try {
        await api.processListing(listing.id);
      } on ApiException {
        // Surfaces on the listing screen itself once there, the same as it
        // would for a real submission — nothing further to do with it here.
      }
      if (!mounted) return;
      context.push(AppRoutes.listingDetailPath(listing.id));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            Space.lg,
            Space.sm,
            Space.lg,
            Space.xl,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  IconButton(
                    onPressed: _running
                        ? null
                        : () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.arrow_back, color: C.inkSoft),
                    tooltip: 'Back',
                  ),
                  const SizedBox(width: Space.xs),
                  Padding(
                    padding: const EdgeInsets.only(top: Space.sm),
                    child: Text('Sample car', style: serif(28)),
                  ),
                ],
              ),
              const SizedBox(height: Space.md),
              ClipRRect(
                borderRadius: Radii.cardAll,
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Image.asset(_demoAssetPath, fit: BoxFit.cover),
                ),
              ),
              const SizedBox(height: Space.lg),
              Text(
                'Nothing to photograph — this runs one sample photograph '
                'through the real pipeline on this account: a genuine '
                'listing, a genuine background removal, a genuine plate '
                'check. What you see afterward is what the product '
                'actually does.',
                style: T.body,
              ),
              const SizedBox(height: Space.sm),
              Text(
                "It creates a real listing on this dealership's account, "
                'titled "$_demoMake $_demoModel" so it stays obviously '
                "separate from real inventory — delete its photograph "
                'afterward from the listing screen if you want it gone.',
                style: T.bodySmall,
              ),
              if (_errorMessage != null) ...[
                const SizedBox(height: Space.lg),
                AppErrorBanner(_errorMessage!),
              ],
              const SizedBox(height: Space.xl),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _running ? null : _startDemo,
                  child: Text(_running ? 'Starting…' : 'Start the demo'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
