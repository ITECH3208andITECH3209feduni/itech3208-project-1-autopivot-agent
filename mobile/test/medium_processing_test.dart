// "Processing", and what is not: lib/api/models/processing_summary.dart, the
// listing screen that polls it (lib/features/listing_detail/), and the banner
// in the app's chrome that counts it (lib/widgets/processing_banner.dart).
//
// On the server a listing is 'pending' until anything at all has been queued
// for it — no jobs, not jobs waiting (_refresh_listing_status in
// api/processing.py) — and a light API with no vision stack refuses to queue
// anything, so there it stays 'pending' for good. 'processing' means a job is
// queued or running. A failed job's review_state stays null; its
// error_message says why.
//
// The real ApiClient makes every request, over a stand-in transport, as in
// session_expiry_test.dart. Photographs never finish loading here — their
// bytes go through path_provider, which nothing answers in these tests — so
// every tile stays a shimmering placeholder, which is one more reason these
// settle with pump(Duration.zero) and never pumpAndSettle().

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/api/models/processing_summary.dart';
import 'package:autopivot/app.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/auth/token_store.dart';
import 'package:autopivot/features/listing_detail/listing_detail_screen.dart';
import 'package:autopivot/features/listings/listings_screen.dart';

const _at = '2026-09-25T09:00:00';
const _interrupted = 'Interrupted — the server stopped before it finished.';

class _MemoryTokenStore extends TokenStore {
  // As in widget_test.dart, the FlutterSecureStorage handed up is never
  // touched: every method below is overridden.
  _MemoryTokenStore([this.token]) : super(const FlutterSecureStorage());

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

/// Stands in for the server at the transport, as in session_expiry_test.dart.
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

Map<String, Object?> _user() => {
  'id': 7,
  'email': 'sam@northshore.test',
  'first_name': 'Sam',
  'last_name': 'Taylor',
  'role': 'dealership_staff',
  'is_active': true,
  'must_change_password': false,
  'dealership': {
    'id': 3,
    'name': 'North Shore Motors',
    'location': 'Auckland',
    'contact_name': null,
    'contact_email': null,
    'contact_phone': null,
    'status': 'active',
    'user_count': 4,
  },
};

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
  'image_count': 2,
  'created_at': _at,
  'updated_at': _at,
};

/// `ImageOut`.
Map<String, Object?> _image(
  int id, {
  String type = 'original',
  int? sourceImageId,
}) => {
  'id': id,
  'image_type': type,
  'source_image_id': sourceImageId,
  'image_kind': null,
  'kind_confidence': null,
  'original_filename': 'IMG_$id.jpg',
  'image_url': '/api/files/3/$type/$id.jpg',
  'width': 4032,
  'height': 3024,
  'file_size_bytes': 2400000,
  'created_at': _at,
};

/// `VehicleListingDetail`.
Map<String, Object?> _detail(
  String processingStatus,
  List<Map<String, Object?>> images,
) => {..._listing(1, processingStatus), 'description': null, 'images': images};

/// `ProcessingJobOut`, the latest attempt for one photograph.
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

/// A summary as the client reads it off the wire.
ProcessingSummary _parsed(
  String processingStatus, [
  List<Map<String, Object?>> jobs = const [],
]) => ProcessingSummary.fromJson(
  jsonDecode(jsonEncode(_summary(processingStatus, jobs)))
      as Map<String, dynamic>,
);

ApiClient _client(_FakeBackend backend) =>
    ApiClient(baseUrl: 'http://autopivot.test', httpClientAdapter: backend);

/// Runs every request in flight to its answer, and builds what follows.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 30; i++) {
    await tester.pump(Duration.zero);
  }
}

/// A route pushed or popped, animated all the way.
Future<void> _transition(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
  await _settle(tester);
}

/// Listing 1's own screen, answered by [answer].
Future<_FakeBackend> _openListing(
  WidgetTester tester,
  FutureOr<ResponseBody> Function(RequestOptions request) answer,
) async {
  final backend = _FakeBackend(answer);
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore()),
      apiClientProvider.overrideWithValue(_client(backend)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: ListingDetailScreen(listingId: 1)),
    ),
  );
  await _settle(tester);
  return backend;
}

/// The whole app at cold start, signed in to a dealership whose vehicles are
/// [processing] and [pending] — the only two filters the banner could ask
/// for. Every other list is empty.
Future<void> _coldStart(
  WidgetTester tester, {
  required List<Map<String, Object?>> processing,
  List<Map<String, Object?>> pending = const [],
}) async {
  final backend = _FakeBackend((request) {
    switch (request.path) {
      case '/auth/me':
        return _json(200, _user());
      case '/api/dashboard/stats':
        return _json(200, {
          'vehicles_this_month': 0,
          'images_processed': 0,
          'needs_review': 0,
        });
      case '/api/listings':
        return _json(
          200,
          switch (request.queryParameters['processing_status']) {
            'processing' => processing,
            'pending' => pending,
            _ => <Object?>[],
          },
        );
    }
    return _notFound();
  });
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(_MemoryTokenStore('from-earlier')),
      apiClientProvider.overrideWithValue(_client(backend)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const AutoPivotApp(),
    ),
  );
  // What AppBootstrap.initState does, called directly for the reason
  // widget_test.dart gives.
  unawaited(container.read(authProvider.notifier).restore());
  await _settle(tester);
}

void main() {
  group('ProcessingSummary.isInProgress', () {
    test('is false for a listing nothing was ever queued for', () {
      expect(_parsed('pending').isInProgress, isFalse);
    });

    test('is true while the pipeline works through a listing', () {
      expect(
        _parsed('processing', [
          _job(11, 'processing'),
          _job(12, 'pending'),
        ]).isInProgress,
        isTrue,
      );
    });

    test('is true while any photograph is still queued', () {
      expect(
        _parsed('needs_review', [
          _job(11, 'failed', errorMessage: _interrupted),
          _job(12, 'pending'),
        ]).isInProgress,
        isTrue,
      );
    });

    test('is false once every photograph has an outcome', () {
      expect(
        _parsed('needs_review', [
          _job(11, 'failed', errorMessage: _interrupted),
          _job(12, 'completed', reviewState: 'ok'),
        ]).isInProgress,
        isFalse,
      );
    });
  });

  group('a listing', () {
    testWidgets(
      'nothing was ever queued for is not shown as processing, nor polled',
      (tester) async {
        final backend = await _openListing(
          tester,
          (request) => switch (request.path) {
            '/api/listings/1' => _json(
              200,
              _detail('pending', [_image(11), _image(12)]),
            ),
            '/api/listings/1/jobs' => _json(200, _summary('pending')),
            _ => _notFound(),
          },
        );
        int progressChecks() => backend.received
            .where((r) => r.path == '/api/listings/1/jobs')
            .length;

        expect(find.textContaining('Processing —'), findsNothing);
        expect(progressChecks(), 1);

        await tester.pump(const Duration(seconds: 30));
        await _settle(tester);
        expect(progressChecks(), 1);
      },
    );

    testWidgets('nothing was ever queued for can be sent from its screen', (
      tester,
    ) async {
      var queued = false;
      final backend = await _openListing(tester, (request) {
        final twoQueued = _summary('processing', [
          _job(11, 'pending'),
          _job(12, 'pending'),
        ]);
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(
              200,
              _detail(queued ? 'processing' : 'pending', [
                _image(11),
                _image(12),
              ]),
            );
          case ('GET', '/api/listings/1/jobs'):
            return _json(200, queued ? twoQueued : _summary('pending'));
          case ('POST', '/api/listings/1/process'):
            queued = true;
            return _json(200, twoQueued);
        }
        return _notFound();
      });

      expect(find.text('AWAITING PROCESSING (2)'), findsOneWidget);
      final process = find.widgetWithText(TextButton, 'Process');
      expect(process, findsOneWidget);
      await tester.ensureVisible(process);
      await tester.pump();
      await tester.tap(process);
      await _settle(tester);

      expect(
        backend.received.where(
          (r) => r.method == 'POST' && r.path == '/api/listings/1/process',
        ),
        hasLength(1),
      );
      expect(find.text('Processing — 0 of 2 done'), findsOneWidget);
    });

    testWidgets('photograph that failed says why, and can be tried again', (
      tester,
    ) async {
      Object? retriedWith;
      await _openListing(tester, (request) {
        switch ((request.method, request.path)) {
          case ('GET', '/api/listings/1'):
            return _json(
              200,
              _detail('needs_review', [
                _image(11),
                _image(12),
                _image(21, type: 'processed', sourceImageId: 12),
              ]),
            );
          case ('GET', '/api/listings/1/jobs'):
            return _json(
              200,
              _summary('needs_review', [
                _job(11, 'failed', errorMessage: _interrupted, backdropId: 3),
                _job(12, 'completed', reviewState: 'ok', backdropId: 3),
              ]),
            );
          case ('POST', '/api/listings/1/process'):
            retriedWith = request.data;
            return _json(
              200,
              _summary('processing', [
                _job(11, 'pending', backdropId: 3),
                _job(12, 'completed', reviewState: 'ok', backdropId: 3),
              ]),
            );
        }
        return _notFound();
      });

      expect(find.text(_interrupted), findsOneWidget);
      expect(find.text('NEEDS REVIEW (1)'), findsOneWidget);
      expect(find.textContaining('AWAITING PROCESSING'), findsNothing);

      final retry = find.widgetWithText(TextButton, 'Retry');
      await tester.ensureVisible(retry);
      await tester.pump();
      await tester.tap(retry);
      await _settle(tester);

      // Tried again against the backdrop the failed attempt used, rather
      // than falling back to a transparent background.
      expect(retriedWith, {'backdrop_id': 3});
    });
  });

  group('the processing banner', () {
    testWidgets('counts only vehicles the pipeline is working on', (
      tester,
    ) async {
      await _coldStart(
        tester,
        processing: [_listing(1, 'processing')],
        pending: [_listing(2, 'pending'), _listing(3, 'pending')],
      );

      expect(find.text('1 vehicle still processing'), findsOneWidget);
    });

    testWidgets('leaves a way back to the overview', (tester) async {
      await _coldStart(tester, processing: [_listing(1, 'processing')]);
      expect(find.text('Overview'), findsOneWidget);

      await tester.tap(find.text('1 vehicle still processing'));
      await _transition(tester);
      expect(find.byType(ListingsScreen), findsOneWidget);
      // The overview is still underneath, to go back to.
      expect(
        GoRouter.of(tester.element(find.byType(ListingsScreen))).canPop(),
        isTrue,
      );

      await tester.tap(find.byTooltip('Back to overview'));
      await _transition(tester);
      expect(find.byType(ListingsScreen), findsNothing);
      expect(find.text('Overview'), findsOneWidget);
    });
  });
}
