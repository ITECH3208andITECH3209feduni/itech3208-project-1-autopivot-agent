// Widget tests for listing_detail_screen.dart's own header, the
// redo-with-a-new-backdrop control offered once a listing has nothing left
// outstanding, and the two include modes on an excluded original.
//
// medium_processing_test.dart already covers Process/Retry, needs-review and
// the processing banner against this same screen — deliberately not
// repeated here. The fixtures and the _FakeBackend/_openListing shape below
// mirror that file's own conventions rather than inventing new ones; see its
// header comment for why pump(Duration.zero) is used throughout instead of
// pumpAndSettle() — photographs never finish loading in these tests, so a
// shimmer placeholder is still animating when pumpAndSettle() would give up
// waiting for it.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/listing_detail/listing_detail_screen.dart';

const _at = '2026-09-25T09:00:00';

class _MemoryTokenStore extends TokenStore {
  // As in medium_processing_test.dart, the FlutterSecureStorage handed up is
  // never touched: every method below is overridden.
  _MemoryTokenStore([this.token]) : super(const FlutterSecureStorage());

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

/// Stands in for the server at the transport, as in
/// medium_processing_test.dart.
class _FakeBackend implements HttpClientAdapter {
  _FakeBackend(this._answer);

  final FutureOr<ResponseBody> Function(RequestOptions request) _answer;

  /// Every request received, in order.
  final received = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    received.add(options);
    return _answer(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(int status, Object body) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

ResponseBody _notFound() => _json(404, {'detail': 'Not found.'});

/// `VehicleListingOut`, as api/routes_listings.py serialises it.
Map<String, Object?> _listing(int id, String processingStatus) => {
  'id': id,
  'stock_number': null,
  'title': '2021 Mazda CX-5',
  'make': 'Mazda',
  'model': 'CX-5',
  'year': 2021,
  'variant': null,
  'price': null,
  'status': 'draft',
  'processing_status': processingStatus,
  'image_count': 1,
  'created_at': _at,
  'updated_at': _at,
};

/// `ImageOut`.
Map<String, Object?> _image(
  int id, {
  String type = 'original',
  int? sourceImageId,
  String? imageKind,
  bool keptWithoutProcessing = false,
}) => {
  'id': id,
  'image_type': type,
  'source_image_id': sourceImageId,
  'image_kind': imageKind,
  'kind_confidence': imageKind == null ? null : 0.9,
  'original_filename': 'IMG_$id.jpg',
  'image_url': '/api/files/3/$type/$id.jpg',
  'width': 4032,
  'height': 3024,
  'file_size_bytes': 2400000,
  'created_at': _at,
  'kept_without_processing': keptWithoutProcessing,
};

/// `VehicleListingDetail`.
Map<String, Object?> _detail(
  String processingStatus,
  List<Map<String, Object?>> images,
) => {..._listing(1, processingStatus), 'description': null, 'images': images};

/// `ProcessingJobOut`.
Map<String, Object?> _job(
  int inputImageId,
  String status, {
  String? reviewState,
  String? errorMessage,
  int? backdropId,
}) => {
  'id': 100 + inputImageId,
  'status': status,
  'processing_type': 'full_pipeline',
  'input_image_id': inputImageId,
  'output_image_id': null,
  'output_image_url': null,
  'backdrop_id': backdropId,
  'detected_angle': null,
  'angle_confidence': null,
  'plates_detected': null,
  'plate_treatment': null,
  'review_state': reviewState,
  'model_used': null,
  'error_message': errorMessage,
  'started_at': null,
  'completed_at': null,
};

/// `ProcessingSummary`, counted the way _summarise in routes_listings.py
/// counts it.
Map<String, Object?> _summary(
  String processingStatus, [
  List<Map<String, Object?>> jobs = const [],
]) => {
  'listing_id': 1,
  'processing_status': processingStatus,
  'total': jobs.length,
  'completed': jobs.where((j) => j['status'] == 'completed').length,
  'failed': jobs.where((j) => j['status'] == 'failed').length,
  'needs_review': jobs.where((j) => j['review_state'] == 'needs_review').length,
  'jobs': jobs,
};

/// `BackdropOut`.
Map<String, Object?> _backdrop(int id, String name, {bool isDefault = false}) =>
    {
      'id': id,
      'name': name,
      'is_default': isDefault,
      'image_url': '/api/files/backdrops/$id.jpg',
    };

ApiClient _client(_FakeBackend backend) =>
    ApiClient(baseUrl: 'http://autopivot.test', httpClientAdapter: backend);

/// Runs every request in flight to its answer, and builds what follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 30; i++) {
    await tester.pump(Duration.zero);
  }
}

/// A route or dialog pushed, animated all the way — a confirmation dialog is
/// itself a route (showDialog pushes one), so this is needed for it the same
/// way medium_processing_test.dart's own _transition is needed for a
/// Navigator push.
Future<void> _transition(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
  await _settle(tester);
}

/// Listing 1's own screen, answered by [answer].
///
/// [disableAnimations] stands in for the OS-level reduced-motion setting —
/// see `MediaQueryData.disableAnimations`. Wrapping just below [MaterialApp]
/// rather than above it is deliberate: [MaterialApp] builds its own
/// [MediaQuery] from the real test view, and the nearest ancestor is what
/// `MediaQuery.of` resolves, so a wrapper above it would simply be shadowed.
Future<_FakeBackend> _openListing(
  WidgetTester tester,
  FutureOr<ResponseBody> Function(RequestOptions request) answer, {
  bool disableAnimations = false,
}) async {
  final backend = _FakeBackend(answer);
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore()),
      apiClientProvider.overrideWithValue(_client(backend)),
    ],
  );
  addTearDown(container.dispose);
  const screen = ListingDetailScreen(listingId: 1);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        home: disableAnimations
            ? const MediaQuery(
                data: MediaQueryData(disableAnimations: true),
                child: screen,
              )
            : screen,
      ),
    ),
  );
  await _settle(tester);
  return backend;
}

/// The before/after tile's own Semantics label, which already carries
/// `_split`'s current value as a percentage — read here rather than
/// reaching into that private state across a library boundary, which this
/// test file cannot do at all.
int _beforeAfterSplitPercent(WidgetTester tester) {
  final finder = find.byWidgetPredicate(
    (widget) =>
        widget is Semantics &&
        (widget.properties.label?.startsWith('Before and after comparison') ??
            false),
  );
  expect(finder, findsOneWidget);
  final label = tester.widget<Semantics>(finder).properties.label!;
  return int.parse(RegExp(r'(\d+)% original').firstMatch(label)!.group(1)!);
}

/// The one [GestureDetector] inside the before/after tile — scoped to that
/// tile's own Semantics subtree so a drag lands on it specifically, not on
/// one of the several other GestureDetectors buttons on this screen build
/// internally.
Finder _beforeAfterGestureDetector() => find.descendant(
  of: find.byWidgetPredicate(
    (widget) =>
        widget is Semantics &&
        (widget.properties.label?.startsWith('Before and after comparison') ??
            false),
  ),
  matching: find.byType(GestureDetector),
);

/// Advances exactly through the before/after tile's own one-shot auto-sweep
/// — a real pumpAndSettle() would also chase the shimmer placeholder every
/// before/after photograph falls back to (see this file's own header
/// comment), which never resolves against the fake backend and so never
/// settles.
Future<void> _runSweepToEnd(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 1400));
  await tester.pump();
}

void main() {
  group('the header', () {
    testWidgets(
      'offers a single, direct delete action with no intermediate menu',
      (tester) async {
        await _openListing(tester, (request) {
          switch ((request.method, request.path)) {
            case ('GET', '/api/listings/1'):
              return _json(200, _detail('pending', [_image(11)]));
            case ('GET', '/api/listings/1/jobs'):
              return _json(200, _summary('pending'));
            case ('GET', '/api/backdrops'):
              return _json(200, <Object?>[]);
          }
          return _notFound();
        });

        // No overflow menu left to open...
        expect(find.byType(PopupMenuButton<void>), findsNothing);
        // ...just the action itself, straight in the header.
        expect(find.byTooltip('Delete listing'), findsOneWidget);
      },
    );

    testWidgets('still confirms before deleting anything', (tester) async {
      final backend = await _openListing(tester, (request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(200, _detail('pending', [_image(11)]));
          case ('GET', '/api/listings/1/jobs'):
            return _json(200, _summary('pending'));
          case ('GET', '/api/backdrops'):
            return _json(200, <Object?>[]);
          case ('DELETE', '/api/listings/1'):
            return _json(200, {});
        }
        return _notFound();
      });

      await tester.tap(find.byTooltip('Delete listing'));
      await _transition(tester);

      // The confirmation dialog this screen has always shown — only the
      // "open a menu to find the option" step was meant to go.
      expect(find.text('Delete "2021 Mazda CX-5"?'), findsOneWidget);
      expect(backend.received.where((r) => r.method == 'DELETE'), isEmpty);

      await tester.tap(find.widgetWithText(FilledButton, 'Delete listing'));
      await _transition(tester);

      expect(backend.received.where((r) => r.method == 'DELETE'), hasLength(1));
    });
  });

  group('a complete listing', () {
    testWidgets('still offers a backdrop picker and a redo action', (
      tester,
    ) async {
      Object? redoneWith;
      await _openListing(tester, (request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(
              200,
              _detail('complete', [
                _image(11),
                _image(21, type: 'processed', sourceImageId: 11),
              ]),
            );
          case ('GET', '/api/listings/1/jobs'):
            return _json(
              200,
              _summary('complete', [
                _job(11, 'completed', reviewState: 'ok', backdropId: 3),
              ]),
            );
          case ('GET', '/api/backdrops'):
            return _json(200, [_backdrop(5, 'Studio White')]);
          case ('POST', '/api/listings/1/process'):
            redoneWith = request.data;
            return _json(
              200,
              _summary('processing', [_job(11, 'pending', backdropId: 5)]),
            );
        }
        return _notFound();
      });

      // Nothing outstanding — Process/Retry's own sections are absent.
      expect(find.textContaining('AWAITING PROCESSING'), findsNothing);
      expect(find.textContaining('NEEDS REVIEW'), findsNothing);
      expect(find.text('REDO WITH A NEW BACKDROP'), findsOneWidget);

      final backdropChoice = find.text('Studio White');
      await tester.ensureVisible(backdropChoice);
      await tester.pump();
      await tester.tap(backdropChoice);
      await _settle(tester);

      final redo = find.widgetWithText(TextButton, 'Redo');
      expect(redo, findsOneWidget);
      await tester.ensureVisible(redo);
      await tester.pump();
      await tester.tap(redo);
      await _settle(tester);

      expect(redoneWith, {'backdrop_id': 5, 'force': true});
    });
  });

  group('an excluded original', () {
    testWidgets('offers Include, which reprocesses it through the pipeline', (
      tester,
    ) async {
      Object? includedWith;
      await _openListing(tester, (request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(
              200,
              _detail('needs_review', [_image(11, imageKind: 'interior')]),
            );
          case ('GET', '/api/listings/1/jobs'):
            return _json(200, _summary('needs_review'));
          case ('GET', '/api/backdrops'):
            return _json(200, <Object?>[]);
          case ('POST', '/api/listings/1/images/11/include'):
            includedWith = request.data;
            return _json(200, _image(11, imageKind: 'exterior'));
        }
        return _notFound();
      });

      expect(find.text('EXCLUDED (1)'), findsOneWidget);
      // Two distinct actions sit on the tile at once — not one button
      // doing double duty.
      final include = find.widgetWithText(TextButton, 'Include');
      final keep = find.widgetWithText(TextButton, 'Keep as-is');
      expect(include, findsOneWidget);
      expect(keep, findsOneWidget);

      await tester.ensureVisible(include);
      await tester.pump();
      await tester.tap(include);
      await _settle(tester);

      expect(includedWith, {'mode': 'rerun'});
      // Reclassified as exterior, so it is no longer excluded at all.
      expect(find.textContaining('EXCLUDED'), findsNothing);
    });

    testWidgets(
      'offers Keep as-is, which leaves the classifier verdict untouched',
      (tester) async {
        Object? includedWith;
        await _openListing(tester, (request) {
          switch ((request.method, request.path)) {
            case ('GET', '/api/listings/1'):
              return _json(
                200,
                _detail('needs_review', [_image(11, imageKind: 'interior')]),
              );
            case ('GET', '/api/listings/1/jobs'):
              return _json(200, _summary('needs_review'));
            case ('GET', '/api/backdrops'):
              return _json(200, <Object?>[]);
            case ('POST', '/api/listings/1/images/11/include'):
              includedWith = request.data;
              return _json(
                200,
                _image(11, imageKind: 'interior', keptWithoutProcessing: true),
              );
          }
          return _notFound();
        });

        final keep = find.widgetWithText(TextButton, 'Keep as-is');
        final include = find.widgetWithText(TextButton, 'Include');
        expect(keep, findsOneWidget);
        expect(include, findsOneWidget);

        await tester.ensureVisible(keep);
        await tester.pump();
        await tester.tap(keep);
        await _settle(tester);

        expect(includedWith, {'mode': 'keep_only'});
        // image_kind is still 'interior' server-side, but
        // kept_without_processing now makes it read as a normal kept
        // original rather than an excluded one.
        expect(find.textContaining('EXCLUDED'), findsNothing);
      },
    );
  });

  group('the before/after auto-sweep', () {
    FutureOr<ResponseBody> onePairAnswer(RequestOptions request) =>
        switch ((request.method, request.path)) {
          ('GET', '/api/listings/1') => _json(
            200,
            _detail('complete', [
              _image(11),
              _image(21, type: 'processed', sourceImageId: 11),
            ]),
          ),
          ('GET', '/api/listings/1/jobs') => _json(
            200,
            _summary('complete', [_job(11, 'completed', reviewState: 'ok')]),
          ),
          ('GET', '/api/backdrops') => _json(200, <Object?>[]),
          _ => _notFound(),
        };

    testWidgets(
      'plays once on first appearance and settles back at the midpoint',
      (tester) async {
        await _openListing(tester, onePairAnswer);

        // Partway through the sweep the split has genuinely moved away from
        // its resting point — proof this is actually sweeping, not just
        // sitting at the midpoint the whole time.
        await tester.pump(const Duration(milliseconds: 200));
        expect(_beforeAfterSplitPercent(tester), isNot(50));

        // ...and settles back there once the one-shot sweep finishes.
        await _runSweepToEnd(tester);
        expect(_beforeAfterSplitPercent(tester), 50);
      },
    );

    testWidgets(
      'never moves at all when the platform asks for reduced motion',
      (tester) async {
        await _openListing(tester, onePairAnswer, disableAnimations: true);

        expect(_beforeAfterSplitPercent(tester), 50);

        // At the moment it would otherwise be mid-sweep, it still has not
        // moved — not merely "back to 50" by the time everything settles.
        await tester.pump(const Duration(milliseconds: 200));
        expect(_beforeAfterSplitPercent(tester), 50);

        await _runSweepToEnd(tester);
        expect(_beforeAfterSplitPercent(tester), 50);
      },
    );

    testWidgets(
      'a drag mid-sweep takes over immediately and is not overridden by the '
      'rest of the sweep',
      (tester) async {
        await _openListing(tester, onePairAnswer);

        // Mid-flight, well before the sweep would naturally finish.
        await tester.pump(const Duration(milliseconds: 500));

        final detector = _beforeAfterGestureDetector();
        final width = tester.getSize(detector).width;
        await tester.drag(detector, Offset(width * 0.4, 0));
        await tester.pump();

        expect(_beforeAfterSplitPercent(tester), 90);

        // The sweep had roughly 800ms left to run; none of it should move
        // the split away from where the drag just put it.
        await tester.pump(const Duration(milliseconds: 900));
        expect(_beforeAfterSplitPercent(tester), 90);
      },
    );
  });

  group('the processing-complete celebration', () {
    testWidgets(
      'fires once when the pipeline finishes while the screen is open and '
      'polling',
      (tester) async {
        var jobsCalls = 0;
        await _openListing(tester, (request) {
          switch ((request.method, request.path)) {
            case ('GET', '/api/listings/1'):
              return _json(
                200,
                _detail(jobsCalls == 0 ? 'processing' : 'complete', [
                  _image(11),
                ]),
              );
            case ('GET', '/api/listings/1/jobs'):
              jobsCalls++;
              return _json(
                200,
                jobsCalls == 1
                    ? _summary('processing', [_job(11, 'processing')])
                    : _summary('complete', [
                        _job(11, 'completed', reviewState: 'ok'),
                      ]),
              );
            case ('GET', '/api/backdrops'):
              return _json(200, <Object?>[]);
          }
          return _notFound();
        });

        expect(find.byIcon(Icons.check_circle), findsNothing);

        // The poll tick 4 seconds in finds the pipeline has finished.
        await tester.pump(const Duration(seconds: 4));
        await _settle(tester);
        expect(find.byIcon(Icons.check_circle), findsOneWidget);

        // One-shot: it does not linger on screen forever. Two separate
        // advances, not one large one — the linger timer is itself only
        // scheduled once the bounce-in animation completes, so it needs its
        // own pump window after that happens rather than a single jump
        // sized to cover both up front.
        await tester.pump(const Duration(milliseconds: 600));
        await _settle(tester);
        await tester.pump(const Duration(milliseconds: 1000));
        await _settle(tester);
        expect(find.byIcon(Icons.check_circle), findsNothing);
      },
    );

    testWidgets(
      'does not fire when an already-complete listing is simply opened',
      (tester) async {
        await _openListing(tester, (request) {
          switch ((request.method, request.path)) {
            case ('GET', '/api/listings/1'):
              return _json(200, _detail('complete', [_image(11)]));
            case ('GET', '/api/listings/1/jobs'):
              return _json(
                200,
                _summary('complete', [
                  _job(11, 'completed', reviewState: 'ok'),
                ]),
              );
            case ('GET', '/api/backdrops'):
              return _json(200, <Object?>[]);
          }
          return _notFound();
        });

        expect(find.byIcon(Icons.check_circle), findsNothing);
      },
    );

    testWidgets('shows its settled look immediately under reduced motion', (
      tester,
    ) async {
      var jobsCalls = 0;
      await _openListing(tester, (request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(
              200,
              _detail(jobsCalls == 0 ? 'processing' : 'complete', [_image(11)]),
            );
          case ('GET', '/api/listings/1/jobs'):
            jobsCalls++;
            return _json(
              200,
              jobsCalls == 1
                  ? _summary('processing', [_job(11, 'processing')])
                  : _summary('complete', [
                      _job(11, 'completed', reviewState: 'ok'),
                    ]),
            );
          case ('GET', '/api/backdrops'):
            return _json(200, <Object?>[]);
        }
        return _notFound();
      }, disableAnimations: true);

      // No bounce-in to wait for — the poll tick alone is enough for the
      // checkmark to already be at its settled look, with no further
      // time needing to pass. Read via FadeTransition.opacity's own
      // current value rather than any pump-and-check-later dance: under
      // normal motion this would still read near 0 immediately after
      // mounting, since the bounce-in has not had any real time to run.
      await tester.pump(const Duration(seconds: 4));
      await _settle(tester);
      final icon = find.byIcon(Icons.check_circle);
      expect(icon, findsOneWidget);
      final fade = tester.widget<FadeTransition>(
        find.ancestor(of: icon, matching: find.byType(FadeTransition)).first,
      );
      expect(fade.opacity.value, 1.0);

      // Drains the still-pending linger timer before the test ends —
      // flutter_test's own binding asserts none are left pending at
      // teardown.
      await tester.pump(const Duration(milliseconds: 1000));
      await _settle(tester);
    });
  });
}
