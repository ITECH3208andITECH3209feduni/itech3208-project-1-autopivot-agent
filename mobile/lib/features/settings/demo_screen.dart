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
/// list. Rather than hide that, [_demoMake]/[_demoModel] make the result
/// unmistakable in "All vehicles" instead of quietly resembling real
/// inventory — and every run after the first goes back to that same listing
/// rather than making another (see [_DemoScreenState._sampleListing]).
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../api/api_exception.dart';
import '../../api/models/listing_detail.dart';
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

  /// Puts the bundled photograph on [listingId]. Straight from the asset
  /// bundle: it used to be copied out to a temporary file first, only for
  /// [ApiClient.uploadImages] to read it back in.
  Future<void> _uploadSample(ApiClient api, int listingId) async {
    final asset = await rootBundle.load(_demoAssetPath);
    await api.uploadImageBytes(
      listingId,
      asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes),
      filename: 'autopivot-demo-car.jpg',
    );
  }

  /// The sample listing with its photograph on it: the one an earlier run
  /// left, or else a new one.
  ///
  /// The server stores a photograph once, under a content hash that has to
  /// be unique, so a second copy of the same bundled sample is refused ("One
  /// of those photographs has already been uploaded."). Making a new listing
  /// every time failed there on every run after the first, and left another
  /// empty "Demo Sample Vehicle" behind each time. A new listing whose upload
  /// is refused anyway — the sample already on a listing since renamed — is
  /// taken back out rather than left empty.
  Future<VehicleListingDetail> _sampleListing(ApiClient api) async {
    final earlier = (await api.listings(query: '$_demoMake $_demoModel'))
        .where((l) => l.make == _demoMake && l.model == _demoModel)
        .firstOrNull;
    if (earlier != null) {
      final listing = await api.listing(earlier.id);
      // Its photograph deleted since, the way to be rid of the sample, so it
      // goes back on.
      if (listing.originals.isEmpty) await _uploadSample(api, listing.id);
      return listing;
    }

    final created = await api.createListing(
      make: _demoMake,
      model: _demoModel,
      year: DateTime.now().year,
    );
    try {
      await _uploadSample(api, created.id);
    } on ApiException {
      try {
        await api.deleteListing(created.id);
      } on ApiException {
        // Left behind after all, empty and plainly named; the refusal that
        // caused this is the thing worth reporting.
      }
      rethrow;
    }
    return created;
  }

  Future<void> _startDemo() async {
    if (_running) return;
    setState(() {
      _running = true;
      _errorMessage = null;
    });

    final api = ref.read(apiClientProvider);
    try {
      final listing = await _sampleListing(api);
      // A processing failure here does not undo the listing or the upload —
      // both are real either way — so it is worth reaching the listing
      // screen regardless; see capture_screen.dart's own _submitListing for
      // the same reasoning between these two calls. A second run over a
      // sample already processed is refused as "nothing to process", which
      // is no reason not to show it again either.
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
                'separate from real inventory, and runs again on that same '
                'listing next time — delete it from the listing screen if '
                'you want it gone.',
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
